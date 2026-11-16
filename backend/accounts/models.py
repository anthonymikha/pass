from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    def create_user(self, email=None, password=None, **fields):
        email = self.normalize_email(email) or None
        user = self.model(email=email, **fields)
        user.set_password(password if email else None)  # None -> unusable password (shadow players never log in)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **fields):
        return self.create_user(email, password, is_staff=True, is_superuser=True, **fields)


class User(AbstractBaseUser, PermissionsMixin):
    class Sex(models.TextChoices):
        MALE = "male"
        FEMALE = "female"

    class Hand(models.TextChoices):
        LEFT = "left"
        RIGHT = "right"
        BOTH = "both"

    email = models.EmailField(unique=True, null=True, blank=True)  # null = shadow player managed by a coach
    phone = models.CharField(max_length=32, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    avatar = models.FileField(upload_to="avatars/", blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    date_of_birth = models.DateField(null=True, blank=True)
    sex = models.CharField(max_length=10, choices=Sex.choices, blank=True)
    # ponytail: latest value only; add a measurements table if weight history is ever charted
    height_cm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    nationality = models.CharField(max_length=2, blank=True)  # ISO 3166-1 alpha-2
    dominant_hand = models.CharField(max_length=10, choices=Hand.choices, blank=True)
    is_coach = models.BooleanField(default=False)
    coach_bio = models.TextField(blank=True)
    coach_rate = models.DecimalField(max_digits=12, decimal_places=3, null=True, blank=True)
    coach_currency = models.CharField(max_length=3, blank=True)
    managed_by = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="managed_players"
    )
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "users"

    def save(self, *args, **kwargs):
        # One place for every write path (API, admin, manager): emails are case-insensitive,
        # and a blank email must be NULL or a second shadow player would break the unique constraint.
        self.email = self.email.strip().lower() if self.email else None
        super().save(*args, **kwargs)

    def __str__(self):
        return self.email or self.full_name or f"user {self.pk}"


class Connection(models.Model):
    class Type(models.TextChoices):
        FRIEND = "friend"
        COACHING = "coaching"

    class Status(models.TextChoices):
        PENDING = "pending"
        ACCEPTED = "accepted"
        BLOCKED = "blocked"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="connections")
    other_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="incoming_connections")
    type = models.CharField(max_length=20, choices=Type.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "connections"
        constraints = [
            models.UniqueConstraint(fields=["user", "other_user", "type"], name="connections_unique"),
        ]

    def __str__(self):
        return f"{self.user} -> {self.other_user} ({self.type}, {self.status})"


class Blockout(models.Model):
    """Unavailable time window, one-off or repeating. Shared by users and courts."""

    class Repeat(models.TextChoices):
        NONE = "none"
        DAILY = "daily"
        WEEKLY = "weekly"  # same weekday as starts_on
        MONTHLY = "monthly"  # same day of month as starts_on; months without that day are skipped

    starts_on = models.DateField()  # the one-off date, or the first occurrence
    start_time = models.TimeField()
    end_time = models.TimeField()
    repeat = models.CharField(max_length=10, choices=Repeat.choices, default=Repeat.NONE)
    repeat_until = models.DateField(null=True, blank=True)  # null = repeats forever
    reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(
                condition=models.Q(repeat_until__gte=models.F("starts_on")),
                name="%(class)s_repeat_until_after_start",
            ),
        ]

    def occurs_on(self, day):
        # ponytail: four fixed patterns; switch to iCalendar RRULE if "every 2 weeks" / "first Monday" is needed
        if day < self.starts_on or (self.repeat_until and day > self.repeat_until):
            return False
        return {
            self.Repeat.NONE: day == self.starts_on,
            self.Repeat.DAILY: True,
            self.Repeat.WEEKLY: day.weekday() == self.starts_on.weekday(),
            self.Repeat.MONTHLY: day.day == self.starts_on.day,
        }[self.repeat]

    def __str__(self):
        return f"{self.starts_on} {self.start_time}-{self.end_time} ({self.repeat})"


class UserBlockout(Blockout):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blockouts")

    class Meta(Blockout.Meta):
        db_table = "user_blockouts"
