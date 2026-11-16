from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from bookings.models import SessionParticipant
from teams.models import Group

from . import services
from .models import Exercise, ExerciseAssignment, SleepLog, SorenessLog, UserAchievement
from .serializers import (
    AchievementSerializer, AreaLevelSerializer, AssignInputSerializer, AssignmentQuerySerializer,
    AssignmentSerializer, ExerciseSerializer, RpeSerializer, SleepImportSerializer, SleepSerializer,
    SorenessCheckInSerializer, SorenessLogSerializer, SuggestionSerializer,
)


def subject(request, user_id):
    """The user whose logs are read: the caller, or one of the coach's players (TEAM-40; anyone else is a 404)."""
    if user_id is None:
        return request.user
    return get_object_or_404(services.players_of(request.user), pk=user_id)


# --- RPE ---

class RpeView(generics.GenericAPIView):
    serializer_class = RpeSerializer

    @extend_schema(responses=RpeSerializer)
    def put(self, request, pk):
        """WEL-1 to WEL-4: log or replace the caller's RPE and post-session soreness; 200."""
        row = get_object_or_404(SessionParticipant, session_id=pk, user=request.user)  # GEN-3: only their own row
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.submit_rpe(row, **serializer.validated_data)
        areas = SorenessLog.objects.filter(user=request.user, session_id=pk, period=SorenessLog.Period.POST_SESSION)
        return Response({
            "session": pk, "rpe": row.rpe, "rpe_minutes": row.rpe_minutes, "rpe_logged_at": row.rpe_logged_at,
            "sore_areas": AreaLevelSerializer(areas.order_by("id"), many=True).data,
        })


# --- soreness ---

class SorenessView(generics.ListAPIView):
    """The same view serves /soreness/ (own, with POST) and /players/<id>/soreness/ (a coach, read only)."""

    serializer_class = SorenessLogSerializer

    def get_queryset(self):
        user = subject(self.request, self.kwargs.get("user_id"))  # ACC-4, TEAM-40
        return SorenessLog.objects.filter(user=user).order_by("-logged_on", "-id")

    @extend_schema(request=SorenessCheckInSerializer, responses=SorenessCheckInSerializer)
    def post(self, request):
        """WEL-10 to WEL-12: replace one check-in; 200 with the suggestions for the areas sent."""
        serializer = SorenessCheckInSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.log_soreness(request.user, data["period"], data["logged_on"], data["areas"])
        found = services.suggestions([(a["body_area"], a["level"]) for a in data["areas"]])
        return Response({
            "period": data["period"], "logged_on": data["logged_on"], "areas": data["areas"],
            "suggestions": SuggestionSerializer(found, many=True).data,
        })


class SorenessSuggestionsView(generics.GenericAPIView):
    serializer_class = SuggestionSerializer

    def get(self, request):
        """WEL-31: suggestions for today, computed on request."""
        return Response(self.get_serializer(services.suggestions_for_today(request.user), many=True).data)


# --- sleep ---

class SleepView(generics.ListCreateAPIView):
    """/sleep/ (own, with POST) and /players/<id>/sleep/ (a coach, read only)."""

    serializer_class = SleepSerializer

    def get_queryset(self):
        user = subject(self.request, self.kwargs.get("user_id"))  # ACC-4, TEAM-40
        return SleepLog.objects.filter(user=user).order_by("-sleep_start", "-id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, source=SleepLog.Source.MANUAL, external_id="")  # WEL-20


class SleepDetailView(generics.GenericAPIView):
    serializer_class = SleepSerializer

    def get_object(self):
        return get_object_or_404(SleepLog, pk=self.kwargs["pk"], user=self.request.user)  # ACC-4, GEN-3

    def patch(self, request, pk):
        """WEL-20: the user changes their manual rows."""
        row = self.get_object()
        if row.source != SleepLog.Source.MANUAL:
            raise PermissionDenied("Only manual sleep entries can be changed.")
        serializer = self.get_serializer(row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        """WEL-20, WEL-22: manual or imported."""
        self.get_object().delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SleepImportView(generics.GenericAPIView):
    serializer_class = SleepImportSerializer

    @extend_schema(responses={200: {"type": "object", "properties": {"created": {"type": "integer"}, "updated": {"type": "integer"}}}})
    def post(self, request):
        """WEL-21: up to 500 records, all or nothing."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        created, updated = services.import_sleep(request.user, serializer.validated_data["records"])
        return Response({"created": created, "updated": updated})


# --- exercises ---

class ExerciseListView(generics.ListAPIView):
    """The catalogue, so a coach can find an exercise to assign (WEL-40). Read only; admins manage it (ACC-7)."""

    serializer_class = ExerciseSerializer
    queryset = Exercise.objects.order_by("name", "id")


class AssignmentListView(generics.ListAPIView):
    """/exercise-assignments/ (own list, pick) and /players/<id>/exercise-assignments/ (a coach reads or sends)."""

    serializer_class = AssignmentSerializer

    def get_queryset(self):
        """WEL-44, TEAM-40."""
        params = AssignmentQuerySerializer(data=self.request.query_params)
        params.is_valid(raise_exception=True)
        rows = ExerciseAssignment.objects.filter(user=subject(self.request, self.kwargs.get("user_id")))
        wanted = params.validated_data.get("status")
        if wanted:
            rows = rows.filter(completed_at__isnull=(wanted == "open"))
        return rows.select_related("exercise").order_by("-created_at", "-id")

    @extend_schema(request=AssignInputSerializer, responses=AssignmentSerializer)
    def post(self, request, user_id=None):
        """WEL-33 (pick: 201 new, 200 the open one); with a player in the URL WEL-40, WEL-41 (a coach sends: 201)."""
        player = subject(request, user_id)  # a non-player is a 404 before anything else
        serializer = AssignInputSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        exercise = data.pop("exercise")
        if user_id is None:
            row, created = services.pick_exercise(request.user, exercise, data)
        else:
            row, created = services.assign_to_player(request.user, player, exercise, data), True
        return Response(AssignmentSerializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class TeamAssignmentsView(generics.GenericAPIView):
    serializer_class = AssignInputSerializer

    @extend_schema(responses=AssignmentSerializer(many=True))
    def post(self, request, pk):
        """WEL-40, WEL-41: a coach sends an exercise to a team; 201 with the rows made."""
        group = get_object_or_404(Group, pk=pk)  # every group is visible by id (TEAM-21)
        if not services.can_send_to_team(request.user, group):
            raise PermissionDenied("Only the coach of a team can send it exercises.")
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        rows = services.assign_to_team(request.user, group, data.pop("exercise"), data)
        return Response(AssignmentSerializer(rows, many=True).data, status=status.HTTP_201_CREATED)


class AssignmentDetailView(generics.GenericAPIView):
    serializer_class = AssignmentSerializer

    def delete(self, request, pk):
        """WEL-43."""
        services.delete_assignment(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssignmentCompleteView(generics.GenericAPIView):
    serializer_class = AssignmentSerializer

    @extend_schema(request=None)
    def post(self, request, pk):
        """WEL-42, WEL-50: 200, also on a repeat (GEN-5)."""
        return Response(AssignmentSerializer(services.complete_assignment(request.user, pk)).data)


class AchievementListView(generics.ListAPIView):
    serializer_class = AchievementSerializer

    def get_queryset(self):
        return UserAchievement.objects.filter(user=self.request.user).order_by("earned_at", "id")  # ACC-4
