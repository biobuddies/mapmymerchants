import django.db.models.deletion
from django.db import migrations, models


def place_brand_name(place):
    return place.name.partition(' #')[0]


def backfill_place_brand(apps, schema_editor):
    Brand = apps.get_model('map_my_merchants', 'Brand')
    Place = apps.get_model('map_my_merchants', 'Place')

    for place in Place.objects.order_by('id'):
        through_rows = place.brands.order_by('id')
        brand = through_rows.first()
        if brand is None:
            brand, _ = Brand.objects.get_or_create(
                name=place_brand_name(place), defaults={'match_pattern': ''}
            )
        place.brand = brand
        place.save(update_fields=('brand',))


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0010_brand_wikidata_id')]

    operations = [
        migrations.AddField(
            model_name='place',
            name='brand',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='places',
                to='map_my_merchants.brand',
            ),
        ),
        migrations.RunPython(backfill_place_brand, migrations.RunPython.noop),
        migrations.RemoveField(model_name='place', name='brands'),
        migrations.AlterField(
            model_name='place',
            name='brand',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='places',
                to='map_my_merchants.brand',
            ),
        ),
    ]
