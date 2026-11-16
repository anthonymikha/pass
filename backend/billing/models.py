from django.conf import settings
from django.db import models

from bookings.models import Session
from venues.models import Club


class Payment(models.Model):
    class Method(models.TextChoices):
        OFFLINE = "offline"
        ONLINE = "online"

    session = models.ForeignKey(Session, on_delete=models.PROTECT, related_name="payments")
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments_made")
    # payee: exactly one of club / coach
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="payments_received"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=3)
    currency = models.CharField(max_length=3)
    platform_fee = models.DecimalField(max_digits=12, decimal_places=3)
    method = models.CharField(max_length=20, choices=Method.choices)
    paid_at = models.DateTimeField()
    settled_at = models.DateTimeField(null=True, blank=True)  # platform's cut settled with the payee
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payments"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(club__isnull=False, coach__isnull=True)
                | models.Q(club__isnull=True, coach__isnull=False),
                name="payments_club_xor_coach",
            ),
        ]

    def __str__(self):
        return f"{self.amount} {self.currency} from {self.payer}"


class CommissionRate(models.Model):
    class AppliesTo(models.TextChoices):
        CLUB = "club"
        COACH = "coach"

    applies_to = models.CharField(max_length=20, choices=AppliesTo.choices)
    # both null = default schedule; one set = negotiated override.
    # CASCADE, not SET_NULL, so deleting a club/coach never turns an override into a default.
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.CASCADE, related_name="commission_rates")
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="commission_rates"
    )
    min_count = models.PositiveIntegerField(default=0)  # tier lower bound
    percent = models.DecimalField(max_digits=5, decimal_places=2)
    effective_from = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "commission_rates"
        indexes = [models.Index(fields=["applies_to", "effective_from"], name="commission_rates_lookup_idx")]

    def __str__(self):
        return f"{self.applies_to} {self.percent}% from {self.effective_from} (min {self.min_count})"
