from rest_framework import serializers

from django.utils import timezone

from accounts.serializers import CONNECTABLE_USERS, PersonSerializer
from config.api import VisibleRelatedField
from config.money import validate_currency
from teams.models import Group
from venues.models import Court, Sport
from venues.serializers import typed_money

from . import services
from .models import Session, SessionParticipant, SessionRental

MONEY = {"max_digits": 12, "decimal_places": 3}  # GEN-13


class SlotQuerySerializer(serializers.Serializer):
    """AVL-10."""

    date = serializers.DateField()
    currency = serializers.CharField(required=False)


class SlotSerializer(serializers.Serializer):
    """AVL-11. The view puts the price (PRC-4) on each slot."""

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    price = serializers.DecimalField(**MONEY)


class RentalInputSerializer(serializers.Serializer):
    equipment = serializers.IntegerField()
    quantity = serializers.IntegerField()  # the range depends on the item: checked in the service (BOOK-7)


class BookingSerializer(serializers.Serializer):
    """BOOK-7 input. Rentals, group and invitees are checked in the service, in the order the page lists."""

    court = VisibleRelatedField(queryset=Court.objects.filter(is_active=True).select_related("club"))
    sport = VisibleRelatedField(queryset=Sport.objects.all())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    currency = serializers.CharField(validators=[validate_currency])
    rentals = RentalInputSerializer(many=True, required=False)
    group = serializers.IntegerField(required=False)
    invitees = serializers.ListField(child=serializers.IntegerField(), required=False)


ACTIVE_COURTS = Court.objects.filter(is_active=True).select_related("club")


class TrainingRequestSerializer(serializers.Serializer):
    """BOOK-20 input: the proposed time is in the future and at most 8 hours long."""

    coach = VisibleRelatedField(queryset=CONNECTABLE_USERS)  # not a coach: `not_a_coach` in the service
    sport = VisibleRelatedField(queryset=Sport.objects.all())
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def validate(self, data):
        if data["starts_at"] <= timezone.now():
            raise serializers.ValidationError({"starts_at": "Must be in the future."})
        if data["ends_at"] <= data["starts_at"]:
            raise serializers.ValidationError({"ends_at": "Must be after the start."})
        if data["ends_at"] - data["starts_at"] > services.MAX_REQUEST:
            raise serializers.ValidationError({"ends_at": "At most 8 hours long."})
        return data


class TrainingConfirmSerializer(serializers.Serializer):
    """BOOK-21 input."""

    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    currency = serializers.CharField(validators=[validate_currency])
    coach_fee = serializers.DecimalField(**MONEY)
    court = VisibleRelatedField(queryset=ACTIVE_COURTS, required=False)

    def validate(self, data):
        typed_money(data["coach_fee"], data["currency"], "coach_fee")  # GEN-17
        return data


class TrainingBookingSerializer(TrainingConfirmSerializer):
    """BOOK-30, BOOK-31 input: a team (`group`) or one of the coach's players (`player`)."""

    sport = VisibleRelatedField(queryset=Sport.objects.all())
    group = VisibleRelatedField(queryset=Group.objects.all(), required=False)
    player = serializers.IntegerField(required=False)  # checked against the coach's players in the service (BOOK-31)
    coach_fee_payer = serializers.IntegerField(required=False, allow_null=True)  # BOOK-32, checked in the service

    def validate(self, data):
        if ("group" in data) == ("player" in data):
            raise serializers.ValidationError({"player": "Give either a team (group) or a player."})
        return super().validate(data)


