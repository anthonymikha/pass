"""Group chat upkeep (TEAM-20, TEAM-28 to TEAM-30, called from teams.services), session cards (CHAT-30, from bookings)
in their caller's transaction, and the chat API rules (CHAT-1 to CHAT-15)."""
from django.db import transaction
from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework.exceptions import NotFound

from accounts.models import User
from accounts.services import friends_of, is_blocked_pair, is_shadow_player, notify
from bookings.models import Session
from config.api import BusinessError
from venues.models import ClubMember, Discount
from venues.services import club_today, current_members

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


# --- club side (ACC-1, ACC-2, CHAT-8) ---

def club_side_users(club):
    """The owner plus staff with a current membership."""
    staff = current_members(club).filter(role=ClubMember.Role.STAFF).values("user")
    return User.objects.filter(Q(pk=club.owner_id) | Q(pk__in=staff))


def is_club_side(user, club):
    return club_side_users(club).filter(pk=user.pk).exists()


def club_side_club_ids(user):
    """Clubs the user owns or currently staffs (checked now, so an expired staff member drops out: ACC-2)."""
    ids = [
        m.club_id
        for m in ClubMember.objects.filter(user=user, role=ClubMember.Role.STAFF, status=ClubMember.Status.ACTIVE)
        .select_related("club")
        if m.expires_on is None or m.expires_on >= club_today(m.club)
    ]
    return set(ids) | set(user.owned_clubs.values_list("pk", flat=True))


# --- who may talk (CHAT-1, CHAT-3) ---

def can_chat(a, b):
    """CHAT-1."""
    from teams.services import coachs_players  # lazy: teams.services imports this module

    if a.pk == b.pk or not (a.is_active and b.is_active):
        return False
    if is_shadow_player(a) or is_shadow_player(b) or is_blocked_pair(a, b):
        return False
    if friends_of(a).filter(pk=b.pk).exists():
        return True
    return any(c.is_coach and coachs_players(c).filter(pk=p.pk).exists() for c, p in ((a, b), (b, a)))


def _lock_users(*users):
    """CHAT-2: lock the rows in id order so two simultaneous opens cannot both create."""
    list(User.objects.select_for_update().filter(pk__in=[u.pk for u in users]).order_by("pk"))


def open_direct(a, b):
    """CHAT-2. Returns (chat, created)."""
    with transaction.atomic():
        _lock_users(a, b)
        if not can_chat(a, b):
            raise BusinessError("cannot_chat", "You cannot chat with this user.")
        chat = Chat.objects.filter(type=Chat.Type.DIRECT, members__user=a).filter(members__user=b).first()
        if chat:
            return chat, False
        chat = Chat.objects.create(type=Chat.Type.DIRECT)
        ChatMember.objects.bulk_create([ChatMember(chat=chat, user=a), ChatMember(chat=chat, user=b)])
        return chat, True


def _may_be_contacted_by(club, user):
    """CHAT-7: a non-cancelled session at the club, a current membership, or a targeted offer."""
    sessions = Session.objects.filter(court__club=club).exclude(status=Session.Status.CANCELLED)
    return (
        sessions.filter(Q(booked_by=user) | Q(participants__user=user)).exists()
        or current_members(club).filter(user=user).exists()
        or Discount.objects.filter(club=club, user=user).exists()
    )


def open_inquiry(caller, club, target=None):
    """CHAT-6 (caller asks the club), CHAT-7 (club side passes `target`, the user to write to). Returns (chat, created)."""
    side = is_club_side(caller, club)
    if target is None:
        if side:  # CHAT-6: not with your own club
            raise BusinessError("cannot_chat", "You cannot start an inquiry with your own club.")
        user = caller
    else:
        if not side:
            raise BusinessError("cannot_chat", "Only the club side can write first.")
        # ACC-12: shadow players are never chat members; the club side cannot be its own inquirer (CHAT-6)
        if not target.is_active or is_shadow_player(target) or is_club_side(target, club) or not _may_be_contacted_by(club, target):
            raise BusinessError("cannot_chat", "You cannot chat with this user.")
        user = target
    with transaction.atomic():
        _lock_users(user)  # CHAT-5: one per (user, club)
        chat = Chat.objects.filter(type=Chat.Type.INQUIRY, club=club, members__user=user).first()
        if chat:
            return chat, False
        chat = Chat.objects.create(type=Chat.Type.INQUIRY, club=club)
        ChatMember.objects.create(chat=chat, user=user)
        return chat, True


