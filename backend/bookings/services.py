"""Court slots, prices, offers, booking, invites, rentals, cancelling (AVL, PRC, DSC, BOOK).

The booking write path is plain functions (`run_slots`, `court_price`, `best_offer`, `lock_court` + `slot_taken`)
so training bookings (BOOK-21, BOOK-30, BOOK-31) can reuse them.
"""
import datetime
import zoneinfo
from collections import namedtuple
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404

from accounts.models import User
from accounts.services import friends_of, is_blocked_pair, is_shadow_player, notify
from chat import services as chat
from config.api import BusinessError
from config.money import round_money, validate_typed_money
from config.storage import get_storage, is_key, upload_form
from teams.models import Group, GroupMember
from teams.services import coachs_players, is_active_member, is_group_manager
from venues.models import ClubMember, Equipment
from venues.services import club_today, current_members, lock_court, visible_clubs

from .models import Recording, RecordingTag, Session, SessionParticipant, SessionRental

UTC = datetime.timezone.utc
HORIZON_DAYS = 60  # AVL-5 item 4
MAX_REQUEST = datetime.timedelta(hours=8)  # BOOK-20
MAX_RANGE = datetime.timedelta(days=14)  # AVL-23
CANCELLED, CONFIRMED, REQUESTED = Session.Status.CANCELLED, Session.Status.CONFIRMED, Session.Status.REQUESTED
INVITED, ACCEPTED, DECLINED = (SessionParticipant.Status.INVITED, SessionParticipant.Status.ACCEPTED,
                               SessionParticipant.Status.DECLINED)
APPROVED = SessionRental.Status.APPROVED
CHECK_IN_OPENS = datetime.timedelta(minutes=30)  # PAY-1: before starts_at
LATE_CHECK_IN = datetime.timedelta(hours=24)  # PAY-7: after ends_at, club side only
MAX_PERIOD_DAYS = 366  # owner-reports intro
RECORDING_TYPES = ("mp4", "mov")  # REC-11
RECORDING_MAX_BYTES = 2 * 1024 ** 3  # REC-11
UPLOAD_OPEN_AFTER_END = datetime.timedelta(days=30)  # REC-10

Slot = namedtuple("Slot", "starts_at ends_at rate")  # `rate` is the CourtRate that produced it (AVL-4)


def _name(user):
    return user.full_name or "Someone"  # never the email in a push


def _tz(club):
    return zoneinfo.ZoneInfo(club.timezone)


# ---- slots (AVL-1 to AVL-8) ----

def _instant(naive, tz):
    """GEN-10: a club-local wall-clock time as a UTC instant, or None if that local time does not exist."""
    utc = naive.replace(tzinfo=tz).astimezone(UTC)  # fold=0
    return utc if utc.astimezone(tz).replace(tzinfo=None) == naive else None


def offered_slots(court, days):
    """AVL-1, AVL-2, AVL-4, AVL-6, AVL-7: the court's offered slots on each local date in `days`, in time order."""
    if not court.is_active:
        return []
    tz, step = _tz(court.club), datetime.timedelta(minutes=court.slot_minutes)
    rates = list(court.rates.prefetch_related("price_overrides").order_by("start_time", "id"))
    slots = []
    for day in days:
        for rate in (r for r in rates if r.weekday == day.weekday()):
            start = datetime.datetime.combine(day, rate.start_time)
            end_day = day + datetime.timedelta(days=1) if rate.end_time == datetime.time(0) else day  # GEN-11
            end = datetime.datetime.combine(end_day, rate.end_time)
            while start + step <= end:  # AVL-2: a leftover shorter than a slot is not offered
                a, b = _instant(start, tz), _instant(start + step, tz)
                if a and b and b - a == step:  # AVL-6
                    slots.append(Slot(a, b, rate))
                start += step
    return slots


def _occurrences(blockouts, tz, days):
    """AVL-8: (start, end) UTC instants of every occurrence of `blockouts` on the local dates `days` of `tz`."""
    # ponytail: blockouts x days looped in Python (at most 61 days per request); index by date only if rows get many
    midnight = datetime.time(0)
    ranges = []
    for blockout in blockouts:
        for day in days:
            if blockout.occurs_on(day):
                end_day = day + datetime.timedelta(days=1) if blockout.end_time == midnight else day
                ranges.append((datetime.datetime.combine(day, blockout.start_time, tzinfo=tz).astimezone(UTC),
                               datetime.datetime.combine(end_day, blockout.end_time, tzinfo=tz).astimezone(UTC)))
    return ranges


def _closed_ranges(court, days):
    """AVL-8, AVL-5 item 1: the closures of a court on the club's local dates `days`."""
    return _occurrences(court.blockouts.all(), _tz(court.club), days)


def _overlaps(start, end, ranges):
    return any(start < b and end > a for a, b in ranges)  # touching does not overlap (AVL-5)


def slot_taken(court, starts_at, ends_at):
    """AVL-5 item 2, BOOK-3: a non-cancelled session overlaps."""
    return court.sessions.exclude(status=CANCELLED).filter(starts_at__lt=ends_at, ends_at__gt=starts_at).exists()


def free_slots(court, day):
    """AVL-5, AVL-11: the free slots of one local date. The caller has checked the date is inside the horizon."""
    now = timezone.now()
    slots = [s for s in offered_slots(court, [day]) if s.starts_at > now]  # item 3
    if not slots:
        return []
    closed = _closed_ranges(court, [day])
    busy = [(s.starts_at, s.ends_at) for s in court.sessions.exclude(status=CANCELLED).filter(
        starts_at__lt=slots[-1].ends_at, ends_at__gt=slots[0].starts_at)]
    return [s for s in slots if not _overlaps(s.starts_at, s.ends_at, closed + busy)]


