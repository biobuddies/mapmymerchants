from django.db import migrations
from django.db.models import F


def create_unknown_place_and_reassign(apps, schema_editor):
    Brand = apps.get_model('map_my_merchants', 'Brand')
    Charge = apps.get_model('map_my_merchants', 'Charge')
    Place = apps.get_model('map_my_merchants', 'Place')

    brand = Brand.objects.filter(name='TROPICAL SMOOTHIE CAFE NC').first()
    if brand is None:
        return
    unknown, _ = Place.objects.get_or_create(name='Unknown', defaults={'brand': brand})

    charges_to_reassign = Charge.objects.filter(description=F('place__name'))
    orphaned_place_ids = set(charges_to_reassign.values_list('place_id', flat=True))
    charges_to_reassign.update(place=unknown)
    if orphaned_place_ids:
        Place.objects.filter(id__in=orphaned_place_ids).delete()


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0014_remove_charge_created_updated')]

    operations = [
        migrations.RunPython(create_unknown_place_and_reassign, migrations.RunPython.noop)
    ]
