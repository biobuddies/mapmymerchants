from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0002_place_osm_fields')]

    operations = [
        migrations.CreateModel(
            name='OSMQueryCache',
            fields=[
                (
                    'id',
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
                ),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('endpoint', models.TextField()),
                ('payload', models.JSONField()),
                ('query', models.TextField()),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name='place',
            name='osm_response',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name='place',
            name='osm_id',
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='osmquerycache',
            constraint=models.UniqueConstraint(
                fields=('endpoint', 'query'),
                name='osm_query_cache_endpoint_query_unique',
            ),
        ),
        migrations.AddConstraint(
            model_name='place',
            constraint=models.UniqueConstraint(
                fields=('osm_type', 'osm_id'),
                name='place_osm_type_osm_id_unique',
            ),
        ),
    ]
