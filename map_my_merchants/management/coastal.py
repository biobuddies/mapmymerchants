from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from re import sub

from django.contrib.auth import get_user_model
from django.db import transaction

from map_my_merchants.management.chase import (
    get_or_create_brand,
    get_or_create_place,
    matching_place,
    matching_platform,
    parse_brand_store_ref,
    place_name,
    register_statement_path,
)
from map_my_merchants.models import Charge, Place, Statement
from map_my_merchants.xsv import statement_csv_rows


@dataclass(frozen=True)
class CoastalRow:
    amount_usd: Decimal
    date: date
    description: str
    line_number: int
    raw_input: dict[str, str]


def coastal_row(line_number: int, raw_input: dict[str, str]) -> CoastalRow | None:
    description = raw_input['Description'].strip()
    if not description.startswith('POS #'):
        return None
    amount_usd = Decimal(raw_input['Amount'].replace('$', '').replace(',', ''))
    if amount_usd >= 0:
        return None
    return CoastalRow(
        amount_usd=abs(amount_usd),
        date=datetime.strptime(raw_input['Date'], '%m/%d/%y').replace(tzinfo=UTC).date(),
        description=sub(r'^POS #\d+\s+', '', description),
        line_number=line_number,
        raw_input=raw_input,
    )


def extract_coastal_rows(statement: Statement, limit: int) -> list[CoastalRow]:
    rows = []
    for line_number, raw_input in statement_csv_rows(statement):
        if row := coastal_row(line_number, raw_input):
            rows.append(row)
            if len(rows) == limit:
                break
    return rows


@transaction.atomic
def import_coastal_rows(csv_path: Path, limit: int = 3) -> list[dict[str, str]]:
    if limit < 1:
        raise ValueError('limit must be positive')
    statement = register_statement_path(csv_path.expanduser().resolve())
    updated_by = get_user_model().objects.get(username='from-statement')
    results = []
    for row in extract_coastal_rows(statement, limit):
        brand_name, store_ref = parse_brand_store_ref(row.description)
        brand = get_or_create_brand(brand_name, updated_by=updated_by)
        place = matching_place(brand, store_ref) if store_ref else None
        place = (
            place
            or Place.objects.filter(brand=brand, name='Online').first()
            or get_or_create_place(
                brand=brand, name=place_name(brand, row.description, store_ref), store_ref=store_ref
            )
        )
        charge, created = Charge.objects.update_or_create(
            line_number=row.line_number,
            statement=statement,
            defaults={
                'amount_usd': row.amount_usd,
                'description': row.description,
                'place': place,
                'platform': matching_platform(row.description),
                'post_date': row.date,
                'raw_input': row.raw_input,
                'transaction_date': row.date,
            },
        )
        results.append({
            'place': place.name,
            'row': str(charge.line_number),
            'status': 'created-charge' if created else 'updated-charge',
        })
    return results
