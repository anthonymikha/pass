from django.db import migrations, models


class Migration(migrations.Migration):
    """PAY-9: the booker pays the court fee in full (false) or it is split among the attendees (true)."""

    dependencies = [
        ('bookings', '0002_participant_rpe_reminded_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='court_fee_split',
            field=models.BooleanField(default=False),
        ),
    ]
