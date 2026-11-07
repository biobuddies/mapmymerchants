"""Preserve merchant data through schema upgrades."""

from django.conf import settings
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from pytest import mark


@mark.django_db(transaction=True)
def test_brand_names_and_provenance_preserve_existing_data():
    executor = MigrationExecutor(connection)
    previous = [
        ('map_my_merchants', '0022_drop_brand_pattern'),
        *executor.loader.graph.leaf_nodes(settings.AUTH_USER_MODEL.split('.')[0]),
    ]
    current = [('map_my_merchants', '0023_brand_names_and_provenance')]
    executor.migrate(previous)
    try:
        apps = executor.loader.project_state(previous).apps
        Brand = apps.get_model('map_my_merchants', 'Brand')
        Place = apps.get_model('map_my_merchants', 'Place')
        User = apps.get_model(settings.AUTH_USER_MODEL)
        brand = Brand.objects.create(name='EXISTING MERCHANT', wikidata_id='Q123')
        named = Brand.objects.create(name='NAMED MERCHANT', display_name='Custom name')
        place = Place.objects.create(brand=brand, name='Existing shop', address='123 Main Street')
        User.objects.filter(username__in=('from-statement', 'from-openstreetmap')).delete()
        user = User.objects.create(username='from-statement', is_active=True)

        executor = MigrationExecutor(connection)
        executor.migrate(current)
        apps = executor.loader.project_state(current).apps
        Brand = apps.get_model('map_my_merchants', 'Brand')
        Place = apps.get_model('map_my_merchants', 'Place')
        User = apps.get_model(settings.AUTH_USER_MODEL)
        migrated = Brand.objects.get(pk=brand.pk)
        assert migrated.statement_name == migrated.display_name == 'EXISTING MERCHANT'
        assert migrated.wikidata_id == 'Q123'
        assert migrated.updated_by_id is None
        assert Brand.objects.get(pk=named.pk).display_name == 'Custom name'
        assert Brand._meta.get_field('statement_name').db_column == 'name'
        assert Place.objects.get(pk=place.pk).brand_id == brand.pk
        assert User.objects.get(username='from-statement').pk == user.pk
        assert User.objects.get(pk=user.pk).is_active
        generated = User.objects.get(username='from-openstreetmap')
        assert not generated.is_active
        assert generated.password.startswith('!')
    finally:
        MigrationExecutor(connection).migrate(current)
