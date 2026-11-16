import datetime
import zoneinfo
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from accounts.serializers import BlockoutSerializer
from config.api import VisibleRelatedField
from config.money import validate_currency, validate_typed_money

from . import services
from .models import Club, ClubCurrency, ClubMember, Court, CourtBlockout, CourtRate, Discount, Equipment, PriceOverride, Sport

User = get_user_model()


def validate_timezone(value):
    if value not in zoneinfo.available_timezones():
        raise serializers.ValidationError("Unknown timezone.")
    return value


def typed_money(value, currency, field):
    """GEN-17 on one field."""
    try:
        validate_typed_money(value, currency)
    except serializers.ValidationError as exc:
        raise serializers.ValidationError({field: exc.detail})


class ClubSerializer(serializers.ModelSerializer):
    class Meta:
        model = Club
        fields = ["id", "name", "address", "latitude", "longitude", "timezone", "currency"]
        extra_kwargs = {  # CLUB-1
            "latitude": {"min_value": -90, "max_value": 90},
            "longitude": {"min_value": -180, "max_value": 180},
            "timezone": {"validators": [validate_timezone]},
            "currency": {"validators": [validate_currency]},  # GEN-14
        }


class ClubSearchSerializer(ClubSerializer):
    distance_km = serializers.SerializerMethodField()
    courts = serializers.SerializerMethodField()

    class Meta(ClubSerializer.Meta):
        fields = [*ClubSerializer.Meta.fields, "distance_km", "courts"]

    def get_distance_km(self, club):
        return getattr(club, "distance_km", None)

    def get_courts(self, club):
        return [{"id": c.id, "name": c.name} for c in club.active_courts]


class SearchParamsSerializer(serializers.Serializer):
    sport = serializers.IntegerField(required=False)
    q = serializers.CharField(required=False)
    lat = serializers.FloatField(required=False, min_value=-90, max_value=90)
    lng = serializers.FloatField(required=False, min_value=-180, max_value=180)
    radius_km = serializers.FloatField(required=False, min_value=1, max_value=200, default=25)

    def validate(self, data):
        if ("lat" in data) != ("lng" in data):  # CLUB-30: a location is lat + lng together
            raise serializers.ValidationError({"lat" if "lat" not in data else "lng": "Send lat and lng together."})
        return data


class ClubCurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClubCurrency
        fields = ["id", "currency", "exchange_rate"]
        extra_kwargs = {
            "currency": {"validators": [validate_currency]},
            "exchange_rate": {"min_value": Decimal("0.000001")},  # CLUB-5, PRC-2: > 0, 6 decimals from the model field
        }


class ClubCurrencyUpdateSerializer(ClubCurrencySerializer):
    class Meta(ClubCurrencySerializer.Meta):
        read_only_fields = ["currency"]  # CLUB-6: only the rate changes


class CourtSerializer(serializers.ModelSerializer):
    sports = VisibleRelatedField(queryset=Sport.objects.all(), many=True, allow_empty=False)  # CLUB-8

    class Meta:
        model = Court
        fields = ["id", "name", "description", "slot_minutes", "sports", "is_active"]

    def validate_slot_minutes(self, value):
        if value % 5 or not 15 <= value <= 480:  # CLUB-8
            raise serializers.ValidationError("Must be a multiple of 5 from 15 to 480.")
        return value


class RateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourtRate
        fields = ["id", "weekday", "start_time", "end_time", "price"]

    def validate_start_time(self, value):
        return self._on_grid(value)

    def validate_end_time(self, value):
        return self._on_grid(value)

    def _on_grid(self, value):
        if value.minute % 5 or value.second or value.microsecond:  # CLUB-11
            raise serializers.ValidationError("Must be on a 5-minute boundary.")
        return value

    def validate_price(self, value):
        typed_money(value, self.context["club"].currency, "price")  # CLUB-11, GEN-17
        return value

    def validate(self, data):
        def value(name):
            return data[name] if name in data else getattr(self.instance, name, None)

        start, end = value("start_time"), value("end_time")
        if start and end and end != datetime.time(0) and end <= start:  # GEN-11
            raise serializers.ValidationError({"end_time": "End time must be after start time, or 00:00 for the end of the day."})
        return data


class ClosureSerializer(BlockoutSerializer):
    class Meta(BlockoutSerializer.Meta):
        model = CourtBlockout
        fields = ["id", *BlockoutSerializer.Meta.fields]

    def to_representation(self, closure):
        data = super().to_representation(closure)
        if self.context.get("conflicts"):  # CLUB-16: only the response to a create or a change
            data["conflicts"] = ConflictSerializer(services.closure_conflicts(closure), many=True).data
        return data


