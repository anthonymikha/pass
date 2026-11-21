"""Payments, commission and the money reports (PAY, COM, RPT-2, RPT-3, RPT-7)."""
import datetime
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from bookings.models import Session, SessionParticipant, SessionRental
from bookings.services import is_club_side
from config.api import BusinessError
from config.money import minor_units, round_money
from teams.services import coachs_players
from venues.models import Club, ClubMember

from .models import CommissionRate, Payment

UTC = datetime.timezone.utc
CLUB, COACH = CommissionRate.AppliesTo.CLUB, CommissionRate.AppliesTo.COACH


# ---- commission (COM-1 to COM-3) ----

def _count(applies_to, payee, now):
    """COM-3, the count N once tiers are on."""
    if applies_to == COACH:
        return coachs_players(payee).count()  # each user once
    # club: non-cancelled sessions on its courts that started in the last 30 days
    return Session.objects.filter(court__club=payee, starts_at__gte=now - datetime.timedelta(days=30), starts_at__lte=now
                                  ).exclude(status=Session.Status.CANCELLED).count()


def commission_percent(applies_to, payee, day, now=None):
    """COM-1: the percent for `payee` (a Club or a coach User) on the UTC date `day`."""
    rows = list(CommissionRate.objects.filter(applies_to=applies_to, effective_from__lte=day).filter(
        Q(**{applies_to: payee}) | Q(club__isnull=True, coach__isnull=True)))
    # COM-3: N is 0 while every row has min_count 0, so it is only counted when a tier exists
    n = _count(applies_to, payee, now or timezone.now()) if any(r.min_count for r in rows) else 0
    rows = [r for r in rows if r.min_count <= n]  # step 1
    own = [r for r in rows if getattr(r, f"{applies_to}_id") == payee.pk]  # step 2
    pool = own or [r for r in rows if r.club_id is None and r.coach_id is None]
    if not pool:
        return Decimal(0)  # step 4
    return max(pool, key=lambda r: (r.effective_from, r.min_count)).percent  # step 3


# ---- billing (PAY-9 to PAY-16, NOTE-33) ----

BILL_AFTER = datetime.timedelta(hours=24)  # PAY-10: check-in has closed (PAY-7)


def split(amount, payers, currency):
    """PAY-13: equal shares rounded down to the minor unit; the first payer also pays the remainder."""
    unit = Decimal(1).scaleb(-minor_units(currency))
    share = (amount / len(payers)).quantize(unit, rounding=ROUND_DOWN)
    remainder = amount - share * len(payers)
    return [(user, share + (remainder if i == 0 else 0)) for i, user in enumerate(payers)]


def _fees(session):
    """PAY-11, PAY-12: [(payer, club, coach, amount)] for a session with at least one attendee."""
    attendees = SessionParticipant.objects.filter(  # ordered by row id, so the booker's row comes first (PAY-13)
        session=session, status=SessionParticipant.Status.ACCEPTED, checked_in_at__isnull=False).select_related("user")
    payers = [row.user for row in attendees.order_by("id") if row.user_id != session.coach_id]  # never the session coach
    wanted = []
    if session.court_id:  # PAY-11
        rentals = session.rentals.filter(status=SessionRental.Status.APPROVED).aggregate(n=Sum("price"))["n"] or 0
        amount, club = session.price - session.discount_amount + rentals, session.court.club
        if session.court_fee_split and payers:
            wanted += [(payer, club, None, share) for payer, share in split(amount, payers, session.currency)]
        else:  # paid in full, or split with only the session coach attending: the booker pays it
            wanted.append((session.booked_by, club, None, amount))
    if session.coach_fee > 0:  # PAY-12
        if session.coach_fee_payer_id:  # paid in full, attended or not
            wanted.append((session.coach_fee_payer, None, session.coach, session.coach_fee))
        elif payers:  # split; no payers, no row
            wanted += [(payer, None, session.coach, share) for payer, share in split(session.coach_fee, payers, session.currency)]
    return wanted


def bill(session, now):
    """PAY-10 for one session whose row the caller has locked and marked billed. Returns the rows created; none when
    nobody attended (no no-show fees, BOOK-51)."""
    if not session.participants.filter(status=SessionParticipant.Status.ACCEPTED, checked_in_at__isnull=False).exists():
        return []
    today = now.astimezone(UTC).date()  # PAY-14: the billing date
    percents, created = {}, []
    for payer, club, coach, amount in _fees(session):
        if amount <= 0:  # PAY-15
            continue
        payee = club or coach
        key = (CLUB if club else COACH, payee.pk)
        if key not in percents:
            percents[key] = commission_percent(key[0], payee, today, now)
        created.append(Payment.objects.create(
            session=session, payer=payer, club=club, coach=coach, amount=amount, currency=session.currency,
            platform_fee=round_money(amount * percents[key] / 100, session.currency)))  # PAY-14
    return created


