# API: wellness (RPE, soreness, sleep, exercises, achievements)

**Status: built and tested.** Code: [views](../../../backend/wellness/views.py), [serializers](../../../backend/wellness/serializers.py), [services](../../../backend/wellness/services.py), [tests](../../../backend/wellness/tests.py). Rules: [wellness](../logic/wellness.md) (WEL-1 to WEL-4, WEL-10 to WEL-12, WEL-20 to WEL-23, WEL-30 to WEL-33, WEL-40 to WEL-44, WEL-50, WEL-51), [teams-and-coaching](../logic/teams-and-coaching.md) (TEAM-40), [access-and-roles](../logic/access-and-roles.md) (ACC-1, ACC-4, ACC-12), [notifications](../logic/notifications.md) (NOTE-20 `exercise_assigned`). Same conventions as [accounts](accounts.md).

No recovery level and no suggested times: deferred to the owner's sports expert (nothing computes, stores or approximates them). WEL-5 (RPE unlocks the video) is enforced by the recordings endpoints (REC-20), not here.

## Who may call

Every call needs a token. A user reads and writes only their own logs (ACC-4); someone else's row or id is `404` (GEN-3). A coach reads, and sends exercises to, their own players only (ACC-1, TEAM-40): anyone else, and every caller who is not a coach, gets `404` on `/api/players/<id>/...`. Dates ("today", `logged_on`, `due_on`, streaks) are in the **caller's** timezone (GEN-8).

## Endpoints

| Method | Path | Who | Body / notes | Success |
|---|---|---|---|---|
| PUT | `/api/sessions/<id>/rpe/` | a participant, own row | `rpe` (1-10), optional `rpe_minutes` (1-600; default the session length in whole minutes), optional `sore_areas` `[{body_area, level 0-10}]`, each area once. Replaces the RPE and the post-session soreness rows in one transaction. `400 not_checked_in`, `400 rpe_closed` (after `ends_at` + 7 days). No row for the caller: `404` (WEL-1 to WEL-4) | `200` `{session, rpe, rpe_minutes, rpe_logged_at, sore_areas}` (also on an edit) |
| GET | `/api/soreness/` | any user | own rows, newest day first, paged: `{id, logged_on, period, session, body_area, level}` | `200` page |
| POST | `/api/soreness/` | any user | `period` (`morning`, `evening`), optional `logged_on` (default today; not in the future; at most 7 days back), `areas` `[{body_area, level 0-10}]`, each area once, may be empty (an empty list deletes that check-in). Replaces the rows of (`logged_on`, `period`) (WEL-10, WEL-11) | `200` `{period, logged_on, areas, suggestions}` (replace, so never `201`) |
| GET | `/api/soreness/suggestions/` | any user | today's suggestions from all of today's rows, highest level per area, sorted by area (WEL-31) | `200` list of suggestions |
| GET | `/api/sleep/` | any user | own entries, newest first, paged: `{id, sleep_start, sleep_end, source, external_id, created_at}` | `200` page |
| POST | `/api/sleep/` | any user | manual entry: `sleep_start`, `sleep_end`; end after start, at most 24 hours, not after now (WEL-20) | `201` |
| PATCH | `/api/sleep/<id>/` | owner | change a manual entry (same checks on the result). An imported entry is `403` | `200` |
| DELETE | `/api/sleep/<id>/` | owner | manual or imported; a later import of the same `external_id` creates it again (WEL-22) | `204` |
| POST | `/api/sleep/import/` | any user | `records`: up to 500 of `{source (apple_health, health_connect), external_id (1-128), sleep_start, sleep_end}`. Upsert on (`source`, `external_id`); all checked first, one bad record writes nothing and `400` carries `{"records": {"<index>": {field: [errors]}}}`; 501 records is `400` (WEL-21) | `200` `{created, updated}` |
| GET | `/api/exercises/` | any user | the catalogue by name, paged: `{id, name, description, kind, min_soreness, max_soreness, video_url}`. Admins manage it (ACC-7) | `200` page |
| GET | `/api/exercise-assignments/` | any user | own assignments, newest first, paged; `?status=open` (not completed) or `done`; self-picked and coach-sent told apart by `assigned_by` (null = self-picked) (WEL-44) | `200` page |
| POST | `/api/exercise-assignments/` | any user | pick: `exercise` (id), optional `sets`, `reps`, `hold_seconds` (1-999), `due_on` (today or later). An open self-picked assignment of the same exercise is returned instead, unchanged (WEL-33) | `201` new, `200` the open one |
| POST | `/api/exercise-assignments/<id>/complete/` | the assignment's user | sets `completed_at`; checks achievements in the same transaction. Not theirs: `404` (WEL-42, WEL-50) | `200` (also on a repeat, nothing changes) |
| DELETE | `/api/exercise-assignments/<id>/` | the user (own self-picked) or the sending coach | a completed assignment, or a coach-sent one by its user, is `403`. Anyone else `404` (WEL-43) | `204` |
| GET | `/api/me/achievements/` | any user | own, by `earned_at`: `{code, earned_at}` (`first_exercise`, `exercise_streak_7`) | `200` page |
| GET | `/api/players/<user_id>/soreness/`, `/sleep/`, `/exercise-assignments/` | a coach, for one of their players | same bodies as the user's own lists (`?status=` on assignments). Read only (`405` otherwise). Not a player of the caller, or caller not a coach: `404` (TEAM-40) | `200` page |
| POST | `/api/players/<user_id>/exercise-assignments/` | a coach, for one of their players | `exercise`, optional `sets`, `reps`, `hold_seconds`, `due_on` (today or later in the coach's timezone). A shadow player is `400 not_assignable`. Pushes `exercise_assigned` (WEL-40, WEL-41) | `201` assignment |
| POST | `/api/groups/<id>/exercise-assignments/` | the coach of a team | same body. One row per active member who is not a shadow player and not the coach, each with `group` set; each gets a push. Not a coach, not a team, or not its manager: `403` (WEL-40, WEL-41) | `201` list of the rows made (empty if nobody qualifies) |

## Suggestions (WEL-30)

```json
{"body_area": "quads", "level": 5, "exercises": [{"id": 3, "name": "Quad stretch", "kind": "stretch", "...": "..."}]}
```

One entry per sent area with level 1 or more, in the order sent (today's suggestions: by area name). Exercises are those linked to the area whose `min_soreness <= level <= max_soreness`, sorted by name. An area with no matching exercise has `"exercises": []`; level 0 gets no entry. Suggestions are computed, never stored (WEL-32).

## Pushes

`exercise_assigned` goes to each recipient with `data = {"id": <their assignment id>}` (NOTE-14, NOTE-20). Nobody is pushed about their own action.

## Not in this version

- `GET /api/sleep/<id>/` and `GET /api/soreness/<id>/` (the lists carry everything).
- Coach reads of RPE history (RPT-8) belong to the reports task.
