from ast import Assign, Name, literal_eval, parse
from pathlib import Path
from pprint import pformat

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.migration import Migration
from django.db.migrations.writer import MigrationWriter

from map_my_merchants.models import Brand, Place

SEED_CODE = """

def seed(apps, schema_editor):
    database = schema_editor.connection.alias
    Brand = apps.get_model('map_my_merchants', 'Brand')
    Place = apps.get_model('map_my_merchants', 'Place')
    for row in BRANDS:
        Brand.objects.using(database).update_or_create(
            statement_name=row['statement_name'],
            defaults=row,
            create_defaults={**row, 'private': False},
        )
    brands = dict(
        Brand.objects.using(database)
        .exclude(private=True)
        .values_list('statement_name', 'pk')
    )
    for row in PLACES:
        if row['brand'] not in brands:
            continue
        fields = {key: value for key, value in row.items() if key != 'brand'}
        fields['brand_id'] = brands[row['brand']]
        Place.objects.using(database).update_or_create(
            name=row['name'],
            defaults=fields,
            create_defaults={**fields, 'private': False},
        )


class Migration(migrations.Migration):
    dependencies = %(dependencies)s

    # Reversals are rare; draft filters in shell_plus, review the rows, then chain .delete().
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
"""


def prune_seed(source: str, identities: dict[str, tuple[str, set[str]]]) -> str:
    lines = source.splitlines(keepends=True)
    for node in reversed(parse(source).body):
        if not (
            isinstance(node, Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], Name)
            and node.targets[0].id in identities
        ):
            continue
        name = node.targets[0].id
        field, values = identities[name]
        rows = literal_eval(node.value)
        remaining = tuple(row for row in rows if row[field] not in values)
        if len(remaining) != len(rows):
            lines[node.lineno - 1 : node.end_lineno] = [
                f'{name} = {pformat(remaining, width=100)}\n'
            ]
    return ''.join(lines)


class Command(BaseCommand):
    help = 'Snapshot explicitly public brands and places and prune superseded seed rows.'

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument('--database', default=DEFAULT_DB_ALIAS)

    def handle(self, *args, **options) -> None:
        database = options['database']
        loader = MigrationLoader(connections[database])
        dependencies = loader.graph.leaf_nodes('map_my_merchants')
        if len(dependencies) != 1:
            raise CommandError('Merge the map_my_merchants migration branches before reseeding.')
        parent = dependencies[0][1]
        name = f'{int(parent.split("_", 1)[0]) + 1:04d}_seed'
        path = Path(MigrationWriter(Migration(name, 'map_my_merchants')).path)
        if path.exists():
            raise CommandError(f'Migration already exists: {path}')
        with transaction.atomic(using=database):
            brands = tuple(
                Brand.objects
                .using(database)
                .filter(private=False)
                .order_by('statement_name')
                .values('display_name', 'statement_name', 'wikidata_id')
            )
            places = tuple(
                {
                    ('brand' if key == 'brand__statement_name' else key): value
                    for key, value in row.items()
                }
                for row in Place.objects
                .using(database)
                .filter(private=False, brand__private=False)
                .order_by('name')
                .values(
                    'address',
                    'brand__statement_name',
                    'mega_latitude',
                    'mega_longitude',
                    'name',
                    'osm_id',
                    'osm_ref',
                    'osm_response',
                    'osm_type',
                )
            )
            identities = {
                'BRANDS': (
                    'statement_name',
                    set(Brand.objects.using(database).values_list('statement_name', flat=True)),
                ),
                'PLACES': (
                    'name',
                    set(Place.objects.using(database).values_list('name', flat=True)),
                ),
            }
        updates = {}
        for app_label, migration_name in loader.graph.forwards_plan(dependencies[0]):
            if app_label != 'map_my_merchants' or 'seed' not in migration_name:
                continue
            previous = Path(MigrationWriter(loader.disk_migrations[app_label, migration_name]).path)
            source = previous.read_text()
            try:
                pruned = prune_seed(source, identities)
            except (KeyError, TypeError, ValueError) as error:
                raise CommandError(f'Cannot prune seed rows in {previous}: {error}') from error
            if source != pruned:
                updates[previous] = pruned
        source = '\n\n'.join((
            'from django.db import migrations',
            f'BRANDS = {pformat(brands, width=100)}',
            f'PLACES = {pformat(places, width=100)}',
        )) + SEED_CODE % {'dependencies': repr(dependencies)}
        with path.open('x') as destination:
            destination.write(source)
        for previous, pruned in updates.items():
            previous.write_text(pruned)
            self.stdout.write(f'Pruned {previous}')
        self.stdout.write(f'Created {path}: {len(brands)} brands, {len(places)} places')
