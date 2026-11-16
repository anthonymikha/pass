from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from . import services
from .models import User
from .serializers import DeviceSerializer, LoginSerializer, RegisterSerializer, UserSerializer


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
