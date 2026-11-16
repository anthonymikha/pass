import zoneinfo

from drf_spectacular.utils import extend_schema
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from bookings.serializers import PeriodSerializer
from bookings.services import club_report_access, report_period

from . import services
from .models import Payment
from .serializers import DueListSerializer, EarningsSerializer, PaymentSerializer, RevenueSerializer


class PaymentListView(generics.ListAPIView):
    """PAY-23: what the caller owes and what they are owed, newest first."""

    serializer_class = PaymentSerializer

    def get_queryset(self):
        return services.visible_payments(self.request.user)


class PaymentView(generics.RetrieveAPIView):
    serializer_class = PaymentSerializer

    def get_queryset(self):
        return services.visible_payments(self.request.user)  # GEN-3, PAY-23: anyone else gets a 404


class PaymentPaidView(generics.GenericAPIView):
    """PAY-20, PAY-21: the payee side only. `paid` is set by `as_view(paid=...)`; `200` also on a repeat (GEN-5)."""

    serializer_class = PaymentSerializer
    paid = True

    def post(self, request, pk):
        payment = get_object_or_404(services.visible_payments(request.user), pk=pk)
        if not services.is_payee_side(request.user, payment):  # the payer sees the row but may not tick it
            raise PermissionDenied("Only the payee can mark a payment.")
        return Response(self.get_serializer(services.set_paid(payment, self.paid)).data)


def period(request, tz):
    params = PeriodSerializer(data=request.query_params)
    params.is_valid(raise_exception=True)
    return report_period(tz, params.validated_data["from"], params.validated_data["to"])


class DuesView(generics.GenericAPIView):
    serializer_class = DueListSerializer

    def get(self, request, club):
        """RPT-2: the club side; not paginated (a due list is short while payees tick rows off)."""
        club = club_report_access(request.user, club)
        return Response(self.get_serializer(services.due_list(Payment.objects.filter(club=club))).data)


class RevenueView(generics.GenericAPIView):
    serializer_class = RevenueSerializer

    @extend_schema(parameters=[PeriodSerializer])
    def get(self, request, club):
        """RPT-3: the club owner only (ACC-6)."""
        club = club_report_access(request.user, club, owner_only=True)
        start, end = period(request, zoneinfo.ZoneInfo(club.timezone))
        return Response(self.get_serializer({"currencies": services.revenue(Payment.objects.filter(club=club), start, end)}).data)


class EarningsView(generics.GenericAPIView):
    serializer_class = EarningsSerializer

    @extend_schema(parameters=[PeriodSerializer])
    def get(self, request):
        """RPT-7: a coach, for themselves; the period is in their own timezone (GEN-8)."""
        if not request.user.is_coach:
            raise PermissionDenied("Only coaches have earnings.")
        payments = Payment.objects.filter(coach=request.user)
        start, end = period(request, zoneinfo.ZoneInfo(request.user.timezone))
        return Response(self.get_serializer({
            "currencies": services.revenue(payments, start, end), "due": services.due_list(payments)}).data)
