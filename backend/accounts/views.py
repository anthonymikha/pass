from rest_framework import generics, permissions, status
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import LoginSerializer, RegisterSerializer, UserSerializer


def token_response(user, status_code=status.HTTP_200_OK):
    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "user": UserSerializer(user).data}, status=status_code)


class PublicAuthView(APIView):
    """Base for the endpoints reachable without a token; throttled per IP."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]
    throttle_scope = "auth"


class RegisterView(PublicAuthView):
    # ponytail: no email verification; add it when the project can send email.
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.create_user(**serializer.validated_data)
        return token_response(user, status.HTTP_201_CREATED)


class LoginView(PublicAuthView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return token_response(serializer.validated_data["user"])


class LogoutView(APIView):
    def post(self, request):
        Token.objects.filter(user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user
