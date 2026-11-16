import logging

from django.conf import settings
from django.db import transaction

from .models import Device

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


def send_push(device, title, body, data):
    """The one place the real FCM sender plugs in (NOTE-10, NOTE-12: delete the device row when
    Firebase says the token is no longer registered). Raise on failure; the caller logs it."""
    if settings.FCM_CREDENTIALS_FILE:
        raise NotImplementedError("The Firebase sender is not built yet")
    logger.info("Fake push to user %s: %s - %s %s", device.user_id, title, body, data)
    outbox.append({"user_id": device.user_id, "token": device.token, "title": title, "body": body, "data": data})
