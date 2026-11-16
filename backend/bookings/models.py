from django.conf import settings
from django.db import models

from teams.models import Group
from venues.models import Court, Discount, Equipment, Sport


class Session(models.Model):
    class Kind(models.TextChoices):
        PLAY = "play"
        TRAINING = "training"

    class Status(models.TextChoices):
        REQUESTED = "requested"
        CONFIRMED = "confirmed"
        CANCELLED = "cancelled"
        COMPLETED = "completed"
        BLOCKED = "blocked"

    court = models.ForeignKey(Court, null=True, blank=True, on_delete=models.PROTECT, related_name="sessions")
    sport = models.ForeignKey(Sport, on_delete=models.PROTECT, related_name="sessions")
    booked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="booked_sessions")
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="coached_sessions"
    )
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    currency = models.CharField(max_length=3)
    price = models.DecimalField(max_digits=12, decimal_places=3)
    coach_fee = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # null = coach fee split equally between team members; set = this user is billed the whole fee
    coach_fee_payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="coach_fees_billed"
    )
    discount = models.ForeignKey(Discount, null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    discount_amount = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sessions"
        constraints = [
            models.CheckConstraint(condition=models.Q(ends_at__gt=models.F("starts_at")), name="sessions_ends_after_starts"),
        ]
        indexes = [models.Index(fields=["court", "starts_at"], name="sessions_court_starts_idx")]

    def __str__(self):
        return f"{self.kind} {self.starts_at:%Y-%m-%d %H:%M} ({self.status})"


class SessionParticipant(models.Model):
    class Status(models.TextChoices):
        INVITED = "invited"
        ACCEPTED = "accepted"
        DECLINED = "declined"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="session_participations")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.INVITED)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    rpe = models.PositiveSmallIntegerField(null=True, blank=True)  # rate of perceived exertion, 1-10
    rpe_minutes = models.PositiveIntegerField(null=True, blank=True)
    rpe_logged_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "session_participants"
        constraints = [
            models.UniqueConstraint(fields=["session", "user"], name="session_participants_unique"),
            models.CheckConstraint(condition=models.Q(rpe__range=(1, 10)), name="session_participants_rpe_range"),
        ]

    def __str__(self):
        return f"{self.user} in session {self.session_id} ({self.status})"


class SessionRental(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested"
        APPROVED = "approved"
        DECLINED = "declined"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="rentals")
    equipment = models.ForeignKey(Equipment, on_delete=models.PROTECT, related_name="rentals")
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=12, decimal_places=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "session_rentals"

    def __str__(self):
        return f"{self.quantity} x {self.equipment} for session {self.session_id}"


class Recording(models.Model):
    session = models.ForeignKey(Session, on_delete=models.PROTECT, related_name="recordings")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recordings")
    storage_key = models.CharField(max_length=512)  # object-storage key; storage backend decided later
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recordings"

    def __str__(self):
        return self.storage_key


class RecordingTag(models.Model):
    recording = models.ForeignKey(Recording, on_delete=models.CASCADE, related_name="tags")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_recording_tags"
    )
    start_second = models.PositiveIntegerField()
    end_second = models.PositiveIntegerField(null=True, blank=True)
    label = models.CharField(max_length=255)
    note = models.TextField(blank=True)
    # no rows = whole-team tag
    players = models.ManyToManyField(
        settings.AUTH_USER_MODEL, db_table="recording_tag_players", related_name="recording_tags", blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "recording_tags"

    def __str__(self):
        return f"{self.label} @ {self.start_second}s"
