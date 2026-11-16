from rest_framework import serializers

from accounts.serializers import PersonSerializer

from .models import Payment

SUM = {"max_digits": 20, "decimal_places": 3}  # totals can be wider than one amount (GEN-13)


class PaymentSerializer(serializers.ModelSerializer):
    """PAY-23."""

    payer = PersonSerializer(read_only=True)
    coach = PersonSerializer(read_only=True)
    club = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "session", "payer", "club", "coach", "amount", "currency", "platform_fee", "method", "paid_at",
                  "settled_at", "created_at"]

    def get_club(self, payment) -> dict | None:
        return payment.club and {"id": payment.club_id, "name": payment.club.name}


class DueSerializer(serializers.ModelSerializer):
    """RPT-2 row."""

    payer = PersonSerializer(read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "session", "payer", "amount", "currency", "created_at"]


class TotalSerializer(serializers.Serializer):
    currency = serializers.CharField()
    total = serializers.DecimalField(**SUM)


class DueListSerializer(serializers.Serializer):
    payments = DueSerializer(many=True)
    totals = TotalSerializer(many=True)


class RevenueRowSerializer(serializers.Serializer):
    currency = serializers.CharField()
    gross = serializers.DecimalField(**SUM)
    fees = serializers.DecimalField(**SUM)
    net = serializers.DecimalField(**SUM)
    owed_to_platform = serializers.DecimalField(**SUM)


class RevenueSerializer(serializers.Serializer):
    """RPT-3."""

    currencies = RevenueRowSerializer(many=True)


class EarningsSerializer(RevenueSerializer):
    """RPT-7: RPT-3 for the coach, plus their own due list (RPT-2)."""

    due = DueListSerializer()
