from django.db import migrations, models


class Migration(migrations.Migration):
    """PAY-25: the payee gave the payment up."""

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='payment',
            name='waived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
