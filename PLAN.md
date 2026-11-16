# PASS: plan and handoff

PASS (Performance Analytics and Sports Solutions) helps players, coaches, and court/club owners stay organised: court booking, teams, coaching, wellness tracking, session video, chat.

Last updated: 2026-11-16. Written so a new session can continue with no other context.

## Prompt to resume

Paste this into a new session opened in `/home/ubuntu/pass`:

> Read PLAN.md in the repo root in full (start with "Status on 2026-11-16 (latest)"), then `docs/backend/logic/README.md` and every page it lists, then `git log --oneline` and `backend/*/models.py`. The logic pages are the specification and are waiting for my review. Ask me for my review corrections (or approval), apply them to the docs, then build the roadmap from step 2 with Sonnet 5.5 subagents under the acceptance gate in my original brief, without asking again, within the standing permissions listed in the status section.

## Status on 2026-11-16 (latest)

- Schema v5 committed (`62c180b`, `d18e4e0`) and verified on Postgres in Docker (12 tests green). `.env` created locally from `.env.example`.
- Owner answered every open question on 2026-11-16 (all recommendations accepted except discounts, see below). Answers are written into `docs/backend/logic/` (17 pages, rule ids). **Waiting for the owner's review of those pages.** After approval the lead has full authority within the granted permissions: commit, push, pip install, Docker and `./data`, new compose services (`minio`, `scheduler`), migrations, schema changes (`devices`, `chats.club_last_read_at`; `session_participants.rpe_reminded_at` proposed).
- Scope: stop after step 10 (no Flutter).
- Discounts (owner note 18): a discount for one specific session is attached to the session, offer link nullable. Read as: owner sets `sessions.discount_amount` with `sessions.discount` empty (DSC-10). Pending confirmation in review.
- The decisions below marked "Not decided" / "Proposal" are now settled; the logic pages are the record.

## Working agreements

- **Minimal code.** No speculative abstractions, fewest files and dependencies. Deliberate shortcuts get a `# ponytail:` comment naming the ceiling and the upgrade path.
- **Design before code.** Discuss schema or behaviour decisions with the owner first. Do not just agree: give an analysis and a recommendation.
- **As few tables as possible**, while following normal database design standards.
- **Database-agnostic Django.** Postgres in Docker, but no `django.contrib.postgres`, no native enums, no Postgres-only constraints. Without `POSTGRES_DB` set, settings fall back to SQLite.
- **Verification for every step:** `manage.py check`, `makemigrations --check --dry-run`, `manage.py test` on SQLite, then the same tests inside the Docker stack on Postgres, plus a few live `curl` calls.
- **Workflow tests** drive the real endpoints with DRF's `APITestCase` (one test per user journey), in each app's `tests.py`. Schema constraint tests live in `backend/tests.py`.
- **Git:** logical commits, conventional messages (`feat:`, `chore:`, `test:`, `docs:`), no attribution or co-author lines. Standing permission (2026-11-16) to commit and to push to `origin` (private repo) after each accepted step. Never force-push or rewrite pushed history.
- **Subagents:** implementation runs on Sonnet 5.5 subagents (owner brief, 2026-11-16); the lead reviews every diff and runs every check itself.
- **Docs are the specification.** Every business rule lives in `docs/backend/logic/` with a stable id, is reviewed by the owner, and only then implemented. Code never holds a rule the docs lack; a rule found during the build is written into the logic page first ("decided during build").
- **Docker data:** every container's data is a bind mount under `./data/<service>` (gitignored). No named volumes.

## Current state

- Repo: branch `main`. Everything is committed and pushed, including this file (tracked since 2026-11-16). Not in git: `.env` (secrets; recreate from `.env.example`).
- Remote `origin` = `https://github.com/anthonymikha/pass.git`. `main` was pushed on 2026-11-16 (the remote was empty; 13 commits, up to `ed35cca`). Schema v5 is not pushed.
- Stack: Python 3.13, Django 6.1.3, djangorestframework 3.18.3, psycopg 3.3.9, gunicorn 27.0.1, whitenoise 6.12.0, Postgres 18.
- Tests: 12 passing on SQLite (8 schema, 4 accounts API). v5 has not been run on Postgres yet.
- Migrations were deleted and regenerated as one fresh `0001_initial` per app for v5. Any existing database must be recreated (`./data/postgres` did not exist at the time).
- Documentation lives in `docs/` (tracked): model pages, user flows, API pages, Eraser code. Keep it in step with the models.

### Layout

