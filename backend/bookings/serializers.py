from rest_framework import serializers

from accounts.serializers import PersonSerializer
from config.api import VisibleRelatedField
from config.money import validate_currency
from venues.models import Court, Sport

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
