from csv import DictReader
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from html import unescape
from json import dumps, load
from logging import getLogger
from pathlib import Path
from re import IGNORECASE, Pattern, compile
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from map_my_merchants.models import Brand, Charge, Place

logger = getLogger(__name__)


def log_fields(**fields: object) -> None:
    logger.info(' '.join(f'{key}={dumps(value, sort_keys=True)}' for key, value in fields.items()))

@dataclass(frozen=True)
class ChaseRow:
    amount_usd: float
    brand: Brand
    description: str
    post_date: datetime
    store_ref: str
    transaction_date: datetime


def import_brands() -> tuple[Brand, ...]:
    return tuple(Brand.objects.exclude(match_pattern='').order_by('name'))


def description_pattern(brand: Brand) -> Pattern[str]:
    brand_pattern = brand.match_pattern.removeprefix('^').removesuffix('$')
    return compile(f'{brand_pattern}{brand.chase_ref_pattern}', IGNORECASE)


def import_latest_places(csv_path: Path, overpass_url: str, overpass_timeout_seconds: int) -> list[dict[str, str]]:
    brands = import_brands()
    rows = tuple(read_matching_rows(csv_path))
    log_fields(event='read-matching-rows', csv_path=str(csv_path), row_count=len(rows))
    results = []
    for brand in brands:
        match = latest_row(rows, brand)
        if match is None:
            log_fields(event='missing-transaction', brand=brand.name)
            results.append({'brand': brand.name, 'status': 'missing-transaction'})
            continue
        log_fields(event='import-latest-place', brand=brand.name, store_ref=match.store_ref)
        if place := matching_place(brand, match.store_ref):
            results.append(reuse_place_and_create_charge(match, place))
            continue
        element = find_osm_element(brand, match.store_ref, overpass_url, overpass_timeout_seconds)
        if element is None:
            Charge.objects.update_or_create(
                amount_usd=Decimal(f'{match.amount_usd:.2f}'),
                brand=brand,
                description=match.description,
                post_date=match.post_date.date(),
                store_ref=match.store_ref,
                transaction_date=match.transaction_date.date(),
                defaults={'place': None},
            )
            log_fields(event='missing-osm', brand=brand.name, store_ref=match.store_ref)
            results.append(
                {
                    'brand': brand.name,
                    'ref': match.store_ref,
                    'status': 'missing-osm',
                }
            )
            continue
        results.append(upsert_place_and_create_charge(match, element))
    return results


def read_matching_rows(csv_path: Path) -> list[ChaseRow]:
    with csv_path.open(newline='') as csv_file:
        return [
            chase_row(row, match)
            for row in DictReader(csv_file)
            if (match := matching_spec(unescape(row['Description']))) is not None
        ]


def chase_row(row: dict[str, str], match: tuple[Brand, str]) -> ChaseRow:
    brand, store_ref = match
    return ChaseRow(
        amount_usd=abs(float(row['Amount'])),
        brand=brand,
        description=unescape(row['Description']).strip(),
        post_date=parse_date(row['Post Date']),
        store_ref=store_ref,
        transaction_date=parse_date(row['Transaction Date']),
    )


def latest_row(rows: list[ChaseRow], brand: Brand) -> ChaseRow | None:
    matches = [row for row in rows if row.brand == brand]
    return max(matches, key=row_sort_key) if matches else None


def row_sort_key(row: ChaseRow) -> tuple[datetime, datetime, float]:
    return row.transaction_date, row.post_date, row.amount_usd


def matching_spec(description: str) -> tuple[Brand, str] | None:
    for brand in import_brands():
        if match := description_pattern(brand).search(description):
            return brand, match.group('ref').lstrip('0') or '0'
    return None


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, '%m/%d/%Y')


def find_osm_element(
    brand: Brand,
    store_ref: str,
    overpass_url: str,
    overpass_timeout_seconds: int,
) -> dict | None:
    query = overpass_query(brand, store_ref, overpass_timeout_seconds)
    log_fields(
        brand=brand.name,
        event='overpass-request-start',
        overpass_url=overpass_url,
        query=query,
        store_ref=store_ref,
        timeout_seconds=overpass_timeout_seconds,
    )
    request = Request(
        f'{overpass_url}?{urlencode({"data": query})}',
        headers={'User-Agent': 'mapmymerchants/0'},
    )
    started_at = perf_counter()
    try:
        with urlopen(request, timeout=overpass_timeout_seconds) as response:
            payload = load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        elapsed_seconds = perf_counter() - started_at
        log_fields(
            brand=brand.name,
            elapsed_seconds=round(elapsed_seconds, 1),
            error=repr(error),
            event='overpass-request-failed',
            overpass_url=overpass_url,
            query=query,
            store_ref=store_ref,
            timeout_seconds=overpass_timeout_seconds,
        )
        raise RuntimeError(f'Unable to query Overpass for {brand.name} #{store_ref}') from error
    elapsed_seconds = perf_counter() - started_at
    log_fields(
        brand=brand.name,
        elapsed_seconds=round(elapsed_seconds, 1),
        element_count=len(payload.get('elements', [])),
        event='overpass-request-finished',
        overpass_url=overpass_url,
        query=query,
        store_ref=store_ref,
        timeout_seconds=overpass_timeout_seconds,
    )
    return best_element(brand, store_ref, payload.get('elements', []))


