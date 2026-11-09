from ast import literal_eval, parse
from importlib import import_module
from pathlib import Path
from shutil import copytree, ignore_patterns

from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from pytest import fixture, mark

from map_my_merchants.management.commands.reseed import prune_seed
from map_my_merchants.models import Brand, Place


@fixture
def seed_directory(tmp_path, monkeypatch, settings):
    module = f'seed_{tmp_path.name}'
    directory = tmp_path / module
    copytree(
        Path(__file__).parents[1] / 'migrations', directory, ignore=ignore_patterns('__pycache__')
    )
    monkeypatch.syspath_prepend(tmp_path)
    settings.MIGRATION_MODULES = {'map_my_merchants': module}
    Brand.objects.update(private=None)
    Place.objects.update(private=None)
    return directory


@mark.django_db
def test_reseed_exports_only_explicitly_public_brands_and_places(seed_directory):
    brand = Brand.objects.get(statement_name='Food Lion')
    assert brand.private is None
    brand.private = False
    brand.save()
    private_brand = Brand.objects.get(statement_name="Lowe's")
    private_brand.private = True
    private_brand.save()
    unknown_brand = Brand.objects.get(statement_name='Chick-fil-A')
    place = Place.objects.create(
        address='Raleigh, NC',
        brand=brand,
        mega_latitude=35816529,
        mega_longitude=-78692302,
        name='Food Lion #1484',
        osm_ref='1484',
        private=False,
    )
    Place.objects.create(brand=brand, name='Food Lion #536', private=True)
    Place.objects.create(brand=brand, name='Food Lion', private=None)
    Place.objects.create(brand=private_brand, name="Lowe's #625", private=False)
    Place.objects.create(brand=unknown_brand, name='Chick-fil-A #3376', private=False)

    previous = set(seed_directory.glob('*_seed.py'))
    call_command('reseed')

    (migration_path,) = set(seed_directory.glob('*_seed.py')) - previous
    seed = import_module(f'{seed_directory.name}.{migration_path.stem}')
    assert (
        {'display_name': brand.display_name, 'statement_name': 'Food Lion', 'wikidata_id': ''},
    ) == seed.BRANDS
    assert len(seed.PLACES) == 1
    assert seed.PLACES[0]['brand'] == 'Food Lion'
    assert seed.PLACES[0]['name'] == 'Food Lion #1484'
    assert seed.PLACES[0]['mega_latitude'] == 35816529
    assert not {'id', 'created', 'updated', 'updated_by'} & seed.BRANDS[0].keys()
    assert seed.Migration.operations[0].reverse_code.__name__ == 'noop'
    assert 'shell_plus' in migration_path.read_text()
    place.delete()
    seed.seed(apps, connection.schema_editor())
    seed.seed(apps, connection.schema_editor())
    restored = Place.objects.get(name='Food Lion #1484')
    assert restored.brand == brand
    assert restored.private is False
    assert restored.mega_latitude == 35816529


@mark.django_db
def test_reseed_prunes_superseded_and_newly_private_rows(seed_directory):
    brand = Brand.objects.get(statement_name='Food Lion')
    brand.private = False
    brand.save()
    place = Place.objects.create(brand=brand, name='Food Lion #1484', private=False)
    previous = set(seed_directory.glob('*_seed.py'))
    call_command('reseed')
    (first,) = set(seed_directory.glob('*_seed.py')) - previous
    brand.display_name = 'FOOD LION'
    brand.save()
    place.private = None
    place.save()

    call_command('reseed')

    first_seed = parse(first.read_text())
    assignments = {
        node.targets[0].id: literal_eval(node.value)
        for node in first_seed.body
        if hasattr(node, 'targets')
    }
    assert assignments == {'BRANDS': (), 'PLACES': ()}
    (second,) = set(seed_directory.glob('*_seed.py')) - previous - {first}
    seed = import_module(f'{seed_directory.name}.{second.stem}')
    assert seed.BRANDS[0]['display_name'] == 'FOOD LION'
    assert seed.PLACES == ()
    assert seed.Migration.dependencies == [('map_my_merchants', first.stem)]
    assert not MigrationLoader(connection).detect_conflicts()
    assert Place.objects.get(pk=place.pk).private is None


def test_prune_seed_preserves_other_rows_and_migration_code():
    source = (
        "BRANDS = ({'statement_name': 'Food Lion'}, {'statement_name': 'Chick-fil-A'})\n"
        "PLACES = ({'name': 'Food Lion #1484'}, {'name': 'Chick-fil-A #3376'})\n"
        "dependencies = [('map_my_merchants', '0024_brand_place_private')]\n"
    )
    pruned = prune_seed(
        source,
        {'BRANDS': ('statement_name', {'Food Lion'}), 'PLACES': ('name', {'Food Lion #1484'})},
    )
    assert "BRANDS = ({'statement_name': 'Chick-fil-A'},)" in pruned
    assert "PLACES = ({'name': 'Chick-fil-A #3376'},)" in pruned
    assert source.splitlines()[-1] == pruned.splitlines()[-1]
