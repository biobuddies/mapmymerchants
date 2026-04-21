from django.test import SimpleTestCase, TestCase

from map_my_merchants.management.chase import (
    TARGETS,
    best_element,
    matching_spec,
    matching_place,
    overpass_query,
)
from map_my_merchants.models import Place


class ChaseImporterTests(SimpleTestCase):
    def test_matching_spec_extracts_food_lion_store_ref(self):
        self.assertEqual(matching_spec('FOOD LION #1484'), (TARGETS[1], '1484'))

    def test_matching_spec_extracts_lowes_store_ref(self):
        self.assertEqual(matching_spec('LOWES #00625*'), (TARGETS[2], '625'))

    def test_matching_spec_extracts_chick_fil_a_store_ref(self):
        self.assertEqual(matching_spec('CHICK-FIL-A #03376'), (TARGETS[0], '3376'))

    def test_overpass_query_searches_zero_padded_and_trimmed_refs(self):
        query = overpass_query(TARGETS[2], '625')
        self.assertIn('["ref"="00625"]', query)
        self.assertIn('["ref"="625"]', query)
        self.assertIn("Lowe's", query)
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
        self.assertEqual(best_element(TARGETS[2], '625', [node, way]), way)

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
        self.assertEqual(matching_place(TARGETS[2], '625'), place)
