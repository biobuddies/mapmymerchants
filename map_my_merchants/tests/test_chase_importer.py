from datetime import datetime

from django.test import TestCase

from map_my_merchants.management.chase import (
    ChaseRow,
    best_element,
    import_brands,
    matching_spec,
    matching_place,
    overpass_query,
    search_pattern,
)
from map_my_merchants.models import Brand, Charge, Place


class ChaseImporterTests(TestCase):
    def test_matching_spec_extracts_food_lion_store_ref(self):
        brand, store_ref = matching_spec('FOOD LION #1484')
        self.assertEqual((brand.name, store_ref), ('Food Lion', '1484'))

    def test_matching_spec_extracts_lowes_store_ref(self):
        brand, store_ref = matching_spec('LOWES #00625*')
        self.assertEqual((brand.name, store_ref), ("Lowe's", '625'))

    def test_matching_spec_extracts_chick_fil_a_store_ref(self):
        brand, store_ref = matching_spec('CHICK-FIL-A #03376')
        self.assertEqual((brand.name, store_ref), ('Chick-fil-A', '3376'))

    def test_overpass_query_regex_matches_zero_padded_and_trimmed_refs(self):
        query = overpass_query(Brand.objects.get(name="Lowe's"), '625')
        self.assertIn('["brand"~"^Lowe.*s$",i]["ref"~"0*625"]', query)
        self.assertIn('["name"~"^Lowe.*s$",i]["ref"~"0*625"]', query)
        self.assertIn('[timeout:180]', query)

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

    def test_search_pattern_tolerates_brand_punctuation(self):
        chick_fil_a = Brand.objects.get(name='Chick-fil-A')
        lowes = Brand.objects.get(name="Lowe's")
        self.assertTrue(search_pattern(chick_fil_a.match_pattern, 'Chick fil A'))
        self.assertTrue(search_pattern(chick_fil_a.match_pattern, 'Chick-fil-A'))
        self.assertTrue(search_pattern(lowes.match_pattern, 'Lowes'))
        self.assertTrue(search_pattern(lowes.match_pattern, "Lowe's"))

    def test_import_brands_reads_database_rules(self):
        self.assertEqual([brand.name for brand in import_brands()], ['Chick-fil-A', 'Food Lion', "Lowe's", "McDonald's"])


class ChaseImporterPlaceCacheTests(TestCase):
    def test_matching_place_uses_store_ref_and_fuzzy_name(self):
        place = Place.objects.create(
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
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
        )
        brand = Brand.objects.get(name="Lowe's")
        row = ChaseRow(
            amount_usd=12.34,
            brand=brand,
            description='LOWES #00625*',
            post_date=datetime(2026, 4, 20),
            store_ref='625',
            transaction_date=datetime(2026, 4, 19),
        )
        charge, _ = Charge.objects.update_or_create(
            amount_usd='12.34',
            brand=brand,
            description='LOWES #00625*',
            post_date=datetime(2026, 4, 20).date(),
            store_ref='625',
            transaction_date=datetime(2026, 4, 19).date(),
            defaults={'place': place},
        )
        self.assertEqual(
            Charge.objects.values_list(
                'amount_usd',
                'brand__name',
                'description',
                'place_id',
                'post_date',
                'store_ref',
                'transaction_date',
            ).get(),
            (
                Charge.objects.get().amount_usd,
                "Lowe's",
                'LOWES #00625*',
                place.id,
                charge.post_date,
                '625',
                charge.transaction_date,
            ),
        )

    def test_create_charge_is_idempotent_for_same_row(self):
        first_place = Place.objects.create(
            address='625 Main St',
            mega_latitude=35_000_000,
            mega_longitude=-78_000_000,
            name="Lowe's #625",
        )
        second_place = Place.objects.create(
            address='626 Main St',
            mega_latitude=35_100_000,
            mega_longitude=-78_100_000,
            name="Lowe's #625 alt",
        )
        brand = Brand.objects.get(name="Lowe's")
        row = ChaseRow(
            amount_usd=12.34,
            brand=brand,
            description='LOWES #00625*',
            post_date=datetime(2026, 4, 20),
            store_ref='625',
            transaction_date=datetime(2026, 4, 19),
        )
        first_charge, _ = Charge.objects.update_or_create(
            amount_usd='12.34',
            brand=brand,
            description='LOWES #00625*',
            post_date=datetime(2026, 4, 20).date(),
            store_ref='625',
            transaction_date=datetime(2026, 4, 19).date(),
            defaults={'place': first_place},
        )
        second_charge, _ = Charge.objects.update_or_create(
            amount_usd='12.34',
            brand=brand,
            description='LOWES #00625*',
            post_date=datetime(2026, 4, 20).date(),
            store_ref='625',
            transaction_date=datetime(2026, 4, 19).date(),
            defaults={'place': second_place},
        )
        self.assertEqual(first_charge.id, second_charge.id)
        self.assertEqual(Charge.objects.count(), 1)
        self.assertEqual(Charge.objects.get().place, second_place)
