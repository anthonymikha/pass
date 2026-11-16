import datetime
import re
import zoneinfo

from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from config.money import validate_currency, validate_typed_money

from .models import Device, User


class UserSerializer(serializers.ModelSerializer):
    """The signed-in user's own profile."""

    class Meta:
        model = User
        # ponytail: avatar is left out until object storage exists (uploads have nowhere to be served from).
        fields = [
            "id", "email", "full_name", "phone", "timezone",
            "date_of_birth", "sex", "height_cm", "weight_kg", "nationality", "dominant_hand",
            "is_coach", "coach_bio", "coach_rate", "coach_currency",
        ]
        read_only_fields = ["id", "email"]
        extra_kwargs = {
            "coach_rate": {"min_value": 0},
            "height_cm": {"min_value": 30, "max_value": 300},
            "weight_kg": {"min_value": 2, "max_value": 500},
        }

    def validate_date_of_birth(self, value):
        if value and value > datetime.date.today():
            raise serializers.ValidationError("Date of birth cannot be in the future.")
        return value

    def validate_nationality(self, value):
        if value and not re.fullmatch(r"[A-Z]{2}", value):
            raise serializers.ValidationError("Use a 2-letter ISO country code, e.g. LB.")
        return value

    def validate_timezone(self, value):
        if value not in zoneinfo.available_timezones():
            raise serializers.ValidationError("Unknown timezone.")
        return value

    def validate_coach_currency(self, value):
        return validate_currency(value) if value else value  # GEN-14

    def validate(self, data):
        rate = data.get("coach_rate", getattr(self.instance, "coach_rate", None))
        currency = data.get("coach_currency", getattr(self.instance, "coach_currency", ""))
        if rate is not None and currency:
            try:
                validate_typed_money(rate, currency)  # GEN-17
            except serializers.ValidationError as exc:
                raise serializers.ValidationError({"coach_rate": exc.detail})
        return data


class BlockoutSerializer(serializers.ModelSerializer):
    """Base for the fields of an `accounts.models.Blockout` (CLUB-15, GEN-11).

    Subclass with `Meta.model` set (user block-outs, court closures) and add the owner field:
    `class Meta(BlockoutSerializer.Meta): model = ...; fields = [*BlockoutSerializer.Meta.fields, "court"]`.
    """

    class Meta:
        fields = ["starts_on", "start_time", "end_time", "repeat", "repeat_until", "reason"]  # reason <= 255 comes from the model

    def validate(self, data):
        # PATCH sends only some fields: fill the rest from the stored row.
        def value(name):
            return data[name] if name in data else getattr(self.instance, name, None)

        start, end, starts_on, until = value("start_time"), value("end_time"), value("starts_on"), value("repeat_until")
        errors = {}
        if start and end and end != datetime.time(0) and end <= start:  # GEN-11: 00:00 means end of day
            errors["end_time"] = "End time must be after start time, or 00:00 for the end of the day."
        if starts_on and until and until < starts_on:  # CLUB-15
            errors["repeat_until"] = "Cannot be before the first date."
        if errors:
            raise serializers.ValidationError(errors)
        return data


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "token", "platform", "created_at"]
        read_only_fields = ["id", "created_at"]
        # The token is unique, but registering an existing one is a move or a repeat (NOTE-2), not an error.
        extra_kwargs = {"token": {"validators": []}}


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