def overpass_query(brand: Brand, store_ref: str, overpass_timeout_seconds: int = 180) -> str:
    ref_pattern = f'0*{store_ref}'
    brand_queries = f'nwr["brand"~"{brand.match_pattern}",i]["ref"~"{ref_pattern}"];'
    name_queries = f'nwr["name"~"{brand.match_pattern}",i]["ref"~"{ref_pattern}"];'
    return (
        f'[out:json][timeout:{overpass_timeout_seconds}];'
        '('
        f'{brand_queries}'
        f'{name_queries}'
        ');'
        'out center tags;'
    )


def matching_place(brand: Brand, store_ref: str) -> Place | None:
    matches = [
        place
        for place in Place.objects.filter(osm_ref=store_ref).order_by('id')
        if place_matches_brand(brand, place)
    ]
    if not matches:
        return None
    place = matches[0]
    log_fields(
        brand=brand.name,
        event='place-cache-hit',
        osm_id=place.osm_id,
        osm_type=place.osm_type,
        place_name=place.name,
        store_ref=store_ref,
    )
    return place


def place_matches_brand(brand: Brand, place: Place) -> bool:
    tags = place.osm_response.get('tags', {})
    place_name = place.name.partition(' #')[0]
    return any(
        (
            tags.get('brand') == brand.name,
            bool(tags.get('name')) and bool(search_pattern(brand.match_pattern, tags['name'])),
            bool(place_name) and bool(search_pattern(brand.match_pattern, place_name)),
        )
    )


def search_pattern(pattern: str, value: str) -> bool:
    return bool(compile(pattern, IGNORECASE).search(value))


def best_element(brand: Brand, store_ref: str, elements: list[dict]) -> dict | None:
    matches = [
        element
        for element in elements
        if normalized_ref(element.get('tags', {}).get('ref', '')) == store_ref
        and has_position(element)
    ]
    if not matches:
        return None
    return max(matches, key=lambda element: element_score(brand, element))


def normalized_ref(value: str) -> str:
    digits = ''.join(character for character in value if character.isdigit())
    return digits.lstrip('0') or digits or value


def has_position(element: dict) -> bool:
    return {'lat', 'lon'} <= element.keys() or {'center'} <= element.keys()


def element_score(brand: Brand, element: dict) -> tuple[int, int, int]:
    tags = element.get('tags', {})
    return (
        int(tags.get('brand') == brand.name),
        int(bool(tags.get('addr:housenumber')) and bool(tags.get('addr:street'))),
        {'node': 3, 'way': 2, 'relation': 1}.get(element.get('type'), 0),
    )


def upsert_place_and_create_charge(row: ChaseRow, element: dict) -> dict[str, str]:
    brand = row.brand
    osm_id = element['id']
    osm_type = element['type']
    name = f'{brand.name} #{row.store_ref}'
    place, _ = Place.objects.update_or_create(
        osm_id=osm_id,
        osm_type=osm_type,
        defaults={
            'address': osm_address(element),
            'mega_latitude': mega_coordinate(element_coordinate(element, 'lat')),
            'mega_longitude': mega_coordinate(element_coordinate(element, 'lon')),
            'name': name,
            'osm_ref': row.store_ref,
            'osm_response': element,
            'osm_type': osm_type,
        },
    )
    place.brands.add(brand)
    Charge.objects.update_or_create(
        amount_usd=Decimal(f'{row.amount_usd:.2f}'),
        brand=brand,
        description=row.description,
        post_date=row.post_date.date(),
        store_ref=row.store_ref,
        transaction_date=row.transaction_date.date(),
        defaults={'place': place},
    )
    return {
        'brand': brand.name,
        'osm_id': str(place.osm_id),
        'ref': row.store_ref,
        'status': 'imported',
    }


def reuse_place_and_create_charge(row: ChaseRow, place: Place) -> dict[str, str]:
    brand = row.brand
    place.brands.add(brand)
    Charge.objects.update_or_create(
        amount_usd=Decimal(f'{row.amount_usd:.2f}'),
        brand=brand,
        description=row.description,
        post_date=row.post_date.date(),
        store_ref=row.store_ref,
        transaction_date=row.transaction_date.date(),
        defaults={'place': place},
    )
    return {
        'brand': brand.name,
        'osm_id': str(place.osm_id),
        'ref': row.store_ref,
        'status': 'reused-place',
    }


def osm_address(element: dict) -> str:
    tags = element.get('tags', {})
    parts = (
        ' '.join(part for part in (tags.get('addr:housenumber', ''), tags.get('addr:street', '')) if part),
        tags.get('addr:city', ''),
        tags.get('addr:state', ''),
        tags.get('addr:postcode', ''),
    )
    return ', '.join(part for part in parts if part) or f"osm:{element['type']}/{element['id']}"


def element_coordinate(element: dict, coordinate: str) -> float:
    return element.get(coordinate, element['center'][coordinate])


def mega_coordinate(value: float) -> int:
    return round(value * 1_000_000)
