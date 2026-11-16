# wellness models

Source: [backend/wellness/models.py](../../../backend/wellness/models.py). Tables: `soreness_logs`, `sleep_logs`, `exercises`, `exercise_body_areas`, `exercise_assignments`, `user_achievements`.

RPE is not here: it is stored on `bookings.SessionParticipant` because it describes one participation. Wellness logic reads it from there.

## BodyArea

A fixed list shared by soreness logs and exercises:

`neck`, `shoulders`, `upper_back`, `lower_back`, `chest`, `arms`, `elbows`, `wrists_hands`, `core`, `hips`, `glutes`, `quads`, `hamstrings`, `knees`, `calves`, `ankles_feet`.

## SorenessLog (`soreness_logs`)

One row per body area per check-in.

| Field | Meaning |
|---|---|
| `user`, `logged_on` | Who and which day |
| `period` | `morning`, `evening`, or `post_session` |
| `session` | Set for `post_session` logs, so two sessions on one day stay separate |
| `body_area` | One of the list above |
| `level` | 0–10 |

A check-in where three areas are sore is three rows. Areas not mentioned are treated as not sore.

```python
SorenessLog.objects.bulk_create([
    SorenessLog(user=me, logged_on=today, period="morning", body_area="quads", level=6),
    SorenessLog(user=me, logged_on=today, period="morning", body_area="calves", level=3),
])
```

Morning and evening logs over several days show how fast a player recovers.

## SleepLog (`sleep_logs`)

| Field | Meaning |
|---|---|
| `sleep_start`, `sleep_end` | UTC |
| `source` | `manual`, `apple_health` (iPhone) or `health_connect` (Android) |
| `external_id` | The health app's own id for the record (HealthKit sample UUID, Health Connect record id). Empty for manual rows |

The phone reads the health data and posts it; the backend never talks to those services. Imports can repeat safely: (`user`, `source`, `external_id`) is unique when `external_id` is set, so sync with `update_or_create` on those three. `sleep_end` must be after `sleep_start`.

### What the health apps can and cannot fill

| Data | From Apple Health / Health Connect? | Lands in |
|---|---|---|
| Sleep sessions | Yes | `sleep_logs` |
| Height, weight, date of birth, sex | Yes (date of birth and sex on iPhone only) | `users`, latest value |
| Soreness, RPE | No. These are the player's own ratings; no health app records them | typed in |
| Exercises done | No. Workouts in health apps are not our catalogue | ticked off in the app |
| Heart rate, HRV, steps, sleep stages | Yes, but **not stored yet**: waiting for the recovery formula to say which are needed | — |

## Exercise (`exercises`)

The catalogue of stretching and mobility exercises, managed in the admin.

| Field | Meaning |
|---|---|
| `name`, `description`, `video_url` | |
| `kind` | `stretch` or `mobility` |
| `min_soreness`, `max_soreness` | The soreness range this exercise suits |

## ExerciseBodyArea (`exercise_body_areas`)

Which areas an exercise targets. One row per (exercise, body area); an exercise can have several.

### Suggesting exercises

For each area a player reported, suggest exercises that target the area and whose range contains the level. Suggestions are computed, not stored; a row is created only when the player picks one ([WEL-30 to WEL-33](../logic/wellness.md#exercise-suggestions)):

```python
Exercise.objects.filter(
    body_areas__body_area="quads", min_soreness__lte=6, max_soreness__gte=6
).distinct()
```

## ExerciseAssignment (`exercise_assignments`)

An exercise given to one user.

| Field | Meaning |
|---|---|
| `exercise`, `user` | What and for whom |
| `assigned_by` | Empty = suggested by the system. Set = the coach who sent it |
| `group` | Set when the coach sent it to a whole team |
| `sets`, `reps` | Optional prescription: `sets` × `reps` per set |
| `hold_seconds` | Optional: how long to hold each rep, for stretches |
| `due_on` | Optional |
| `completed_at` | Set when the player ticks it off |

Sending to a team creates one row per active member, all with the same `group`, so each player ticks off their own.

```python
ExerciseAssignment.objects.bulk_create([
    ExerciseAssignment(exercise=ex, user=u, assigned_by=coach, group=team) for u in active_members
])
```

## UserAchievement (`user_achievements`)

| Field | Meaning |
|---|---|
| `achievement_code` | A code defined in the application, e.g. `first_exercise` |
| `earned_at` | |

One per (user, code). The list of achievements and their conditions lives in code, not in a table, and is written in [WEL-50](../logic/wellness.md#achievements).

## Recovery level

Not built, and no formula is agreed: it waits on input from a sports expert. It will be computed from training load (`rpe × rpe_minutes`), soreness and sleep, and never stored. Suggested play and training times depend on it.

## Used together with

- `bookings.SessionParticipant` for RPE and load.
- `teams.Group` for team assignments and, later, team recovery.
- Journey: [wellness](../flows/wellness.md).
