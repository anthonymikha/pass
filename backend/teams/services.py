from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied

from accounts.models import Connection, User
from accounts.services import friends_of, is_blocked_pair, is_shadow_player, notify
from chat import services as chat
from config.api import BusinessError
from venues.models import ClubMember
from venues.services import club_today, current_members

from .models import Group, GroupMember

ACTIVE, INVITED, REQUESTED = GroupMember.Status.ACTIVE, GroupMember.Status.INVITED, GroupMember.Status.REQUESTED
TEAM = Group.Type.TEAM


def _name(user):
    return user.full_name or "Someone"  # never the email in a push


# --- ACC-1 names (later tasks import these) ---

def group_managers(group):
    """ACC-1: a play group's creator; a team's coach only (the creator of a team has no rights). TEAM-34: a team
    without a coach has none."""
    manager = group.coach if group.type == TEAM else group.created_by
    return [manager] if manager else []


def is_group_manager(user, group):
    return user.pk == (group.coach_id if group.type == TEAM else group.created_by_id)


def coachs_players(coach):
    """ACC-1: accepted coaching connections from `coach`, active members of teams where `coach` is the team coach,
    and shadow players managed by the coach. Never the coach themself."""
    teams = Group.objects.filter(type=TEAM, coach=coach)
    accepted = Connection.objects.filter(user=coach, type=Connection.Type.COACHING, status=Connection.Status.ACCEPTED)
    return User.objects.filter(
        Q(pk__in=accepted.values("other_user"))
        | Q(pk__in=GroupMember.objects.filter(group__in=teams, status=ACTIVE).values("user"))
        | Q(managed_by=coach, email__isnull=True)
    ).exclude(pk=coach.pk).order_by("full_name", "id")


def is_active_member(user, group):
    return GroupMember.objects.filter(group=group, user=user, status=ACTIVE).exists()


# --- membership plumbing ---

def _activate(row):
    """TEAM-28: a row becomes active and a non-shadow user joins the chat, in the same transaction."""
    row.status = ACTIVE
    row.save(update_fields=["status"])
    if not is_shadow_player(row.user):
        chat.add_chat_member(row.group, row.user)


def _remove(row):
    """TEAM-26, TEAM-28: deleting an active row drops the chat membership."""
    if row.status == ACTIVE:
        chat.remove_chat_member(row.group, row.user)
    row.delete()


def _row(group, user_id):
    return GroupMember.objects.select_related("group", "user").filter(group=group, user_id=user_id).first()


# --- TEAM-20 to TEAM-31 ---

def create_group(user, name, type, sport=None):
    """TEAM-20."""
    with transaction.atomic():
        if type == TEAM and not user.is_coach:
            raise BusinessError("not_a_coach", "Only coaches can create teams.")
        group = Group.objects.create(
            type=type, name=name, sport=sport, created_by=user, coach=user if type == TEAM else None)
        GroupMember.objects.create(group=group, user=user, status=ACTIVE)
        chat.create_group_chat(group, user)
        return group


def invite(group, manager, invitee):
    """TEAM-22: returns (row, created). `invitee` is already known to be an active non-shadow user."""
    with transaction.atomic():
        if is_blocked_pair(manager, invitee):
            raise BusinessError("cannot_invite", "You cannot invite this user.")
        if group.type == Group.Type.PLAY_GROUP and not friends_of(manager).filter(pk=invitee.pk).exists():
            raise BusinessError("cannot_invite", "You can only invite friends to a play group.")
        row, created = GroupMember.objects.get_or_create(group=group, user=invitee, defaults={"status": INVITED})
        if created:
            notify([invitee], "group_invite", "Group invitation", f"{_name(manager)} invited you to {group.name}",
                   {"id": group.id})
        elif row.status == REQUESTED:  # they had asked
            _activate(row)
        return row, created


def accept_invite(group, user):
    """TEAM-23: the invitee accepts; repeating on an active row is a 200 (GEN-5)."""
    with transaction.atomic():
        row = _row(group, user.pk)
        if not row or row.status == REQUESTED:
            raise NotFound()
        if row.status == INVITED:
            _activate(row)
        return row


def ask_to_join(group, user):
    """TEAM-24: returns (row, created)."""
    with transaction.atomic():
        if any(is_blocked_pair(user, m) for m in group_managers(group)):
            raise BusinessError("cannot_join", "You cannot join this group.")
        row, created = GroupMember.objects.get_or_create(group=group, user=user, defaults={"status": REQUESTED})
        if created:
            notify([m for m in group_managers(group) if m.pk != user.pk], "join_request", "Join request",
                   f"{_name(user)} wants to join {group.name}", {"id": group.id})
        elif row.status == INVITED:
            _activate(row)
        return row, created