class AvailabilityParamsSerializer(serializers.Serializer):
    """AVL-23 (`from` is a keyword, so that field is added in __init__)."""

    to = serializers.DateTimeField()
    min_minutes = serializers.IntegerField(min_value=5, max_value=1440, default=30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from"] = serializers.DateTimeField()


class IntervalSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class SessionInviteSerializer(serializers.Serializer):
    """BOOK-15."""

    invitees = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class AnswerSerializer(serializers.Serializer):
    """BOOK-16."""

    status = serializers.ChoiceField(choices=[SessionParticipant.Status.ACCEPTED, SessionParticipant.Status.DECLINED])


class RentalDecisionSerializer(serializers.Serializer):
    """BOOK-40."""

    status = serializers.ChoiceField(choices=[SessionRental.Status.APPROVED, SessionRental.Status.DECLINED])


class QuoteRentalSerializer(serializers.Serializer):
    equipment = serializers.IntegerField()
    name = serializers.CharField()
    quantity = serializers.IntegerField()
    price = serializers.DecimalField(**MONEY)


class QuoteOfferSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    message = serializers.CharField()


class QuoteSerializer(serializers.Serializer):
    """BOOK-6."""

    currency = serializers.CharField()
    price = serializers.DecimalField(**MONEY)
    offer = QuoteOfferSerializer(allow_null=True)
    discount_amount = serializers.DecimalField(**MONEY)
    rentals = QuoteRentalSerializer(many=True)
    court_amount = serializers.DecimalField(**MONEY)


class MyParamsSerializer(serializers.Serializer):
    """BOOK-66 filters (`from` is a keyword, so that field is added in __init__)."""

    to = serializers.DateTimeField(required=False)
    status = serializers.ChoiceField(choices=Session.Status.values, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from"] = serializers.DateTimeField(required=False)


class ParticipantSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)

    class Meta:
        model = SessionParticipant
        fields = ["id", "user", "status", "checked_in_at"]


class RentalSerializer(serializers.ModelSerializer):
    equipment = serializers.SerializerMethodField()

    class Meta:
        model = SessionRental
        fields = ["id", "session", "equipment", "quantity", "price", "status"]

    def get_equipment(self, rental) -> dict:
        return {"id": rental.equipment_id, "name": rental.equipment.name}


class SessionSerializer(serializers.ModelSerializer):
    """BOOK-65. `status` is the shown status (BOOK-55)."""

    status = serializers.SerializerMethodField()
    court = serializers.SerializerMethodField()
    sport = serializers.SerializerMethodField()
    booked_by = PersonSerializer(read_only=True)
    coach = PersonSerializer(read_only=True)
    participants = ParticipantSerializer(many=True, read_only=True)
    rentals = RentalSerializer(many=True, read_only=True)

    class Meta:
        model = Session
        fields = [
            "id", "kind", "status", "court", "sport", "booked_by", "coach", "group", "starts_at", "ends_at", "currency",
            "price", "coach_fee", "coach_fee_payer", "discount", "discount_amount", "participants", "rentals",
            "created_at",
        ]

    def get_status(self, session) -> str:
        return services.shown_status(session)

    def get_court(self, session) -> dict | None:
        court = session.court
        return court and {"id": court.id, "name": court.name, "club": {"id": court.club_id, "name": court.club.name}}

    def get_sport(self, session) -> dict:
        return {"id": session.sport_id, "name": session.sport.name}


class DiscountSerializer(serializers.Serializer):
    """DSC-11 input. The range and decimals depend on the session, so the service checks them."""

    amount = serializers.DecimalField(**MONEY)


class PeriodSerializer(serializers.Serializer):
    """Owner-reports intro: local dates, both included (`from` is a keyword, so that field is added in __init__)."""

    to = serializers.DateField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["from"] = serializers.DateField()


class ScheduleParamsSerializer(PeriodSerializer):
    court = serializers.IntegerField(required=False)


class ScheduleSessionSerializer(serializers.ModelSerializer):
    """RPT-1 row (`accepted` is annotated by the service)."""

    court = serializers.SerializerMethodField()
    sport = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    booker = PersonSerializer(source="booked_by", read_only=True)
    coach = PersonSerializer(read_only=True)
    group = serializers.CharField(source="group.name", default=None, read_only=True)
    accepted_count = serializers.IntegerField(source="accepted", read_only=True)
    rentals = RentalSerializer(many=True, read_only=True)

    class Meta:
        model = Session
        fields = ["id", "court", "sport", "kind", "status", "starts_at", "ends_at", "booker", "coach", "group",
                  "accepted_count", "rentals"]

    def get_court(self, session) -> dict:
        return {"id": session.court_id, "name": session.court.name}

    def get_sport(self, session) -> dict:
        return {"id": session.sport_id, "name": session.sport.name}

    def get_status(self, session) -> str:
        return services.shown_status(session)  # BOOK-55


class ScheduleClosureSerializer(serializers.Serializer):
    court = serializers.IntegerField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField()


class ScheduleSerializer(serializers.Serializer):
    sessions = ScheduleSessionSerializer(many=True)
    closures = ScheduleClosureSerializer(many=True)


class CustomerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField()
    sessions = serializers.IntegerField()


class CustomersSerializer(serializers.Serializer):
    """RPT-4, RPT-5."""

    customers = serializers.IntegerField()
    repeat_rate = serializers.DecimalField(max_digits=5, decimal_places=2, allow_null=True)
    people = CustomerSerializer(many=True)


class AttendanceSerializer(serializers.Serializer):
    """RPT-6."""

    session = serializers.IntegerField()
    accepted = ParticipantSerializer(many=True)
    checked_in = serializers.IntegerField()
    no_shows = PersonSerializer(many=True)


class PlayerSessionSerializer(serializers.ModelSerializer):
    """RPT-8 row."""

    session = serializers.IntegerField(source="session_id")
    kind = serializers.CharField(source="session.kind")
    starts_at = serializers.DateTimeField(source="session.starts_at")
    ends_at = serializers.DateTimeField(source="session.ends_at")
    training_load = serializers.SerializerMethodField()

    class Meta:
        model = SessionParticipant
        fields = ["session", "kind", "starts_at", "ends_at", "checked_in_at", "rpe", "rpe_minutes", "training_load"]

    def get_training_load(self, row) -> int | None:
        return row.rpe * row.rpe_minutes if row.rpe is not None and row.rpe_minutes is not None else None