def check_day(club, day):
    """AVL-12: the date is today (club timezone) or up to 60 days ahead."""
    today = club_today(club)
    if day < today or day > today + datetime.timedelta(days=HORIZON_DAYS):
        raise BusinessError("outside_horizon", "That date is outside the days that can be booked.")


def run_slots(court, starts_at, ends_at):
    """BOOK-4: the contiguous run of offered slots from `starts_at` to `ends_at`, each in the future (AVL-5 item 3),
    inside 60 days (item 4) and not under a closure (item 1). Anything else is `not_bookable`.
    A session on top of a slot is not checked here: that is `slot_taken` inside the lock (BOOK-2)."""
    refuse = BusinessError("not_bookable", "These times are not a run of free slots on this court.")
    club = court.club
    tz = _tz(club)
    if ends_at <= starts_at or starts_at <= timezone.now():
        raise refuse
    first = starts_at.astimezone(tz).date()
    last = (ends_at - datetime.timedelta(microseconds=1)).astimezone(tz).date()
    if last > club_today(club) + datetime.timedelta(days=HORIZON_DAYS):
        raise refuse
    days = [first + datetime.timedelta(days=n) for n in range((last - first).days + 1)]
    by_start = {s.starts_at: s for s in offered_slots(court, days)}
    run, cursor = [], starts_at
    while cursor < ends_at:
        slot = by_start.get(cursor)
        if slot is None:
            raise refuse
        run.append(slot)
        cursor = slot.ends_at
    if cursor != ends_at or _overlaps(starts_at, ends_at, _closed_ranges(court, days)):
        raise refuse
    return run


# ---- prices (PRC-1 to PRC-6) ----

def club_rate(club, currency):
    """PRC-1: units of `currency` per 1 base unit (1 for the base itself), or `currency_not_accepted`."""
    if currency == club.currency:
        return Decimal(1)
    row = club.currencies.filter(currency=currency).first()
    if row is None:
        raise BusinessError("currency_not_accepted", "The club does not accept this currency.")
    return row.exchange_rate


def unit_price(item, base, currency, club, rate):
    """PRC-4. `item` is a CourtRate or an Equipment (both have `price_overrides`), `base` its base price."""
    if currency == club.currency:
        return base
    override = next((o for o in item.price_overrides.all() if o.currency == currency), None)
    return override.price if override else round_money(base * rate, currency)


def court_price(slots, currency, club, rate):
    """PRC-5: the sum of the per-slot prices."""
    return sum((unit_price(s.rate, s.rate.price, currency, club, rate) for s in slots), Decimal(0))


# ---- offers (DSC-1 to DSC-5) ----

def best_offer(court, booker, starts_at, price, currency, rate):
    """DSC-1 to DSC-4: (offer or None, discount_amount). `starts_at` is when the session is played."""
    club = court.club
    # DSC-2: past, non-cancelled bookings of this booker at the club
    count = Session.objects.filter(booked_by=booker, court__club=club, starts_at__lt=timezone.now()).exclude(
        status=CANCELLED).count()
    offers = club.discounts.filter(  # DSC-1 items 1 to 3 and 5
        Q(court__isnull=True) | Q(court=court), Q(user__isnull=True) | Q(user=booker),
        starts_at__lte=starts_at, ends_at__gt=starts_at).order_by("id")
    best, best_amount = None, Decimal(0)
    for offer in offers:
        if offer.min_bookings is not None and count < offer.min_bookings:  # DSC-1 item 4
            continue
        if offer.percent_off is not None:  # DSC-3
            amount = round_money(price * offer.percent_off / 100, currency)
        elif currency == club.currency:
            amount = offer.amount_off
        else:
            amount = round_money(offer.amount_off * rate, currency)
        amount = min(amount, price)
        if amount > best_amount:  # DSC-4: ids ascend, so a tie keeps the lowest id
            best, best_amount = offer, amount
    return best, best_amount


# ---- checks of BOOK-7 ----

def _field_error(field, message):
    return ValidationError({field: [message]})


def check_rentals(court, items, currency, rate):
    """BOOK-7 rentals row: [(equipment, quantity, price)]."""
    lines, seen = [], set()
    for item in items:
        equipment = Equipment.objects.filter(
            Q(court__isnull=True) | Q(court=court), pk=item["equipment"], club=court.club).first()
        if equipment is None:
            raise _field_error("rentals", f"Equipment {item['equipment']}: Not found.")
        if equipment.pk in seen:
            raise _field_error("rentals", f"Equipment {equipment.pk} is listed twice.")
        seen.add(equipment.pk)
        if equipment.rental_price is None:
            raise _field_error("rentals", f"{equipment.name} is not for rent.")
        if not 1 <= item["quantity"] <= equipment.quantity:
            raise _field_error("rentals", f"{equipment.name}: quantity must be between 1 and {equipment.quantity}.")
        price = unit_price(equipment, equipment.rental_price, currency, court.club, rate) * item["quantity"]  # PRC-6
        lines.append((equipment, item["quantity"], price))
    return lines


def check_group(user, group_id):
    """BOOK-7 group row: the caller is an active member or a manager (else it does not exist for them, GEN-18)."""
    if group_id is None:
        return None
    group = Group.objects.filter(pk=group_id).first()
    if group is None or not (is_active_member(user, group) or is_group_manager(user, group)):
        raise _field_error("group", "Not found.")
    return group


