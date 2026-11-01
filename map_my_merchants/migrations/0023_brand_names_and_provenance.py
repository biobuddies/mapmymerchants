"""Complete brand names and provenance without replaying locally applied migrations."""

from django.apps.registry import Apps
from django.conf import settings
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.models.deletion import PROTECT


def populate_brand_names_and_users(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    database = schema_editor.connection.alias
    Brand = apps.get_model('map_my_merchants', 'Brand')
    Brand.objects.using(database).filter(display_name__isnull=True).update(
        display_name=models.F('statement_name')
    )
    User = apps.get_model(settings.AUTH_USER_MODEL)
    for username in ('from-statement', 'from-openstreetmap'):
        User.objects.using(database).get_or_create(
            username=username, defaults={'is_active': False, 'password': '!'}
        )


class Migration(migrations.Migration):
    replaces = (
        ('map_my_merchants', '0023_add_brand_updated_by'),
        ('map_my_merchants', '0024_create_brand_users'),
        ('map_my_merchants', '0026_make_display_name_non_nullable'),
    )
    dependencies = (
        ('map_my_merchants', '0022_drop_brand_pattern'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    )
    operations = (
        migrations.AddField(
            model_name='brand',
            name='updated_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=PROTECT,
                related_name='brand_updates',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name='brand', name='name', field=models.TextField(db_column='name', unique=True)
        ),
        migrations.RenameField(model_name='brand', old_name='name', new_name='statement_name'),
        migrations.RunPython(populate_brand_names_and_users, migrations.RunPython.noop),
        migrations.AlterField(model_name='brand', name='display_name', field=models.TextField()),
    )
