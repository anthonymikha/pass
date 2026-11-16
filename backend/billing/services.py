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
from teams.models import GroupMember
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


# ---- creating payments (PAY-10 to PAY-16) ----

def _coach_fee_rows(session):
    """PAY-12, PAY-13: [(payer, amount)] for the coach fee."""
    if session.coach_fee <= 0:
        return []
    if session.coach_fee_payer_id:  # PAY-13
        return [(session.coach_fee_payer, session.coach_fee)]
    rows = SessionParticipant.objects.filter(session=session, status=SessionParticipant.Status.ACCEPTED).exclude(
        user=session.coach_id).select_related("user").order_by("id")
    if session.group_id:  # PAY-12: only active members of the group now
        rows = rows.filter(user__in=GroupMember.objects.filter(group_id=session.group_id, status="active").values("user"))
    payers = [r.user for r in rows]
    if not payers:
        return []
    unit = Decimal(1).scaleb(-minor_units(session.currency))
    share = (session.coach_fee / len(payers)).quantize(unit, rounding=ROUND_DOWN)
    remainder = session.coach_fee - share * len(payers)
    return [(user, share + (remainder if i == 0 else 0)) for i, user in enumerate(payers)]


def record_payments(session):
    """PAY-10: the caller is the booker's check-in and holds the session row lock (select_for_update), so the check
    below and the writes run alone. Returns the rows created (empty when the session already has payments)."""
    if session.payments.exists():
        return []
    now = timezone.now()
    today = now.astimezone(UTC).date()  # PAY-14
    wanted = []  # (payer, club, coach, amount)
    if session.court_id:  # PAY-11
        rentals = session.rentals.filter(status=SessionRental.Status.APPROVED).aggregate(n=Sum("price"))["n"] or 0
        wanted.append((session.booked_by, session.court.club, None, session.price - session.discount_amount + rentals))
    wanted += [(payer, None, session.coach, amount) for payer, amount in _coach_fee_rows(session)]
    percents, created = {}, []
    for payer, club, coach, amount in wanted:
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


# ---- marking paid (PAY-20, PAY-21) ----

def set_paid(payment, paid):
    """The view has checked the caller is the payee side. A repeat changes nothing (GEN-5)."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("payer", "club", "coach").get(pk=payment.pk)
        if paid:
            if payment.paid_at is not None:
                return payment
            payment.method, payment.paid_at = Payment.Method.OFFLINE, timezone.now()
        else:
            if payment.settled_at:
                raise BusinessError("already_settled", "The platform's cut of this payment is settled; it cannot go back to due.")
            if payment.paid_at is None:
                return payment
            payment.method, payment.paid_at = "", None
        payment.save(update_fields=["method", "paid_at"])
    return payment


# ---- reports (RPT-2, RPT-3, RPT-7) ----

def due_list(payments):
    """RPT-2: the payments of `payments` not yet paid, and the totals per currency."""
    rows = payments.filter(paid_at__isnull=True).select_related("payer").order_by("created_at", "id")
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