def check_invitees(user, ids, group=None):
    """BOOK-7 invitees row, BOOK-15: friends of the caller (or active members of `group`), never shadow, never the
    caller, no duplicates. Returns the users."""
    if len(set(ids)) != len(ids):
        raise _field_error("invitees", "The same user is listed twice.")
    pool = {u.pk: u for u in friends_of(user)}  # ponytail: loads every friend; filter by ids if friend lists get long
    if group:
        pool.update({m.user_id: m.user for m in GroupMember.objects.filter(
            group=group, status=GroupMember.Status.ACTIVE).select_related("user")})
    for pk in ids:
        if pk == user.pk:
            raise _field_error("invitees", "You cannot invite yourself.")
        if pk not in pool:
            raise _field_error("invitees", f"User {pk}: Not found.")
        if is_shadow_player(pool[pk]):
            raise _field_error("invitees", f"User {pk} cannot be invited.")
    return [pool[pk] for pk in ids]


def plan_court(court, sport, currency, starts_at, ends_at):
    """BOOK-7 sport, currency and run rows, in that order (also BOOK-21, BOOK-30, BOOK-31): rate, slots and price."""
    if not court.sports.filter(pk=sport.pk).exists():
        raise BusinessError("sport_not_offered", "This court does not offer that sport.")
    rate = club_rate(court.club, currency)
    slots = run_slots(court, starts_at, ends_at)
    return {"rate": rate, "slots": slots, "price": court_price(slots, currency, court.club, rate)}


def check_court_booking(user, data):
    """BOOK-7 in its order, up to the lock. Returns what the write needs."""
    court, currency = data["court"], data["currency"]
    plan = plan_court(court, data["sport"], currency, data["starts_at"], data["ends_at"])
    rentals = check_rentals(court, data.get("rentals", []), currency, plan["rate"])
    group = check_group(user, data.get("group"))
    invitees = check_invitees(user, data.get("invitees", []))
    return {**plan, "rentals": rentals, "group": group, "invitees": invitees}


def quote_court_booking(user, data):
    """BOOK-6: the same checks and prices as booking, nothing written or held."""
    plan = check_court_booking(user, data)
    court, starts_at = data["court"], data["starts_at"]
    if slot_taken(court, starts_at, data["ends_at"]):
        raise BusinessError("slot_taken", "Someone else just booked these times.", 409)
    offer, discount = best_offer(court, user, starts_at, plan["price"], data["currency"], plan["rate"])
    rentals = sum((price for _, _, price in plan["rentals"]), Decimal(0))
    return {
        "currency": data["currency"], "price": plan["price"], "offer": offer, "discount_amount": discount,
        "rentals": [{"equipment": e.pk, "name": e.name, "quantity": q, "price": p} for e, q, p in plan["rentals"]],
        "court_amount": plan["price"] - discount + rentals,
    }


# ---- booking (BOOK-2, BOOK-8, BOOK-10, BOOK-60) ----

def _lock_and_price(booker, data, plan):
    """BOOK-2, BOOK-8 step 1 and 2: lock the court, re-check the run and the overlap, then pick the offer for `booker`.
    Without a court (BOOK-21, BOOK-30) there is nothing to lock and no offer (DSC-1)."""
    court = data.get("court")
    if court is None:
        return None, Decimal(0)
    lock_court(court)  # the court row is locked here; everything below runs one booker at a time
    run_slots(court, data["starts_at"], data["ends_at"])  # still offered, in the future and not closed
    if slot_taken(court, data["starts_at"], data["ends_at"]):
        raise BusinessError("slot_taken", "Someone else just booked these times.", 409)  # GEN-6
    return best_offer(court, booker, data["starts_at"], plan["price"], data["currency"], plan["rate"])


def book_court(user, data):
    """BOOK-8. Returns the new session."""
    plan = check_court_booking(user, data)
    court, starts_at, ends_at, group = data["court"], data["starts_at"], data["ends_at"], plan["group"]
    with transaction.atomic():
        offer, discount = _lock_and_price(user, data, plan)  # BOOK-2, step 2
        session = Session.objects.create(  # step 3
            court=court, sport=data["sport"], booked_by=user, kind=Session.Kind.PLAY, status=CONFIRMED,
            starts_at=starts_at, ends_at=ends_at, group=group, currency=data["currency"], price=plan["price"],
            discount=offer, discount_amount=discount)
        SessionParticipant.objects.create(session=session, user=user, status=ACCEPTED)  # step 4
        for equipment, quantity, price in plan["rentals"]:  # step 5
            SessionRental.objects.create(session=session, equipment=equipment, quantity=quantity, price=price)
        people = {u: INVITED for u in plan["invitees"]}  # step 6
        if group:  # BOOK-10: every active member but the booker; shadow players cannot answer, so they are accepted
            for member in GroupMember.objects.filter(group=group, status=GroupMember.Status.ACTIVE).exclude(
                    user=user).select_related("user"):
                people.setdefault(member.user, ACCEPTED if is_shadow_player(member.user) else INVITED)
        invited = _add_participants(session, people)
        if group:
            chat.post_session_card(session)  # step 7, BOOK-60
        _notify_invited(user, session, invited)  # step 8
    return session