def bill_ended_sessions():
    """PAY-10, NOTE-33: one transaction per session; `billed_at` is set under the session lock, so overlapping ticks
    bill each session once. Returns how many sessions were billed."""
    now = timezone.now()
    due = Session.objects.filter(status=Session.Status.CONFIRMED, billed_at__isnull=True, ends_at__lte=now - BILL_AFTER)
    billed = 0
    for pk in due.values_list("pk", flat=True):
        with transaction.atomic():
            session = Session.objects.select_for_update().get(pk=pk)  # no select_related: nullable court (Postgres)
            if session.billed_at:
                continue
            session.billed_at = now
            session.save(update_fields=["billed_at"])
            bill(session, now)
        billed += 1
    return billed


# ---- who sees what (PAY-23) ----

def is_payee_side(user, payment):
    """PAY-20: the payee coach, or the club side of the payee club."""
    return payment.coach_id == user.pk or (payment.club_id is not None and is_club_side(user, payment.club))


def visible_payments(user):
    """PAY-23: rows the caller owes, and rows they are the payee side of."""
    # ponytail: club-side check per candidate club; fine for a handful of clubs per user
    clubs = [c.pk for c in Club.objects.filter(
        Q(owner=user) | Q(members__user=user, members__role=ClubMember.Role.STAFF)).distinct() if is_club_side(user, c)]
    return Payment.objects.filter(Q(payer=user) | Q(coach=user) | Q(club__in=clubs)).select_related(
        "payer", "club", "coach").order_by("-id")


# ---- the payee's ticks (PAY-20, PAY-21, PAY-25) ----

def _locked(payment):
    return Payment.objects.select_for_update(of=("self",)).select_related("payer", "club", "coach").get(pk=payment.pk)


def set_paid(payment, paid):
    """PAY-20 (received) and PAY-21 (back to due). The view has checked the caller is the payee side. A repeat
    changes nothing (GEN-5)."""
    with transaction.atomic():
        payment = _locked(payment)
        if paid:
            if payment.paid_at is not None:
                return payment
            if payment.waived_at is not None:
                raise BusinessError("already_waived", "This payment was waived; move it back to due first.")
            payment.method, payment.paid_at = Payment.Method.OFFLINE, timezone.now()
        else:
            if payment.settled_at:
                raise BusinessError("already_settled", "The platform's cut of this payment is settled; it cannot go back to due.")
            if payment.paid_at is None and payment.waived_at is None:
                return payment
            payment.method, payment.paid_at, payment.waived_at = "", None, None  # PAY-21: also un-waives (PAY-25)
        payment.save(update_fields=["method", "paid_at", "waived_at"])
    return payment


def waive(payment):
    """PAY-25: the payee side gives up a due payment. A repeat changes nothing (GEN-5)."""
    with transaction.atomic():
        payment = _locked(payment)
        if payment.waived_at is not None:
            return payment
        if payment.paid_at is not None:
            raise BusinessError("already_paid", "This payment was received; move it back to due first.")
        payment.waived_at = timezone.now()
        payment.save(update_fields=["waived_at"])
    return payment


# ---- reports (RPT-2, RPT-3, RPT-7) ----

def due_list(payments):
    """RPT-2: the payments of `payments` still due (not received, not waived), and the totals per currency."""
    rows = payments.filter(paid_at__isnull=True, waived_at__isnull=True).select_related("payer").order_by("created_at", "id")
    totals = rows.order_by().values("currency").annotate(total=Sum("amount")).order_by("currency")
    return {"payments": rows, "totals": list(totals)}


def revenue(payments, start, end):
    """RPT-3, RPT-7: collected money with `paid_at` in [start, end) per currency, plus what is still owed to the platform."""
    zero = Decimal(0)
    by_currency = {}
    for r in payments.filter(paid_at__gte=start, paid_at__lt=end).order_by().values("currency").annotate(
            gross=Sum("amount"), fees=Sum("platform_fee")):
        by_currency[r["currency"]] = {"currency": r["currency"], "gross": r["gross"], "fees": r["fees"],
                                      "net": r["gross"] - r["fees"], "owed_to_platform": zero}
    for r in payments.filter(paid_at__isnull=False, settled_at__isnull=True).order_by().values("currency").annotate(
            owed=Sum("platform_fee")):  # any date (COM-11)
        row = by_currency.setdefault(r["currency"], {"currency": r["currency"], "gross": zero, "fees": zero, "net": zero})
        row["owed_to_platform"] = r["owed"]
    return sorted(by_currency.values(), key=lambda row: row["currency"])
