from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from venues.models import Court

from . import services
from .models import SessionRental
from .serializers import (
    AnswerSerializer, BookingSerializer, SessionInviteSerializer, MyParamsSerializer, ParticipantSerializer, QuoteSerializer,
    RentalDecisionSerializer, RentalSerializer, SessionSerializer, SlotQuerySerializer, SlotSerializer,
)


class SlotsView(generics.GenericAPIView):
    """AVL-10 to AVL-12: public, not paginated."""

    permission_classes = [permissions.AllowAny]
    serializer_class = SlotSerializer

    @extend_schema(parameters=[SlotQuerySerializer], responses=SlotSerializer(many=True))
    def get(self, request, pk):
        court = get_object_or_404(Court.objects.select_related("club").filter(is_active=True), pk=pk)  # AVL-12
        params = SlotQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        club, day = court.club, params.validated_data["date"]
        currency = params.validated_data.get("currency", club.currency)
        rate = services.club_rate(club, currency)  # PRC-1, AVL-12
        services.check_day(club, day)  # AVL-12
        slots = [
            {"starts_at": s.starts_at, "ends_at": s.ends_at, "price": services.unit_price(s.rate, s.rate.price, currency, club, rate)}
            for s in services.free_slots(court, day)
        ]
        return Response(SlotSerializer(slots, many=True).data)


class QuoteView(generics.GenericAPIView):
    serializer_class = BookingSerializer

    @extend_schema(responses=QuoteSerializer)
    def post(self, request):
        """BOOK-6: read-only."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(QuoteSerializer(services.quote_court_booking(request.user, serializer.validated_data)).data)


class BookingView(generics.GenericAPIView):
    serializer_class = BookingSerializer

    @extend_schema(responses=SessionSerializer)
    def post(self, request):
        """BOOK-5, BOOK-7, BOOK-8."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.book_court(request.user, serializer.validated_data)
        return Response(SessionSerializer(session).data, status=status.HTTP_201_CREATED)


class SessionView(generics.GenericAPIView):
    serializer_class = SessionSerializer

    def get(self, request, pk):
        """BOOK-65."""
        return Response(self.get_serializer(services.seen_session(request.user, pk)).data)


class MySessionsView(generics.ListAPIView):
    """BOOK-66."""

    serializer_class = SessionSerializer

    @extend_schema(parameters=[MyParamsSerializer])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        params = MyParamsSerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        return services.my_sessions(self.request.user, data.get("from"), data.get("to"), data.get("status"))


class CancelView(generics.GenericAPIView):
    serializer_class = SessionSerializer

    def post(self, request, pk):
        """BOOK-50, BOOK-51: `200` also on a repeat."""
        session = services.cancel(request.user, services.seen_session(request.user, pk))
        return Response(self.get_serializer(session).data)


class ParticipantsView(generics.GenericAPIView):
    serializer_class = SessionInviteSerializer

    @extend_schema(responses=SessionSerializer)
    def post(self, request, pk):
        """BOOK-15: `201` if someone was invited, `200` if everyone already had a row."""
        session = services.seen_session(request.user, pk)
        if session.booked_by_id != request.user.pk:
            raise PermissionDenied("Only the booker can invite.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invited = services.invite(request.user, session, serializer.validated_data["invitees"])
        code = status.HTTP_201_CREATED if invited else status.HTTP_200_OK
        return Response(SessionSerializer(services.seen_session(request.user, pk)).data, status=code)


class ParticipantView(generics.GenericAPIView):
    serializer_class = AnswerSerializer

    def row(self, pk, user_id):
        session = services.seen_session(self.request.user, pk)
        row = session.participants.filter(user_id=user_id).select_related("user").first()
        if row is None:
            raise NotFound()
        return session, row

    @extend_schema(responses=ParticipantSerializer)
    def patch(self, request, pk, user_id):
        """BOOK-16: the invitee answers; `200` also on a repeat."""
        session, row = self.row(pk, user_id)
        if row.user_id != request.user.pk:
            raise PermissionDenied("You can only change your own answer.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(ParticipantSerializer(services.respond(session, row, serializer.validated_data["status"])).data)

    def delete(self, request, pk, user_id):
        """BOOK-17: the booker removes someone."""
        session, row = self.row(pk, user_id)
        services.remove_participant(request.user, session, row)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RentalView(generics.GenericAPIView):
    serializer_class = RentalDecisionSerializer

    @extend_schema(responses=RentalSerializer)
    def patch(self, request, pk):
        """BOOK-40, BOOK-41: the club side approves or declines."""
        rental = get_object_or_404(SessionRental.objects.select_related("equipment", "session__court__club"), pk=pk)
        if not services.can_see(request.user, rental.session):  # GEN-3
            raise NotFound()
        if not services.is_club_side(request.user, rental.session.court.club):
            raise PermissionDenied("Only the club can decide on rentals.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(RentalSerializer(services.decide_rental(rental, serializer.validated_data["status"])).data)