def _add_participants(session, people):
    """`people` is {user: status}. A user who already has a row is skipped. Returns the users newly invited."""
    have = set(session.participants.values_list("user", flat=True))
    new = {u: status for u, status in people.items() if u.pk not in have}
    SessionParticipant.objects.bulk_create(SessionParticipant(session=session, user=u, status=s) for u, s in new.items())
    return [u for u, status in new.items() if status == INVITED]


def _notify_invited(booker, session, users):
    if users:
        notify(users, "session_invite", "You are invited to play", f"{_name(booker)} invited you to a session",
               {"id": session.id})  # NOTE-20


# ---- who sees what (ACC-1, BOOK-65) ----

def is_club_side(user, club):
    """ACC-1: the owner, or current staff."""
    return club.owner_id == user.pk or current_members(club).filter(user=user, role=ClubMember.Role.STAFF).exists()


def can_see(user, session):
    """BOOK-65: participants, the booker, the session coach, the club side of the court's club, and the managing coach
    of a shadow participant (so PAY-2 can be used)."""
    if user.pk in (session.booked_by_id, session.coach_id) or session.participants.filter(
            Q(user=user) | Q(user__managed_by=user, user__email__isnull=True)).exists():
        return True
    return session.court_id is not None and is_club_side(user, session.court.club)


def seen_session(user, pk):
    """GEN-3: a session the caller may not see does not exist for them."""
    session = Session.objects.select_related("court__club", "sport", "booked_by", "coach").prefetch_related(
        "participants__user", "rentals__equipment").filter(pk=pk).first()
    if session is None or not can_see(user, session):
        raise NotFound()
    return session


def my_sessions(user, starts_from=None, starts_to=None, status=None):
    """BOOK-66, BOOK-55: filters work on the shown status, so `completed` is a confirmed session that has ended."""
    sessions = Session.objects.filter(
        Q(booked_by=user) | Q(coach=user) | Q(participants__user=user, participants__status__in=[INVITED, ACCEPTED])
    ).distinct().select_related("court__club", "sport", "booked_by", "coach").prefetch_related(
        "participants__user", "rentals__equipment").order_by("starts_at", "id")
    if starts_from:
        sessions = sessions.filter(starts_at__gte=starts_from)
    if starts_to:
        sessions = sessions.filter(starts_at__lt=starts_to)
    now = timezone.now()
    if status == "completed":
        sessions = sessions.filter(status=CONFIRMED, ends_at__lte=now)
    elif status == CONFIRMED:
        sessions = sessions.filter(status=CONFIRMED, ends_at__gt=now)
    elif status:
        sessions = sessions.filter(status=status)
    return sessions


def shown_status(session):
    """BOOK-55: `completed` is shown, never stored."""
    if session.status == CONFIRMED and session.ends_at <= timezone.now():
        return "completed"
    return session.status


# ---- invites (BOOK-15 to BOOK-17) ----

def _open_for_changes(session):
    """BOOK-15, BOOK-16: confirmed and not started."""
    if session.status != CONFIRMED or session.starts_at <= timezone.now():
        raise BusinessError("session_closed", "This session has started or was cancelled.")


def invite(user, session, ids):
    """BOOK-15 (the view checks the caller is the booker): returns the users newly invited (those who already have a row are skipped)."""
    with transaction.atomic():
        _open_for_changes(session)
        users = check_invitees(user, ids, session.group)
        new = _add_participants(session, {u: INVITED for u in users})
        _notify_invited(user, session, new)
    return new


def respond(session, row, status):
    """BOOK-16: the invitee changes their own row (the view checks it is theirs). Repeating the status is a 200 (GEN-5)."""
    if row.status == status:
        return row
    _open_for_changes(session)
    if row.user_id == session.booked_by_id:  # the booker is always accepted, so this is a withdrawal
        raise BusinessError("booker_cannot_leave", "The booker cannot leave the session.")
    row.status = status
    row.save(update_fields=["status"])
    return row


def remove_participant(user, session, row):
    """BOOK-17."""
    if session.booked_by_id != user.pk:
        raise PermissionDenied("Only the booker can remove a participant.")
    if session.starts_at <= timezone.now():
        raise BusinessError("session_closed", "This session has started.")
    if row.user_id == session.booked_by_id:
        raise BusinessError("booker_cannot_leave", "The booker cannot be removed.")
    if row.checked_in_at:
        raise BusinessError("already_checked_in", "This participant has checked in.")
    row.delete()


# ---- rentals (BOOK-40, BOOK-41) ----

def decide_rental(rental, status):
    """BOOK-40. The view has checked the caller is the club side."""
    session = rental.session
    if rental.status == status:  # GEN-5
        return rental
    if session.status == CANCELLED:
        raise BusinessError("session_cancelled", "This session was cancelled.")
    if session.payments.exists():  # BOOK-40: frozen once the booker has checked in
        raise BusinessError("already_payable", "The session has payments; rentals are frozen.")
    with transaction.atomic():
        equipment = Equipment.objects.select_for_update().get(pk=rental.equipment_id)  # BOOK-41: lock the item
        if status == APPROVED:
            taken = SessionRental.objects.filter(
                equipment=equipment, status=APPROVED, session__starts_at__lt=session.ends_at,
                session__ends_at__gt=session.starts_at).exclude(session__status=CANCELLED).exclude(pk=rental.pk)
            if (taken.aggregate(n=Sum("quantity"))["n"] or 0) + rental.quantity > equipment.quantity:
                raise BusinessError("out_of_stock", "Not enough of this item is left for these times.", 409)
        rental.status = status
        rental.save(update_fields=["status"])
    return rental


