from csv import DictReader
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from django.db.models import DecimalField, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth

from map_my_merchants.management.chase import register_statement_path
from map_my_merchants.models import Transaction


def first_value(row: dict[str, str], *names: str) -> str:
    return next((row[name] for name in names if row.get(name)), '')


def parse_amount_usd(text: str) -> Decimal:
    """Accept `-12.34`, `$1,234.56`, and accounting-style `(12.34)`."""
    cleaned = text.replace('$', '').replace(',', '').strip()
    return -Decimal(cleaned[1:-1]) if cleaned.startswith('(') else Decimal(cleaned or 0)


def parse_post_date(text: str) -> date:
    for date_format in ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%y'):
        try:
            return datetime.strptime(text.strip(), date_format).date()
        except ValueError:
            continue
    raise ValueError(f'Unrecognized date {text!r}')


def signed_amount_usd(row: dict[str, str]) -> Decimal:
    """Chase signs one `Amount` column; many credit unions split unsigned credits and debits."""
    if 'amount' in row:
        return parse_amount_usd(row['amount'])
    return abs(parse_amount_usd(first_value(row, 'credit', 'deposit', 'deposits'))) - abs(
        parse_amount_usd(first_value(row, 'debit', 'withdrawal', 'withdrawals'))
    )


def import_cash_flow_csv(csv_path: Path) -> int:
    statement = register_statement_path(csv_path)
    with csv_path.open(encoding='utf-8-sig', newline='') as file:
        raw_rows = tuple(DictReader(file))
    rows = tuple(
        {key.strip().lower(): (value or '').strip() for key, value in raw_row.items() if key}
        for raw_row in raw_rows
    )
    Transaction.objects.bulk_create(
        [
            Transaction(
                amount_usd=signed_amount_usd(row),
                description=first_value(row, 'description', 'payee', 'memo'),
                line_number=line_number,
                post_date=parse_post_date(
                    first_value(row, 'post date', 'posting date', 'posted date', 'date')
                    or first_value(row, 'transaction date', 'effective date')
                ),
                raw_input=raw_row,
                statement=statement,
            )
            for line_number, (raw_row, row) in enumerate(zip(raw_rows, rows, strict=True), 1)
        ],
        unique_fields=('statement', 'line_number'),
        update_conflicts=True,
        update_fields=('amount_usd', 'description', 'post_date', 'raw_input'),
    )
    return len(rows)


def summarize_months() -> tuple[dict, ...]:
    def total(condition: Q):
        return Coalesce(
            Sum('amount_usd', filter=condition), Decimal(0), output_field=DecimalField()
        )

    return tuple(
        {**month, 'direction': 'saving' if month['net_usd'] >= 0 else 'spending'}
        for month in Transaction.objects
        .annotate(month=TruncMonth('post_date'))
        .values('month')
        .annotate(
            expense_usd=-total(Q(amount_usd__lt=0)),
            income_usd=total(Q(amount_usd__gt=0)),
            net_usd=total(Q()),
        )
        .order_by('month')
    )