def accept_request(group, user_id):
    """TEAM-25: a manager accepts a join request; repeating on an active row is a 200 (GEN-5)."""
    with transaction.atomic():
        row = _row(group, user_id)
        if not row or row.status == INVITED:
            raise NotFound()
        if row.status == REQUESTED:
            _activate(row)
        return row


def remove_member(group, caller, user_id):
    """TEAM-26, TEAM-31: leave or decline (own row), remove or reject (a manager, never a manager's own row)."""
    with transaction.atomic():
        if user_id != caller.pk and not is_group_manager(caller, group):
            raise PermissionDenied("Only a group manager can remove other members.")
        if any(m.pk == user_id for m in group_managers(group)):  # TEAM-31
            raise BusinessError("manager_cannot_leave",
                                "A group manager cannot leave; hand the team over or delete the group instead.")
        row = _row(group, user_id)
        if not row:
            raise NotFound()
        _remove(row)


def add_shadow_player(group, manager, player):
    """TEAM-27: returns (row, created)."""
    with transaction.atomic():
        if group.type != TEAM:
            raise BusinessError("not_a_team", "Shadow players can only join teams.")
        if player.managed_by_id != manager.pk:
            raise BusinessError("not_your_player", "This is not one of your shadow players.")
        row, created = GroupMember.objects.get_or_create(group=group, user=player, defaults={"status": ACTIVE})
        if not created and row.status != ACTIVE:
            _activate(row)
        return row, created


def seat_coach(group):
    """TEAM-29, TEAM-35: the team coach gets an active member row and the chat membership (TEAM-28)."""
    row, _ = GroupMember.objects.select_related("group", "user").get_or_create(
        group=group, user=group.coach, defaults={"status": ACTIVE})
    if row.status != ACTIVE:
        _activate(row)
    else:
        chat.add_chat_member(group, group.coach)


def hand_over(group, new_coach):
    """TEAM-29: the view checked the caller is the team coach; `new_coach` is an active non-shadow user."""
    with transaction.atomic():
        if group.type != TEAM:
            raise BusinessError("not_a_team", "Only teams have a coach.")
        if not new_coach.is_coach:
            raise BusinessError("not_a_coach", "This user is not a coach.")
        previous = group.coach
        if previous.pk == new_coach.pk:  # GEN-5
            return group
        group.coach = new_coach  # created_by stays and gives no rights (ACC-1)
        group.save(update_fields=["coach"])
        seat_coach(group)
        old = _row(group, previous.pk)
        if old:
            _remove(old)  # the previous coach leaves the team and its chat (TEAM-28)
        from bookings.services import hand_over_training  # downward call (docs/backend/README.md); lazy: it imports us
        hand_over_training(group, previous, new_coach)
        return group


def delete_group(group):
    """TEAM-30: members go with the group (cascade); sessions and the chat keep their data with `group` emptied."""
    with transaction.atomic():
        chat.detach_chat(group)
        group.delete()


# --- Finding people (ACC-20 to ACC-23) ---

def findable_users(viewer):
    """Active non-shadow users the viewer is not in a blocked pair with."""
    blocked = Connection.objects.filter(type=Connection.Type.FRIEND, status=Connection.Status.BLOCKED)
    return User.objects.filter(is_active=True, email__isnull=False).exclude(
        Q(pk__in=blocked.filter(user=viewer).values("other_user"))
        | Q(pk__in=blocked.filter(other_user=viewer).values("user"))
    )


def search_users(viewer, q):
    """ACC-20."""
    return findable_users(viewer).filter(Q(full_name__icontains=q) | Q(email__iexact=q)).order_by("full_name", "id")


def search_coaches(viewer, q=None, club=None):
    """ACC-22: `club` is a Club the viewer may see (or None for no club filter)."""
    coaches = findable_users(viewer).filter(is_coach=True)
    if q:
        coaches = coaches.filter(full_name__icontains=q)
    if club:
        coaches = coaches.filter(pk__in=current_members(club).filter(role=ClubMember.Role.COACH).values("user"))
    return coaches.order_by("full_name", "id")


def affiliated_clubs(user):
    """ACC-21: clubs where the user has an active, unexpired coach membership (ACC-2), by name.
    ponytail: one query per profile; batch it if lists get long."""
    rows = user.club_memberships.filter(role=ClubMember.Role.COACH, status=ClubMember.Status.ACTIVE).select_related("club")
    clubs = [m.club for m in rows if m.expires_on is None or m.expires_on >= club_today(m.club)]
    return sorted(clubs, key=lambda c: (c.name, c.pk))