```
backend/            Django project
  config/           settings.py, urls.py, wsgi.py, asgi.py
  accounts/ venues/ teams/ bookings/ billing/ wellness/ chat/
  tests.py          schema constraint tests
  requirements.txt  Dockerfile  .dockerignore  manage.py
frontend/           README placeholder; one Flutter project later (web, iOS, Android)
docker-compose.yml  db (Postgres) + backend; commented stub for the future `web` service
data/               created by Docker, gitignored, root-owned
.env.example        copy to .env
```

### Run and test

```sh
cd backend && DEBUG=1 .venv/bin/python manage.py test        # SQLite
cp .env.example .env && docker compose up --build -d          # full stack on :8000
docker compose exec -T backend python manage.py test          # same tests on Postgres
docker compose down
docker run --rm -v "$PWD":/w alpine rm -rf /w/data            # remove root-owned test data
```

Local commands need `DEBUG=1`; without it a missing `SECRET_KEY` stops startup on purpose. Running `manage.py` locally can leave `backend/db.sqlite3` (ignored); delete it.

## Architecture rules

Seven apps in this order: `accounts`, `venues`, `teams`, `bookings`, `billing`, `wellness`, `chat`.

- **Foreign keys only point to apps earlier in the list.**
- **Models hold data and constraints only.** Every model sets `Meta.db_table` to the plain table name. Value sets are `TextChoices`.
- **Business logic goes in one `services.py` per app** as plain functions. Views and serializers stay thin.
- Later apps may read earlier apps' data.
- **Two deliberate "downward" calls from `bookings`:** booker check-in calls `billing.services.record_payments()`; session confirmed calls `chat.services.post_session_card()`. Explicit calls inside the same transaction, no Django signals. Switch to signals only if that list grows.
- **Back office is the Django admin** (sports, exercise catalogue, commission schedules, marking payments settled).
- Types: money `Decimal(12,3)`; currency 3-letter ISO code; exchange rate `Decimal(18,6)`; percent `Decimal(5,2)`.
- Future front end: a reverse proxy serves the Flutter web build at `/` and forwards `/api/`, `/admin/` and `/static/` to Django on the same origin, so there is no CORS setup.

## Schema v5 (33 tables, source of truth is `backend/*/models.py`)

- **accounts:** `users`, `connections`, `user_blockouts`
- **venues:** `sports`, `clubs`, `club_members`, `club_currencies`, `courts`, `court_sports`, `court_rates`, `court_blockouts`, `equipment`, `price_overrides`, `discounts`
- **teams:** `groups`, `group_members`
- **bookings:** `sessions`, `session_participants`, `session_rentals`, `recordings`, `recording_tags`, `recording_tag_players`
- **billing:** `payments`, `commission_rates`
- **wellness:** `soreness_logs`, `sleep_logs`, `exercises`, `exercise_body_areas`, `exercise_assignments`, `user_achievements`
- **chat:** `chats`, `chat_members`, `messages`

Django adds `users_groups`, `users_user_permissions` and `authtoken_token`.

### What changed from v4 to v5 (2026-11-16)

| Table | Change |
|---|---|
| `users` | Added `date_of_birth`, `sex` (`male`/`female`), `height_cm`, `weight_kg`, `nationality` (2-letter ISO country), `dominant_hand` (`left`/`right`/`both`). All optional, all editable via `PATCH /api/me/`. Height and weight hold the latest value only |
| `user_blockouts` | `weekday`/`on_date` replaced by `starts_on`, `repeat` (`none`/`daily`/`weekly`/`monthly`), `repeat_until`, `reason`. Fields come from the abstract `accounts.Blockout`, which has `occurs_on(date)` |
| `court_blockouts` | **New.** Same shape, for court closures. Replaces the `blocked` session status, which is gone |
| `court_rates` | Unchanged on purpose: rates repeat weekly only; monthly patterns belong to closures |
| `club_members` | New role `player` (registered or subscribed), new `expires_on`. Unique key is now (club, user, role) |
| `groups` | New `coach` (nullable). `owner` stays as creator and administrator |
| `payments` | `paid_at` nullable (empty = still due); `method` empty until paid |
| `sleep_logs` | `source` is `manual`/`apple_health`/`health_connect`; new `external_id`; unique (user, source, external_id) when set; `sleep_end` must be after `sleep_start` |
| `exercise_assignments` | New `sets`, `reps`, `hold_seconds` |

### Business rules agreed (not all are in code yet)

