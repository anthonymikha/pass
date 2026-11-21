# teams models

Source: [backend/teams/models.py](../../../backend/teams/models.py). Tables: `groups`, `group_members`.

## Group (`groups`)

A named set of users. Two kinds share one table because they behave the same.

| `type` | Created by | Purpose |
|---|---|---|
| `play_group` | Any player | Friends who schedule games together |
| `team` | A coach | A coached team |

| Field | Meaning |
|---|---|
| `name` | |
| `created_by` | Who created it (renamed from `owner` at review 2026-11-17). Manages a play group; for a team it is history only and gives no rights |
| `coach` | The **team coach**, the team's only manager. Empty for play groups. Starts as the creator |
| `sport` | Optional |

The creator is not automatically a member row. Create one for them (status `active`) when the group is created, so "members" always means the people who play.

**Handing a team over:** set `coach` to the new coach; the previous coach leaves the team and its chat. Members, chat and history stay with the team. Upcoming team training passes to the new coach, who also becomes its booker; sessions already started keep the coach who ran them (`sessions.coach`). `created_by` does not change ([TEAM-29](../logic/teams-and-coaching.md#play-groups-and-teams)). Invites, join requests and leaving: [TEAM-20 to TEAM-31](../logic/teams-and-coaching.md#play-groups-and-teams).

```python
Group.objects.filter(pk=team.pk).update(coach=new_coach)
```

## GroupMember (`group_members`)

| `status` | Meaning |
|---|---|
| `invited` | A group manager invited the user; waiting for the user |
| `requested` | The user asked to join; waiting for a group manager |
| `active` | Member |

Unique per (group, user). Declining or leaving deletes the row.

```python
team = Group.objects.create(type="team", name="U12 Tigers", created_by=coach, coach=coach, sport=basketball)
GroupMember.objects.create(group=team, user=player, status="invited")      # coach invites
GroupMember.objects.create(group=team, user=other, status="requested")     # player asks to join
GroupMember.objects.filter(group=team, user=player).update(status="active")  # accepted

active = User.objects.filter(group_memberships__group=team, group_memberships__status="active")
```

Shadow players can be team members; the coach adds them directly as `active`.

## Used together with

- `bookings.Session.group`: a session booked for the group.
- `chat.Chat.group`: each group has exactly one chat.
- `wellness.ExerciseAssignment.group`: exercises a coach sent to the whole team.
- `accounts.UserBlockout` + sessions: group availability.
- Full journey: [coaching-and-teams](../flows/coaching-and-teams.md).
