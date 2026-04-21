from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0004_delete_osm_query_cache')]

    operations = [
        migrations.RenameModel(old_name='Business', new_name='Brand'),
        migrations.AlterModelOptions(name='brand', options={'verbose_name_plural': 'Brands'}),
        migrations.RenameField(model_name='place', old_name='businesses', new_name='brands'),
        migrations.CreateModel(
            name='Charge',
            fields=[
                (
                    'id',
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID'),
                ),
                ('amount_usd', models.DecimalField(decimal_places=2, max_digits=12)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('description', models.TextField()),
                ('post_date', models.DateField()),
                ('store_ref', models.TextField(blank=True)),
                ('transaction_date', models.DateField()),
                ('updated', models.DateTimeField(auto_now=True)),
                (
                    'brand',
                    models.ForeignKey(
                        on_delete=models.deletion.PROTECT,
                        related_name='charges',
                        to='map_my_merchants.brand',
                    ),
                ),
                (
                    'place',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=models.deletion.SET_NULL,
                        related_name='charges',
                        to='map_my_merchants.place',
                    ),
                ),
            ],
            options={'ordering': ('-transaction_date', '-post_date', '-id')},
        ),
    ]