**Users and roles**
- Login is by email and password; no username. Emails are lowercased on save; a blank email is stored as NULL.
- A **shadow player** is a `users` row with no email and an unusable password, with `managed_by` set to the coach. Coaches track attendance for them only.
- Roles are not a column: a coach has `is_coach` true (self-declared in the profile, no approval); an owner is whoever owns a club.
- `connections` covers friends and 1:1 coaching (`type`), with `pending` / `accepted` / `blocked`.
- `club_members` links a user to a club as `coach` (many clubs, or none for freelancers), `staff`, or `player` (registered or subscribed, with optional `expires_on`). Booking a court does not need a membership. Subscription price and contents are not modelled.
- Profile body data (`date_of_birth`, `sex`, `height_cm`, `weight_kg`, `nationality`, `dominant_hand`) is optional. No weight history; add a measurements table if it is ever charted.
- **Block-outs** (users and courts) are one-off or repeat daily, weekly (weekday of `starts_on`) or monthly (day of month of `starts_on`; months without that day are skipped), until `repeat_until` or forever. "Every two weeks" and "first Monday" are not supported; switch to iCalendar RRULE if needed.
- **Teams:** `groups.coach` is who runs training (starts as the owner). Changing coach is one field update; past sessions keep their coach. Not decided: whether the new coach also becomes `owner`.

**Courts, hours and prices**
- A solo court owner is a club with one court. A court can host several sports; the session picks which.
- `court_rates` is both open hours and pricing: a row means "open in this window at this price per slot". Open hours are the union of rows. An `end_time` of 00:00 means end of day.
- Booking is in fixed slots of `courts.slot_minutes`.
- Owner closures and holidays are `court_blockouts` rows. Bookable time = rate windows − court block-outs − non-cancelled sessions.
- `equipment`: `court` empty means shared across the club's courts; set means tied to that court. `rental_price` empty means included for free. Rental availability checking is deferred.

**Currency**
- `clubs.currency` is the base currency; all rates, rental prices and `amount_off` discounts are entered in base.
- `club_currencies` lists other accepted currencies with a club-set `exchange_rate` (units per 1 base).
- Default price in another currency = base price × exchange rate. A `price_overrides` row replaces that with a hand-set price for one rate or one equipment item in one currency.
- The booker picks the currency; the session and its payments snapshot the currency and converted amounts. No FX table; the platform's cut is reported per currency.

**Discounts**
- One table covers targeted offers (`user`), frequent-player discounts (`min_bookings`), court/time promos (`court`, `starts_at`/`ends_at`). The session snapshots `discount` and `discount_amount`.
- Not decided: whether discounts stack. Proposal: apply the single best one.

**Payments and commission**
- No payment gateway yet. A payment row records money that is **due**. When the **booker checks in** to a confirmed session, the payment rows are created with `paid_at` and `method` empty. The payee then marks each one paid (`method = offline`, `paid_at = now`). Not decided: exactly who may mark it paid (assumed: club owner/staff or the coach).
- Each payment has exactly one payee: a club (court fee) or a coach (coach fee). A training session at a club creates both.
- **Coach fee:** `sessions.coach_fee`. If `coach_fee_payer` is set, that user is billed the whole fee. If empty (the default), it is split equally, one payment per accepted team member (not only those who checked in). All shares are created as due at check-in and ticked off one by one.
- `platform_fee` on each payment snapshots our cut. `settled_at` records when the cut was settled with the payee.
- **Commission lookup** (`commission_rates`): one query. Take rows for the payee type with `effective_from` ≤ today and `min_count` ≤ the payee's count; prefer the payee's own override rows over default rows (both ids empty); order newest `effective_from` first, then highest `min_count`; take the first. A new schedule is a full set of rows with a later date. For now each schedule is a single row with `min_count` 0 (flat rate); tiers are a future switch.
- Count used for tiers: coaches = distinct active players (accepted coaching connections plus active members of their teams); clubs = booking volume, counting window not yet decided.

**Sessions, attendance, RPE, video**
- `sessions` covers court bookings and coach training requests (`status = requested`, `coach` set). Closures are not sessions.
- Attendance: `checked_in_at` empty after the session ends is a no-show. Coaches set it for shadow players.
- RPE lives on `session_participants` (`rpe` 1–10, `rpe_minutes`, `rpe_logged_at`). It stays in `bookings`; it would move to `wellness` only if off-app training load is ever logged.
- **Video unlock:** a participant can see a session's recordings only when they checked in and logged RPE.
- Tags: a tag with no players is a whole-team tag; with players it concerns those players.

**Computed, never stored:** revenue, customer and repeat-customer rates, attendance, recovery level, group availability, suggested times, video unlock.

## Decisions on infrastructure

