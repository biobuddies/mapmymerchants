from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0001_initial')]

    operations = [
        migrations.AddField(
            model_name='place',
            name='osm_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(model_name='place', name='osm_ref', field=models.TextField(blank=True)),
        migrations.AddField(
            model_name='place', name='osm_type', field=models.TextField(blank=True)
        ),
    ]
