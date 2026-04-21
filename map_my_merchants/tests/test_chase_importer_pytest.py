from io import BytesIO
from urllib.parse import parse_qs, urlparse

from pytest import mark

from map_my_merchants.management import chase
from map_my_merchants.models import Charge, Place


@mark.django_db
def test_import_latest_places_mocks_overpass_response(monkeypatch, tmp_path):
    csv_path = tmp_path / 'chase.csv'
    csv_path.write_text(
        'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
        '04/19/2026,04/20/2026,LOWES #00625*,Shopping,Sale,-12.34,\n'
    )
    payload = (
        '{"elements":[{"center":{"lat":35.868915,"lon":-78.718725},"id":47879843,'
        '"tags":{"addr:city":"Raleigh","addr:housenumber":"4831","addr:postcode":"27613",'
        '"addr:state":"NC","addr:street":"Grove Barton Road","brand":"Lowe\'s",'
        '"name":"Lowe\'s","ref":"0625"},"type":"way"}]}'
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

    assert chase.import_latest_places(csv_path, 'https://overpass.invalid/api/interpreter', 5) == [
        {'brand': 'Chick-fil-A', 'status': 'missing-transaction'},
        {'brand': 'Food Lion', 'status': 'missing-transaction'},
        {'brand': "Lowe's", 'osm_id': '47879843', 'ref': '625', 'status': 'imported'},
        {'brand': "McDonald's", 'status': 'missing-transaction'},
    ]
    assert Place.objects.get(name="Lowe's #625").osm_id == 47879843
    assert Charge.objects.get(brand__name="Lowe's").place.osm_id == 47879843
    assert requests[0][1] == 5
    assert urlparse(requests[0][0]).netloc == 'overpass.invalid'
    assert 'ref"~"0*625"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]
    assert 'brand"~"^Lowe.*s$"' in parse_qs(urlparse(requests[0][0]).query)['data'][0]
