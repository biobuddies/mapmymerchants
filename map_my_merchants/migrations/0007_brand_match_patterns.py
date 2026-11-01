from django.db import migrations, models


def load_brand_match_patterns(apps, schema_editor):
    Brand = apps.get_model('map_my_merchants', 'Brand')
    rules = {
        'Chick-fil-A': {
            'chase_ref_pattern': r'\s+#(?P<ref>\d+)',
            'match_pattern': r'^Chick.*fil.*A$',
        },
        'Food Lion': {'chase_ref_pattern': r'\s+#?(?P<ref>\d+)', 'match_pattern': r'^Food.*Lion$'},
        "Lowe's": {'chase_ref_pattern': r'\s+#?(?P<ref>\d+)', 'match_pattern': r'^Lowe.*s$'},
        "McDonald's": {
            'chase_ref_pattern': r'(?:\s+#?|\s+)(?P<ref>\d+)',
            'match_pattern': r'^McDonald.*s$',
        },
    }
    for name, fields in rules.items():
        brand, created = Brand.objects.update_or_create(name=name, defaults=fields)
        if created and not brand.display_name:
            brand.display_name = name
            brand.save(update_fields=['display_name'])
        elif not brand.display_name:
            Brand.objects.filter(pk=brand.pk).update(display_name=name)


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0006_charge_charge_identity_unique')]

    operations = [
        migrations.AddField(
            model_name='brand',
            name='display_name',
            field=models.TextField(blank=True, null=True),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='brand',
            name='chase_ref_pattern',
            field=models.TextField(default=r'\s+#?(?P<ref>\d+)'),
        ),
        migrations.AddField(
            model_name='brand', name='match_pattern', field=models.TextField(default='')
        ),
        migrations.RunPython(load_brand_match_patterns, migrations.RunPython.noop),
    ]
