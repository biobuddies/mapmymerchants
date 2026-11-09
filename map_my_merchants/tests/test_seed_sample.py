from importlib import import_module

from django.apps import apps
from django.db import connection
from pytest import mark

from map_my_merchants.models import Brand, Place

sample = import_module('map_my_merchants.migrations.0025_seed')


@mark.django_db
def test_seed_sample_contains_raleigh_locations_and_online_brands():
    places = Place.objects.filter(name__in=[row['name'] for row in sample.PLACES])
    assert 10 <= places.count() <= 20
    assert (
        places.filter(
            mega_latitude__range=(35_600_000, 36_100_000),
            mega_longitude__range=(-79_100_000, -78_300_000),
        ).count()
        == places.count()
    )
    online = {'EVERYDAYDOSE', 'FACTOR75LLC', 'HUNGRYROOT.COM', 'NewBalance.com', 'TARGET.COM'}
    assert Brand.objects.filter(statement_name__in=online, private=False).count() == len(online)
    assert not places.filter(address='').exists()
    assert all(
        row['brand'] in {brand['statement_name'] for brand in sample.BRANDS}
        for row in sample.PLACES
    )


@mark.django_db
def test_seed_sample_replays_without_changing_privacy_decisions():
    brand = Brand.objects.get(statement_name='EVERYDAYDOSE')
    brand.private = True
    brand.save()
    place = Place.objects.get(name='Circle K #6119')
    place.private = None
    place.save()
    sample.seed(apps, connection.schema_editor())
    sample.seed(apps, connection.schema_editor())
    brand.refresh_from_db()
    place.refresh_from_db()
    assert brand.private is True
    assert place.private is None
    assert Place.objects.filter(name__in=[row['name'] for row in sample.PLACES]).count() == 10
