from django.db import migrations


def create_platforms_and_assign_charges(apps, schema_editor):
    Charge = apps.get_model('map_my_merchants', 'Charge')
    Platform = apps.get_model('map_my_merchants', 'Platform')

    platforms = {
        'Toast': r'^TST',
        'Shopify': r'^SP',
    }
    for name, pattern in platforms.items():
        platform, _ = Platform.objects.get_or_create(
            name=name,
            defaults={'pattern': pattern},
        )
        Charge.objects.filter(description__regex=pattern).update(platform=platform)


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0016_platform_charge_platform')]

    operations = [migrations.RunPython(create_platforms_and_assign_charges, migrations.RunPython.noop)]
