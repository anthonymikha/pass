"""Wellness logic (WEL). No recovery level and no suggested times: deferred to the sports expert."""
import datetime
import zoneinfo

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.models import User
from accounts.services import is_shadow_player, notify
from bookings.models import Session, SessionParticipant
from config.api import BusinessError
from teams import services as teams
from teams.models import Group, GroupMember

from .models import Exercise, ExerciseAssignment, SleepLog, SorenessLog, UserAchievement

POST_SESSION = SorenessLog.Period.POST_SESSION


def user_today(user):
    """GEN-8, GEN-9: today's date in the user's timezone."""
    return timezone.now().astimezone(zoneinfo.ZoneInfo(user.timezone)).date()


def _lock_user(user):
    """Serialises a user's own writes (check-in replace, pick, complete)."""
    User.objects.select_for_update().get(pk=user.pk)


# --- RPE (WEL-1 to WEL-4) ---

def submit_rpe(row, rpe, rpe_minutes=None, sore_areas=()):
    """WEL-3: one transaction; `row` is the caller's own participant row. Returns the locked, updated row."""
    with transaction.atomic():
        row = SessionParticipant.objects.select_for_update(of=("self",)).select_related("session").get(pk=row.pk)
        session, now = row.session, timezone.now()
        # WEL-1, WEL-4
        if session.status != Session.Status.CONFIRMED:
            raise BusinessError("invalid_status", "This session is not confirmed.")
        if row.checked_in_at is None:
            raise BusinessError("not_checked_in", "You did not check in to this session.")
        if now > session.ends_at + datetime.timedelta(days=7):
            raise BusinessError("rpe_closed", "RPE can only be logged within 7 days after the session.")
        row.rpe = rpe
        # WEL-2: default = session length in whole minutes, rounded down
        row.rpe_minutes = rpe_minutes or int((session.ends_at - session.starts_at).total_seconds() // 60)
        row.rpe_logged_at = now
        row.save(update_fields=["rpe", "rpe_minutes", "rpe_logged_at"])
        logged_on = session.starts_at.astimezone(zoneinfo.ZoneInfo(row.user.timezone)).date()
        SorenessLog.objects.filter(user=row.user, session=session, period=POST_SESSION).delete()
        SorenessLog.objects.bulk_create([
            SorenessLog(user=row.user, session=session, period=POST_SESSION, logged_on=logged_on,
                        body_area=a["body_area"], level=a["level"]) for a in sore_areas])
        return row


# --- Soreness (WEL-10 to WEL-12, WEL-30 to WEL-33) ---

def suggestions(pairs):
    """WEL-30: [(area, level)] -> [{body_area, level, exercises}]; level 0 gets nothing, no match is an empty list."""
    return [
        {"body_area": area, "level": level, "exercises": list(
            Exercise.objects.filter(body_areas__body_area=area, min_soreness__lte=level, max_soreness__gte=level)
            .order_by("name", "id"))}
        for area, level in pairs if level >= 1
    ]


def log_soreness(user, period, logged_on, areas):
    """WEL-11: replace the rows of (logged_on, period); an empty list deletes them."""
    with transaction.atomic():
        _lock_user(user)
        SorenessLog.objects.filter(user=user, logged_on=logged_on, period=period).delete()
        SorenessLog.objects.bulk_create([
            SorenessLog(user=user, logged_on=logged_on, period=period, body_area=a["body_area"], level=a["level"])
            for a in areas])


def suggestions_for_today(user):
    """WEL-31: today's rows (user timezone), all periods, highest level per area."""
    highest = {}
    rows = SorenessLog.objects.filter(user=user, logged_on=user_today(user))
    for area, level in rows.values_list("body_area", "level"):
        highest[area] = max(level, highest.get(area, 0))
    return suggestions(sorted(highest.items()))


# --- Sleep (WEL-20 to WEL-22) ---

def import_sleep(user, records):
    """WEL-21: upsert on (user, source, external_id); `records` were all validated first. Returns (created, updated)."""
    created = 0
    # ponytail: up to 500 queries per import; batch with bulk_create/bulk_update if imports get slow.
    with transaction.atomic():
        for r in records:
            _, new = SleepLog.objects.update_or_create(
                user=user, source=r["source"], external_id=r["external_id"],
                defaults={"sleep_start": r["sleep_start"], "sleep_end": r["sleep_end"]})
            created += new
    return created, len(records) - created


# --- Exercises (WEL-33, WEL-40 to WEL-44) ---

def pick_exercise(user, exercise, prescription):
    """WEL-33: returns (assignment, created). An open self-picked one of the same exercise is returned instead."""
    with transaction.atomic():
        _lock_user(user)
        open_pick = ExerciseAssignment.objects.filter(
            user=user, exercise=exercise, assigned_by__isnull=True, completed_at__isnull=True).first()
        if open_pick:
            return open_pick, False
        return ExerciseAssignment.objects.create(user=user, exercise=exercise, **prescription), True


def _send(coach, players, exercise, prescription, group=None):
    rows = []
    for player in players:
        row = ExerciseAssignment.objects.create(
            user=player, exercise=exercise, assigned_by=coach, group=group, **prescription)
        notify([player], "exercise_assigned", "New exercise",  # NOTE-20
               f"{coach.full_name or 'Your coach'} sent you {exercise.name}", {"id": row.id})
        rows.append(row)
    return rows


def assign_to_player(coach, player, exercise, prescription):
    """WEL-40, WEL-41: `player` is one of the coach's players (ACC-1)."""
    with transaction.atomic():
        if is_shadow_player(player):
            raise BusinessError("not_assignable", "Shadow players cannot receive exercises.")
        return _send(coach, [player], exercise, prescription)[0]


def can_send_to_team(coach, group):
    """WEL-40: a coach, to a team the coach manages."""
    return coach.is_coach and group.type == Group.Type.TEAM and teams.is_group_manager(coach, group)


def assign_to_team(coach, group, exercise, prescription):
    """WEL-41: one row per active member who is not a shadow player and not the coach."""
    with transaction.atomic():
        members = User.objects.filter(
            pk__in=GroupMember.objects.filter(group=group, status=GroupMember.Status.ACTIVE).values("user"),
            email__isnull=False).exclude(pk=coach.pk).order_by("id")
        return _send(coach, members, exercise, prescription, group)


def complete_assignment(user, pk):
    """WEL-42, WEL-50: sets completed_at once (GEN-5) and checks achievements in the same transaction."""
    with transaction.atomic():
        _lock_user(user)
        row = ExerciseAssignment.objects.select_for_update(of=("self",)).select_related("exercise").filter(pk=pk, user=user).first()
        if row is None:
            raise NotFound()
        if row.completed_at is None:
            row.completed_at = now = timezone.now()
            row.save(update_fields=["completed_at"])
            _check_achievements(user, now)
        return row


def delete_assignment(user, pk):
    """WEL-43: own self-picked ones, or ones the caller sent; never a completed one (403: the caller can see it)."""
    with transaction.atomic():
        row = ExerciseAssignment.objects.select_for_update().filter(pk=pk).first()
        if not row or user.pk not in (row.user_id, row.assigned_by_id):
            raise NotFound()  # GEN-3
        own_pick = row.user_id == user.pk and row.assigned_by_id is None
        if row.completed_at or not (own_pick or row.assigned_by_id == user.pk):
            raise PermissionDenied("You cannot delete this exercise.")
        row.delete()


def _check_achievements(user, now):
    """WEL-50, WEL-51: codes and conditions exactly as the table says; each earned once."""
    def earn(code):
        UserAchievement.objects.get_or_create(user=user, achievement_code=code, defaults={"earned_at": now})

    earn("first_exercise")  # this is a completion, so it is the first one or the user already has it
    tz = zoneinfo.ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    week = {today - datetime.timedelta(days=i) for i in range(7)}
    # a day of slack before the window, then the dates are taken in the user's timezone now (see the DST edge case)
    since = datetime.datetime.combine(today - datetime.timedelta(days=7), datetime.time.min, tz)
    done = ExerciseAssignment.objects.filter(user=user, completed_at__gte=since).values_list("completed_at", flat=True)
    if week <= {c.astimezone(tz).date() for c in done}:
        earn("exercise_streak_7")


# --- Reads ---

def players_of(coach):
    """TEAM-40: the users a coach may read about; an invisible one is a 404 (GEN-3)."""
    return teams.coachs_players(coach) if coach.is_coach else User.objects.none()
