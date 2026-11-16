"""Court slots, prices, offers, booking, invites, rentals, cancelling (AVL, PRC, DSC, BOOK).

The booking write path is plain functions (`run_slots`, `court_price`, `best_offer`, `lock_court` + `slot_taken`)
so training bookings (BOOK-21, BOOK-30, BOOK-31) can reuse them.
"""
import datetime
import zoneinfo
from collections import namedtuple
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from accounts.services import friends_of, is_shadow_player, notify
from chat import services as chat
from config.api import BusinessError
from config.money import round_money
from teams.models import Group, GroupMember
from teams.services import is_active_member, is_group_manager
from venues.models import ClubMember, Equipment
from venues.services import club_today, current_members, lock_court

from .models import Session, SessionParticipant, SessionRental

UTC = datetime.timezone.utc
HORIZON_DAYS = 60  # AVL-5 item 4
CANCELLED, CONFIRMED, REQUESTED = Session.Status.CANCELLED, Session.Status.CONFIRMED, Session.Status.REQUESTED
INVITED, ACCEPTED, DECLINED = (SessionParticipant.Status.INVITED, SessionParticipant.Status.ACCEPTED,
                               SessionParticipant.Status.DECLINED)
APPROVED = SessionRental.Status.APPROVED

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


def _closed_ranges(court, days):
    """AVL-8: (start, end) of every closure occurrence on the local dates `days`."""
    # ponytail: closures x days looped in Python (at most 61 days per request); index by date only if courts get many closures
    tz, midnight = _tz(court.club), datetime.time(0)
    ranges = []
    for closure in court.blockouts.all():
        for day in days:
            if closure.occurs_on(day):
                end_day = day + datetime.timedelta(days=1) if closure.end_time == midnight else day
                ranges.append((datetime.datetime.combine(day, closure.start_time, tzinfo=tz),
                               datetime.datetime.combine(end_day, closure.end_time, tzinfo=tz)))
    return ranges


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


def check_court_booking(user, data):
    """BOOK-7 in its order, up to the lock. Returns what the write needs."""
    court, sport, currency = data["court"], data["sport"], data["currency"]
    club = court.club
    if not court.sports.filter(pk=sport.pk).exists():
        raise BusinessError("sport_not_offered", "This court does not offer that sport.")
    rate = club_rate(club, currency)
    slots = run_slots(court, data["starts_at"], data["ends_at"])
    rentals = check_rentals(court, data.get("rentals", []), currency, rate)
    group = check_group(user, data.get("group"))
    invitees = check_invitees(user, data.get("invitees", []))
    price = court_price(slots, currency, club, rate)
    return {"rate": rate, "slots": slots, "rentals": rentals, "group": group, "invitees": invitees, "price": price}


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

def book_court(user, data):
    """BOOK-8. Returns the new session."""
    plan = check_court_booking(user, data)
    court, starts_at, ends_at, group = data["court"], data["starts_at"], data["ends_at"], plan["group"]
    with transaction.atomic():
        lock_court(court)  # BOOK-2: the court row is locked here; everything below runs one booker at a time
        run_slots(court, starts_at, ends_at)  # still offered, in the future and not closed
        if slot_taken(court, starts_at, ends_at):
            raise BusinessError("slot_taken", "Someone else just booked these times.", 409)  # GEN-6
        offer, discount = best_offer(court, user, starts_at, plan["price"], data["currency"], plan["rate"])  # step 2
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
    """BOOK-65: participants, the booker, the session coach, the club side of the court's club."""
    if user.pk in (session.booked_by_id, session.coach_id) or session.participants.filter(user=user).exists():
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
