# accounts models

Source: [backend/accounts/models.py](../../../backend/accounts/models.py). Tables: `users`, `connections`, `user_blockouts`, `devices`.

## User (`users`)

One row per person, whatever their role. Login is by email and password; there is no username.

| Field | Meaning |
|---|---|
| `email` | Unique login. **Empty means a shadow player** (see below). Always stored lowercase |
| `phone`, `full_name`, `avatar`, `timezone` | Profile. `timezone` is an IANA name such as `Asia/Beirut` |
| `date_of_birth`, `sex` | Optional. `sex` is `male` or `female` |
| `height_cm`, `weight_kg` | Optional, **latest value only** (no history). The phone can fill them from Apple Health / Health Connect |
| `nationality` | Optional, 2-letter ISO country code such as `LB` |
| `dominant_hand` | Optional: `left`, `right` or `both` |
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
- A user with sessions or payments cannot be deleted as a row. Deleting an account (review 2026-11-20, [ACC-33](../logic/access-and-roles.md#your-account)) deactivates it and scrubs its personal data instead: `full_name` "Deleted user", `email` `deleted-<id>@invalid`, `is_active = False`. An admin setting `is_active = False` alone is a reversible deactivation (ACC-35).
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

The unique rule only covers one direction; requests, crossing requests and blocking are handled by [TEAM-1 to TEAM-6](../logic/teams-and-coaching.md#friends).

## Blockout (shared shape) and UserBlockout (`user_blockouts`)

`Blockout` is an abstract model: a time window that is unavailable, one-off or repeating. Two tables use it: `user_blockouts` (times a user cannot play: work, school) and [`court_blockouts`](venues.md#courtblockout-court_blockouts) (court closures).

| Field | Meaning |
|---|---|
| `starts_on` | The date of a one-off, or the first occurrence of a repeating one |
| `start_time`, `end_time` | In the user's own `timezone` (the club's, for courts) |
| `repeat` | `none`, `daily`, `weekly` or `monthly` |
| `repeat_until` | Last date it can occur. Empty = repeats forever. Cannot be before `starts_on` |
| `reason` | Optional note |

The pattern is taken from `starts_on`: `weekly` repeats on its weekday, `monthly` on its day of the month. A monthly block-out on the 31st is skipped in months without a 31st.

```python
UserBlockout.objects.create(user=me, starts_on=date(2027, 1, 4), start_time=time(9), end_time=time(17), repeat="weekly")   # every Monday
UserBlockout.objects.create(user=me, starts_on=date(2027, 1, 6), start_time=time(9), end_time=time(12))                    # once
UserBlockout.objects.create(user=me, starts_on=date(2027, 1, 15), start_time=time(18), end_time=time(20), repeat="monthly", repeat_until=date(2027, 6, 30))

blockout.occurs_on(date(2027, 2, 15))   # True
```

Patterns such as "every two weeks" or "first Monday of the month" are not supported. Exact occurrence rules: [AVL-8](../logic/court-availability.md#closures).

A user is free at a given time when no block-out covers it and they are in no session then. Availability for a group is the same check across all active members. See [coaching-and-teams](../flows/coaching-and-teams.md).

## Device (`devices`)

A phone registered for push notifications ([NOTE-1 to NOTE-3](../logic/notifications.md#devices)).

| Field | Meaning |
|---|---|
| `user` | The owner. Deleted with the user |
| `token` | The Firebase registration token. Unique across all users (up to 4096 characters); registering a token that belongs to someone else moves it |
| `platform` | `ios`, `android` or `web` |

## Used together with

- `venues.Club.owner`, `venues.ClubMember.user` for ownership and coach affiliation.
- `teams.GroupMember.user` for group membership.
- `bookings.SessionParticipant.user` for attendance and RPE.
