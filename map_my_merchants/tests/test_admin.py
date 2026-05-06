from pathlib import Path
from types import SimpleNamespace

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client, RequestFactory, TestCase
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
                'description',
                'line_number',
                'platform',
                'post_date',
                'raw_input',
                'raw_input_table',
                'statement',
                'transaction_date',
            ),
        )

    def test_charge_admin_formats_raw_input_as_table(self):
        place = Place.objects.create(
            address='',
            brand=Brand.objects.get(name="Lowe's"),
            name="Lowe's #625",
        )
        statement = Statement.objects.create(
            content_sha256='statement-1',
            source_name='statement-1.csv',
            source_path='/tmp/statement-1.csv',
        )
        charge = Charge.objects.create(
            amount_usd='4.56',
            description='LOWES #00625*',
            line_number=1,
            place=place,
            post_date='2026-04-20',
            raw_input={'Category': 'Home', 'Memo': ''},
            statement=statement,
            transaction_date='2026-04-20',
        )

        rendered = self.charge_admin.raw_input_table(charge)

        self.assertIsInstance(rendered, SafeString)
        self.assertIn('<table>', rendered)
        self.assertIn('<code>Category</code>', rendered)
        self.assertIn('<code>Home</code>', rendered)

    def test_statement_admin_is_read_only(self):
        self.assertFalse(self.statement_admin.has_add_permission(self.request))
        self.assertFalse(self.statement_admin.has_delete_permission(self.request))
        self.assertEqual(
            self.statement_admin.get_readonly_fields(self.request),
            ('id', 'content_sha256', 'created', 'source_name', 'source_path', 'source_preview', 'updated'),
        )

    def test_statement_admin_previews_source_data(self):
        statement_path = Path('/tmp/statement-admin-preview.csv')
        statement_path.write_text(
            'Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n'
            '04/18/2026,04/19/2026,LOWES #00625*,Home,Sale,-244.18,\n'
        )
        self.addCleanup(statement_path.unlink)
        statement = Statement.objects.create(
            content_sha256='statement-preview',
            source_name='statement-admin-preview.csv',
            source_path=str(statement_path),
        )

        rendered = self.statement_admin.source_preview(statement)

        self.assertIsInstance(rendered, SafeString)
        self.assertIn('<pre><code>', rendered)
        self.assertIn('LOWES #00625*', rendered)

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
                'osm_response_html',
                'osm_type',
                'updated',
            ),
        )

    def test_place_admin_hides_coordinates_when_incomplete(self):
        place = Place.objects.create(address='', brand=Brand.objects.get(name="Lowe's"), name="Lowe's #625")
        self.assertEqual(self.place_admin.coordinates(place), '')

    def test_place_admin_save_model_refreshes_from_osm_lookup(self):
        place = Place.objects.create(address='', brand=Brand.objects.get(name="Lowe's"), name="Lowe's #625")
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


class AdminLoadTests(TestCase):
    def setUp(self):
        User.objects.create_superuser('admin', 'admin@test.com', 'pass')
        self.client = Client()
        self.client.login(username='admin', password='pass')

    def test_brand_admin_loads(self):
        response = self.client.get('/admin/map_my_merchants/brand/')
        self.assertEqual(response.status_code, 200)

    def test_charge_admin_loads(self):
        response = self.client.get('/admin/map_my_merchants/charge/')
        self.assertEqual(response.status_code, 200)

    def test_place_admin_loads(self):
        response = self.client.get('/admin/map_my_merchants/place/')
        self.assertEqual(response.status_code, 200)

    def test_statement_admin_loads(self):
        response = self.client.get('/admin/map_my_merchants/statement/')
        self.assertEqual(response.status_code, 200)
