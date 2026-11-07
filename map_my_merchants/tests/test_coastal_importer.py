from csv import DictReader, DictWriter
from decimal import Decimal
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from pytest import fixture, mark, raises

from map_my_merchants.management.coastal import coastal_row, import_coastal_rows
from map_my_merchants.models import Charge, Statement
from map_my_merchants.xsv import preview_statement_data


@fixture
def coastal_csv(tmp_path: Path) -> Path:
    csv_path = tmp_path / 'coastal.csv'
    csv_path.write_bytes((Path(__file__).parent / 'fixtures' / 'coastal.csv').read_bytes())
    return csv_path


@mark.django_db
def test_import_coastal_purchases_preserves_rows_and_reuses_places(coastal_csv: Path):
    csv_path = coastal_csv

    results = import_coastal_rows(csv_path, limit=1)
    assert results == [{'place': 'Food Lion #1484', 'row': '3', 'status': 'created-charge'}]
    call_command('import_coastal_csv', str(csv_path), limit=1)

    charge = Charge.objects.get()
    assert charge.amount_usd == Decimal('86.17')
    assert charge.line_number == 3
    assert charge.place.name == 'Food Lion #1484'
    assert charge.place.brand.statement_name == 'Food Lion'
    assert charge.raw_input['Account ID'] == '000000-S0000'
    assert charge.raw_input['Transaction ID'] == '20261014:968961'
    assert charge.raw_input['Description'] == 'POS #628709796984 FOOD LION #1484 RALEIGH NC'
    assert charge.raw_input['Balance'] == '$3,141.60'
    assert charge.transaction_date.isoformat() == '2026-10-14'
    assert charge.post_date == charge.transaction_date
    assert Statement.objects.filter(source_path=str(csv_path)).count() == 1
    assert 'Transaction ID' in preview_statement_data(charge.statement)

    call_command('import_coastal_csv', str(csv_path), limit=3)

    assert set(Charge.objects.values_list('line_number', flat=True)) == {3, 4}
    assert Charge.objects.values('place').distinct().count() == 1


@mark.django_db
def test_import_coastal_rejects_nonpositive_limit(tmp_path: Path):
    with raises(CommandError, match='--limit must be positive'):
        call_command('import_coastal_csv', str(tmp_path / 'missing.csv'), limit=0)
    assert not Statement.objects.filter(source_name='missing.csv').exists()

    with raises(ValueError, match='limit must be positive'):
        import_coastal_rows(tmp_path / 'missing.csv', limit=0)


@mark.parametrize('row_index', (0, 1))
def test_coastal_row_skips_nonpurchases(coastal_csv: Path, row_index: int):
    with coastal_csv.open() as source:
        row = list(DictReader(source))[row_index]
    assert coastal_row(row_index + 1, row) is None


@mark.django_db
def test_import_coastal_rolls_back_invalid_statement(coastal_csv: Path):
    csv_path = coastal_csv
    with csv_path.open() as source:
        rows = list(DictReader(source))
    rows[-1]['Date'] = 'invalid'
    with csv_path.open('w', newline='') as destination:
        writer = DictWriter(destination, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)

    with raises(ValueError, match='invalid'):
        import_coastal_rows(csv_path)

    assert not Statement.objects.filter(source_path=str(csv_path)).exists()
    assert not Charge.objects.filter(statement__source_path=str(csv_path)).exists()
