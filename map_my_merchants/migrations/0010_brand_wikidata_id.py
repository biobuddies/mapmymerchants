from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0009_statement_charge_line_number')]

    operations = [
        migrations.AddField(
            model_name='brand',
            name='wikidata_id',
            field=models.TextField(blank=True),
        ),
    ]
