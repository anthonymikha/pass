from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MaxValueValidator
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
    email = models.EmailField(unique=True, null=True, blank=True)  # null = shadow player managed by a coach
    phone = models.CharField(max_length=32, blank=True)
    full_name = models.CharField(max_length=255, blank=True)
    avatar = models.FileField(upload_to="avatars/", blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
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


class UserBlockout(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="blockouts")
    weekday = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MaxValueValidator(6)]
    )  # 0=Monday, recurring weekly
    on_date = models.DateField(null=True, blank=True)  # one-off
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_blockouts"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekday__isnull=False, on_date__isnull=True)
                | models.Q(weekday__isnull=True, on_date__isnull=False),
                name="user_blockouts_weekday_xor_on_date",
            ),
        ]

    def __str__(self):
        return f"{self.user}: {self.on_date or self.weekday} {self.start_time}-{self.end_time}"
