import datetime

from django.utils import timezone
from rest_framework import serializers

from config.api import VisibleRelatedField

from . import services
from .models import BodyArea, Exercise, ExerciseAssignment, SleepLog, SorenessLog, UserAchievement


# --- soreness and RPE ---

class AreaLevelSerializer(serializers.Serializer):
    body_area = serializers.ChoiceField(choices=BodyArea.choices)
    level = serializers.IntegerField(min_value=0, max_value=10)


def unique_areas(areas):
    """WEL-2, WEL-10: each area at most once."""
    names = [a["body_area"] for a in areas]
    if len(names) != len(set(names)):
        raise serializers.ValidationError("Each body area may be listed at most once.")
    return areas


class RpeSerializer(serializers.Serializer):
    rpe = serializers.IntegerField(min_value=1, max_value=10)
    rpe_minutes = serializers.IntegerField(min_value=1, max_value=600, required=False)
    sore_areas = AreaLevelSerializer(many=True, default=list)

    def validate_sore_areas(self, value):
        return unique_areas(value)


class SorenessCheckInSerializer(serializers.Serializer):
    period = serializers.ChoiceField(choices=[SorenessLog.Period.MORNING, SorenessLog.Period.EVENING])
    logged_on = serializers.DateField(required=False)
    areas = AreaLevelSerializer(many=True)  # may be empty

    def validate_areas(self, value):
        return unique_areas(value)

    def validate_logged_on(self, value):  # WEL-10: user timezone, not in the future, at most 7 days back
        today = services.user_today(self.context["request"].user)
        if value > today:
            raise serializers.ValidationError("Cannot be in the future.")
        if value < today - datetime.timedelta(days=7):
            raise serializers.ValidationError("Cannot be more than 7 days back.")
        return value

    def validate(self, data):
        data.setdefault("logged_on", services.user_today(self.context["request"].user))
        return data


class ExerciseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exercise
        fields = ["id", "name", "description", "kind", "min_soreness", "max_soreness", "video_url"]


class SuggestionSerializer(serializers.Serializer):
    body_area = serializers.CharField()
    level = serializers.IntegerField()
    exercises = ExerciseSerializer(many=True)


class SorenessLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SorenessLog
        fields = ["id", "logged_on", "period", "session", "body_area", "level"]


# --- sleep ---

def check_sleep_window(start, end):
    """WEL-20: end after start, at most 24 hours long, end not after now."""
    if end <= start:
        raise serializers.ValidationError({"sleep_end": "Must be after sleep_start."})
    if end - start > datetime.timedelta(hours=24):
        raise serializers.ValidationError({"sleep_end": "A sleep record is at most 24 hours long."})
    if end > timezone.now():
        raise serializers.ValidationError({"sleep_end": "Cannot be in the future."})


class SleepSerializer(serializers.ModelSerializer):
    """Manual entry (WEL-20); PATCH sends only some fields, the rest come from the stored row."""

    class Meta:
        model = SleepLog
        fields = ["id", "sleep_start", "sleep_end", "source", "external_id", "created_at"]
        read_only_fields = ["id", "source", "external_id", "created_at"]

    def validate(self, data):
        def value(name):
            return data[name] if name in data else getattr(self.instance, name)

        check_sleep_window(value("sleep_start"), value("sleep_end"))
        return data


class SleepImportRecordSerializer(SleepSerializer):
    """One phone record (WEL-21)."""

    source = serializers.ChoiceField(choices=[SleepLog.Source.APPLE_HEALTH, SleepLog.Source.HEALTH_CONNECT])
    external_id = serializers.CharField(min_length=1, max_length=128)

    class Meta(SleepSerializer.Meta):
        read_only_fields = ["id", "created_at"]


class SleepImportSerializer(serializers.Serializer):
    # errors come back as a list with one entry per record, so they are by index
    records = SleepImportRecordSerializer(many=True, max_length=500)


# --- exercises ---

class AssignmentSerializer(serializers.ModelSerializer):
    exercise = ExerciseSerializer(read_only=True)

    class Meta:
        model = ExerciseAssignment
        fields = ["id", "exercise", "user", "assigned_by", "group", "sets", "reps", "hold_seconds", "due_on",
                  "completed_at", "created_at"]


class AssignInputSerializer(serializers.Serializer):
    """WEL-33 (pick) and WEL-40 (a coach sends); the target of a coach is in the URL."""

    exercise = VisibleRelatedField(queryset=Exercise.objects.all())
    sets = serializers.IntegerField(min_value=1, max_value=999, required=False)
    reps = serializers.IntegerField(min_value=1, max_value=999, required=False)
    hold_seconds = serializers.IntegerField(min_value=1, max_value=999, required=False)
    due_on = serializers.DateField(required=False)

    def validate_due_on(self, value):  # today or later, in the caller's timezone (GEN-8)
        if value < services.user_today(self.context["request"].user):
            raise serializers.ValidationError("Cannot be in the past.")
        return value


class AssignmentQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["open", "done"], required=False)  # WEL-44


class AchievementSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="achievement_code")

    class Meta:
        model = UserAchievement
        fields = ["code", "earned_at"]