# ---- cancelling (BOOK-50, BOOK-51) ----

def cancel(user, session):
    """BOOK-50. The caller can see the session. Returns the session."""
    if user.pk not in (session.booked_by_id, session.coach_id) and not (
            session.court_id and session.court.club.owner_id == user.pk):
        raise PermissionDenied("Only the booker, the coach or the club owner can cancel.")
    if session.status == CANCELLED:  # GEN-5
        return session
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.status == CANCELLED:
            return session
        if session.status != CONFIRMED:
            raise BusinessError("invalid_status", "Only a confirmed session can be cancelled here.")
        if session.ends_at <= timezone.now():
            raise BusinessError("session_closed", "This session has ended.")
        if session.payments.exists():
            raise BusinessError("already_payable", "The session has payments and can no longer be cancelled.")
        session.status = CANCELLED
        session.save(update_fields=["status"])
        session.rentals.filter(status=SessionRental.Status.REQUESTED).update(status=SessionRental.Status.DECLINED)
        people = {p.user for p in session.participants.filter(status__in=[INVITED, ACCEPTED]).select_related("user")}
        if session.coach:
            people.add(session.coach)
        people = [u for u in people if u.pk != user.pk]
        if people:
            notify(people, "session_cancelled", "Session cancelled",
                   f"{_name(user)} cancelled the session on {session.starts_at:%Y-%m-%d %H:%M} UTC", {"id": session.id})
    return session


# ---- training: requests (BOOK-20 to BOOK-22) ----

def _when(session):
    return f"{session.starts_at:%Y-%m-%d %H:%M} UTC"


def request_training(user, data):
    """BOOK-20: a player asks a coach. The times were checked by the serializer. Returns the new session."""
    coach = data["coach"]
    if coach.pk == user.pk or is_blocked_pair(user, coach):
        raise BusinessError("cannot_request", "You cannot ask this user for training.")
    if not coach.is_coach:
        raise BusinessError("not_a_coach", "This user is not a coach.")
    with transaction.atomic():
        session = Session.objects.create(  # no court, no currency, nothing owed yet; the requester pays the coach fee
            sport=data["sport"], booked_by=user, coach=coach, kind=Session.Kind.TRAINING, status=REQUESTED,
            starts_at=data["starts_at"], ends_at=data["ends_at"], currency="", price=0, coach_fee=0, coach_fee_payer=user)
        SessionParticipant.objects.create(session=session, user=user, status=ACCEPTED)
        notify([coach], "training_request", "Training request",
               f"{_name(user)} asked you for training on {_when(session)}", {"id": session.id})  # NOTE-20
    return session


def plan_training(data):
    """BOOK-21, BOOK-30, BOOK-31 up to the lock. With a court: BOOK-7 sport, currency and run rows.
    Without one (the coach's own venue): price 0, any valid currency, the time only has to be in the future."""
    court = data.get("court")
    if court is not None:
        return plan_court(court, data["sport"], data["currency"], data["starts_at"], data["ends_at"])
    if data["starts_at"] <= timezone.now():
        raise _field_error("starts_at", "Must be in the future.")
    if data["ends_at"] <= data["starts_at"]:
        raise _field_error("ends_at", "Must be after the start.")
    return {"rate": None, "price": Decimal(0)}


def confirm_training(session, data):
    """BOOK-21 (the view checked the caller is the session coach). Returns the confirmed session."""
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)  # a withdrawal cannot slip in between
        if session.status != REQUESTED:
            raise BusinessError("invalid_status", "Only a requested session can be confirmed.")
        data = {**data, "sport": session.sport}
        plan = plan_training(data)
        offer, discount = _lock_and_price(session.booked_by, data, plan)  # BOOK-2; DSC-1: the requester is the booker
        session.court, session.starts_at, session.ends_at = data.get("court"), data["starts_at"], data["ends_at"]
        session.currency, session.price, session.coach_fee = data["currency"], plan["price"], data["coach_fee"]
        session.discount, session.discount_amount, session.status = offer, discount, CONFIRMED
        session.save()  # coach_fee_payer stays the requester; a request has no group, so no card (BOOK-60)
        notify([session.booked_by], "training_confirmed", "Training confirmed",
               f"{_name(session.coach)} confirmed your training on {_when(session)}", {"id": session.id})
    return session


def end_request(session, declining):
    """BOOK-22 (the view checked the caller): the coach declines or the requester withdraws a request."""
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.status == CANCELLED:  # GEN-5
            return session
        if session.status != REQUESTED:
            raise BusinessError("invalid_status", "Only a requested session can be declined or withdrawn.")
        if session.starts_at <= timezone.now():  # BOOK-1: before starts_at
            raise BusinessError("session_closed", "The proposed time has passed.")
        session.status = CANCELLED
        session.save(update_fields=["status"])
        if declining:
            notify([session.booked_by], "training_declined", "Training declined",
                   f"{_name(session.coach)} declined your training request for {_when(session)}", {"id": session.id})
        else:
            notify([session.coach], "training_withdrawn", "Training request withdrawn",
                   f"{_name(session.booked_by)} withdrew the training request for {_when(session)}", {"id": session.id})
    return session


# ---- training: booked by a coach (BOOK-30 to BOOK-33) ----

