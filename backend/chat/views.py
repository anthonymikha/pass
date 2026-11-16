from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from venues.services import visible_clubs

from . import services
from .serializers import (
    ChatSerializer, DirectOpenSerializer, InquiryOpenSerializer, MessageCreateSerializer, MessageSerializer,
    PollQuerySerializer,
)


def chat_response(request, chat, created=False):
    """GEN-5: 201 only on the call that created the chat."""
    return Response(ChatSerializer(services.get_chat(request.user, chat.pk), context={"request": request}).data,
                    status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class ChatListView(generics.ListAPIView):
    """CHAT-15."""

    serializer_class = ChatSerializer

    def get_queryset(self):
        qs = services.visible_chats(self.request.user).select_related("group", "club").prefetch_related("members__user")
        return services.sorted_chats(qs)


class ChatDetailView(generics.GenericAPIView):
    serializer_class = ChatSerializer

    def get(self, request, pk):
        return Response(self.get_serializer(services.get_chat(request.user, pk)).data)


class DirectChatView(generics.GenericAPIView):
    serializer_class = DirectOpenSerializer

    @extend_schema(responses=ChatSerializer)
    def post(self, request):
        """CHAT-1, CHAT-2."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat, created = services.open_direct(request.user, serializer.validated_data["user"])
        return chat_response(request, chat, created)


class ClubInquiryView(generics.GenericAPIView):
    serializer_class = InquiryOpenSerializer

    @extend_schema(responses=ChatSerializer)
    def post(self, request, pk):
        """CHAT-6, CHAT-7."""
        club = get_object_or_404(visible_clubs(request.user), pk=pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chat, created = services.open_inquiry(request.user, club, serializer.validated_data.get("user"))
        return chat_response(request, chat, created)


class ChatMessagesView(generics.GenericAPIView):
    serializer_class = MessageCreateSerializer

    @extend_schema(parameters=[PollQuerySerializer], responses=MessageSerializer(many=True))
    def get(self, request, pk):
        """CHAT-14: a plain list, not paged."""
        chat = services.get_chat(request.user, pk)
        params = PollQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)
        limit = params.validated_data["limit"]
        if "before" in params.validated_data:
            rows = services.messages_before(chat, params.validated_data["before"], limit)
        else:
            rows = services.messages_after(chat, params.validated_data.get("after", 0), limit)
        return Response(MessageSerializer(rows, many=True).data)

    @extend_schema(responses=MessageSerializer)
    def post(self, request, pk):
        """CHAT-3, CHAT-4, CHAT-8, CHAT-10."""
        chat = services.get_chat(request.user, pk)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = services.send_message(chat, request.user, serializer.validated_data["body"])
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


class ChatReadView(generics.GenericAPIView):
    serializer_class = ChatSerializer

    def post(self, request, pk):
        """CHAT-11, CHAT-12, GEN-5."""
        chat = services.get_chat(request.user, pk)
        services.mark_read(chat, request.user)
        return chat_response(request, chat)
