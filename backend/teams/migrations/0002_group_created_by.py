import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """ACC-1, TEAM-20, TEAM-29: `owner` becomes `created_by`, history only, emptied if that account is deleted."""

    dependencies = [
        ('teams', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RenameField(model_name='group', old_name='owner', new_name='created_by'),
        migrations.AlterField(
            model_name='group',
            name='created_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='created_groups', to=settings.AUTH_USER_MODEL),
        ),
    ]
