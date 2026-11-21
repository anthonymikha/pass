from django.db import migrations, models


class Migration(migrations.Migration):
    """PAY-26, PAY-27: the payer said "I paid"; a claim only, the payee's paid_at decides."""

    dependencies = [
        ('billing', '0002_payment_waived_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='payer_marked_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
