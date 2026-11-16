"""Group chat upkeep (TEAM-20, TEAM-28 to TEAM-30, called from teams.services) and session cards (CHAT-30, from bookings), in their caller's transaction."""
from .models import Chat, ChatMember, Message


def create_group_chat(group, owner):
    """TEAM-20: the group's chat, with the owner as its first member."""
    chat = Chat.objects.create(type=Chat.Type.GROUP, group=group)
    ChatMember.objects.create(chat=chat, user=owner)
    return chat


def add_chat_member(group, user):
    """TEAM-28, CHAT-4: no-op if already a member or the group has no chat."""
    chat = Chat.objects.filter(group=group).first()
    if chat:
        ChatMember.objects.get_or_create(chat=chat, user=user)


def remove_chat_member(group, user):
    """TEAM-28."""
    ChatMember.objects.filter(chat__group=group, user=user).delete()


def detach_chat(group):
    """TEAM-30: the chat stays, with `group` emptied and no members."""
    ChatMember.objects.filter(chat__group=group).delete()
    Chat.objects.filter(group=group).update(group=None)


def post_session_card(session):
    """CHAT-30, BOOK-60: one card per session in the group's chat; nothing if the group has no chat."""
    chat = Chat.objects.filter(group=session.group_id).first()
    if chat and not Message.objects.filter(chat=chat, session=session).exists():
        Message.objects.create(chat=chat, session=session)
