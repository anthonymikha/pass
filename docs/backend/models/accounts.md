# accounts models

Source: [backend/accounts/models.py](../../../backend/accounts/models.py). Tables: `users`, `connections`, `user_blockouts`.

## User (`users`)

One row per person, whatever their role. Login is by email and password; there is no username.

| Field | Meaning |
|---|---|
| `email` | Unique login. **Empty means a shadow player** (see below). Always stored lowercase |
| `phone`, `full_name`, `avatar`, `timezone` | Profile. `timezone` is an IANA name such as `Asia/Beirut` |
| `is_coach` | The user offers coaching. Self-declared, no approval |
| `coach_bio`, `coach_rate`, `coach_currency` | Shown on the coach's profile. `coach_rate` is informational; the real fee is set per session |
| `managed_by` | For shadow players: the coach who manages them |
| `is_staff`, `is_active`, `is_superuser` | Django admin access and account switch |

**Roles are not a column.**
- Player: every user.
- Coach: `is_coach` is true.
- Owner: owns at least one club (`user.owned_clubs.exists()`).
- One person can be all three.

**Shadow players** are people who cannot have an account (for example children without phones). A coach creates them to track attendance. They have no email, an unusable password, and `managed_by` set.

```python
# normal user
User.objects.create_user("pat@example.com", "a-strong-password", full_name="Pat")

# shadow player managed by a coach
User.objects.create_user(full_name="Kid", managed_by=coach)
```

Rules:
- Always create users with `create_user()` so the password is hashed, or left unusable when there is no email.
- `save()` lowercases the email and turns a blank one into NULL. Any number of shadow players can therefore coexist.
- A user with sessions or payments cannot be deleted. Deactivate with `is_active = False` instead.
- If a coach is deleted, their shadow players stay, with `managed_by` emptied.

## Connection (`connections`)

A directed link between two users.

| Field | Meaning |
|---|---|
| `user` | Who started it |
| `other_user` | Who it is aimed at |
| `type` | `friend` or `coaching` |
| `status` | `pending` → `accepted`, or `blocked` |

Unique on (`user`, `other_user`, `type`).

- **Friends:** one row covers the friendship. To list someone's friends, look at accepted rows where they are on either side.
- **Coaching (1:1):** `user` is the coach, `other_user` is the player.

```python
from django.db.models import Q

friends = Connection.objects.filter(
    Q(user=me) | Q(other_user=me), type="friend", status="accepted"
)
my_players = User.objects.filter(
    incoming_connections__user=coach,
    incoming_connections__type="coaching",
    incoming_connections__status="accepted",
)
```

Before creating a friend request, check the reverse row does not already exist; the unique rule only covers one direction.

## UserBlockout (`user_blockouts`)

Times a user is not available to play (work, school).

| Field | Meaning |
|---|---|
| `weekday` | 0–6, repeats every week |
| `on_date` | A single date |
| `start_time`, `end_time` | In the user's own `timezone` |

Exactly one of `weekday` and `on_date` must be set; the database rejects both or neither.

```python
UserBlockout.objects.create(user=me, weekday=0, start_time=time(9), end_time=time(17))   # every Monday
UserBlockout.objects.create(user=me, on_date=date(2027, 1, 6), start_time=time(9), end_time=time(12))
```

A user is free at a given time when no block-out covers it and they are in no session then. Availability for a group is the same check across all active members. See [coaching-and-teams](../flows/coaching-and-teams.md).

## Used together with

- `venues.Club.owner`, `venues.ClubMember.user` for ownership and coach affiliation.
- `teams.GroupMember.user` for group membership.
- `bookings.SessionParticipant.user` for attendance and RPE.
