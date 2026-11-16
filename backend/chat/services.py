"""Group chat upkeep for the group rules (TEAM-20, TEAM-28 to TEAM-30). Called from teams.services in its transaction."""
from .models import Chat, ChatMember


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