def book_training(coach, data):
    """BOOK-30 (`group` is a team the caller manages) or BOOK-31 (`player` is one of the caller's players).
    Returns the new session."""
    group, chosen = data.get("group"), data.get("coach_fee_payer")  # `chosen`: an id the coach typed
    payer_id = chosen
    if group:  # BOOK-30
        if group.type != Group.Type.TEAM:
            raise BusinessError("not_a_team", "Training is booked for a team.")
        if not is_group_manager(coach, group):
            raise PermissionDenied("Only the team's coach or owner can book training for it.")
        members = list(GroupMember.objects.filter(group=group, status=GroupMember.Status.ACTIVE).exclude(
            user=coach).select_related("user"))
        payers = {m.user_id: m.user for m in members}
        people = {m.user: ACCEPTED if is_shadow_player(m.user) else INVITED for m in members}
    else:  # BOOK-31
        player = coachs_players(coach).filter(pk=data["player"]).first()
        if player is None:
            raise BusinessError("not_your_player", "This user is not one of your players.")
        payers = {player.pk: player}
        people = {player: ACCEPTED if is_shadow_player(player) else INVITED}
        payer_id = payer_id or player.pk  # BOOK-31: defaults to the player
    plan = plan_training(data)
    payer = payers.get(payer_id)
    if payer_id and (payer is None or (chosen and is_shadow_player(payer) and payer.managed_by_id != coach.pk)):
        # BOOK-32: an active member of the team, or the player; never the coach. ACC-12: a shadow player only by their coach
        raise _field_error("coach_fee_payer", "Must be an active member of the team, or the player, and not the coach.")
    with transaction.atomic():
        offer, discount = _lock_and_price(coach, data, plan)  # BOOK-2; DSC-1: the coach is the booker (BOOK-33)
        session = Session.objects.create(
            court=data.get("court"), sport=data["sport"], booked_by=coach, coach=coach, group=group,
            kind=Session.Kind.TRAINING, status=CONFIRMED, starts_at=data["starts_at"], ends_at=data["ends_at"],
            currency=data["currency"], price=plan["price"], coach_fee=data["coach_fee"], coach_fee_payer=payer,
            discount=offer, discount_amount=discount)
        invited = _add_participants(session, {coach: ACCEPTED, **people})
        if group:
            chat.post_session_card(session)  # BOOK-60
        _notify_invited(coach, session, invited)
    return session


# ---- personal and group availability (AVL-20 to AVL-25) ----

def availability_user(asker, pk):
    """AVL-22: the user themselves, or a coach about one of the coach's players. Anyone else: 404."""
    if pk != asker.pk and not coachs_players(asker).filter(pk=pk).exists():
        raise NotFound()
    return [User.objects.get(pk=pk)]


def availability_group(asker, pk):
    """AVL-22: an active member or a group manager. Anyone else: 404. Returns the active members (AVL-21)."""
    group = Group.objects.filter(pk=pk).first()
    if group is None or not (is_active_member(asker, group) or is_group_manager(asker, group)):
        raise NotFound()
    return [m.user for m in GroupMember.objects.filter(group=group, status=GroupMember.Status.ACTIVE).select_related("user")]


def _busy(user, start, end):
    """AVL-20: block-outs in the user's own timezone, and confirmed sessions of the user, as (start, end) UTC pairs."""
    tz = zoneinfo.ZoneInfo(user.timezone)
    first, last = start.astimezone(tz).date(), (end - datetime.timedelta(microseconds=1)).astimezone(tz).date()
    days = [first + datetime.timedelta(days=n) for n in range((last - first).days + 1)]
    sessions = Session.objects.filter(status=CONFIRMED, starts_at__lt=end, ends_at__gt=start).filter(
        Q(booked_by=user) | Q(coach=user) | Q(participants__user=user, participants__status=ACCEPTED)).distinct()
    return _occurrences(user.blockouts.all(), tz, days) + [(s.starts_at, s.ends_at) for s in sessions]


def free_intervals(users, start, end, min_minutes):
    """AVL-21, AVL-23: the parts of [start, end) where every user in `users` is free, touching parts merged,
    at least `min_minutes` long. AVL-24: `bad_range`."""
    if end <= start or end - start > MAX_RANGE:
        raise BusinessError("bad_range", "`to` must be after `from`, and at most 14 days later.")
    # ponytail: two queries per member; fine for team-sized groups, batch by member ids if groups get large
    busy = sorted(pair for user in users for pair in _busy(user, start, end))
    free, cursor = [], start
    for a, b in busy:  # sweep: the gaps between the merged busy ranges are the free intervals
        if a > cursor:
            free.append((cursor, min(a, end)))
        cursor = max(cursor, b)
        if cursor >= end:
            break
    if cursor < end:
        free.append((cursor, end))
    return [{"starts_at": a, "ends_at": b} for a, b in free if b - a >= datetime.timedelta(minutes=min_minutes)]


# ---- check-in (PAY-1 to PAY-7) ----

