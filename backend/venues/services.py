import datetime
import math
import zoneinfo

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from accounts.services import notify
from config.api import BusinessError

from .models import Club, ClubCurrency, ClubMember, Court, PriceOverride

EARTH_KM = 6371


def club_today(club):
    """GEN-9: today in the club's timezone."""
    return timezone.now().astimezone(zoneinfo.ZoneInfo(club.timezone)).date()


def visible_clubs(user):
    """Clubs the caller may see: public ones (an active court, CLUB-30), their own, ones they have a membership row in."""
    seen = Q(courts__is_active=True)
    if user.is_authenticated:
        seen |= Q(owner=user) | Q(members__user=user)
    return Club.objects.filter(seen).distinct()


def current_members(club):
    """ACC-1, ACC-2: active rows that have not expired."""
    return club.members.filter(status=ClubMember.Status.ACTIVE).filter(
        Q(expires_on__isnull=True) | Q(expires_on__gte=club_today(club))
    )


def can_list_members(user, club):
    """CLUB-29: the owner, and anyone with a current membership (staff, affiliated coach, player)."""
    return club.owner_id == user.id or current_members(club).filter(user=user).exists()


# ---- club and currencies ----

def check_base_currency(club, data):
    if data.get("currency", club.currency) != club.currency:  # CLUB-3
        raise BusinessError("base_currency_fixed", "The base currency cannot be changed after the club is created.")


def add_currency(club, currency, exchange_rate):
    """CLUB-5. `currency_exists` covers the base and an already listed one."""
    if currency == club.currency:
        raise BusinessError("currency_exists", "That is the base currency.")
    try:
        with transaction.atomic():
            return ClubCurrency.objects.create(club=club, currency=currency, exchange_rate=exchange_rate)
    except IntegrityError:
        raise BusinessError("currency_exists", "This currency is already accepted.")


def remove_currency(accepted):
    """CLUB-7: also deletes the club's overrides in that currency."""
    with transaction.atomic():
        PriceOverride.objects.filter(currency=accepted.currency).filter(
            Q(court_rate__court__club=accepted.club) | Q(equipment__club=accepted.club)
        ).delete()
        accepted.delete()


# ---- courts, rates, equipment ----

def delete_court(court):
    """CLUB-10: PROTECT on sessions (and on rentals of its equipment) refuses the delete; the rest cascades."""
    try:
        court.delete()
    except ProtectedError:
        raise BusinessError("court_in_use", "This court has sessions; make it inactive instead.")


def delete_equipment(item):
    """CLUB-19: PROTECT on rentals refuses the delete."""
    try:
        item.delete()
    except ProtectedError:
        raise BusinessError("equipment_in_use", "This item has been rented.")


def check_rate_overlap(court, data, instance=None):
    """CLUB-12: same court and weekday, touching is fine, 00:00 as the end is 24:00.

    Call inside transaction.atomic() after locking the court row, so two edits cannot both pass.
    """
    def value(name):
        return data[name] if name in data else getattr(instance, name)

    def minutes(t, end=False):
        return 24 * 60 if end and t == datetime.time(0) else t.hour * 60 + t.minute

    start, end = minutes(value("start_time")), minutes(value("end_time"), end=True)
    others = court.rates.filter(weekday=value("weekday"))
    if instance:
        others = others.exclude(pk=instance.pk)
    for other in others:
        if start < minutes(other.end_time, end=True) and end > minutes(other.start_time):
            raise BusinessError("rate_overlap", "This window overlaps another rate on the same weekday.")


def lock_court(court):
    Court.objects.select_for_update().get(pk=court.pk)


# ---- closures ----

def closure_conflicts(closure):
    """CLUB-16: non-cancelled sessions starting after now that overlap an occurrence (AVL-8). Reads court.sessions only."""
    tz = zoneinfo.ZoneInfo(closure.court.club.timezone)
    midnight = datetime.time(0)
    day_after = datetime.timedelta(days=1)
    # ponytail: scans every future session of the court; narrow by the closure's date range if courts get busy
    sessions = closure.court.sessions.exclude(status="cancelled").filter(starts_at__gt=timezone.now()).order_by("starts_at")
    found = []
    for session in sessions:
        first, last = session.starts_at.astimezone(tz).date(), session.ends_at.astimezone(tz).date()
        for n in range((last - first).days + 1):
            day = first + datetime.timedelta(days=n)
            if not closure.occurs_on(day):
                continue
            start = datetime.datetime.combine(day, closure.start_time, tzinfo=tz)  # GEN-10, fold=0
            end_day = day + day_after if closure.end_time == midnight else day  # GEN-11
            end = datetime.datetime.combine(end_day, closure.end_time, tzinfo=tz)
            if session.starts_at < end and session.ends_at > start:
                found.append(session)
                break
    return found


