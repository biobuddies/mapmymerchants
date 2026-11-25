import django.db.models.deletion
from django.db import migrations, models


def charge_place_name(brand_name, description, store_ref):
    return f'{brand_name} #{store_ref}' if store_ref else description


def charge_place_address(brand_name, description, store_ref):
    return f'pending:{brand_name}#{store_ref}' if store_ref else f'pending:{description}'


def backfill_charge_place_and_raw_input(apps, schema_editor):
    Charge = apps.get_model('map_my_merchants', 'Charge')
    Place = apps.get_model('map_my_merchants', 'Place')

    for charge in Charge.objects.select_related('brand', 'place').order_by('id'):
        charge.raw_input = {
            'Brand': charge.brand.name,
            'Description': charge.description,
            'Store Ref': charge.store_ref,
        }
        place = charge.place
        if place is None:
            place, _ = Place.objects.get_or_create(
                name=charge_place_name(charge.brand.name, charge.description, charge.store_ref),
                defaults={
                    'address': charge_place_address(
                        charge.brand.name, charge.description, charge.store_ref
                    ),
                    'osm_ref': charge.store_ref,
                },
            )
        charge.place = place
        charge.save(update_fields=('place', 'raw_input'))
        place.brands.add(charge.brand)


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0007_brand_match_patterns')]

    operations = [
        migrations.AddField(
            model_name='charge', name='raw_input', field=models.JSONField(blank=True, default=dict)
        ),
        migrations.RunPython(backfill_charge_place_and_raw_input, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='charge', name='charge_identity_unique'),
        migrations.AlterField(
            model_name='charge',
            name='place',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='charges',
                to='map_my_merchants.place',
            ),
        ),
        migrations.RemoveField(model_name='charge', name='brand'),
        migrations.RemoveField(model_name='charge', name='store_ref'),
        migrations.AddConstraint(
            model_name='charge',
            constraint=models.UniqueConstraint(
                fields=('amount_usd', 'description', 'place', 'post_date', 'transaction_date'),
                name='charge_identity_unique',
            ),
        ),
    ]
