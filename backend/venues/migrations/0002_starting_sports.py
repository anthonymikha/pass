"""CLUB-36: the starting sports, added when no sport of that name exists. Reversing it removes nothing."""
from django.db import migrations

STARTING_SPORTS = ["Padel", "Tennis", "Basketball", "Pickleball"]


def add_sports(apps, schema_editor):
    Sport = apps.get_model("venues", "Sport")
    for name in STARTING_SPORTS:
        if not Sport.objects.filter(name__iexact=name).exists():
            Sport.objects.create(name=name)


class Migration(migrations.Migration):
    dependencies = [("venues", "0001_initial")]
    operations = [migrations.RunPython(add_sports, migrations.RunPython.noop)]
