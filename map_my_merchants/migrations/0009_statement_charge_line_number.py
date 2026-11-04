from django.db import migrations, models
import django.db.models.deletion


def backfill_charge_statement(apps, schema_editor):
    Charge = apps.get_model('map_my_merchants', 'Charge')
    Statement = apps.get_model('map_my_merchants', 'Statement')
    statement, _ = Statement.objects.get_or_create(
        content_sha256='legacy-import', defaults={'source_name': 'legacy-import', 'source_path': ''}
    )
    for line_number, charge in enumerate(Charge.objects.order_by('id'), start=1):
        charge.line_number = line_number
        charge.statement = statement
        charge.save(update_fields=('line_number', 'statement'))


class Migration(migrations.Migration):
    dependencies = [('map_my_merchants', '0008_charge_place_raw_input')]

    operations = [
        migrations.CreateModel(
            name='Statement',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                    ),
                ),
                ('content_sha256', models.TextField(unique=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('source_name', models.TextField()),
                ('source_path', models.TextField(blank=True)),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name='charge',
            name='line_number',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='charge',
            name='statement',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='charges',
                to='map_my_merchants.statement',
            ),
        ),
        migrations.RunPython(backfill_charge_statement, migrations.RunPython.noop),
        migrations.RemoveConstraint(model_name='charge', name='charge_identity_unique'),
        migrations.AlterField(model_name='charge', name='line_number', field=models.IntegerField()),
        migrations.AlterField(
            model_name='charge',
            name='statement',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='charges',
                to='map_my_merchants.statement',
            ),
        ),
        migrations.AddConstraint(
            model_name='charge',
            constraint=models.UniqueConstraint(
                fields=('statement', 'line_number'), name='charge_identity_unique'
            ),
        ),
    ]
