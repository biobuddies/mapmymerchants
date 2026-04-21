from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0003_osm_query_cache_place_response')]

    operations = [migrations.DeleteModel(name='OSMQueryCache')]
