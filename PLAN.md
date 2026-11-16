# PASS: plan and handoff

PASS (Performance Analytics and Sports Solutions) helps players, coaches, and court/club owners stay organised: court booking, teams, coaching, wellness tracking, session video, chat.

Last updated: 2026-11-16. Written so a new session can continue with no other context.

## Prompt to resume

Paste this into a new session opened in the repo root:

> Read PLAN.md in the repo root in full (start with "Status on 2026-11-16 (latest)"), then `docs/backend/logic/README.md` and every page it lists, then `git log --oneline` and `backend/*/models.py`. The logic pages are the approved specification. Steps 2 to 10 are done; the next piece of work is step 11 (Flutter) or whatever the owner asks, within the standing permissions in "Working agreements".

## Status on 2026-11-16 (latest)

- **Roadmap steps 2 to 10 are built** (backend only). 111 tests, green on SQLite and on Postgres in Docker; every step was also exercised with curl against the running stack. Everything is committed and pushed to `origin/main`.
- Owner review done (2026-11-16): note 18 reading (DSC-10 to DSC-14), `rpe_reminded_at` (NOTE-9) and late club-side check-in (PAY-7) approved; every other open item took its recommended default. Rules added or changed during the build are marked *decided during build* on their logic page (search for that phrase).
- Known weakness: on a first start from an empty database the scheduler's first `tick` can run before the backend has applied migrations; it logs a traceback and succeeds a minute later (NOTE-30 allows skipped runs).
- Not done, on purpose: the recovery level and suggested times (deferred to the sports expert), a real Firebase push (no Firebase project yet; the sender is tested with mocks), CORS on the bucket for Flutter web, the Flutter app (step 11).
- Docker on this machine: host port 8000 is taken by another project, so `.env` sets `BACKEND_PORT=8001`.
- `docs/backend/logic/` is the only record of rules; the rule summaries that used to be in this file were removed.
- Next: step 11 (Flutter app), and the sports expert's input for the recovery level and the exercise catalogue.

## Build plan (steps 2 to 10)

Run in this order; tasks on one line run in parallel in separate worktrees.

| # | Task | Apps | Rules | Status |
|---|---|---|---|---|
| T1 | Foundation: error shape with `code`, pagination, strict timestamps, `round_money`, `devices` + `notify()` with fake sender, OpenAPI schema | config, accounts | GEN-1 to GEN-18, NOTE-1 to NOTE-3, NOTE-11 to NOTE-14 | done |
| T2 / T3 / T4 | Seed (step 2) / owner setup (step 3) / friends, coaching links, block-outs, shadow players (step 5 part 1) | wellness command / venues / accounts | SEED / CLUB, PRC-1 to PRC-3 / TEAM-1 to TEAM-15, ACC-10 to ACC-13 | done |
| T5 | Groups and teams, group chat sync, user and coach search (step 5 part 2) | teams, chat services | TEAM-20 to TEAM-40, ACC-20 to ACC-23 | done |
| T6 | Slots, prices, offers, court booking, invites, rentals, cancel (step 4 part 1) | bookings | AVL-1 to AVL-12, PRC-4 to PRC-12, DSC-1 to DSC-8, BOOK-1 to BOOK-17, BOOK-40 to BOOK-66, CHAT-30, CHAT-31 | done |
| T7 | Training requests, coach-booked training, personal and group availability (step 5 part 3) | bookings | BOOK-20 to BOOK-33, AVL-20 to AVL-25 | done |
| T8 | Check-in, payments, commission, mark paid, one-off discount, reports (step 4 part 2) | bookings, billing | PAY, COM, DSC-10 to DSC-14, RPT | done |
| T9 / T10 / T11 | Wellness (step 6) / recordings, storage, avatars (step 7) / chat (step 8) | wellness / bookings, accounts / chat | WEL / REC / CHAT | done |
| T12 | Scheduler, RPE reminder, FCM sender, trigger audit (step 9) | accounts, bookings, compose | NOTE-9, NOTE-10, NOTE-20, NOTE-30, NOTE-31 | done |
| T13 | Full pass (step 10): both databases, docs, Eraser, PLAN | all | | done |

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

