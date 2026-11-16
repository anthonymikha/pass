from django.conf import settings
from django.db import models

from bookings.models import Session
from teams.models import Group


class BodyArea(models.TextChoices):
    NECK = "neck"
    SHOULDERS = "shoulders"
    UPPER_BACK = "upper_back"
    LOWER_BACK = "lower_back"
    CHEST = "chest"
    ARMS = "arms"
    ELBOWS = "elbows"
    WRISTS_HANDS = "wrists_hands"
    CORE = "core"
    HIPS = "hips"
    GLUTES = "glutes"
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    KNEES = "knees"
    CALVES = "calves"
    ANKLES_FEET = "ankles_feet"


class SorenessLog(models.Model):
    class Period(models.TextChoices):
        MORNING = "morning"
        EVENING = "evening"
        POST_SESSION = "post_session"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="soreness_logs")
    logged_on = models.DateField()
    period = models.CharField(max_length=20, choices=Period.choices)
    session = models.ForeignKey(
        Session, null=True, blank=True, on_delete=models.PROTECT, related_name="soreness_logs"
    )
    body_area = models.CharField(max_length=20, choices=BodyArea.choices)
    level = models.PositiveSmallIntegerField()  # 0-10
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "soreness_logs"
        constraints = [
            models.CheckConstraint(condition=models.Q(level__range=(0, 10)), name="soreness_logs_level_range"),
        ]

    def __str__(self):
        return f"{self.user} {self.logged_on} {self.body_area}: {self.level}"


class SleepLog(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual"
        HEALTH_APP = "health_app"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sleep_logs")
    sleep_start = models.DateTimeField()
    sleep_end = models.DateTimeField()
    source = models.CharField(max_length=20, choices=Source.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sleep_logs"

    def __str__(self):
        return f"{self.user} {self.sleep_start:%Y-%m-%d %H:%M}-{self.sleep_end:%H:%M}"


class Exercise(models.Model):
    class Kind(models.TextChoices):
        STRETCH = "stretch"
        MOBILITY = "mobility"

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    min_soreness = models.PositiveSmallIntegerField()
    max_soreness = models.PositiveSmallIntegerField()
    video_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exercises"

    def __str__(self):
        return self.name


class ExerciseBodyArea(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.CASCADE, related_name="body_areas")
    body_area = models.CharField(max_length=20, choices=BodyArea.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exercise_body_areas"
        constraints = [
            models.UniqueConstraint(fields=["exercise", "body_area"], name="exercise_body_areas_unique"),
        ]

    def __str__(self):
        return f"{self.exercise}: {self.body_area}"


class ExerciseAssignment(models.Model):
    exercise = models.ForeignKey(Exercise, on_delete=models.PROTECT, related_name="assignments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exercise_assignments")
    # null = system suggestion
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_exercises"
    )
    group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="exercise_assignments"
    )
    due_on = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "exercise_assignments"

    def __str__(self):
        return f"{self.exercise} for {self.user}"


class UserAchievement(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="achievements")
    achievement_code = models.CharField(max_length=64)  # definitions live in code later
    earned_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "user_achievements"
        constraints = [
            models.UniqueConstraint(fields=["user", "achievement_code"], name="user_achievements_unique"),
        ]

    def __str__(self):
        return f"{self.user}: {self.achievement_code}"