class ConflictSerializer(serializers.Serializer):
    """A session in the way of a closure. Plain serializer: venues never imports bookings."""

    id = serializers.IntegerField()
    status = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class EquipmentSerializer(serializers.ModelSerializer):
    court = VisibleRelatedField(queryset=Court.objects.none(), required=False, allow_null=True)

    class Meta:
        model = Equipment
        fields = ["id", "name", "quantity", "court", "rental_price"]
        extra_kwargs = {"quantity": {"min_value": 1}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        club = self.context.get("club")
        if club:
            self.fields["court"].queryset = club.courts.all()  # CLUB-18: a court of this club

    def validate_rental_price(self, value):
        if value is not None:
            typed_money(value, self.context["club"].currency, "rental_price")  # CLUB-18, GEN-17
        return value


class OverrideSerializer(serializers.ModelSerializer):
    court_rate = VisibleRelatedField(queryset=CourtRate.objects.none(), required=False, allow_null=True)
    equipment = VisibleRelatedField(queryset=Equipment.objects.none(), required=False, allow_null=True)

    class Meta:
        model = PriceOverride
        fields = ["id", "court_rate", "equipment", "currency", "price"]
        extra_kwargs = {"currency": {"validators": [validate_currency]}}
        validators = []  # the per-target uniqueness constraints are conditional: override_exists comes from the insert

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        club = self.context.get("club")
        if club:
            self.fields["court_rate"].queryset = CourtRate.objects.filter(court__club=club)
            self.fields["equipment"].queryset = club.equipment.all()

    def validate(self, data):
        if (data.get("court_rate") is None) == (data.get("equipment") is None):  # CLUB-20: exactly one
            raise serializers.ValidationError("Give exactly one of court_rate or equipment.")
        if data.get("equipment") and data["equipment"].rental_price is None:  # CLUB-20: a rentable item
            raise serializers.ValidationError({"equipment": "This item is not rentable."})
        typed_money(data["price"], data["currency"], "price")  # CLUB-20, GEN-17
        return data


class OverridePriceSerializer(OverrideSerializer):
    """CLUB-21: only the price changes."""

    class Meta(OverrideSerializer.Meta):
        read_only_fields = ["court_rate", "equipment", "currency"]

    def validate(self, data):
        if "price" in data:
            typed_money(data["price"], self.instance.currency, "price")
        return data


class OfferSerializer(serializers.ModelSerializer):
    court = VisibleRelatedField(queryset=Court.objects.none(), required=False, allow_null=True)
    user = VisibleRelatedField(  # CLUB-22: active, non-shadow
        queryset=User.objects.filter(is_active=True, email__isnull=False), required=False, allow_null=True
    )

    class Meta:
        model = Discount
        fields = ["id", "court", "user", "min_bookings", "percent_off", "amount_off", "starts_at", "ends_at", "message"]
        extra_kwargs = {"min_bookings": {"min_value": 1}, "message": {"max_length": 1000}}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        club = self.context.get("club")
        if club:
            self.fields["court"].queryset = club.courts.all()

    def validate_percent_off(self, value):
        if value is not None and not 0 < value <= 100:
            raise serializers.ValidationError("Must be above 0 and at most 100.")
        return value

    def validate_amount_off(self, value):
        if value is not None:
            if value <= 0:
                raise serializers.ValidationError("Must be above 0.")
            typed_money(value, self.context["club"].currency, "amount_off")  # PRC-3, GEN-17
        return value

    def validate(self, data):
        def value(name):
            return data[name] if name in data else getattr(self.instance, name, None)

        if (value("percent_off") is None) == (value("amount_off") is None):  # CLUB-22: exactly one
            raise serializers.ValidationError("Give exactly one of percent_off or amount_off.")
        if value("starts_at") and value("ends_at") and value("starts_at") >= value("ends_at"):
            raise serializers.ValidationError({"ends_at": "Must be after starts_at."})
        return data


class MemberUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "full_name"]  # no email: members see each other's names only


class MemberSerializer(serializers.ModelSerializer):
    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = ClubMember
        fields = ["id", "user", "role", "status", "expires_on"]


class MemberUpdateSerializer(MemberSerializer):
    class Meta(MemberSerializer.Meta):
        read_only_fields = ["role", "status"]  # CLUB-29: only expires_on changes


class MemberCreateSerializer(serializers.Serializer):
    """CLUB-25: the owner adds staff or a player by email."""

    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=ClubMember.Role.choices)  # same choices as the row: one enum in the schema
    expires_on = serializers.DateField(required=False, allow_null=True)

    def validate_role(self, value):
        if value == ClubMember.Role.COACH:  # coaches ask for themselves (CLUB-26)
            raise serializers.ValidationError("Coaches ask to be affiliated; the owner adds staff or players here.")
        return value

    def validate_expires_on(self, value):
        if value and value < services.club_today(self.context["club"]):
            raise serializers.ValidationError("Must be today or later.")
        return value

    def validate_email(self, value):
        user = User.objects.filter(email=value.lower(), is_active=True).first()
        if user is None:
            return None  # reported as a business error once the rest of the input is valid
        if user.pk == self.context["club"].owner_id:
            raise serializers.ValidationError("The club owner cannot be a member.")
        return user


class SportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Sport
        fields = ["id", "name"]


class CourtDetailSerializer(CourtSerializer):
    sports = SportSerializer(many=True, read_only=True)


def court_detail(court):
    """CLUB-31: what the public sees of one court."""
    club = court.club
    ctx = {"club": club}
    items = Equipment.objects.filter(Q(court=court) | Q(court__isnull=True), club=club).order_by("id")
    return {
        "club": {**ClubSerializer(club).data, "currencies": ClubCurrencySerializer(club.currencies.order_by("id"), many=True).data},
        "court": CourtDetailSerializer(court).data,
        "rates": RateSerializer(court.rates.order_by("weekday", "start_time"), many=True, context=ctx).data,
        "equipment": {
            "included": EquipmentSerializer(items.filter(rental_price__isnull=True), many=True, context=ctx).data,
            "rentable": EquipmentSerializer(items.filter(rental_price__isnull=False), many=True, context=ctx).data,
        },
    }
