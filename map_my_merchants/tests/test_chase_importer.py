from datetime import datetime
from pathlib import Path

from django.test import TestCase
from django.db import connection

from map_my_merchants.management.chase import (
    ChaseRow,
    best_element,
    chase_brand_store_ref,
    create_placeholder_place_and_charge,
    extract_chase_rows,
    import_statement,
    lookup_brand,
    matching_place,
    overpass_query,
    place_name,
    primary_pattern,
    unresolved_places,
)
from map_my_merchants.models import Brand, Charge, Place, Statement
from map_my_merchants.xsv import load_statement_tables


def _match_spec(description):
    # dup: chase_brand_store_ref primary_pattern logic
    match = primary_pattern().search(description)
    if not match:
        return None
    brand = lookup_brand(match.group('brand'))
    return brand, match.group('ref').lstrip('0') or '0'


class ChaseImporterTests(TestCase):
    def test_import_statement_reuses_existing_csv_hash(self):
        csv_path = Path('/tmp/tmp-test-import-statement.csv')
        csv_path.write_text('Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n')
        self.addCleanup(csv_path.unlink)
        first = import_statement(csv_path)
        second = import_statement(csv_path)
        self.assertEqual(first.id, second.id)
        self.assertEqual(Statement.objects.filter(source_name='tmp-test-import-statement.csv').count(), 1)

    def test_extract_chase_rows_reads_registered_statement_path(self):
        csv_path = Path('/tmp/tmp-test-extract-chase-rows.csv')
        csv_path.write_text(
            'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
            '04/17/2026,04/19/2026,FOOD LION #1484,Groceries,Sale,-46.20,\n'
        )
        self.addCleanup(csv_path.unlink)

        statement = import_statement(csv_path)

        self.assertEqual(
            [
                (row.line_number, row.description, row.raw_input['Category'])
                for row in extract_chase_rows(statement)
            ],
            [(1, 'FOOD LION #1484', 'Groceries')],
        )

    def test_load_statement_tables_makes_registered_statement_available(self):
        csv_path = Path('/tmp/tmp-test-load-statement-tables.csv')
        csv_path.write_text(
            'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
            '04/18/2026,04/19/2026,LOWES #00625*,Home,Sale,-244.18,\n'
        )
        self.addCleanup(csv_path.unlink)
        statement = import_statement(csv_path)

        load_statement_tables()

        with connection.cursor() as cursor:
            cursor.execute("select name from sqlite_temp_master where type = 'table'")
            self.assertIn(f'statement_{statement.id}', {name for name, in cursor.fetchall()})

    def test_matching_spec_extracts_food_lion_store_ref(self):
        brand, store_ref = _match_spec('FOOD LION #1484')
        self.assertEqual((brand.name, store_ref), ('Food Lion', '1484'))

    def test_matching_spec_extracts_lowes_store_ref(self):
        brand, store_ref = _match_spec('LOWES #00625*')
        self.assertEqual((brand.name, store_ref), ("Lowe's", '625'))

    def test_matching_spec_extracts_chick_fil_a_store_ref(self):
        brand, store_ref = _match_spec('CHICK-FIL-A #03376')
        self.assertEqual((brand.name, store_ref), ('Chick-fil-A', '3376'))

    def test_overpass_query_uses_exact_brand_and_substring_ref(self):
        query = overpass_query(Brand.objects.get(name="Lowe's"), '625')
        self.assertIn('["brand"="Lowe\'s"]["ref"~"625"]', query)
        self.assertIn('[timeout:180]', query)
        self.assertNotIn('name', query)

    def test_best_element_prefers_exact_brand_and_address(self):
        node = {
            'id': 1,
            'lat': 35.0,
            'lon': -78.0,
            'tags': {'brand': "Lowe's", 'ref': '00625'},
            'type': 'node',
        }
        way = {
            'center': {'lat': 35.1, 'lon': -78.1},
            'id': 2,
            'tags': {
                'addr:housenumber': '123',
                'addr:street': 'Main St',
                'brand': "Lowe's",
                'ref': '625',
            },
            'type': 'way',
        }
        self.assertEqual(best_element(Brand.objects.get(name="Lowe's"), '625', [node, way]), way)

    def test_primary_pattern_tolerates_brand_punctuation(self):
        self.assertTrue(primary_pattern().search('Chick fil A #03376'))
        self.assertTrue(primary_pattern().search('Chick-fil-A #03376'))
        self.assertTrue(primary_pattern().search('Lowes #00625'))
        self.assertTrue(primary_pattern().search("Lowe's #00625"))

    def test_primary_pattern_skips_descriptions_without_ref(self):
        self.assertIsNone(primary_pattern().search('PAYPAL'))
        self.assertIsNone(primary_pattern().search('APPLE.COM/BILL'))
        self.assertIsNone(primary_pattern().search('AMAZON MKTPL*BC8AND3900'))

    def test_unresolved_places_returns_places_missing_coordinates(self):
        lowes = Brand.objects.get(name="Lowe's")
        food_lion = Brand.objects.get(name='Food Lion')
        Place.objects.create(
            address='1 Main St',
            brand=lowes,
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
            osm_ref='625',
        )
        unresolved = Place.objects.create(
            address='',
            brand=food_lion,
            name='Food Lion #1484',
            osm_ref='1484',
        )
        self.assertEqual(unresolved_places(), (unresolved,))