# --- reading (CHAT-8, CHAT-11 to CHAT-15) ---

def visible_chats(user):
    """CHAT-15: chats the user is a member of, plus inquiry chats of clubs on whose side they are now."""
    return Chat.objects.filter(
        Q(members__user=user) | Q(type=Chat.Type.INQUIRY, club__in=club_side_club_ids(user))
    ).distinct()


def get_chat(user, pk):
    """GEN-3: a chat the user may not see is a 404."""
    chat = visible_chats(user).select_related("group", "club").prefetch_related("members__user").filter(pk=pk).first()
    if chat is None:
        raise NotFound()
    return chat


def sorted_chats(qs):
    """CHAT-15: newest last message first (a chat with no message sorts by its creation)."""
    newest = Message.objects.filter(chat=OuterRef("pk")).order_by("-id").values("created_at")[:1]
    return qs.annotate(last_at=Coalesce(Subquery(newest), F("created_at"))).order_by("-last_at", "-id")


def viewer_member(chat, user):
    """The user's own member row, or None when they read as the club side. A member row wins if they are both."""
    return next((m for m in chat.members.all() if m.user_id == user.pk), None)


def unread_count(chat, user):
    """CHAT-13."""
    member = viewer_member(chat, user)
    messages = Message.objects.filter(chat=chat)
    if member:
        marker = member.last_read_at
        messages = messages.exclude(sender=user)
    else:
        marker = chat.club_last_read_at
        # sent by the inquirer or the system
        messages = messages.filter(Q(sender__isnull=True) | Q(sender__in=[m.user_id for m in chat.members.all()]))
    return messages.filter(created_at__gt=marker).count() if marker else messages.count()


def mark_read(chat, user):
    """CHAT-12, CHAT-11, GEN-5."""
    member = viewer_member(chat, user)
    if member:
        member.last_read_at = timezone.now()
        member.save(update_fields=["last_read_at"])
    else:
        chat.club_last_read_at = timezone.now()
        chat.save(update_fields=["club_last_read_at"])


def messages_after(chat, after, limit):
    """CHAT-14: larger ids, oldest first."""
    return list(Message.objects.filter(chat=chat, id__gt=after).select_related("sender").order_by("id")[:limit])


def messages_before(chat, before, limit):
    """CHAT-14: older ids, newest first."""
    return list(Message.objects.filter(chat=chat, id__lt=before).select_related("sender").order_by("-id")[:limit])


# --- sending (CHAT-3, CHAT-10) ---

def send_message(chat, sender, body):
    """CHAT-10. The caller can see the chat (CHAT-4, CHAT-8); a direct chat also needs CHAT-1 now (CHAT-3)."""
    members = [m.user for m in chat.members.all()]
    if chat.type == Chat.Type.DIRECT:
        others = [u for u in members if u.pk != sender.pk]
        if len(others) != 1 or not can_chat(sender, others[0]):  # CHAT-3
            raise BusinessError("cannot_chat", "You cannot send messages in this chat.")
    with transaction.atomic():
        message = Message.objects.create(chat=chat, sender=sender, body=body)
        recipients = members  # NOTE-20: the other members
        if chat.type == Chat.Type.INQUIRY and sender in members:  # the member writes: the club side hears it
            recipients = club_side_users(chat.club) if chat.club else []
        notify([u for u in recipients if u.pk != sender.pk], "chat_message", sender.full_name, body[:140], {"id": chat.pk})
    return message


def forget_user(user):
    """ACC-33 step 4: the user leaves every chat; the messages they sent stay."""
    ChatMember.objects.filter(user=user).delete()
