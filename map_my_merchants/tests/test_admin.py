from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite
from django.test import RequestFactory, TestCase
from django.utils.safestring import SafeString

from map_my_merchants import admin as admin_module
from map_my_merchants.admin import BrandAdmin, ChargeAdmin, PlaceAdmin, StatementAdmin
from map_my_merchants.models import Brand, Charge, Place, Statement


class AdminTests(TestCase):
    def setUp(self):
        self.request = RequestFactory().get('/admin/')
        self.brand_admin = BrandAdmin(Brand, AdminSite())
        self.charge_admin = ChargeAdmin(Charge, AdminSite())
        self.place_admin = PlaceAdmin(Place, AdminSite())
        self.statement_admin = StatementAdmin(Statement, AdminSite())

    def test_brand_admin_is_read_only(self):
        self.assertFalse(self.brand_admin.has_add_permission(self.request))
        self.assertFalse(self.brand_admin.has_delete_permission(self.request))
        self.assertEqual(
            self.brand_admin.get_readonly_fields(self.request),
            ('id', 'chase_ref_pattern', 'created', 'match_pattern', 'name', 'updated', 'wikidata_id'),
        )

    def test_charge_admin_only_allows_place_edit(self):
        self.assertFalse(self.charge_admin.has_add_permission(self.request))
        self.assertFalse(self.charge_admin.has_delete_permission(self.request))
        self.assertEqual(
            self.charge_admin.get_readonly_fields(self.request),
            (
                'id',
                'amount_usd',
                'created',
                'description',
                'line_number',
                'post_date',
                'raw_input',
                'raw_input_table',
                'statement',
                'transaction_date',
                'updated',
            ),
        )

    def test_charge_admin_formats_raw_input_as_table(self):
        place = Place.objects.create(
            address='',
            brand=Brand.objects.create(name='Starbucks'),
            name='Starbucks #1234',
        )
        statement = Statement.objects.create(
            content_sha256='statement-1',
            source_name='statement-1.csv',
            source_path='/tmp/statement-1.csv',
        )
        charge = Charge.objects.create(
            amount_usd='4.56',
            description='Starbucks 1234',
            line_number=1,
            place=place,
            post_date='2026-04-20',
            raw_input={'Category': 'Coffee', 'Memo': ''},
            statement=statement,
            transaction_date='2026-04-20',
        )

        rendered = self.charge_admin.raw_input_table(charge)

        self.assertIsInstance(rendered, SafeString)
        self.assertIn('<table>', rendered)
        self.assertIn('<code>Category</code>', rendered)
        self.assertIn('<code>Coffee</code>', rendered)

    def test_statement_admin_is_read_only(self):
        self.assertFalse(self.statement_admin.has_add_permission(self.request))
        self.assertFalse(self.statement_admin.has_delete_permission(self.request))
        self.assertEqual(
            self.statement_admin.get_readonly_fields(self.request),
            ('id', 'content_sha256', 'created', 'source_name', 'source_path', 'updated'),
        )

    def test_place_admin_is_read_only(self):
        self.assertFalse(self.place_admin.has_add_permission(self.request))
        self.assertFalse(self.place_admin.has_delete_permission(self.request))
        self.assertEqual(
            self.place_admin.get_readonly_fields(self.request),
            (
                'id',
                'address',
                'brand',
                'coordinates',
                'created',
                'mega_latitude',
                'mega_longitude',
                'name',
                'osm_id',
                'osm_link',
                'osm_ref',
                'osm_response',
                'osm_type',
                'updated',
            ),
        )

    def test_place_admin_hides_coordinates_when_incomplete(self):
        place = Place.objects.create(address='', brand=Brand.objects.create(name='Starbucks'), name='Starbucks #1234')
        self.assertEqual(self.place_admin.coordinates(place), '')

    def test_place_admin_save_model_refreshes_from_osm_lookup(self):
        place = Place.objects.create(address='', brand=Brand.objects.create(name='Starbucks'), name='Starbucks #1234')
        calls = []

        def fake_refresh(*args, **kwargs):
            calls.append((args, kwargs))

        original_refresh = admin_module.refresh_place_from_osm_lookup
        admin_module.refresh_place_from_osm_lookup = fake_refresh
        self.addCleanup(setattr, admin_module, 'refresh_place_from_osm_lookup', original_refresh)

        self.place_admin.save_model(
            self.request,
            place,
            SimpleNamespace(cleaned_data={'osm_lookup': 'way/47879843'}),
            change=True,
        )

        self.assertEqual(calls[0][0], (place, 'way/47879843'))
