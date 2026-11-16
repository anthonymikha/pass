# Flow: friends, play groups, coaches and teams

**Status: planned.**

Models: [User, Connection, UserBlockout](../models/accounts.md), [ClubMember](../models/venues.md), [Group, GroupMember](../models/teams.md), [Session, SessionParticipant](../models/bookings.md), [Payment](../models/billing.md), [Chat](../models/chat.md).

## Players: friends and play groups

1. **Add a friend:** create a `Connection` (`type=friend`, `pending`). The other user accepts (`accepted`) or the row is deleted.
2. **Block-out times:** each player keeps `UserBlockout` rows for work or school.
3. **Create a play group:** a `Group` (`type=play_group`), an `active` `GroupMember` for the creator, `invited` rows for friends, and the group's `Chat`.
4. **Find a time everyone can play:** see availability below.
5. **Book for the group:** the normal [booking flow](booking-and-payment.md) with `Session.group` set and a participant row per active member.

## Availability

A user is free in a time window when:
- no `UserBlockout` covers it (weekly ones matched by weekday, one-off ones by date, both in the user's timezone), and
- they are not an accepted participant in a non-cancelled `Session` overlapping it.

A group is free when every active member is free. Coaches use the same check for a single player or a whole team before booking.

## Becoming a coach

1. The user sets `is_coach` and fills in the coach fields on their profile.
2. Optional: ask to join clubs. A `ClubMember` (`role=coach`, `pending`) that the club owner makes `active`. A coach with no memberships is a freelancer.
3. Affiliated coaches see their clubs' courts first when booking.

## Coaching a single player

- **Player asks:** the player finds a coach and creates a `Session` with `kind=training`, `coach` set, `status=requested`. The coach accepts by setting the court, time, `coach_fee` and `status=confirmed`.
- **Ongoing relationship:** a `Connection` with `type=coaching` (`user` = coach, `other_user` = player). This is what lets the coach see the player's progress, recovery and availability.

## Teams

1. **Create:** the coach creates a `Group` (`type=team`) and its `Chat`.
2. **Fill it:**
   - Coach invites a player: `GroupMember` `invited` → player accepts → `active`.
   - Player asks to join: `GroupMember` `requested` → coach accepts → `active`.
   - Shadow players: the coach creates the `User` (no email, `managed_by` = coach) and adds them as `active`.
3. **Book training:** the coach creates a `Session` with `booked_by` = `coach` = themselves, `group` = the team, and a participant row per active member.
4. **Choose who pays the coach fee:** leave `coach_fee_payer` empty to split it across accepted members, or set it to bill one account.
5. **At the session:** players check in; the coach checks in shadow players. The coach is the booker, so the coach's own check-in records the payments.

```
coach ─owner─> Group(team) ─> GroupMember(active) ─┐
   │                                               ├─> Session(training, group) ─> SessionParticipant × n
   └─booked_by, coach──────────────────────────────┘            │
                                                    coach checks in ─> Payment × n (split) or × 1
```

## What a coach can see

| About | From |
|---|---|
| Attendance of a player or team | `SessionParticipant.checked_in_at` on sessions they coached |
| Training load | `rpe × rpe_minutes` on those rows |
| Soreness, sleep, exercises done | wellness tables, for their players only |
| Free times | the availability check above |

A coach's "players" are users with an accepted coaching connection to them, active members of teams they own, and shadow players they manage.

## Open points

- Whether the two friends in a `Connection` should be stored in a fixed order to make reverse duplicates impossible.
- Whether a team split bills every accepted member (current rule) or only those who attended.
