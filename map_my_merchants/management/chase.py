from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from html import unescape
from json import dumps, load
from logging import getLogger
from pathlib import Path
from re import IGNORECASE, Pattern, compile, escape as escape_pattern, search
from time import perf_counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.db.models import Q

from map_my_merchants.models import Brand, Charge, Place, Statement
from map_my_merchants.xsv import refresh_statement_table, statement_csv_rows

logger = getLogger(__name__)
CSV_ROW_LIMIT = 30


def log_fields(**fields: object) -> None:
    logger.info(' '.join(f'{key}={dumps(value, sort_keys=True)}' for key, value in fields.items()))

@dataclass(frozen=True)
class ChaseRow:
    amount_usd: float
    brand: Brand
    description: str
    line_number: int
    post_date: datetime
    raw_input: dict[str, str]
    statement: Statement
    store_ref: str
    transaction_date: datetime


def import_brands() -> tuple[Brand, ...]:
    return tuple(Brand.objects.exclude(match_pattern='').order_by('name'))


def description_pattern(brand: Brand) -> Pattern[str]:
    brand_pattern = brand.match_pattern.removeprefix('^').removesuffix('$')
    return compile(f'{brand_pattern}{brand.chase_ref_pattern}', IGNORECASE)


def import_chase_rows(csv_path: Path) -> list[dict[str, str]]:
    statement = register_statement_path(csv_path)
    rows = tuple(extract_chase_rows(statement))
    log_fields(event='read-rows', csv_path=str(csv_path), row_count=len(rows))
    results = []
    for row in rows:
        log_fields(event='import-place', brand=row.brand.name, store_ref=row.store_ref)
        if not row.store_ref:
            results.append(create_placeholder_place_and_charge(row))
            continue
        if place := matching_place(row.brand, row.store_ref):
            results.append(reuse_place_and_create_charge(row, place))
            continue
        results.append(create_placeholder_place_and_charge(row))
    return results


def import_latest_places(csv_path: Path, overpass_url: str, overpass_timeout_seconds: int) -> list[dict[str, str]]:
    return import_chase_rows(csv_path)


def import_statement(csv_path: Path) -> Statement:
    return register_statement_path(csv_path)


def register_statement_path(csv_path: Path) -> Statement:
    content_sha256 = sha256(csv_path.read_bytes()).hexdigest()
    if statement := Statement.objects.filter(source_path=str(csv_path)).first():
        update_statement_registry(statement, content_sha256, csv_path)
        refresh_statement_table(statement.id, statement.source_path)
        return statement
    statement, _ = Statement.objects.get_or_create(
        content_sha256=content_sha256,
        defaults={'source_name': csv_path.name, 'source_path': str(csv_path)},
    )
    update_statement_registry(statement, content_sha256, csv_path)
    refresh_statement_table(statement.id, statement.source_path)
    return statement


def extract_chase_rows(statement: Statement) -> list[ChaseRow]:
    return [chase_row(line_number, row, statement) for line_number, row in statement_csv_rows(statement, CSV_ROW_LIMIT)]


def chase_row(line_number: int, row: dict[str, str], statement: Statement) -> ChaseRow:
    raw_input = {key: unescape(value).strip() for key, value in row.items()}
    brand, store_ref = chase_brand_store_ref(raw_input['Description'])
    return ChaseRow(
        amount_usd=abs(float(row['Amount'])),
        brand=brand,
        description=raw_input['Description'],
        line_number=line_number,
        post_date=parse_date(row['Post Date']),
        raw_input=raw_input,
        statement=statement,
        store_ref=store_ref,
        transaction_date=parse_date(row['Transaction Date']),
    )


def update_statement_registry(statement: Statement, content_sha256: str, csv_path: Path) -> None:
    update_fields = tuple(
        field_name
        for field_name, value in (
            ('content_sha256', content_sha256),
            ('source_name', csv_path.name),
            ('source_path', str(csv_path)),
        )
        if getattr(statement, field_name) != value
    )
    if not update_fields:
        return
    statement.content_sha256 = content_sha256
    statement.source_name = csv_path.name
    statement.source_path = str(csv_path)
    statement.save(update_fields=update_fields)


def chase_brand_store_ref(description: str) -> tuple[Brand, str]:
    if match := matching_spec(description):
        return match
    store_ref_match = search(r'\s+#?(?P<ref>\d+)\*?$', description)
    name = description[: store_ref_match.start()] if store_ref_match else description
    name = name.rstrip(' *').strip()
    brand, _ = Brand.objects.get_or_create(
        name=name,
        defaults={'match_pattern': f'^{escape_pattern(name).replace(r"\\ ", r"\\s+")}$'},
    )
    store_ref = (store_ref_match.group('ref').lstrip('0') or '0') if store_ref_match else ''
    return brand, store_ref


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


def resolve_missing_place_coordinates(
    overpass_url: str,
    overpass_timeout_seconds: int,
) -> list[dict[str, str]]:
    results = []
    for place in unresolved_places():
        if (brand := place.brand) is None:
            results.append({'place': place.name, 'status': 'missing-brand'})
            continue
        log_fields(event='resolve-place', brand=brand.name, place_name=place.name, store_ref=place.osm_ref)
        element = find_osm_element(brand, place.osm_ref, overpass_url, overpass_timeout_seconds)
        if element is None:
            log_fields(event='missing-osm', brand=brand.name, place_name=place.name, store_ref=place.osm_ref)
            results.append({'brand': brand.name, 'place': place.name, 'ref': place.osm_ref, 'status': 'missing-osm'})
            continue
        results.append(update_place_from_osm(place, brand, element))
    return results


