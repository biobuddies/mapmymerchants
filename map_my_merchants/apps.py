from django.apps import AppConfig
from django.db.backends.signals import connection_created


class MapMyMerchantsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'map_my_merchants'
    verbose_name = 'Map My Merchants'

    def ready(self):
        from .xsv import load_sqlite_xsv_connection

        connection_created.connect(load_sqlite_xsv_connection)
