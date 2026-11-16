# Flow: RPE, soreness, sleep and recovery exercises

**Status: planned.** The recovery score is deliberately not designed yet.

Models: [SessionParticipant](../models/bookings.md), [SorenessLog, SleepLog, Exercise, ExerciseBodyArea, ExerciseAssignment, UserAchievement](../models/wellness.md), [Group](../models/teams.md).

## After a session: the RPE form

Meant to take under two minutes.

1. When a session ends, each participant who checked in gets a reminder.
2. They submit effort (1–10) and, optionally, minutes and sore areas.
3. Written in one request:
   - `SessionParticipant.rpe`, `rpe_minutes` (default: session length), `rpe_logged_at`.
   - One `SorenessLog` per sore area with `period=post_session` and `session` set.
4. Submitting unlocks the session's video ([recordings](recordings.md)).

Only a participant who checked in can submit. Shadow players do not log RPE.

## Daily check-ins

- **Morning and evening soreness:** one `SorenessLog` per sore area, `period=morning` or `evening`.
- **Sleep:** a `SleepLog`, typed in or sent by the phone after reading Apple Health / Google Health Connect (`source=health_app`).

## Exercise suggestions

After a soreness check-in:

1. For each reported area and level, pick exercises that target the area and whose `min_soreness`–`max_soreness` range contains the level.
2. Offer them as `ExerciseAssignment` rows with `assigned_by` empty.
3. The player ticks one off: set `completed_at`.
4. Completions can earn a `UserAchievement` (for example the first completed exercise, or a streak).

```
SorenessLog(quads, 6) ─> Exercise ⋈ ExerciseBodyArea(quads), 6 in [min,max]
                              └─> ExerciseAssignment ─ completed_at ─> UserAchievement
```

## Coach-sent exercises

A coach picks exercises and a target:
- one player: one `ExerciseAssignment` with `assigned_by` = coach;
- a team: one row per active member, each with `group` set.

Players see system suggestions and coach assignments in one list, distinguished by `assigned_by`.

## What is read back

| View | Query |
|---|---|
| A player's load over time | their `SessionParticipant` rows: `rpe × rpe_minutes` by date |
| Soreness trend per area | `SorenessLog` by `logged_on`, `period`, `body_area` |
| Sleep duration | `sleep_end − sleep_start` per night |
| Outstanding exercises | `ExerciseAssignment` with `completed_at` empty |
| Team view for a coach | the same, across the team's active members |

## Not designed yet

- **Recovery level:** a score from load, soreness and sleep. Waiting on a sports expert; do not invent a formula.
- **Suggested play and training times**, for a player or a group: depends on the recovery level.
