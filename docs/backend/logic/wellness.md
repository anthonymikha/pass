# Wellness (WEL)

**Status: built** (`backend/wellness/`, API page [wellness](../api/wellness.md)); recovery level and suggested times stay deferred. RPE after sessions, soreness check-ins, sleep, exercise suggestions and coach assignments, achievements.

> **Deferred to the owner's sports-expert partner, not designed here:** the **recovery level** formula and **suggested play and training times** (for a player, a group or a team). No code computes, stores or approximates them. Heart rate, HRV, steps and sleep stages are not stored until that formula says which are needed.

## RPE after a session

**WEL-1.** Who may: a participant, for their own row only. Preconditions: the row has `checked_in_at`; the session is `confirmed`; now ≤ `ends_at + 7 days`. Shadow players never log RPE (they cannot sign in).

**WEL-2.** Input: `rpe` (whole number 1–10), optional `rpe_minutes` (1–600; default = the session's length in minutes, rounded down), optional `sore_areas`: a list of `body_area` + `level` (0–10), each area at most once.

**WEL-3.** Writes, in one transaction: `rpe`, `rpe_minutes`, `rpe_logged_at` = now on the participant row; and replaces the user's `post_session` soreness rows for this session with one row per listed area (`period = post_session`, `session` set, `logged_on` = the session's start date in the user's timezone). Submitting again inside the window replaces both (an edit). `rpe_logged_at` is updated on every submit.

**WEL-4.** Errors: session not `confirmed` (cancelled) `400 invalid_status` (*decided during build, 2026-11-16*, same code as PAY-5); not checked in `400 not_checked_in`; window over `400 rpe_closed`; bad values `400` per field.

**WEL-5.** Logging RPE is what unlocks the session's video for that participant (REC-20).

## Soreness check-ins

**WEL-10.** Who may: a user, for themselves. Input: `period` (`morning` or `evening`), optional `logged_on` (default today in the user's timezone; not in the future; at most 7 days back), `areas`: a list of `body_area` + `level` (0–10), each area at most once, may be empty.

**WEL-11.** Writes: replaces the user's rows for (`logged_on`, `period`) with one row per listed area. An empty list deletes that check-in's rows. Areas not listed are not sore.

**WEL-12.** The response includes the suggestions of WEL-30 for the areas just sent.

## Sleep

**WEL-20.** **Manual entry.** A user, for themselves: `sleep_start`, `sleep_end`; `sleep_end` after `sleep_start`, at most 24 hours long, `sleep_end` not after now. Stored with `source = manual`, `external_id` empty. The user may change or delete their manual rows.

**WEL-21.** **Phone import.** A user, for themselves: a list of up to 500 records, each with `source` (`apple_health` or `health_connect`), `external_id` (1–128 characters), `sleep_start`, `sleep_end` (same checks as WEL-20). Each record is upserted on (user, `source`, `external_id`): new rows are created, existing rows get the new times. The whole list is checked first; if any record is invalid nothing is written and the response says which (`400`, errors by list index). Response: `created` and `updated` counts.

**WEL-22.** Imported rows can be deleted by the user; a later import with the same `external_id` creates them again.

**WEL-23.** Profile data from the phone (height, weight, date of birth, sex) is sent to `PATCH /api/me/` like any profile edit.

## Exercise suggestions

**WEL-30.** For a set of (area, level) pairs: for each pair with level ≥ 1, the exercises linked to that area (`exercise_body_areas`) with `min_soreness ≤ level ≤ max_soreness`. Grouped by area, each group sorted by exercise name. Level 0 gets no suggestions. An area with no matching exercise returns an empty list; the app shows "rest; ask your coach" (placeholder text until the sports expert reviews it).

**WEL-31.** **Suggestions for today** (on request): built from the user's soreness rows dated today (user timezone), all periods, using the highest level per area.

**WEL-32.** Suggestions are computed and not stored. A suggestion becomes an `exercise_assignments` row only when the user picks it (WEL-33).

**WEL-33.** **Pick.** A user adds an exercise for themselves: an assignment with `assigned_by` empty, `group` empty, optional `sets`, `reps`, `hold_seconds` (each 1–999), optional `due_on` (today or later). If the user already has an uncompleted self-picked assignment of the same exercise, that one is returned instead (`200`).

## Coach assignments

**WEL-40.** Who may: a coach, to one of the coach's players (ACC-1), or to a team the coach manages. Input: `exercise`, target (`user` or `group`), optional `sets`, `reps`, `hold_seconds` (1–999), `due_on` (today or later, coach's timezone).

**WEL-41.** To a team: one row per active member who is not a shadow player and not the coach, each with `group` set and `assigned_by` = coach. To one player: one row, `group` empty. Shadow players cannot receive assignments (`400 not_assignable`). Each recipient is notified (NOTE-20).

**WEL-42.** **Complete.** The assignment's user sets `completed_at` = now. Already completed: no change (GEN-5). There is no "undo".

**WEL-43.** **Delete.** The user may delete their own self-picked assignments. The assigning coach may delete an assignment they sent while it is not completed. Completed assignments stay.

**WEL-45.** *Decided during build (2026-11-16):* a completed assignment is never deleted by anyone (WEL-43 "completed assignments stay"); trying is `403`. A user cannot delete a coach-sent assignment (`403`). Imported sleep rows (WEL-22) can be deleted but not changed (`403`). Users read their own soreness and sleep logs, assignments and achievements (ACC-4), and any user may read the exercise catalogue (needed to pick and assign).

**WEL-44.** A user sees all their assignments in one list (self-picked and coach-sent, told apart by `assigned_by`), filter `open` (not completed) or `done`.

## Achievements

**WEL-50.** Checked when an assignment is completed (WEL-42), in the same transaction. Each is earned once per user (`user_achievements` is unique per user and code); `earned_at` = now.

| Code | Earned when |
|---|---|
| `first_exercise` | the user's first completed assignment |
| `exercise_streak_7` | the user has completed at least one assignment on each of the 7 local dates ending today (user timezone), today included |

**WEL-51.** Achievement codes and conditions live in code only, exactly as in this table. A new achievement is added to this table first.

## Edge cases

- **Two sessions on one day:** post-session soreness rows carry `session`, so they stay apart (WEL-3).
- **A phone syncs the same night twice:** the second sync updates the row (WEL-21).
- **Streak across a timezone change:** dates are taken in the user's timezone at the moment of checking; earlier completions are re-read in the new timezone.
- **Coach sends to a team, then a player leaves:** their assignment stays theirs.

## Deferred

- Recovery level and suggested times: deferred to the sports expert (see the top of this page).
- TEAM-40 lets a coach read a player's sleep logs; revisit with the sports expert.
