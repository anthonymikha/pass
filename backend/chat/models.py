from django.conf import settings
from django.db import models

from bookings.models import Session
from teams.models import Group
from venues.models import Club


class Chat(models.Model):
    class Type(models.TextChoices):
        DIRECT = "direct"
        GROUP = "group"
        INQUIRY = "inquiry"

    type = models.CharField(max_length=20, choices=Type.choices)
    # OneToOne null=True = unique when set (NULLs never collide): one chat per group.
    group = models.OneToOneField(Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="chat")
    club = models.ForeignKey(Club, null=True, blank=True, on_delete=models.SET_NULL, related_name="chats")  # inquiry
    # CHAT-11: the club side's read marker on an inquiry, shared by the owner and all staff.
    club_last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chats"

    def __str__(self):
        return f"{self.type} chat {self.pk}"


class ChatMember(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_memberships")
    last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "chat_members"
        constraints = [models.UniqueConstraint(fields=["chat", "user"], name="chat_members_unique")]

    def __str__(self):
        return f"{self.user} in chat {self.chat_id}"


class Message(models.Model):
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    # null = system-generated session card. PROTECT, not SET_NULL, so a deleted user's
    # messages never turn into "system" messages.
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="sent_messages"
    )
    body = models.TextField(blank=True)
    # set = the message is a card linking to that session
    session = models.ForeignKey(Session, null=True, blank=True, on_delete=models.PROTECT, related_name="messages")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "messages"
        indexes = [models.Index(fields=["chat", "created_at"], name="messages_chat_created_idx")]

    def __str__(self):
        return f"chat {self.chat_id}: {self.body[:40] or f'session {self.session_id}'}"