- Repo: branch `main`, committed and pushed to `origin` (`https://github.com/anthonymikha/pass.git`, private). Not in git: `.env` (secrets; recreate from `.env.example` with fresh random values).
- Stack: Python 3.13, Django 6.1.3, djangorestframework 3.18.3, drf-spectacular 0.30.0, boto3 1.44.3, google-auth 2.62.2, requests 2.34.2, psycopg 3.3.9, gunicorn 27.0.1, whitenoise 6.12.0, Postgres 18, SeaweedFS 4.52 (S3 storage). All pinned in `backend/requirements.txt` and `docker-compose.yml`.
- Tests: 111 (schema constraints in `backend/tests.py`, workflow tests in each app's `tests.py`), green on SQLite and Postgres.
- Migrations: `0001_initial` per app plus `accounts/0002` (devices), `chat/0002` (`club_last_read_at`), `bookings/0002` (`rpe_reminded_at`).
- API: one page per app in `docs/backend/api/`; OpenAPI schema at `GET /api/schema/` (no warnings).
- Documentation lives in `docs/` (tracked): logic pages (the specification), model pages, flows, API pages, Eraser code. Keep it in step with the code.

### Layout

```
backend/            Django project
  config/           settings.py, urls.py, wsgi.py, asgi.py
  accounts/ venues/ teams/ bookings/ billing/ wellness/ chat/
  tests.py          schema constraint tests
  requirements.txt  Dockerfile  .dockerignore  manage.py
frontend/           README placeholder; one Flutter project later (web, iOS, Android)
docker-compose.yml  db (Postgres), storage + storage-init (SeaweedFS S3), backend, scheduler (tick every 60 s); commented stub for the future `web` service
data/               created by Docker, gitignored, root-owned
.env.example        copy to .env
```

### Run and test

```sh
cd backend && DEBUG=1 .venv/bin/python manage.py test        # SQLite
cp .env.example .env && docker compose up --build -d          # full stack on :8000 (BACKEND_PORT), storage on :9000
docker compose exec -T backend python manage.py seed          # sports, default commission, placeholder exercises
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
- **Deliberate "downward" calls:** booker check-in calls `billing.services.record_payments()`; session confirmed calls `chat.services.post_session_card()`; group changes call `chat.services` to keep the group chat in step. Push sending lives in `accounts`. Full list: `docs/backend/README.md`. Explicit calls inside the same transaction, no Django signals.
- **Back office is the Django admin** (sports, exercise catalogue, commission schedules, marking payments settled).
- Types: money `Decimal(12,3)`; currency 3-letter ISO code; exchange rate `Decimal(18,6)`; percent `Decimal(5,2)`.
- Future front end: a reverse proxy serves the Flutter web build at `/` and forwards `/api/`, `/admin/` and `/static/` to Django on the same origin, so there is no CORS setup.

## Schema (34 tables, source of truth is `backend/*/models.py`)

- **accounts:** `users`, `connections`, `user_blockouts`, `devices`
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

v5 plus three columns or tables approved at review: `devices` (NOTE-1), `chats.club_last_read_at` (CHAT-11), `session_participants.rpe_reminded_at` (NOTE-9).

## Decisions on infrastructure

| Topic | Status |
|---|---|
| Sign-in | **Decided:** email + password, DRF token (one non-expiring token per user). |
| Chat delivery | **Decided:** polling first, WebSockets later. |
| Sleep import | **Decided:** Apple Health / Google Health Connect are read on the phone by Flutter; backend only receives logs. |
| Recovery level formula | **Deferred** until the owner meets their partner, a sports expert. Do not invent one. Suggested session times depend on it and are deferred too. |
| Push notifications | **Built:** Firebase Cloud Messaging HTTP v1 (relays to Apple's APNs), behind `FCM_CREDENTIALS_FILE`; without it a fake sender logs pushes. Still needed from the owner: a Firebase project (service-account file, mounted into the backend and scheduler containers) and an Apple developer key uploaded to Firebase. |
| Video and avatar storage | **Decided:** S3-compatible object storage; built with SeaweedFS in compose (`./data/storage`) because MinIO stopped publishing images (REC-1). Phones upload and play back through short-lived signed links, so video never passes through Django. Moving to a cloud bucket later is a settings change. The owner asked whether a plain server directory would do; the answer given was no for video (multi-GB uploads block workers, no seeking). |
| Virtual environments | `backend/.venv` only. Flutter has no virtualenv (SDK is machine-wide, packages in `pubspec.yaml`). |

## Roadmap

### Done

- **Step 0: repo and schema.** Monorepo, Docker, 7 apps, admin, constraint tests.
- **Schema v5**: see the change table above.
- **Step 1: API foundation.** `POST /api/auth/register/`, `POST /api/auth/login/`, `POST /api/auth/logout/`, `GET|PATCH /api/me/`. Register and login are limited to 10 requests/minute per IP (per-process counter). Skipped on purpose: avatar upload (waits for storage), email verification and password reset (no email sending yet), changing email, role permission classes (arrive in step 3).

### Step 2: seed data (done 2026-11-16: `manage.py seed`, SEED-1 to SEED-3)

An idempotent `manage.py seed` command (or data migration; command preferred so it can be re-run):
- **Sports:** proposal: padel, tennis, basketball, volleyball, football (5-a-side), pickleball, squash, badminton.
- **Exercises:** a starter catalogue of stretch and mobility exercises, each linked to one or more of the 16 body areas, with `min_soreness`/`max_soreness`.
- **Commission:** one default flat row for clubs and one for coaches (`min_count` 0).

Open questions to ask first:
1. Which sports at launch?
2. Default commission percent for clubs and for coaches (10% was only an example)?
3. Exercise catalogue: write a placeholder set now for the sports expert to review, or wait for their list?

### Step 3: owner setup (done 2026-11-16: `backend/venues/`, CLUB-1 to CLUB-33)

- Add default pagination and the first permission classes (club owner, club staff).
- Endpoints for owners: clubs, accepted currencies, courts (with sports), rates, closures (`court_blockouts`, one-off and repeating), equipment, price overrides, discounts, club members (coaches, staff, players with `expires_on`). Everything scoped to clubs the user owns.
- Public: search clubs and courts by sport and location; court detail with included and rentable equipment.
- Validation: rate windows must not overlap for the same court and weekday; currency codes; exchange rate > 0.
- Workflow test: owner registers, creates a club with two currencies, two courts (one multi-sport), day and evening rates, equipment; another user cannot edit any of it; a player can find the court.
- Consider adding an OpenAPI schema (e.g. drf-spectacular) here so the Flutter client can be generated later; decide with the owner.

### Step 4: booking and money (done 2026-11-16: `backend/bookings/`, `backend/billing/`)

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

Settled (logic pages): court bookings confirm instantly (BOOK-9), check-in opens 30 minutes before the start (PAY-1), `completed` is computed (BOOK-55).

Workflow test: owner setup → player sees slots → books in a non-base currency with a rental → second player cannot double-book → invite accepted → booker checks in → one due payment with the right amount, currency and platform fee → owner marks it paid → owner sees it in schedule, revenue and attendance.

### Step 5: players, coaches, teams (done 2026-11-16: `backend/accounts/`, `backend/teams/`, training in `backend/bookings/`)

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

### Step 6: wellness (done 2026-11-16: `backend/wellness/`; recovery score still deferred)

- Log RPE after a session (requires check-in; `rpe_minutes` defaults to the session length).
- Soreness check-ins morning, evening and post-session: a list of body area + level.
- Sleep: manual entry plus a bulk endpoint for phone imports. Imports carry `source` and `external_id` and use `update_or_create` on (user, source, external_id), which is already unique. The phone can also send height, weight, date of birth and sex to `PATCH /api/me/`.
- Exercise suggestions: for each sore area, exercises linked to that area whose soreness range contains the level.
- Coach sends exercises to a player or a team (one assignment row per member). Tick off as done. Assignments carry optional `sets`, `reps`, `hold_seconds`.
- Achievements for completed exercises (codes defined in code).
- **Not stored yet:** heart rate, HRV, steps and sleep stages from the health apps. Wait for the sports expert to say which the recovery formula needs.
- **Deferred:** recovery level, suggested play/training times, team recovery view.

### Step 7: recordings (done 2026-11-16: storage in `backend/config/storage.py`, SeaweedFS in compose)

- Storage container and signed upload/playback links (SeaweedFS, REC-1).
- Players attach a video to a session they checked into; coaches upload to sessions they coached.
- Viewing follows the unlock rule; the session's coach always sees them.
- Tags: coach creates on sessions they coached, optionally naming players. A player sees tags naming them and whole-team tags in sessions they checked into.
- Avatar upload joins the profile here.

### Step 8: chat (done 2026-11-16: `backend/chat/`)

- Direct chats, a group chat per play group or team, and inquiry chats between a user and a club (owner and staff reply).
- `GET messages?after=<id>` for polling, send, mark read (`last_read_at`), unread counts.
- When a group session is confirmed, post a session card (start and end time, link to the session).

### Step 9: push notifications (done 2026-11-16: `devices`, FCM sender, `tick` and the `scheduler` service)

- `devices` table (user, token, platform), register and unregister endpoints.
- Sending through Firebase (built; needs the owner's Firebase project to go live).
- Triggers: RPE reminder after a session ends, invites, chat messages, owner offers.
- The RPE reminder needs something that runs on a schedule. Proposal: a small management command run every minute by a compose service; a task queue only if that stops being enough.

### Step 10: full pass and publish (done 2026-11-16)

All workflow tests on Postgres in Docker from an empty `./data`, docs and Eraser regenerated, pushed.

### Step 11: Flutter app

One project in `frontend/` for web, iOS and Android; add the `web` service and reverse proxy to compose.

### Later

Recovery score and suggested times, WebSockets for chat, a payment gateway (`payments` gains status and a gateway reference), commission tiers, email verification and password reset, per-device expiring tokens, a shared cache for rate limiting.

## Eraser diagrams

File "PASS - Database Schema v4": https://app.eraser.io/workspace/qn00Arwk1YCFHWdlXAu3

- The diagrams online are still **v4**. The current code is in `docs/backend/eraser/` (`overview.eraser` plus one file per app), generated from the Django models by `docs/backend/eraser/generate.py`. The owner pastes it into Eraser themselves.
- **The full overview diagram is broken:** it was replaced by an older copy from an open browser tab and now renders tables without relationship lines. To fix: have the owner reload the tab, list the file's diagrams to get the current id, then rewrite the overview code.
- Eraser's AI tools are out of free credits; write diagram code directly. Eraser's ERD type has no grouping, hence one diagram per app.
- Regenerate the `.eraser` files whenever the models change: from `backend/`, `DEBUG=1 .venv/bin/python manage.py shell < ../docs/backend/eraser/generate.py`.
