from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from teams.services import coachs_players
from venues.models import Court

from . import services
from .models import SessionRental
from .serializers import (
    AnswerSerializer, AttendanceSerializer, AvailabilityParamsSerializer, BookingSerializer, CustomersSerializer,
    DiscountSerializer, IntervalSerializer, SessionInviteSerializer, MyParamsSerializer, ParticipantSerializer,
    PeriodSerializer, PlayerSessionSerializer, QuoteSerializer, RentalDecisionSerializer, RentalSerializer,
    ScheduleParamsSerializer, ScheduleSerializer, SessionSerializer, SlotQuerySerializer, SlotSerializer,
    TrainingBookingSerializer, TrainingConfirmSerializer, TrainingRequestSerializer,
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


def seen_row(user, pk, user_id):
    """GEN-3: the session must be visible, and the participant row must exist in it."""
    session = services.seen_session(user, pk)
    row = session.participants.filter(user_id=user_id).select_related("user").first()
    if row is None:
        raise NotFound()
    return session, row


class ParticipantView(generics.GenericAPIView):
    serializer_class = AnswerSerializer

    def row(self, pk, user_id):
        return seen_row(self.request.user, pk, user_id)

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


class TrainingRequestView(generics.GenericAPIView):
    serializer_class = TrainingRequestSerializer

    @extend_schema(responses=SessionSerializer)
    def post(self, request):
        """BOOK-20: a player asks a coach."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.request_training(request.user, serializer.validated_data)
        return Response(SessionSerializer(services.seen_session(request.user, session.pk)).data, status=status.HTTP_201_CREATED)


class RequestAnswerView(generics.GenericAPIView):
    """BOOK-21, BOOK-22: an action on a training request is for one party only, and for everyone else the session
    does not exist (BOOK-21: not the session's coach is a 404). Subclasses set `party` (who may) and `act`."""

    party = "coach_id"

    def post(self, request, pk):
        session = services.seen_session(request.user, pk)
        if getattr(session, self.party) != request.user.pk:
            raise NotFound()
        session = self.act(request, session)
        return Response(SessionSerializer(services.seen_session(request.user, pk)).data)


class TrainingConfirmView(RequestAnswerView):
    serializer_class = TrainingConfirmSerializer

    def act(self, request, session):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return services.confirm_training(session, serializer.validated_data)


class TrainingDeclineView(RequestAnswerView):
    serializer_class = SessionSerializer

    def act(self, request, session):
        return services.end_request(session, declining=True)


class TrainingWithdrawView(RequestAnswerView):
    party = "booked_by_id"
    serializer_class = SessionSerializer

    def act(self, request, session):
        return services.end_request(session, declining=False)


class CoachTrainingView(generics.GenericAPIView):
    serializer_class = TrainingBookingSerializer

    @extend_schema(responses=SessionSerializer)
    def post(self, request):
        """BOOK-30, BOOK-31: coaches only."""
        if not request.user.is_coach:
            raise PermissionDenied("Only coaches can book training.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.book_training(request.user, serializer.validated_data)
        return Response(SessionSerializer(services.seen_session(request.user, session.pk)).data, status=status.HTTP_201_CREATED)


class AvailabilityView(generics.GenericAPIView):
    """AVL-20 to AVL-24: not paginated. `who` is a function of (asker, id) returning the users to check (404 if not allowed)."""

    serializer_class = AvailabilityParamsSerializer
    who = None

    @extend_schema(parameters=[AvailabilityParamsSerializer], responses=IntervalSerializer(many=True))
    def get(self, request, pk):
        users = self.who(request.user, pk)  # AVL-22 before the input (GEN-4)
        params = AvailabilityParamsSerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        intervals = services.free_intervals(users, data["from"], data["to"], data["min_minutes"])
        return Response(IntervalSerializer(intervals, many=True).data)


class CheckInView(generics.GenericAPIView):
    serializer_class = ParticipantSerializer

    def post(self, request, pk, user_id):
        """PAY-1 to PAY-7: check a participant in; `200` also on a repeat (GEN-5). The booker's check-in creates the payments."""
        session, row = seen_row(request.user, pk, user_id)
        return Response(self.get_serializer(services.check_in(request.user, session, row)).data)


class DiscountView(generics.GenericAPIView):
    serializer_class = DiscountSerializer

    @extend_schema(responses=SessionSerializer)
    def put(self, request, pk):
        """DSC-10 to DSC-14: the club owner sets (or with 0 removes) the one-off discount."""
        session = services.seen_session(request.user, pk)
        if not (session.court_id and session.court.club.owner_id == request.user.pk):  # permission before input (GEN-4)
            raise PermissionDenied("Only the club owner can discount a session.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_session_discount(session, serializer.validated_data["amount"])
        return Response(SessionSerializer(services.seen_session(request.user, pk)).data)


class AttendanceView(generics.GenericAPIView):
    serializer_class = AttendanceSerializer

    def get(self, request, pk):
        """RPT-6: the club side of the court's club, or the session coach."""
        session = services.seen_session(request.user, pk)
        if not (session.coach_id == request.user.pk or (
                session.court_id and services.is_club_side(request.user, session.court.club))):
            raise PermissionDenied("Only the club side or the session coach can read attendance.")
        rows, no_shows = services.attendance(session)
        return Response(AttendanceSerializer({
            "session": session.pk, "accepted": rows, "checked_in": sum(1 for r in rows if r.checked_in_at),
            "no_shows": no_shows}).data)


class ScheduleView(generics.GenericAPIView):
    serializer_class = ScheduleParamsSerializer

    @extend_schema(parameters=[ScheduleParamsSerializer], responses=ScheduleSerializer)
    def get(self, request, club):
        """RPT-1: the club side; not paginated."""
        club = services.club_report_access(request.user, club)
        params = self.get_serializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        data = params.validated_data
        court = None
        if "court" in data:
            court = club.courts.filter(pk=data["court"]).first()
            if court is None:
                raise ValidationError({"court": ["Not found."]})  # GEN-18
        sessions, closures = services.schedule(club, data["from"], data["to"], court)
        return Response(ScheduleSerializer({"sessions": sessions, "closures": closures}).data)


class CustomersView(generics.GenericAPIView):
    serializer_class = PeriodSerializer

    @extend_schema(parameters=[PeriodSerializer], responses=CustomersSerializer)
    def get(self, request, club):
        """RPT-4, RPT-5: the club owner only (ACC-6); not paginated."""
        club = services.club_report_access(request.user, club, owner_only=True)
        params = self.get_serializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        people, rate = services.customers(club, params.validated_data["from"], params.validated_data["to"])
        return Response(CustomersSerializer({"customers": len(people), "repeat_rate": rate, "people": people}).data)


class PlayerHistoryView(generics.ListAPIView):
    serializer_class = PlayerSessionSerializer

    def get_queryset(self):
        """RPT-8: a coach, for one of the coach's players (ACC-1); anyone else's id is a 404."""
        coach = self.request.user
        if not coach.is_coach:
            raise PermissionDenied("Only coaches can read player history.")
        player = get_object_or_404(coachs_players(coach), pk=self.kwargs["user_id"])
        return services.player_history(coach, player)
