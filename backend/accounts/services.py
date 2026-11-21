import functools
import logging

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.generics import get_object_or_404

from config.api import BusinessError
from config.storage import get_storage, is_key, upload_form

from .models import Connection, Device, User, UserBlockout

logger = logging.getLogger(__name__)

# NOTE-11: the fake sender records every push here, like django.core.mail.outbox.
# Tests inspect it and clear it (`outbox.clear()`).
outbox = []


def register_device(user, token, platform):
    """NOTE-2: returns (device, created). A token held by someone else moves to `user`."""
    with transaction.atomic():
        device, created = Device.objects.get_or_create(token=token, defaults={"user": user, "platform": platform})
        if not created and device.user_id != user.id:
            device.user = user
            device.save(update_fields=["user"])
    return device, created


def unregister_device(user, key):
    """NOTE-3: delete one of the user's own devices, found by token or id. False if they have none like that."""
    devices = Device.objects.filter(user=user)
    device = devices.filter(token=key).first() or (devices.filter(pk=key).first() if key.isdigit() else None)
    if device:
        device.delete()
    return device is not None


def notify(users, type, title, body, data=None):
    """Push to every device of `users` once the surrounding transaction commits (NOTE-13).

    `data` carries the id of the object to open, e.g. {"id": session.id}; `type` (a NOTE-20
    trigger name) is added to it (NOTE-14). Nothing is sent if the transaction rolls back.
    """
    user_ids = {u.pk for u in users}
    # FCM data values must be strings
    payload = {k: str(v) for k, v in {**(data or {}), "type": type}.items()}
    transaction.on_commit(lambda: _send_to_users(user_ids, title, body, payload))


def _send_to_users(user_ids, title, body, data):
    try:
        # Shadow players have no devices; the filter keeps it true if one ever got one.
        devices = Device.objects.filter(user__in=user_ids, user__is_active=True, user__email__isnull=False)
        for device in devices:
            try:
                send_push(device, title, body, data)
            except Exception:
                logger.exception("Push to device %s failed", device.pk)  # NOTE-13: never raised
    except Exception:
        logger.exception("Push sending failed")


@functools.lru_cache(maxsize=1)
def _fcm_session(credentials_file):
    """The service-account file is read once per process (the session refreshes its own OAuth token)."""
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        credentials_file, scopes=["https://www.googleapis.com/auth/firebase.messaging"])
    return AuthorizedSession(creds), creds.project_id


def send_push(device, title, body, data):
    """NOTE-10, NOTE-12: FCM HTTP v1 when FCM_CREDENTIALS_FILE is set, else the fake sender (NOTE-11).
    Deletes the device row when Firebase says the token is no longer registered; raises on any other failure
    (the caller logs it)."""
    if not settings.FCM_CREDENTIALS_FILE:
        logger.info("Fake push to user %s: %s - %s %s", device.user_id, title, body, data)
        outbox.append({"user_id": device.user_id, "token": device.token, "title": title, "body": body, "data": data})
        return
    session, project_id = _fcm_session(settings.FCM_CREDENTIALS_FILE)
    message = {"token": device.token, "notification": {"title": title, "body": body}, "data": data}
    response = session.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send", json={"message": message}, timeout=10)
    if response.ok:
        return
    error = response.json().get("error", {}) if response.content else {}
    if any(d.get("errorCode") == "UNREGISTERED" for d in error.get("details", [])):
        device.delete()
        return
    raise RuntimeError(f"FCM answered {response.status_code}: {response.text[:500]}")


# --- People: shadow players, blocked pairs, friends (ACC-1, TEAM-1 to TEAM-7) ---

FRIEND, COACHING = Connection.Type.FRIEND, Connection.Type.COACHING
PENDING, ACCEPTED, BLOCKED = Connection.Status.PENDING, Connection.Status.ACCEPTED, Connection.Status.BLOCKED


def is_shadow_player(user):
    """ACC-1. No email is what makes an account unable to sign in; a shadow player whose coach was
    deleted (managed_by emptied) is still one."""
    return user.email is None


def _pair(a, b):
    return Q(user=a, other_user=b) | Q(user=b, other_user=a)


def is_blocked_pair(a, b):
    """ACC-1: a `blocked` connection in either direction."""
    return Connection.objects.filter(_pair(a, b), type=FRIEND, status=BLOCKED).exists()