| Topic | Status |
|---|---|
| Sign-in | **Decided:** email + password, DRF token (one non-expiring token per user). |
| Chat delivery | **Decided:** polling first, WebSockets later. |
| Sleep import | **Decided:** Apple Health / Google Health Connect are read on the phone by Flutter; backend only receives logs. |
| Recovery level formula | **Deferred** until the owner meets their partner, a sports expert. Do not invent one. Suggested session times depend on it and are deferred too. |
| Push notifications | Owner wants the platforms' standard services. **Recommended, not yet confirmed:** send both through Firebase Cloud Messaging (it relays to Apple's APNs), one backend integration and one Flutter plugin. Needs a `devices` table (33rd table), a Firebase project and an Apple developer key. |
| Video and avatar storage | **Recommended, not yet confirmed:** S3-compatible object storage from the start, run as a MinIO container in compose with data in `./data/minio`. Phones upload and play back through short-lived signed links, so video never passes through Django. Moving to a cloud bucket later is a settings change. The owner asked whether a plain server directory would do; the answer given was no for video (multi-GB uploads block workers, no seeking). |
| Virtual environments | `backend/.venv` only. Flutter has no virtualenv (SDK is machine-wide, packages in `pubspec.yaml`). |

## Roadmap

### Done

- **Step 0: repo and schema.** Monorepo, Docker, 7 apps, admin, constraint tests.
- **Schema v5** (uncommitted): see the change table above. 33 tables.
- **Step 1: API foundation.** `POST /api/auth/register/`, `POST /api/auth/login/`, `POST /api/auth/logout/`, `GET|PATCH /api/me/`. Register and login are limited to 10 requests/minute per IP (per-process counter). Skipped on purpose: avatar upload (waits for storage), email verification and password reset (no email sending yet), changing email, role permission classes (arrive in step 3).

### Step 2: seed data (approved, not started)

An idempotent `manage.py seed` command (or data migration; command preferred so it can be re-run):
- **Sports:** proposal: padel, tennis, basketball, volleyball, football (5-a-side), pickleball, squash, badminton.
- **Exercises:** a starter catalogue of stretch and mobility exercises, each linked to one or more of the 16 body areas, with `min_soreness`/`max_soreness`.
- **Commission:** one default flat row for clubs and one for coaches (`min_count` 0).

Open questions to ask first:
1. Which sports at launch?
2. Default commission percent for clubs and for coaches (10% was only an example)?
3. Exercise catalogue: write a placeholder set now for the sports expert to review, or wait for their list?

### Step 3: owner setup

- Add default pagination and the first permission classes (club owner, club staff).
- Endpoints for owners: clubs, accepted currencies, courts (with sports), rates, closures (`court_blockouts`, one-off and repeating), equipment, price overrides, discounts, club members (coaches, staff, players with `expires_on`). Everything scoped to clubs the user owns.
- Public: search clubs and courts by sport and location; court detail with included and rentable equipment.
- Validation: rate windows must not overlap for the same court and weekday; currency codes; exchange rate > 0.
- Workflow test: owner registers, creates a club with two currencies, two courts (one multi-sport), day and evening rates, equipment; another user cannot edit any of it; a player can find the court.
- Consider adding an OpenAPI schema (e.g. drf-spectacular) here so the Flutter client can be generated later; decide with the owner.

### Step 4: booking and money (the core slice)

`bookings/services.py`:
- **Free slots** for a court and date: take that weekday's rate windows in the club's timezone, cut into `slot_minutes` slots, remove any overlapping a `court_blockouts` occurrence on that date (`occurs_on`) or a session whose status is not `cancelled`.
- **Price:** for each slot, the override for (rate, currency) if one exists, else base price × exchange rate; currency must be the base or in `club_currencies`. Then apply the discount rule.
- **Book:** in one transaction, lock the court row with `select_for_update()`, re-check overlap (`starts_at < new_end AND ends_at > new_start`), create the session and the booker's participant row.
- **Rentals:** request items with the booking; owner approves or declines.
- **Mark paid:** the payee sets `method` and `paid_at` on a payment; owner view of what is still due.
- **Invites:** invite friends or a group; accept or decline.
- **Check-in:** participant sets `checked_in_at`; if they are the booker, call `billing.services.record_payments(session)` in the same transaction. Must be idempotent.

`billing/services.py`:
- `commission_for(payee)` as described above.
- `record_payments(session)`: court payment to the club (amount = price − discount + approved rentals: proposal), coach payment(s) per the split rule, each with its `platform_fee`, created as due (`paid_at` empty). Rounding remainder of a split goes to the first share.

Owner views: schedule per court and date, revenue per period and currency, customers and repeat-customer rate, attendance per session.

