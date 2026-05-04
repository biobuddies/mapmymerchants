from io import BytesIO
from urllib.parse import parse_qs, urlparse

from pytest import mark, raises
from django.core.management import call_command

from map_my_merchants.management import chase
from map_my_merchants.models import Brand, Charge, Place, Statement
from map_my_merchants import xsv


@mark.django_db
def test_import_chase_rows_creates_placeholder_places(monkeypatch, tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n'
        '04/18/2026,04/19/2026,LOWES #00625*,Home,Sale,-244.18,\n'
    )
    monkeypatch.setattr(chase, 'urlopen', lambda request, timeout: (_ for _ in ()).throw(AssertionError))

    assert chase.import_chase_rows(csv_path) == [
        {'place': 'Food Lion #1484', 'ref': '1484', 'status': 'created-place'},
        {'place': "Lowe's #625", 'ref': '625', 'status': 'created-place'},
    ]
    assert Statement.objects.get(source_name='chase.csv').source_name == 'chase.csv'
    assert Place.objects.get(name='Food Lion #1484').mega_latitude is None
    assert Place.objects.get(name="Lowe's #625").address == ''
    assert Charge.objects.get(description='FOOD LION #1484').place.name == 'Food Lion #1484'
    assert Charge.objects.get(description='FOOD LION #1484').raw_input['Category'] == 'Groceries'
    assert Charge.objects.get(description='FOOD LION #1484').line_number == 1
    assert Charge.objects.get(description='LOWES #00625*').place.name == "Lowe's #625"
    assert Charge.objects.get(description='LOWES #00625*').line_number == 2


@mark.django_db
def test_import_chase_rows_reads_only_first_30_csv_rows(monkeypatch, tmp_path):
    csv_path = tmp_path / 'chase.csv'
    rows = (
        '04/16/2026,04/19/2026,CHICK-FIL-A #03376,Food & Drink,Sale,-21.87,\n',
        '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n',
        '04/18/2026,04/19/2026,LOWES #00625*,Home,Sale,-244.18,\n',
        '04/11/2026,04/12/2026,FOOD LION #0536,Groceries,Sale,-15.27,\n',
        '04/06/2026,04/08/2026,CHICK-FIL-A #02583,Food & Drink,Sale,-56.98,\n',
        '04/01/2026,04/03/2026,CHICK-FIL-A #05452,Food & Drink,Sale,-11.26,\n',
        '03/16/2026,03/18/2026,CHICK-FIL-A #05395,Food & Drink,Sale,-30.54,\n',
    )
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        + ''.join(rows[index % len(rows)] for index in range(32))
    )
    monkeypatch.setattr(chase, 'urlopen', lambda request, timeout: (_ for _ in ()).throw(AssertionError))

    assert len(chase.import_chase_rows(csv_path)) == 30
    assert Charge.objects.count() == 30
    assert not Charge.objects.filter(line_number=31).exists()


@mark.django_db
def test_import_chase_rows_reuses_statement_for_same_csv(tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n'
    )

    first = chase.import_chase_rows(csv_path)
    second = chase.import_chase_rows(csv_path)

    assert first == [{'place': 'Food Lion #1484', 'ref': '1484', 'status': 'created-place'}]
    assert second == [{'place': 'Food Lion #1484', 'ref': '1484', 'status': 'reused-place'}]
    assert Statement.objects.filter(source_name='chase.csv').count() == 1
    assert Charge.objects.count() == 1


@mark.django_db
def test_import_chase_csv_register_only_creates_statement_registry_entry(tmp_path, capsys):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n'
    )

    call_command('import_chase_csv', str(csv_path), '--register-only')

    statement = Statement.objects.get(source_path=str(csv_path))
    assert statement.source_name == 'chase.csv'
    assert Charge.objects.count() == 0
    assert 'status=registered-statement' in capsys.readouterr().out


@mark.django_db
def test_resolve_missing_place_coordinates_updates_place_from_overpass(monkeypatch):
    place = Place.objects.create(
        address='',
        brand=Brand.objects.get(name="Lowe's"),
        name="Lowe's #625",
        osm_ref='625',
    )
    payload = (
        '{"elements":[{"center":{"lat":35.868915,"lon":-78.718725},"id":47879843,'
        '"tags":{"addr:city":"Raleigh","addr:housenumber":"4831","addr:postcode":"27613",'
        '"addr:state":"NC","addr:street":"Grove Barton Road","brand":"Lowe\'s",'
        '"name":"Lowe\'s","ref":"00625"},"type":"way"}]}'
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
            'brand': "Lowe's",
            'osm_id': '47879843',
            'place': "Lowe's #625",
            'ref': '625',
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
    assert 'ref"~"0*625"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]
    assert 'brand"~"^Lowe.*s$"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]


@mark.django_db
def test_refresh_place_from_osm_lookup_updates_place_from_explicit_osm_id(monkeypatch):
    place = Place.objects.create(
        address='',
        brand=Brand.objects.get(name="Lowe's"),
        name="Lowe's #625",
    )
    payload = (
        '{"elements":[{"center":{"lat":35.868915,"lon":-78.718725},"id":47879843,'
        '"tags":{"addr:city":"Raleigh","addr:housenumber":"4831","addr:postcode":"27613",'
        '"addr:state":"NC","addr:street":"Grove Barton Road","brand":"Lowe\'s",'
        '"name":"Lowe\'s","ref":"00625"},"type":"way"}]}'
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

    assert chase.refresh_place_from_osm_lookup(
        place,
        'way/47879843',
        'https://overpass.invalid/api/interpreter',
        5,
    ) == {
        'brand': "Lowe's",
        'osm_id': '47879843',
        'place': "Lowe's #625",
        'ref': '625',
        'status': 'resolved-place',
    }
    place.refresh_from_db()
    assert place.address == '4831 Grove Barton Road, Raleigh, NC, 27613'
    assert place.mega_latitude == 35_868_915
    assert place.mega_longitude == -78_718_725
    assert place.osm_id == 47879843
    assert place.osm_type == 'way'
    assert requests[0][1] == 5
    assert 'way(47879843)' in parse_qs(urlparse(requests[0][0]).query)['data'][0]


def test_parsed_osm_lookup_requires_type_and_numeric_id():
    assert chase.parsed_osm_lookup('way/47879843') == ('way', 47879843)
    with raises(ValueError, match='Invalid OpenStreetMap lookup'):
        chase.parsed_osm_lookup('47879843')


def test_load_statement_tables_raises_when_registry_table_is_unavailable(monkeypatch):
    class FakeIntrospection:
        def table_names(self):
            return []

    class FakeConnection:
        vendor = 'sqlite'
        connection = object()
        _map_my_merchants_xsv_loaded = True
        introspection = FakeIntrospection()

    with raises(RuntimeError, match='Statement registry table is unavailable'):
        xsv.load_statement_tables(FakeConnection())
