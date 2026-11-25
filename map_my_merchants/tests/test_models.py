from unittest.mock import patch

from geopy.location import Location
from pytest import mark

from map_my_merchants.models import Brand, Place


@mark.django_db
@mark.parametrize(
    ('location', 'expected'),
    (
        (
            Location('2420 Wycliff Road, Raleigh, NC, 27607', (35.8165287, -78.6923019), {}),
            (35816529, -78692302),
        ),
        (None, (None, None)),
    ),
)
def test_geocoding_preserves_integer_coordinates_and_handles_no_match(location, expected):
    place = Place.objects.create(
        address='2420 Wycliff Road, Raleigh, NC, 27607',
        brand=Brand.objects.get(statement_name='Food Lion'),
        name='Food Lion #1484',
    )
    with patch('map_my_merchants.models.Nominatim.geocode', return_value=location):
        place.set_mega_latitude_mega_longitude_from_address()
    place.refresh_from_db()
    assert (place.mega_latitude, place.mega_longitude) == expected
