from csv import DictReader
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from json import load
from pathlib import Path
from re import IGNORECASE, Pattern, compile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from map_my_merchants.models import Business, Place


@dataclass(frozen=True)
class MerchantSpec:
    business_name: str
    brand: str
    description_pattern: Pattern[str]
    name_pattern: str


@dataclass(frozen=True)
class ChaseRow:
    amount_usd: float
    description: str
    post_date: datetime
    store_ref: str
    transaction_date: datetime


TARGETS = (
    MerchantSpec(
        business_name="Chick-fil-A",
        brand="Chick-fil-A",
        description_pattern=compile(r'CHICK-FIL-A\s+#?(?P<ref>\d+)', IGNORECASE),
        name_pattern=r"^Chick-fil-A$",
    ),
    MerchantSpec(
        business_name="Lowe's",
        brand="Lowe's",
        description_pattern=compile(r'LOWES\s+#?(?P<ref>\d+)', IGNORECASE),
        name_pattern=r"^Lowe'?s$",
    ),
    MerchantSpec(
        business_name="McDonald's",
        brand="McDonald's",
        description_pattern=compile(r"MCDONALD'?S(?:\s+#?|\s+)(?P<ref>\d+)", IGNORECASE),
        name_pattern=r"^McDonald'?s$",
    ),
)


def import_latest_places(csv_path: Path, overpass_url: str) -> list[dict[str, str]]:
    rows = tuple(read_matching_rows(csv_path))
    results = []
    for spec in TARGETS:
        match = latest_row(rows, spec)
        if match is None:
            results.append({'business': spec.business_name, 'status': 'missing-transaction'})
            continue
        element = find_osm_element(spec, match.store_ref, overpass_url)
        if element is None:
            results.append(
                {
                    'business': spec.business_name,
                    'ref': match.store_ref,
                    'status': 'missing-osm',
                }
            )
            continue
        results.append(upsert_place(spec, match, element))
    return results


def read_matching_rows(csv_path: Path) -> list[ChaseRow]:
    with csv_path.open(newline='') as csv_file:
        return [
            chase_row(row, match)
            for row in DictReader(csv_file)
            if (match := matching_spec(unescape(row['Description']))) is not None
        ]


def chase_row(row: dict[str, str], match: tuple[MerchantSpec, str]) -> ChaseRow:
    _, store_ref = match
    return ChaseRow(
        amount_usd=abs(float(row['Amount'])),
        description=unescape(row['Description']).strip(),
        post_date=parse_date(row['Post Date']),
        store_ref=store_ref,
        transaction_date=parse_date(row['Transaction Date']),
    )


def latest_row(rows: list[ChaseRow], spec: MerchantSpec) -> ChaseRow | None:
    matches = [row for row in rows if matching_spec(row.description) == (spec, row.store_ref)]
    return max(matches, key=row_sort_key) if matches else None


def row_sort_key(row: ChaseRow) -> tuple[datetime, datetime, float]:
    return row.transaction_date, row.post_date, row.amount_usd


def matching_spec(description: str) -> tuple[MerchantSpec, str] | None:
    for spec in TARGETS:
        if match := spec.description_pattern.search(description):
            return spec, match.group('ref').lstrip('0') or '0'
    return None


def parse_date(value: str) -> datetime:
    return datetime.strptime(value, '%m/%d/%Y')


def find_osm_element(spec: MerchantSpec, store_ref: str, overpass_url: str) -> dict | None:
    request = Request(
        f'{overpass_url}?{urlencode({"data": overpass_query(spec, store_ref)})}',
        headers={'User-Agent': 'mapmymerchants/0'},
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = load(response)
    except (HTTPError, URLError, TimeoutError) as error:
        raise RuntimeError(f'Unable to query Overpass for {spec.business_name} #{store_ref}') from error
    elements = payload.get('elements', [])
    return best_element(spec, store_ref, elements)


def overpass_query(spec: MerchantSpec, store_ref: str) -> str:
    refs = sorted({store_ref, store_ref.zfill(5)})
    brand_queries = ''.join(f'nwr["brand"="{spec.brand}"]["ref"="{ref}"];' for ref in refs)
    name_queries = ''.join(f'nwr["name"~"{spec.name_pattern}",i]["ref"="{ref}"];' for ref in refs)
    return (
        '[out:json][timeout:25];'
        '('
        f'{brand_queries}'
        f'{name_queries}'
        ');'
        'out center tags;'
    )


def best_element(spec: MerchantSpec, store_ref: str, elements: list[dict]) -> dict | None:
    matches = [
        element
        for element in elements
        if normalized_ref(element.get('tags', {}).get('ref', '')) == store_ref
        and has_position(element)
    ]
    if not matches:
        return None
    return max(matches, key=lambda element: element_score(spec, element))


def normalized_ref(value: str) -> str:
    digits = ''.join(character for character in value if character.isdigit())
    return digits.lstrip('0') or digits or value


def has_position(element: dict) -> bool:
    return {'lat', 'lon'} <= element.keys() or {'center'} <= element.keys()


def element_score(spec: MerchantSpec, element: dict) -> tuple[int, int, int]:
    tags = element.get('tags', {})
    return (
        int(tags.get('brand') == spec.brand),
        int(bool(tags.get('addr:housenumber')) and bool(tags.get('addr:street'))),
        {'node': 3, 'way': 2, 'relation': 1}.get(element.get('type'), 0),
    )


def upsert_place(spec: MerchantSpec, row: ChaseRow, element: dict) -> dict[str, str]:
    business, _ = Business.objects.get_or_create(name=spec.business_name)
    osm_id = element['id']
    osm_type = element['type']
    name = f'{spec.business_name} #{row.store_ref}'
    place, _ = Place.objects.update_or_create(
        name=name,
        defaults={
            'address': osm_address(element),
            'mega_latitude': mega_coordinate(element_coordinate(element, 'lat')),
            'mega_longitude': mega_coordinate(element_coordinate(element, 'lon')),
            'osm_id': osm_id,
            'osm_ref': row.store_ref,
            'osm_type': osm_type,
        },
    )
    place.businesses.add(business)
    return {
        'business': business.name,
        'osm_id': str(place.osm_id),
        'ref': row.store_ref,
        'status': 'imported',
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
