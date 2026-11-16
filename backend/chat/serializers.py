from rest_framework import serializers

from accounts.models import User
from config.api import VisibleRelatedField

from . import services
from .models import Chat, Message


class DirectOpenSerializer(serializers.Serializer):
    """CHAT-2: GEN-18, an unknown id is "Not found."; who may be chatted with is CHAT-1."""

    user = VisibleRelatedField(queryset=User.objects.all())


class InquiryOpenSerializer(serializers.Serializer):
    """CHAT-6, CHAT-7: `user` only from the club side."""

    user = VisibleRelatedField(queryset=User.objects.all(), required=False)


class MessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=4000)  # CHAT-10: trimmed, 1-4000


class PollQuerySerializer(serializers.Serializer):
    """CHAT-14."""

    after = serializers.IntegerField(min_value=0, required=False)
    before = serializers.IntegerField(min_value=0, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=50)

    def validate(self, data):
        if "after" in data and "before" in data:
            raise serializers.ValidationError({"before": "Use either after or before, not both."})
        return data


class MessageSerializer(serializers.ModelSerializer):
    sender = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "chat", "sender", "body", "session", "created_at"]  # CHAT-17: text only; session = card (CHAT-30)

    def get_sender(self, obj) -> dict | None:
        return {"id": obj.sender_id, "full_name": obj.sender.full_name} if obj.sender_id else None


class ChatSerializer(serializers.ModelSerializer):
    """CHAT-15, for the viewer in `context["request"]`. Expects `members__user`, `group` and `club` loaded."""

    title = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Chat
        fields = ["id", "type", "group", "club", "title", "last_message", "unread_count", "created_at"]

    def get_title(self, chat) -> str:
        me = self.context["request"].user
        if chat.type == Chat.Type.GROUP:
            return chat.group.name if chat.group else ""
        if chat.type == Chat.Type.INQUIRY and services.viewer_member(chat, me):
            return chat.club.name if chat.club else ""
        # a direct chat's other person; the inquirer for the club side
        other = next((m.user for m in chat.members.all() if m.user_id != me.pk), None)
        return other.full_name if other else ""

    def get_last_message(self, chat) -> dict | None:
        # ponytail: one query per chat on the page (<= 50); annotate if lists get slow
        last = Message.objects.filter(chat=chat).select_related("sender").order_by("-id").first()
        return MessageSerializer(last).data if last else None

    def get_unread_count(self, chat) -> int:
        return services.unread_count(chat, self.context["request"].user)