def refresh_place_from_osm_lookup(
    place: Place,
    osm_lookup: str,
    overpass_url: str,
    overpass_timeout_seconds: int,
) -> dict[str, str]:
    osm_type, osm_id = parsed_osm_lookup(osm_lookup)
    element = fetch_osm_element(osm_type, osm_id, overpass_url, overpass_timeout_seconds)
    if element is None:
        raise RuntimeError(f'Unable to query Overpass for {osm_type}/{osm_id}')
    return update_place_from_osm(place, place.brand, element)


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
            place.brand_id == brand.id,
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


def fetch_osm_element(
    osm_type: str,
    osm_id: int,
    overpass_url: str,
    overpass_timeout_seconds: int,
) -> dict | None:
    query = osm_lookup_query(osm_type, osm_id, overpass_timeout_seconds)
    log_fields(
        event='osm-lookup-start',
        osm_id=osm_id,
        osm_type=osm_type,
        overpass_url=overpass_url,
        query=query,
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
            elapsed_seconds=round(elapsed_seconds, 1),
            error=repr(error),
            event='osm-lookup-failed',
            osm_id=osm_id,
            osm_type=osm_type,
            overpass_url=overpass_url,
            query=query,
            timeout_seconds=overpass_timeout_seconds,
        )
        raise RuntimeError(f'Unable to query Overpass for {osm_type}/{osm_id}') from error
    elapsed_seconds = perf_counter() - started_at
    log_fields(
        elapsed_seconds=round(elapsed_seconds, 1),
        element_count=len(payload.get('elements', [])),
        event='osm-lookup-finished',
        osm_id=osm_id,
        osm_type=osm_type,
        overpass_url=overpass_url,
        query=query,
        timeout_seconds=overpass_timeout_seconds,
    )
    return next((element for element in payload.get('elements', []) if element.get('id') == osm_id), None)


def normalized_ref(value: str) -> str:
    digits = ''.join(character for character in value if character.isdigit())
    return digits.lstrip('0') or digits or value


def unresolved_places() -> tuple[Place, ...]:
    return tuple(
        Place.objects.filter(Q(mega_latitude__isnull=True) | Q(mega_longitude__isnull=True))
        .exclude(osm_ref='')
        .order_by('id')
    )


def osm_lookup_query(osm_type: str, osm_id: int, overpass_timeout_seconds: int) -> str:
    return f'[out:json][timeout:{overpass_timeout_seconds}];{osm_type}({osm_id});out center tags;'


def parsed_osm_lookup(value: str) -> tuple[str, int]:
    if not (match := search(r'^(node|relation|way)/(\d+)$', value.strip())):
        raise ValueError(f'Invalid OpenStreetMap lookup: {value}')
    return match.group(1), int(match.group(2))


def has_position(element: dict) -> bool:
    return {'lat', 'lon'} <= element.keys() or {'center'} <= element.keys()


def element_score(brand: Brand, element: dict) -> tuple[int, int, int]:
    tags = element.get('tags', {})
    return (
        int(tags.get('brand') == brand.name),
        int(bool(tags.get('addr:housenumber')) and bool(tags.get('addr:street'))),
        {'node': 3, 'way': 2, 'relation': 1}.get(element.get('type'), 0),
    )


def upsert_charge(row: ChaseRow, place: Place) -> Charge:
    charge, _ = Charge.objects.update_or_create(
        line_number=row.line_number,
        statement=row.statement,
        defaults={
            'amount_usd': Decimal(f'{row.amount_usd:.2f}'),
            'description': row.description,
            'place': place,
            'post_date': row.post_date.date(),
            'raw_input': row.raw_input,
            'transaction_date': row.transaction_date.date(),
        },
    )
    return charge


def create_placeholder_place_and_charge(row: ChaseRow) -> dict[str, str]:
    place, _ = Place.objects.update_or_create(
        name=place_name(row.brand, row.description, row.store_ref),
        defaults={
            'address': unresolved_place_address(row.brand, row.description, row.store_ref),
            'brand': row.brand,
            'osm_ref': row.store_ref,
        },
    )
    if place.brand_id != row.brand.id:
        place.brand = row.brand
        place.save(update_fields=('brand',))
    upsert_charge(row, place)
    result = {'place': place.name, 'status': 'created-place'}
    if row.store_ref:
        result['ref'] = row.store_ref
    return result


def update_place_from_osm(place: Place, brand: Brand, element: dict) -> dict[str, str]:
    place.address = osm_address(element)
    place.brand = brand
    place.mega_latitude = mega_coordinate(element_coordinate(element, 'lat'))
    place.mega_longitude = mega_coordinate(element_coordinate(element, 'lon'))
    place.osm_ref = normalized_ref(element.get('tags', {}).get('ref', '')) or place.osm_ref
    place.name = place_name(brand, place.name.partition(' #')[0], place.osm_ref)
    place.osm_id = element['id']
    place.osm_response = element
    place.osm_type = element['type']
    place.save()
    return {
        'brand': brand.name,
        'osm_id': str(place.osm_id),
        'place': place.name,
        'ref': place.osm_ref,
        'status': 'resolved-place',
    }


def reuse_place_and_create_charge(row: ChaseRow, place: Place) -> dict[str, str]:
    if place.brand_id != row.brand.id:
        place.brand = row.brand
        place.save(update_fields=('brand',))
    upsert_charge(row, place)
    result = {'place': place.name, 'status': 'reused-place'}
    if place.osm_id is not None:
        result['osm_id'] = str(place.osm_id)
    if row.store_ref:
        result['ref'] = row.store_ref
    return result


def place_name(brand: Brand, description: str, store_ref: str) -> str:
    return f'{brand.name} #{store_ref}' if store_ref else description


def unresolved_place_address(brand: Brand, description: str, store_ref: str) -> str:
    return ''


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
