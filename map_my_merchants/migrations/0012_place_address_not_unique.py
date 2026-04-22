from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0011_place_brand')]

    operations = [
        migrations.AlterField(
            model_name='place',
            name='address',
            field=models.TextField(blank=True),
        ),
    ]