def friends_of(user):
    """ACC-1: users with an accepted friend connection to `user` in either direction, each once (TEAM-7)."""
    accepted = Connection.objects.filter(type=FRIEND, status=ACCEPTED)
    return User.objects.filter(
        Q(pk__in=accepted.filter(user=user).values("other_user")) | Q(pk__in=accepted.filter(other_user=user).values("user"))
    ).order_by("full_name", "id")


def _people(pks):
    return User.objects.filter(pk__in=pks).order_by("full_name", "id")


def incoming_friend_requests(user):  # TEAM-6
    return _people(Connection.objects.filter(other_user=user, type=FRIEND, status=PENDING).values("user"))


def outgoing_friend_requests(user):  # TEAM-6
    return _people(Connection.objects.filter(user=user, type=FRIEND, status=PENDING).values("other_user"))


def blocked_users(user):  # TEAM-6: only the users the caller blocked, never who blocked the caller
    return _people(Connection.objects.filter(user=user, type=FRIEND, status=BLOCKED).values("other_user"))


def _friend_rows(a, b):
    """Friend rows between two users in either direction, blocked rows excluded (TEAM-7: there can be two)."""
    return Connection.objects.filter(_pair(a, b), type=FRIEND).exclude(status=BLOCKED)


def _check_can_connect(user, other):
    if user.pk == other.pk:
        raise BusinessError("cannot_connect", "You cannot connect with yourself.")
    if is_blocked_pair(user, other):  # TEAM-1 step 1, TEAM-10
        raise BusinessError("cannot_connect", "You cannot connect with this user.")


def _name(user):
    return user.full_name or "Someone"  # never the email in a push


def request_friend(user, other):
    """TEAM-1: returns (status, created). `other` is already known to be an active non-shadow user."""
    with transaction.atomic():
        _check_can_connect(user, other)
        rows = _friend_rows(user, other)
        if rows.filter(status=ACCEPTED).exists():  # step 2
            return ACCEPTED, False
        if rows.filter(user=user).exists():  # step 3
            return PENDING, False
        if rows.filter(user=other).update(status=ACCEPTED):  # step 4: both want it
            return ACCEPTED, False
        row, created = Connection.objects.get_or_create(user=user, other_user=other, type=FRIEND, defaults={"status": PENDING})
        if created:  # step 5
            notify([other], "friend_request", "New friend request", f"{_name(user)} wants to be your friend", {"id": row.id})
        return PENDING, created


def accept_friend(user, other):
    """TEAM-2: the other_user of a pending row accepts. Repeating on friends is a 200 (GEN-5)."""
    with transaction.atomic():
        if Connection.objects.filter(user=other, other_user=user, type=FRIEND, status=PENDING).update(status=ACCEPTED):
            # TEAM-7: with two crossing pending rows, accepting either makes the pair friends
            Connection.objects.filter(user=user, other_user=other, type=FRIEND, status=PENDING).update(status=ACCEPTED)
        elif not _friend_rows(user, other).filter(status=ACCEPTED).exists():
            raise NotFound()


def end_friend(user, other):
    """TEAM-3: decline, cancel or unfriend; either side may delete any non-blocked row of the pair."""
    if not _friend_rows(user, other).delete()[0]:
        raise NotFound()


def block(user, other):
    """TEAM-4: returns created (False on a repeat, GEN-5). Their own block of us (if any) stays."""
    with transaction.atomic():
        if user.pk == other.pk:
            raise BusinessError("cannot_connect", "You cannot block yourself.")
        _friend_rows(user, other).delete()
        Connection.objects.filter(_pair(user, other), type=COACHING).delete()
        return Connection.objects.get_or_create(user=user, other_user=other, type=FRIEND, defaults={"status": BLOCKED})[1]


def unblock(user, other_id):
    """TEAM-5: only the blocker's own row can be deleted, so the blocked user always gets a 404."""
    if not Connection.objects.filter(user=user, other_user_id=other_id, type=FRIEND, status=BLOCKED).delete()[0]:
        raise NotFound()


# --- Coaching links (TEAM-10 to TEAM-13) ---

