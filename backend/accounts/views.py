from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from . import services
from .models import Connection, User, UserBlockout
from .serializers import (
    CoachingRequestSerializer, CoachingSerializer, DeviceSerializer, LoginSerializer, PersonSerializer,
    RegisterSerializer, ShadowPlayerSerializer, UserBlockoutSerializer, UserSerializer, UserTargetSerializer,
)


def token_response(user, status_code=status.HTTP_200_OK):
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status_code)


class PublicAuthView(generics.GenericAPIView):
    """Base for the endpoints reachable without a token; throttled per IP."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"


class RegisterView(PublicAuthView):
    serializer_class = RegisterSerializer  # also what the OpenAPI schema shows as the request body

    # ponytail: no email verification; add it when the project can send email.
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_user(**serializer.validated_data)
        return token_response(user, status.HTTP_201_CREATED)


class LoginView(PublicAuthView):
    serializer_class = LoginSerializer

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return token_response(serializer.validated_data["user"])


class LogoutView(generics.GenericAPIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        with transaction.atomic():
            Token.objects.filter(user=request.user).delete()
            request.user.devices.all().delete()  # NOTE-3
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


class DeviceView(generics.GenericAPIView):
    serializer_class = DeviceSerializer

    def post(self, request):
        """NOTE-2: 201 for a new token, 200 for a repeat or a token that moved to the caller (GEN-5)."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device, created = services.register_device(request.user, **serializer.validated_data)
        return Response(self.get_serializer(device).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class DeviceDetailView(generics.GenericAPIView):
    serializer_class = DeviceSerializer

    def delete(self, request, key):
        """NOTE-3: own devices only; anyone else's is a 404 (GEN-3)."""
        if not services.unregister_device(request.user, key):
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BlockoutListView(generics.ListCreateAPIView):
    """TEAM-15, ACC-4: the caller's own block-outs."""

    serializer_class = UserBlockoutSerializer

    def get_queryset(self):
        return UserBlockout.objects.filter(user=self.request.user).order_by("starts_on", "start_time", "id")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class BlockoutDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = UserBlockoutSerializer
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return UserBlockout.objects.filter(user=self.request.user)  # someone else's is a 404 (GEN-3)


def person_response(person, status_name, created):
    return Response(
        {**PersonSerializer(person).data, "status": status_name},
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
    )


class PeopleListView(generics.ListAPIView):
    """Lists of other users (TEAM-6). `people` is a services function: user -> User queryset."""

    serializer_class = PersonSerializer
    people = None

    def get_queryset(self):
        return self.people(self.request.user)


class FriendsView(PeopleListView):
    @extend_schema(request=UserTargetSerializer, responses=PersonSerializer)
    def post(self, request):
        """TEAM-1: 201 for a new request; 200 for every repeat or an accepted crossing request (GEN-5)."""
        serializer = UserTargetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        other = serializer.validated_data["user"]
        friend_status, created = services.request_friend(request.user, other)
        return person_response(other, friend_status, created)


class FriendDetailView(generics.GenericAPIView):
    """`user_id` is the other user's id; it names the pair, whoever sent the request."""

    serializer_class = PersonSerializer

    def delete(self, request, user_id):
        """TEAM-3: decline, cancel or unfriend."""
        services.end_friend(request.user, get_object_or_404(User, pk=user_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class FriendAcceptView(generics.GenericAPIView):
    serializer_class = PersonSerializer

    @extend_schema(request=None)
    def post(self, request, user_id):
        """TEAM-2: accept the pending request that user `user_id` sent the caller."""
        other = get_object_or_404(User, pk=user_id)
        services.accept_friend(request.user, other)
        return person_response(other, Connection.Status.ACCEPTED, False)


class BlocksView(PeopleListView):
    @extend_schema(request=UserTargetSerializer, responses=PersonSerializer)
    def post(self, request):
        """TEAM-4: 201, or 200 if already blocked (GEN-5)."""
        serializer = UserTargetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        other = serializer.validated_data["user"]
        created = services.block(request.user, other)
        return person_response(other, Connection.Status.BLOCKED, created)


class BlockDetailView(generics.GenericAPIView):
    serializer_class = PersonSerializer

    def delete(self, request, user_id):
        """TEAM-5: only the blocker can unblock."""
        services.unblock(request.user, user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CoachingView(generics.ListAPIView):
    """The caller's coaching links, as coach or as player."""

    serializer_class = CoachingSerializer

    def get_queryset(self):
        me = self.request.user
        rows = Connection.objects.filter(Q(user=me) | Q(other_user=me), type=Connection.Type.COACHING)
        return rows.select_related("user", "other_user").order_by("-created_at", "-id")

    @extend_schema(request=CoachingRequestSerializer, responses=CoachingSerializer)
    def post(self, request):
        """TEAM-10, TEAM-13: any user asks a coach (the caller is always the player); 201 new, 200 if pending or accepted."""
        serializer = CoachingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row, created = services.request_coaching(request.user, serializer.validated_data["coach"])
        return Response(CoachingSerializer(row).data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CoachingDetailView(generics.GenericAPIView):
    serializer_class = CoachingSerializer

    def delete(self, request, pk):
        """TEAM-11 decline, TEAM-12 end."""
        services.end_coaching(request.user, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class CoachingAcceptView(generics.GenericAPIView):
    serializer_class = CoachingSerializer

    @extend_schema(request=None)
    def post(self, request, pk):
        """TEAM-11: the coach accepts."""
        return Response(CoachingSerializer(services.accept_coaching(request.user, pk)).data)


class ShadowPlayerListView(generics.ListCreateAPIView):
    """ACC-10, ACC-11: the calling coach's shadow players."""

    serializer_class = ShadowPlayerSerializer

    def get_queryset(self):
        return User.objects.filter(managed_by=self.request.user).order_by("full_name", "id")

    def create(self, request, *args, **kwargs):
        if not request.user.is_coach:  # ACC-10
            raise PermissionDenied("Only coaches can create shadow players.")
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        serializer.instance = services.create_shadow_player(self.request.user, serializer.validated_data)


class ShadowPlayerDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = ShadowPlayerSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return User.objects.filter(managed_by=self.request.user)  # another coach's is a 404 (ACC-11, GEN-3)
