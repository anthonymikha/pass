import datetime

from django.db import migrations, models
from django.db.models import Min
from django.utils import timezone


def mark_old_sessions_billed(apps, schema_editor):
    """PAY-10 (decided during build, 2026-11-21): a session billed under the old rule (payments made at the booker's
    check-in) gets `billed_at` = its first payment's time, so the tick never bills it twice. A confirmed session whose
    check-in had already closed (ends_at + 24h) with no payments owed nothing under the old rule and is marked billed
    with no rows. Sessions still inside the window are billed by the tick under the new rule."""
    Session = apps.get_model('bookings', 'Session')
    Payment = apps.get_model('billing', 'Payment')
    for row in Payment.objects.values('session').annotate(first=Min('created_at')):
        Session.objects.filter(pk=row['session']).update(billed_at=row['first'])
    now = timezone.now()
    Session.objects.filter(status='confirmed', billed_at__isnull=True,
                           ends_at__lte=now - datetime.timedelta(hours=24)).update(billed_at=now)


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0003_session_court_fee_split'),
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='session',
            name='billed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(mark_old_sessions_billed, migrations.RunPython.noop),
    ]