Not decided: whether court bookings confirm instantly when the slot is free (proposal: yes; training requests wait for the coach); how early check-in opens (proposal: 30 minutes before start until the end); how sessions become `completed` (proposal: computed from time, no job).

Workflow test: owner setup → player sees slots → books in a non-base currency with a rental → second player cannot double-book → invite accepted → booker checks in → one due payment with the right amount, currency and platform fee → owner marks it paid → owner sees it in schedule, revenue and attendance.

### Step 5: players, coaches, teams

- Friends: request, accept, block, list. Block-out times CRUD (one-off and repeating).
- Change a team's coach.
- Play groups and teams: create, invite, request to join, accept, leave. Only coaches create teams.
- Shadow players: coach creates, edits, adds to teams, marks attendance.
- Coaching links (1:1) and club affiliation (coach requests, owner approves).
- Coach search; player requests a training session; coach accepts, sets fee and court.
- Coach books a session for a player or a team, choosing single payer or split.
- Availability: free windows for a user or a whole group in a date range (not blocked out, not already in a session).
- Coach views: player attendance and RPE history.
- Workflow tests: play group finds a common free time and books; coach builds a team with a shadow player, books training with a split fee, checks in, payments are split correctly.

### Step 6: wellness (without the recovery score)

- Log RPE after a session (requires check-in; `rpe_minutes` defaults to the session length).
- Soreness check-ins morning, evening and post-session: a list of body area + level.
- Sleep: manual entry plus a bulk endpoint for phone imports. Imports carry `source` and `external_id` and use `update_or_create` on (user, source, external_id), which is already unique. The phone can also send height, weight, date of birth and sex to `PATCH /api/me/`.
- Exercise suggestions: for each sore area, exercises linked to that area whose soreness range contains the level.
- Coach sends exercises to a player or a team (one assignment row per member). Tick off as done. Assignments carry optional `sets`, `reps`, `hold_seconds`.
- Achievements for completed exercises (codes defined in code).
- **Not stored yet:** heart rate, HRV, steps and sleep stages from the health apps. Wait for the sports expert to say which the recovery formula needs.
- **Deferred:** recovery level, suggested play/training times, team recovery view.

### Step 7: recordings

- Storage container and signed upload/playback links (pending the storage decision above).
- Players attach a video to a session they checked into; coaches upload to sessions they coached.
- Viewing follows the unlock rule; the session's coach always sees them.
- Tags: coach creates on sessions they coached, optionally naming players. A player sees tags naming them and whole-team tags in sessions they checked into.
- Avatar upload joins the profile here.

### Step 8: chat (polling)

- Direct chats, a group chat per play group or team, and inquiry chats between a user and a club (owner and staff reply).
- `GET messages?after=<id>` for polling, send, mark read (`last_read_at`), unread counts.
- When a group session is confirmed, post a session card (start and end time, link to the session).

### Step 9: push notifications

- `devices` table (user, token, platform), register and unregister endpoints.
- Sending through Firebase (pending confirmation).
- Triggers: RPE reminder after a session ends, invites, chat messages, owner offers.
- The RPE reminder needs something that runs on a schedule. Proposal: a small management command run every minute by a compose service; a task queue only if that stops being enough.

### Step 10: full pass and publish

All workflow tests on Postgres in Docker, then push (owner's go-ahead required). The first push already happened on 2026-11-16.

### Step 11: Flutter app

One project in `frontend/` for web, iOS and Android; add the `web` service and reverse proxy to compose.

### Later

Recovery score and suggested times, WebSockets for chat, a payment gateway (`payments` gains status and a gateway reference), commission tiers, email verification and password reset, per-device expiring tokens, a shared cache for rate limiting.

## Eraser diagrams

File "PASS - Database Schema v4": https://app.eraser.io/workspace/qn00Arwk1YCFHWdlXAu3

- The diagrams online are still **v4**. The v5 code is in `docs/backend/eraser/` (`overview.eraser` plus one file per app), generated from the Django models. The owner pastes it into Eraser themselves.
- **The full overview diagram is broken:** it was replaced by an older copy from an open browser tab and now renders tables without relationship lines. To fix: have the owner reload the tab, list the file's diagrams to get the current id, then rewrite the overview code.
- Eraser's AI tools are out of free credits; write diagram code directly. Eraser's ERD type has no grouping, hence one diagram per app.
- Regenerate the `.eraser` files whenever the models change (walk `apps.get_models()`, emit one entity per `db_table` and one `a.col > b.id` line per foreign key). `devices` is not in the schema yet.