class ChaseImporterPlaceCacheTests(TestCase):
    def test_matching_place_uses_store_ref_and_fuzzy_name(self):
        place = Place.objects.create(
            brand=Brand.objects.get(name="Lowe's"),
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
            osm_id=47749318,
            osm_ref='625',
            osm_response={'tags': {'brand': "Lowe's", 'name': "Lowe's"}},
            osm_type='way',
        )
        self.assertEqual(matching_place(Brand.objects.get(name="Lowe's"), '625'), place)

    def test_create_charge_links_brand_and_place(self):
        place = Place.objects.create(
            brand=Brand.objects.get(name="Lowe's"),
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
        )
        brand = Brand.objects.get(name="Lowe's")
        statement = Statement.objects.create(
            content_sha256='statement-1',
            source_name='statement-1.csv',
            source_path='/tmp/statement-1.csv',
        )
        row = ChaseRow(
            amount_usd=12.34,
            brand=brand,
            description='LOWES #00625*',
            line_number=1,
            post_date=datetime(2026, 4, 20),
            raw_input={'Description': 'LOWES #00625*'},
            statement=statement,
            store_ref='625',
            transaction_date=datetime(2026, 4, 19),
        )
        charge, _ = Charge.objects.update_or_create(
            line_number=1,
            statement=statement,
            defaults={
                'amount_usd': '12.34',
                'description': 'LOWES #00625*',
                'place': place,
                'post_date': datetime(2026, 4, 20).date(),
                'raw_input': row.raw_input,
                'transaction_date': datetime(2026, 4, 19).date(),
            },
        )
        self.assertEqual(
            Charge.objects.values_list(
                'amount_usd',
                'description',
                'line_number',
                'place_id',
                'post_date',
                'raw_input',
                'statement_id',
                'transaction_date',
            ).get(),
            (
                Charge.objects.get().amount_usd,
                'LOWES #00625*',
                1,
                place.id,
                charge.post_date,
                {'Description': 'LOWES #00625*'},
                statement.id,
                charge.transaction_date,
            ),
        )

    def test_create_placeholder_place_and_charge_links_charge(self):
        brand = Brand.objects.get(name="Lowe's")
        statement = Statement.objects.create(
            content_sha256='statement-2',
            source_name='statement-2.csv',
            source_path='/tmp/statement-2.csv',
        )
        row = ChaseRow(
            amount_usd=12.34,
            brand=brand,
            description='LOWES #00625*',
            line_number=1,
            post_date=datetime(2026, 4, 20),
            raw_input={'Description': 'LOWES #00625*'},
            statement=statement,
            store_ref='625',
            transaction_date=datetime(2026, 4, 19),
        )
        self.assertEqual(
            create_placeholder_place_and_charge(row),
            {'place': "Lowe's #625", 'ref': '625', 'status': 'created-place'},
        )
        place = Place.objects.get(name=place_name(brand, row.description, '625'))
        self.assertEqual(place.address, '')
        self.assertEqual(place.brand, brand)
        self.assertEqual(Charge.objects.get().place, place)
        self.assertEqual(Charge.objects.get().raw_input, {'Description': 'LOWES #00625*'})

    def test_place_latitude_longitude_is_blank_when_coordinate_missing(self):
        place = Place.objects.create(address='', brand=Brand.objects.get(name="Lowe's"), name="Lowe's #625")
        self.assertEqual(place.latitude_longitude, '')

    def test_create_charge_is_idempotent_for_same_row(self):
        first_place = Place.objects.create(
            address='625 Main St',
            brand=Brand.objects.get(name="Lowe's"),
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
        )
        brand = Brand.objects.get(name="Lowe's")
        statement = Statement.objects.create(
            content_sha256='statement-3',
            source_name='statement-3.csv',
            source_path='/tmp/statement-3.csv',
        )
        row = ChaseRow(
            amount_usd=12.34,
            brand=brand,
            description='LOWES #00625*',
            line_number=1,
            post_date=datetime(2026, 4, 20),
            raw_input={'Description': 'LOWES #00625*'},
            statement=statement,
            store_ref='625',
            transaction_date=datetime(2026, 4, 19),
        )
        first_charge, _ = Charge.objects.update_or_create(
            line_number=1,
            statement=statement,
            defaults={
                'amount_usd': '12.34',
                'description': 'LOWES #00625*',
                'place': first_place,
                'post_date': datetime(2026, 4, 20).date(),
                'raw_input': row.raw_input,
                'transaction_date': datetime(2026, 4, 19).date(),
            },
        )
        second_charge, _ = Charge.objects.update_or_create(
            line_number=1,
            statement=statement,
            defaults={
                'amount_usd': '12.34',
                'description': 'LOWES #00625*',
                'place': first_place,
                'post_date': datetime(2026, 4, 20).date(),
                'raw_input': {'Description': 'LOWES #00625*', 'Memo': 'updated'},
                'transaction_date': datetime(2026, 4, 19).date(),
            },
        )
        self.assertEqual(first_charge.id, second_charge.id)
        self.assertEqual(Charge.objects.count(), 1)
        self.assertEqual(Charge.objects.get().place, first_place)
        self.assertEqual(Charge.objects.get().raw_input['Memo'], 'updated')

    def test_place_name_uses_brand_name_when_store_ref_missing(self):
        brand = Brand.objects.get(name="Lowe's")
        self.assertEqual(place_name(brand, 'LOWES RALEIGH', ''), "Lowe's")
