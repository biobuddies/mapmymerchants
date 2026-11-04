from django.db import migrations


def create_online_place(apps, schema_editor):
    Brand = apps.get_model('map_my_merchants', 'Brand')
    Place = apps.get_model('map_my_merchants', 'Place')
    brand = Brand.objects.filter(name__iendswith='everydaydose').first()
    if brand is None:
        return
    Place.objects.get_or_create(
        name='Online', defaults={'brand': brand, 'mega_latitude': None, 'mega_longitude': None}
    )


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0012_place_address_not_unique')]

    operations = [migrations.RunPython(create_online_place, migrations.RunPython.noop)]
