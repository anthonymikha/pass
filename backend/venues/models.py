from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models


class Sport(models.Model):
    name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sports"

    def __str__(self):
        return self.name


class Club(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="owned_clubs")
    name = models.CharField(max_length=255)
    address = models.TextField(blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    timezone = models.CharField(max_length=64)
    currency = models.CharField(max_length=3)  # base pricing currency
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "clubs"

    def __str__(self):
        return self.name


class ClubMember(models.Model):
    class Role(models.TextChoices):
        COACH = "coach"
        STAFF = "staff"

    class Status(models.TextChoices):
        PENDING = "pending"
        ACTIVE = "active"

    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="club_memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "club_members"
        constraints = [models.UniqueConstraint(fields=["club", "user"], name="club_members_unique")]

    def __str__(self):
        return f"{self.user} @ {self.club} ({self.role})"


class ClubCurrency(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="currencies")
    currency = models.CharField(max_length=3)
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=6)  # units of this currency per 1 base unit
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "club_currencies"
        constraints = [models.UniqueConstraint(fields=["club", "currency"], name="club_currencies_unique")]

    def __str__(self):
        return f"{self.club}: {self.currency} @ {self.exchange_rate}"


class Court(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="courts")
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    slot_minutes = models.PositiveSmallIntegerField()  # length of one bookable slot
    is_active = models.BooleanField(default=True)
    sports = models.ManyToManyField(Sport, db_table="court_sports", related_name="courts", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "courts"

    def __str__(self):
        return f"{self.club} / {self.name}"


class CourtRate(models.Model):
    # One row = "open in this window at this price"; open hours are the union of rows.
    # No end_time > start_time check on purpose: end_time 00:00 means end of day (e.g. 17:00 to midnight).
    court = models.ForeignKey(Court, on_delete=models.CASCADE, related_name="rates")
    weekday = models.PositiveSmallIntegerField(validators=[MaxValueValidator(6)])  # 0=Monday
    start_time = models.TimeField()
    end_time = models.TimeField()
    price = models.DecimalField(max_digits=12, decimal_places=3)  # per slot, club base currency
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "court_rates"

    def __str__(self):
        return f"{self.court} day {self.weekday} {self.start_time}-{self.end_time}: {self.price}"


class Equipment(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="equipment")
    # null = shared across the club's courts. CASCADE, not SET_NULL, so deleting a court
    # never silently turns its equipment into club-wide equipment.
    court = models.ForeignKey(Court, null=True, blank=True, on_delete=models.CASCADE, related_name="equipment")
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    rental_price = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)  # null = free
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "equipment"

    def __str__(self):
        return f"{self.club}: {self.name}"


class PriceOverride(models.Model):
    # Hand-set price in a non-base currency; without a row the base price is converted at the club rate.
    court_rate = models.ForeignKey(
        CourtRate, null=True, blank=True, on_delete=models.CASCADE, related_name="price_overrides"
    )
    equipment = models.ForeignKey(
        Equipment, null=True, blank=True, on_delete=models.CASCADE, related_name="price_overrides"
    )
    currency = models.CharField(max_length=3)
    price = models.DecimalField(max_digits=12, decimal_places=3)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "price_overrides"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(court_rate__isnull=False, equipment__isnull=True)
                | models.Q(court_rate__isnull=True, equipment__isnull=False),
                name="price_overrides_court_rate_xor_equipment",
            ),
            models.UniqueConstraint(
                fields=["court_rate", "currency"],
                condition=models.Q(court_rate__isnull=False),
                name="price_overrides_court_rate_currency_unique",
            ),
            models.UniqueConstraint(
                fields=["equipment", "currency"],
                condition=models.Q(equipment__isnull=False),
                name="price_overrides_equipment_currency_unique",
            ),
        ]

    def __str__(self):
        return f"{self.court_rate or self.equipment}: {self.price} {self.currency}"


class Discount(models.Model):
    club = models.ForeignKey(Club, on_delete=models.CASCADE, related_name="discounts")
    # court/user null = applies more broadly; CASCADE so deletion never widens a targeted offer.
    court = models.ForeignKey(Court, null=True, blank=True, on_delete=models.CASCADE, related_name="discounts")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="discounts"
    )
    min_bookings = models.PositiveIntegerField(null=True, blank=True)  # frequent-player threshold
    percent_off = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    amount_off = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)  # base currency
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "discounts"

    def __str__(self):
        return f"{self.club}: {self.percent_off or self.amount_off} off ({self.starts_at:%Y-%m-%d})"
