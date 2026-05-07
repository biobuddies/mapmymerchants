from django.db import migrations


def populate_brand_pattern(apps, schema_editor):
    Brand = apps.get_model('map_my_merchants', 'Brand')
    for brand in Brand.objects.exclude(match_pattern=''):
        brand_pattern = brand.match_pattern.removeprefix('^').removesuffix('$')
        brand.pattern = f'(?P<brand>{brand_pattern}){brand.ref_pattern}'
        brand.save(update_fields=('pattern',))


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0019_add_brand_pattern')]
    operations = [migrations.RunPython(populate_brand_pattern, migrations.RunPython.noop)]