def check_in(user, session, row):
    """PAY-4. The caller can see `session` and `row` is one of its participant rows. Returns the row.
    The session row lock (step 1) is what makes two simultaneous booker check-ins create the payments once (PAY-10)."""
    booker_row = row.user_id == session.booked_by_id
    club_side = bool(booker_row and session.court_id and is_club_side(user, session.court.club))  # PAY-3
    if not (row.user_id == user.pk  # PAY-2
            or (is_shadow_player(row.user) and user.pk in (session.coach_id, row.user.managed_by_id))
            or club_side):
        raise PermissionDenied("You cannot check this person in.")
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)  # step 1: no select_related (nullable court)
        row = SessionParticipant.objects.get(pk=row.pk)
        if row.checked_in_at:  # step 2, GEN-5
            return row
        if session.status != CONFIRMED:  # PAY-5
            raise BusinessError("invalid_status", "Only a confirmed session can be checked in to.")
        if row.status != ACCEPTED:
            raise BusinessError("not_accepted", "This participant has not accepted the session.")
        now = timezone.now()
        closes = session.ends_at + (LATE_CHECK_IN if club_side else datetime.timedelta(0))  # PAY-7
        if not session.starts_at - CHECK_IN_OPENS <= now <= closes:  # PAY-1
            raise BusinessError("checkin_closed", "Check-in is not open now.")
        row.checked_in_at = now  # step 3
        row.save(update_fields=["checked_in_at"])
        if booker_row:  # step 4: the downward call allowed by docs/backend/README.md
            from billing.services import record_payments  # here, not at the top: billing.services imports this module
            record_payments(session)
    return row


# ---- one-off discount (DSC-10 to DSC-14) ----

def set_session_discount(session, amount):
    """DSC-13. The view has checked the caller is the club owner of the session's court (DSC-10). Returns the session."""
    try:  # DSC-11, GEN-17
        validate_typed_money(amount, session.currency)
    except ValidationError as exc:
        raise ValidationError({"amount": exc.detail})
    if amount > session.price:
        raise _field_error("amount", "Must not be more than the session price.")
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        if session.payments.exists():  # DSC-12, DSC-14
            raise BusinessError("already_payable", "The session has payments; its price can no longer change.")
        if session.status not in (REQUESTED, CONFIRMED):
            raise BusinessError("session_cancelled", "This session was cancelled.")
        session.discount, session.discount_amount = None, amount  # replaces any offer, never re-applied
        session.save(update_fields=["discount", "discount_amount"])
    return session


# ---- reports (RPT-1, RPT-4, RPT-5, RPT-6, RPT-8) ----

def report_period(tz, first, last):
    """Owner-reports intro: local dates `first` to `last`, both included, as the UTC range [start, end).
    Over 366 days, or `last` before `first`: `bad_range`."""
    if last < first or (last - first).days + 1 > MAX_PERIOD_DAYS:
        raise BusinessError("bad_range", "`to` must not be before `from`, and the period is at most 366 days.")
    midnight = lambda day: datetime.datetime.combine(day, datetime.time(0), tzinfo=tz).astimezone(UTC)
    return midnight(first), midnight(last + datetime.timedelta(days=1))


def club_report_access(user, club_id, owner_only=False):
    """RPT-1 to RPT-5: the club (404 if the caller cannot see it, GEN-3), who must be its club side, or its owner (ACC-6)."""
    club = get_object_or_404(visible_clubs(user), pk=club_id)
    if club.owner_id != user.pk and (owner_only or not is_club_side(user, club)):
        raise PermissionDenied("Not allowed for you.")
    return club


def schedule(club, first, last, court=None):
    """RPT-1: (sessions, closures) of the club, or of `court`, in the local dates `first` to `last`."""
    tz = _tz(club)
    start, end = report_period(tz, first, last)
    courts = [court] if court else list(club.courts.all())
    sessions = Session.objects.filter(court__in=courts, starts_at__lt=end, ends_at__gt=start).exclude(
        status=CANCELLED).select_related("court", "sport", "booked_by", "coach", "group").prefetch_related(
        "rentals__equipment").annotate(accepted=Count("participants", filter=Q(participants__status=ACCEPTED))
                                       ).order_by("starts_at", "id")
    days = [first + datetime.timedelta(days=n) for n in range((last - first).days + 1)]
    closures = [{"court": c.pk, "starts_at": a, "ends_at": b, "reason": blockout.reason}
                for c in courts for blockout in c.blockouts.all() for a, b in _occurrences([blockout], tz, days)]
    return sessions, sorted(closures, key=lambda x: (x["starts_at"], x["court"]))