def request_coaching(player, coach):
    """TEAM-10: returns (row, created). Row is user = coach, other_user = player."""
    with transaction.atomic():
        _check_can_connect(player, coach)
        if not coach.is_coach:
            raise BusinessError("not_a_coach", "This user is not a coach.")
        row, created = Connection.objects.get_or_create(user=coach, other_user=player, type=COACHING, defaults={"status": PENDING})
        if created:
            notify([coach], "coaching_request", "New coaching request", f"{_name(player)} wants you as a coach", {"id": row.id})
        return row, created


def _coaching_row(user, pk):
    """A coaching row the user is part of; anyone else's is a 404 (GEN-3)."""
    rows = Connection.objects.filter(Q(user=user) | Q(other_user=user), type=COACHING).select_related("user", "other_user")
    return get_object_or_404(rows, pk=pk)


def accept_coaching(coach, pk):
    """TEAM-11: only the coach (the row's user) accepts; repeating is a 200 (GEN-5)."""
    row = _coaching_row(coach, pk)
    if row.user_id != coach.pk:
        raise PermissionDenied("Only the coach can accept.")
    if row.status == PENDING:
        row.status = ACCEPTED
        row.save(update_fields=["status"])
    return row


def end_coaching(user, pk):
    """TEAM-11 decline (the coach, pending) and TEAM-12 end (either side, accepted)."""
    row = _coaching_row(user, pk)
    if row.status == PENDING and row.user_id != user.pk:
        raise PermissionDenied("Only the coach can decline.")
    row.delete()


# --- Shadow players (ACC-10) ---

def create_shadow_player(coach, data):
    return User.objects.create_user(email=None, managed_by=coach, timezone=coach.timezone, **data)


AVATAR_TYPES = ("jpg", "jpeg", "png", "webp")
AVATAR_MAX_BYTES = 5 * 1024 * 1024


def avatar_url(user):
    """REC-30, ACC-21: a signed link to the avatar, or empty."""
    return get_storage().url(user.avatar.name) if user.avatar else ""


def avatar_form(user, ext, size_bytes):
    """REC-30: a signed upload form for a new avatar key."""
    return upload_form(f"avatars/{user.pk}", ext, size_bytes)


def set_avatar(user, key):
    """REC-30: the key must be this user's and the object must exist; the old object is deleted. Repeating the
    current key changes nothing (GEN-5)."""
    if not is_key(key, f"avatars/{user.pk}", AVATAR_TYPES):
        raise BusinessError("bad_key", "This is not an avatar upload key of yours.")
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        old = user.avatar.name
        if old == key:
            return user
        if not get_storage().exists(key):
            raise BusinessError("not_uploaded", "Nothing was uploaded to this key.")
        user.avatar = key
        user.save(update_fields=["avatar"])
        if old:
            get_storage().delete(old)
    return user


# --- your account (ACC-33) ---

DELETED_NAME = "Deleted user"


def delete_account(user):
    """ACC-33: the view has checked the password and that the user owns no club. One transaction; the avatar file
    goes after commit. Each later app forgets the user through one function (docs/backend/README.md)."""
    from bookings.services import leave_upcoming_sessions
    from chat.services import forget_user as leave_chats
    from teams.services import leave_all_groups
    from venues.services import forget_user as leave_clubs
    from wellness.services import forget_user as forget_wellness
    from rest_framework.authtoken.models import Token

    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        leave_upcoming_sessions(user)  # step 1
        leave_all_groups(user)  # step 2
        User.objects.filter(managed_by=user, email__isnull=True).update(managed_by=None)  # step 3
        Token.objects.filter(user=user).delete()  # step 4
        user.devices.all().delete()
        Connection.objects.filter(Q(user=user) | Q(other_user=user)).delete()
        UserBlockout.objects.filter(user=user).delete()
        forget_wellness(user)
        leave_chats(user)
        leave_clubs(user)
        avatar = user.avatar.name
        user.full_name, user.email = DELETED_NAME, f"deleted-{user.pk}@invalid"  # step 5; never empty (ACC-1)
        user.phone, user.sex, user.nationality, user.dominant_hand = "", "", "", ""
        user.date_of_birth = user.height_cm = user.weight_kg = user.coach_rate = None
        user.coach_bio, user.coach_currency, user.is_coach, user.timezone = "", "", False, "UTC"
        user.avatar, user.is_active = "", False
        user.set_unusable_password()
        user.save()
        if avatar:
            transaction.on_commit(lambda: get_storage().delete(avatar))
