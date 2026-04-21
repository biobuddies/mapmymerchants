from io import BytesIO
from urllib.parse import parse_qs, urlparse

from pytest import mark
from django.core.management import call_command

from map_my_merchants.management import chase
from map_my_merchants.models import Brand, Charge, Place, Statement


@mark.django_db
def test_import_chase_rows_creates_placeholder_places(monkeypatch, tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/20/2026,04/20/2026,Starbucks 1234,Coffee,Sale,-4.56,\n'
        '04/19/2026,04/20/2026,LOWES #00625*,Shopping,Sale,-12.34,\n'
    )
    monkeypatch.setattr(chase, 'urlopen', lambda request, timeout: (_ for _ in ()).throw(AssertionError))

    assert chase.import_chase_rows(csv_path) == [
        {'place': 'Starbucks #1234', 'ref': '1234', 'status': 'created-place'},
        {'place': "Lowe's #625", 'ref': '625', 'status': 'created-place'},
    ]
    assert Statement.objects.get(source_name='chase.csv').source_name == 'chase.csv'
    assert Place.objects.get(name='Starbucks #1234').mega_latitude is None
    assert Place.objects.get(name="Lowe's #625").address == "pending:Lowe's#625"
    assert Charge.objects.get(description='Starbucks 1234').place.name == 'Starbucks #1234'
    assert Charge.objects.get(description='Starbucks 1234').raw_input['Category'] == 'Coffee'
    assert Charge.objects.get(description='Starbucks 1234').line_number == 1
    assert Charge.objects.get(description='LOWES #00625*').place.name == "Lowe's #625"
    assert Charge.objects.get(description='LOWES #00625*').line_number == 2


@mark.django_db
def test_import_chase_rows_reads_only_first_30_csv_rows(monkeypatch, tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        + ''.join(
            f'04/19/2026,04/20/2026,Merchant {index} Main,Shopping,Sale,-{index}.00,\n'
            for index in range(1, 33)
        )
    )
    monkeypatch.setattr(chase, 'urlopen', lambda request, timeout: (_ for _ in ()).throw(AssertionError))

    assert chase.import_chase_rows(csv_path) == [
        {'place': f'Merchant {index} Main', 'status': 'created-place'} for index in range(1, 31)
    ]
    assert Charge.objects.count() == 30
    assert not Charge.objects.filter(description='Merchant 31 Main').exists()


@mark.django_db
def test_import_chase_rows_reuses_statement_for_same_csv(tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/20/2026,04/20/2026,Starbucks 1234,Coffee,Sale,-4.56,\n'
    )

    first = chase.import_chase_rows(csv_path)
    second = chase.import_chase_rows(csv_path)

    assert first == [{'place': 'Starbucks #1234', 'ref': '1234', 'status': 'created-place'}]
    assert second == [{'place': 'Starbucks #1234', 'ref': '1234', 'status': 'reused-place'}]
    assert Statement.objects.filter(source_name='chase.csv').count() == 1
    assert Charge.objects.count() == 1


@mark.django_db
def test_import_chase_csv_repair_raw_input_rewrites_legacy_keys(tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/20/2026,04/20/2026,Starbucks 1234,Coffee,Sale,-4.56,hello\n'
    )
    statement = chase.import_statement(csv_path)
    place = Place.objects.create(address='pending:Starbucks#1234', name='Starbucks #1234', osm_ref='1234')
    charge = Charge.objects.create(
        amount_usd='4.56',
        description='Starbucks 1234',
        line_number=1,
        place=place,
        post_date='2026-04-20',
        raw_input={'Brand': 'Starbucks', 'Description': 'Starbucks 1234', 'Store Ref': '1234'},
        statement=statement,
        transaction_date='2026-04-20',
    )

    call_command('import_chase_csv', str(csv_path), '--repair-raw-input')

    charge.refresh_from_db()
    assert charge.raw_input == {
        'Amount': '-4.56',
        'Category': 'Coffee',
        'Description': 'Starbucks 1234',
        'Memo': 'hello',
        'Post Date': '04/20/2026',
        'Transaction Date': '04/20/2026',
        'Type': 'Sale',
    }


@mark.django_db
def test_import_chase_csv_repair_raw_input_falls_back_when_line_number_drifted(tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/20/2026,04/20/2026,Starbucks 1234,Coffee,Sale,-4.56,hello\n'
    )
    statement = chase.import_statement(csv_path)
    place = Place.objects.create(address='pending:Starbucks#1234', name='Starbucks #1234', osm_ref='1234')
    charge = Charge.objects.create(
        amount_usd='4.56',
        description='Starbucks 1234',
        line_number=7,
        place=place,
        post_date='2026-04-20',
        raw_input={'Brand': 'Starbucks', 'Description': 'Starbucks 1234', 'Store Ref': '1234'},
        statement=statement,
        transaction_date='2026-04-20',
    )

    call_command('import_chase_csv', str(csv_path), '--repair-raw-input')

    charge.refresh_from_db()
    assert charge.raw_input['Category'] == 'Coffee'
    assert charge.raw_input['Amount'] == '-4.56'


@mark.django_db
def test_import_chase_csv_repair_raw_input_skips_missing_charge(tmp_path, capsys):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/20/2026,04/20/2026,Starbucks 1234,Coffee,Sale,-4.56,hello\n'
    )
    chase.import_statement(csv_path)

    call_command('import_chase_csv', str(csv_path), '--repair-raw-input')

    assert 'line_number=1 status=missing-charge' in capsys.readouterr().out


@mark.django_db
def test_resolve_missing_place_coordinates_updates_place_from_overpass(monkeypatch):
    place = Place.objects.create(address='pending:Starbucks#1234', name='Starbucks #1234', osm_ref='1234')
    place.brands.add(Brand.objects.get_or_create(name='Starbucks', defaults={'match_pattern': '^Starbucks$'})[0])
    payload = (
        '{"elements":[{"center":{"lat":35.868915,"lon":-78.718725},"id":47879843,'
        '"tags":{"addr:city":"Raleigh","addr:housenumber":"4831","addr:postcode":"27613",'
        '"addr:state":"NC","addr:street":"Grove Barton Road","brand":"Starbucks",'
        '"name":"Starbucks","ref":"01234"},"type":"way"}]}'
    ).encode()
    requests = []

    class FakeResponse(BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            self.close()

    def fake_urlopen(request, timeout):
        requests.append((request.full_url, timeout))
        return FakeResponse(payload)

    monkeypatch.setattr(chase, 'urlopen', fake_urlopen)

    assert chase.resolve_missing_place_coordinates('https://overpass.invalid/api/interpreter', 5) == [
        {
            'brand': 'Starbucks',
            'osm_id': '47879843',
            'place': 'Starbucks #1234',
            'ref': '1234',
            'status': 'resolved-place',
        }
    ]
    place.refresh_from_db()
    assert place.address == '4831 Grove Barton Road, Raleigh, NC, 27613'
    assert place.mega_latitude == 35_868_915
    assert place.mega_longitude == -78_718_725
    assert place.osm_id == 47879843
    assert place.osm_type == 'way'
    assert requests[0][1] == 5
    assert urlparse(requests[0][0]).netloc == 'overpass.invalid'
    assert 'ref"~"0*1234"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]
    assert 'brand"~"^Starbucks$"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]