def customers(club, first, last):
    """RPT-4, RPT-5: (list of {id, full_name, sessions}, repeat rate or None)."""
    start, end = report_period(_tz(club), first, last)
    rows = Session.objects.filter(court__club=club, starts_at__gte=start, starts_at__lt=end).exclude(
        status=CANCELLED).order_by().values("booked_by", "booked_by__full_name").annotate(n=Count("id"))
    people = sorted(({"id": r["booked_by"], "full_name": r["booked_by__full_name"], "sessions": r["n"]} for r in rows),
                    key=lambda p: (-p["sessions"], p["full_name"], p["id"]))
    if not people:
        return people, None
    repeat = sum(1 for p in people if p["sessions"] >= 2)
    return people, (Decimal(repeat) * 100 / len(people)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def attendance(session, now=None):
    """RPT-6: the accepted rows, and the no-shows (accepted, not checked in, session over). PAY-6."""
    rows = list(session.participants.filter(status=ACCEPTED).select_related("user").order_by("id"))
    over = (now or timezone.now()) > session.ends_at
    return rows, [r.user for r in rows if over and r.checked_in_at is None]


def player_history(coach, player):
    """RPT-8: the player's accepted rows in confirmed sessions the coach coached, newest first."""
    return SessionParticipant.objects.filter(
        user=player, status=ACCEPTED, session__coach=coach, session__status=CONFIRMED).select_related("session").order_by(
        "-session__starts_at", "-id")


# ---- recordings and tags (REC) ----


def uploadable_session(user, pk):
    """REC-10, REC-13: who may upload. A session the caller cannot see is `404` (GEN-3); one they see but may not
    upload to (not the coach, not a participant who checked in) is `403`."""
    session = seen_session(user, pk)
    if user.pk != session.coach_id and not session.participants.filter(user=user, checked_in_at__isnull=False).exists():
        raise PermissionDenied("Only the coach or a participant who checked in can upload a recording.")
    return session


def check_upload_window(session):
    """REC-10, REC-13: confirmed, from the start until 30 days after the end."""
    if session.status != CONFIRMED or not session.starts_at <= timezone.now() <= session.ends_at + UPLOAD_OPEN_AFTER_END:
        raise BusinessError("upload_closed", "Recordings of this session cannot be uploaded now.")


def recording_form(session, ext, size_bytes):
    """REC-11: a signed upload form; nothing is written."""
    check_upload_window(session)
    return upload_form(f"recordings/{session.pk}", ext, size_bytes)


def confirm_recording(user, session, key, duration_seconds):
    """REC-12: returns (recording, created). Checks run in the order bad_key, repeat, upload_closed, not_uploaded; the
    session row lock makes two confirms of one key create one row."""
    if not is_key(key, f"recordings/{session.pk}", RECORDING_TYPES):
        raise BusinessError("bad_key", "This is not an upload key of this session.")
    with transaction.atomic():
        session = Session.objects.select_for_update().get(pk=session.pk)
        existing = Recording.objects.filter(session=session, storage_key=key).first()
        if existing:  # GEN-5
            return existing, False
        check_upload_window(session)
        if not get_storage().exists(key):
            raise BusinessError("not_uploaded", "Nothing was uploaded to this key.")
        recording = Recording.objects.create(
            session=session, uploaded_by=user, storage_key=key, duration_seconds=duration_seconds)
    return recording, True


def is_session_coach(user, session):
    return user.pk == session.coach_id


def may_watch(user, session):
    """REC-20: the session coach, or a participant whose row has both `checked_in_at` and `rpe`."""
    return is_session_coach(user, session) or session.participants.filter(
        user=user, checked_in_at__isnull=False, rpe__isnull=False).exists()


def watchable_session(user, pk):
    """REC-20: anyone who may not watch gets `404`, an uploader without RPE included."""
    session = Session.objects.filter(pk=pk).first()
    if session is None or not may_watch(user, session):
        raise NotFound()
    return session


def watched_recording(user, pk):
    """REC-20: a recording of a session the caller may watch; anyone else gets `404`."""
    recording = Recording.objects.select_related("session").filter(pk=pk).first()
    if recording is None or not may_watch(user, recording.session):
        raise NotFound()
    return recording


def recording_to_delete(user, pk):
    """REC-14: the uploader can always reach their own recording, even without RPE; the rest follows REC-20."""
    recording = Recording.objects.select_related("session").filter(pk=pk, uploaded_by=user).first()
    return recording or watched_recording(user, pk)


def delete_recording(user, recording):
    """REC-14: the uploader or the session coach. The row goes first inside the transaction, so a storage failure
    rolls it back."""
    if recording.uploaded_by_id != user.pk and not is_session_coach(user, recording.session):
        raise PermissionDenied("Only the uploader or the session coach can delete a recording.")
    with transaction.atomic():
        recording.delete()  # the tags go with it
        get_storage().delete(recording.storage_key)


def visible_tags(user, recording):
    """REC-27: the coach sees every tag; a participant who may watch sees whole-team tags and tags naming them."""
    tags = recording.tags.order_by("start_second", "id")
    if is_session_coach(user, recording.session):
        return tags
    if may_watch(user, recording.session):
        return tags.filter(Q(players=None) | Q(players=user)).distinct()
    return tags.none()


def taggable_recording(user, pk):
    """REC-25, REC-28: a recording the caller may watch (`404` otherwise); only the session coach may tag it."""
    recording = watched_recording(user, pk)
    if not is_session_coach(user, recording.session):
        raise PermissionDenied("Only the session coach can tag a recording.")
    return recording


def tag_for_change(user, pk):
    """REC-26: the creator or the session coach changes or deletes a tag; anyone who cannot see it gets `404`."""
    tag = RecordingTag.objects.select_related("recording__session").filter(pk=pk).first()
    if tag is None:
        raise NotFound()
    mine = tag.created_by_id == user.pk
    if not (mine or visible_tags(user, tag.recording).filter(pk=tag.pk).exists()):
        raise NotFound()
    if not (mine or is_session_coach(user, tag.recording.session)):
        raise PermissionDenied("Only the creator or the session coach can change a tag.")
    return tag


def send_rpe_reminders():
    """NOTE-31: one `rpe_reminder` per checked-in participant without an RPE, for sessions that ended in the last 7 days.
    Returns how many were sent. The conditional update claims each row, so two overlapping ticks never remind twice."""
    now = timezone.now()
    due = SessionParticipant.objects.filter(
        checked_in_at__isnull=False, rpe__isnull=True, rpe_reminded_at__isnull=True,
        session__status=Session.Status.CONFIRMED, session__ends_at__gte=now - datetime.timedelta(days=7), session__ends_at__lte=now,
    ).select_related("user")
    sent = 0
    for p in due:
        with transaction.atomic():
            if SessionParticipant.objects.filter(pk=p.pk, rpe_reminded_at__isnull=True).update(rpe_reminded_at=now):
                notify([p.user], "rpe_reminder", "How hard was it?", "Tell us how the session felt.", {"id": p.session_id})
                sent += 1
    return sent
