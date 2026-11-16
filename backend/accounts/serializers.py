import re
import zoneinfo

from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    """The signed-in user's own profile."""

    class Meta:
        model = User
        # ponytail: avatar is left out until object storage exists (uploads have nowhere to be served from).
        fields = [
            "id", "email", "full_name", "phone", "timezone",
            "is_coach", "coach_bio", "coach_rate", "coach_currency",
        ]
        read_only_fields = ["id", "email"]
        extra_kwargs = {"coach_rate": {"min_value": 0}}

    def validate_timezone(self, value):
        if value not in zoneinfo.available_timezones():
            raise serializers.ValidationError("Unknown timezone.")
        return value

    def validate_coach_currency(self, value):
        if value and not re.fullmatch(r"[A-Z]{3}", value):
            raise serializers.ValidationError("Use a 3-letter ISO currency code, e.g. USD.")
        return value


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(max_length=255)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate(self, data):
        try:
            password_validation.validate_password(
                data["password"], User(email=data["email"], full_name=data["full_name"])
            )
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"password": exc.messages})
        return data


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        # Shadow players have no email and an unusable password, so they can never match.
        user = authenticate(username=data["email"].lower(), password=data["password"])
        if user is None:
            raise serializers.ValidationError("Wrong email or password.")
        data["user"] = user
        return data