# ---- overrides and offers ----

def add_override(club, data):
    """CLUB-20."""
    if not club.currencies.filter(currency=data["currency"]).exists():
        raise BusinessError("currency_not_accepted", "The club does not accept this currency.")  # PRC-1
    try:
        with transaction.atomic():
            return PriceOverride.objects.create(**data)
    except IntegrityError:
        raise BusinessError("override_exists", "There is already an override for this item and currency.")


def create_offer(serializer, club):
    """CLUB-22, CLUB-24."""
    with transaction.atomic():
        offer = serializer.save(club=club)
        if offer.user:
            notify([offer.user], "offer", f"New offer from {club.name}", offer.message, {"id": offer.id})  # NOTE-20
    return offer


def player_offers(club, user, court_id):
    """CLUB-32: running or future offers for this player; court empty or the given court."""
    court = Q(court__isnull=True) | Q(court_id=court_id) if court_id else Q(court__isnull=True)
    return club.discounts.filter(court, Q(user__isnull=True) | Q(user=user), ends_at__gt=timezone.now()).order_by("id")


# ---- members ----

def add_member(club, user, role, expires_on=None, status=ClubMember.Status.ACTIVE):
    """CLUB-25, CLUB-26."""
    try:
        with transaction.atomic():
            return ClubMember.objects.create(club=club, user=user, role=role, status=status, expires_on=expires_on)
    except IntegrityError:
        raise BusinessError("member_exists", "This user already has this role at the club.")


# ---- public search ----

def search_clubs(sport=None, q=None, lat=None, lng=None, radius_km=25):
    """CLUB-30. Clubs with an active court, filtered; sorted by name, or by distance when a location is given."""
    courts = Court.objects.filter(club=OuterRef("pk"), is_active=True)
    if sport:
        courts = courts.filter(sports=sport)
    clubs = Club.objects.filter(Exists(courts)).prefetch_related(
        Prefetch("courts", Court.objects.filter(is_active=True).order_by("id"), to_attr="active_courts")
    )
    if q:
        clubs = clubs.filter(name__icontains=q)
    if lat is None:
        return clubs.order_by("name", "id")
    # ponytail: Python haversine after a latitude band (ignores longitude wrap); move to PostGIS only if the club list gets large
    band = radius_km / 111.0
    clubs = clubs.filter(latitude__isnull=False, longitude__isnull=False, latitude__range=(lat - band, lat + band))
    found = []
    for club in clubs:
        d = _distance_km(lat, lng, float(club.latitude), float(club.longitude))
        if d <= radius_km:
            club.distance_km = round(d, 1)
            found.append((d, club.name, club.pk, club))
    return [item[-1] for item in sorted(found, key=lambda item: item[:3])]


def _distance_km(lat1, lng1, lat2, lng2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def my_clubs(user):
    """CLUB-33: clubs the user owns or has a current staff/coach membership in, with their roles, by name."""
    roles = {c.pk: (c, ["owner"]) for c in Club.objects.filter(owner=user)}
    rows = ClubMember.objects.filter(
        user=user, status=ClubMember.Status.ACTIVE, role__in=[ClubMember.Role.STAFF, ClubMember.Role.COACH]
    ).select_related("club")
    for row in rows:
        if row.expires_on is None or row.expires_on >= club_today(row.club):  # ACC-2, club timezone
            roles.setdefault(row.club_id, (row.club, []))[1].append(row.role)
    clubs = []
    for club, club_roles in roles.values():
        club.roles = sorted(club_roles, key=["owner", "staff", "coach"].index)
        clubs.append(club)
    return sorted(clubs, key=lambda c: (c.name, c.pk))
