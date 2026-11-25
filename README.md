# PASS (Performance Analytics and Sports Solutions)

## Layout

- `backend/` Django project: `config/` (settings, urls) and 7 apps: `accounts`, `venues`, `teams`, `bookings`, `billing`, `wellness`, `chat`. Foreign keys only point to apps earlier in that list.
- `frontend/` the web app (Flutter web, pass_v1's design): [docs/frontend](docs/frontend/README.md). `scripts/flutter.sh` runs Flutter in Docker; `docker/` holds its image.
- `scripts/autoupdate.sh` pulls and rebuilds the stack on a server when `origin` has new commits ([deployment](docs/deployment.md#auto-update)).
- `docker-compose.yml` Postgres, object storage, backend (which also serves the web app), scheduler and nightly backup; `docker-compose.traefik.yml` and `docker-compose.caddy.yml` add a reverse proxy on a server ([deployment](docs/deployment.md)).

- `data/` created by Docker for container data (database files); gitignored, root-owned.

URLs: the web app at `/`, Django admin at `/admin/`, REST API under `/api/`.

## API

JSON only. Send `Authorization: Token <token>` on every call except register, login and password reset (those three share a limit of 10 requests a minute per IP).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register/` | `email`, `password`, `full_name` | 201 `{token, user}` |
| POST | `/api/auth/login/` | `email`, `password` | 200 `{token, user}` |
| POST | `/api/auth/logout/` | optional `device_token` | 204; forgets that device only, the token keeps working (ACC-31) |
| POST | `/api/auth/password-reset/` | `email` | 200, the same answer for any email; an account gets a link to `/account/reset/<uid>/<token>/` (ACC-32) |
| GET | `/api/me/` | none | own profile |
| PATCH | `/api/me/` | any of `full_name`, `phone`, `timezone`, `date_of_birth`, `sex`, `height_cm`, `weight_kg`, `nationality`, `dominant_hand`, `is_coach`, `coach_bio`, `coach_rate`, `coach_currency` | updated profile |
| DELETE | `/api/me/` | `password` | 204; the account is deactivated and scrubbed (ACC-33); `400 owns_club` for a club owner |

## Run with Docker

```sh
cp .env.example .env   # then edit the secrets; for a local stack on plain http also set HTTPS=0 and PASS_HOST=localhost:8000
docker compose up --build
docker compose exec backend python manage.py createsuperuser
```

App: http://localhost:8000/ (the backend image builds it; the first build downloads the Flutter image and takes a few minutes). Admin: http://localhost:8000/admin/. On start the backend runs `migrate`, `createcachetable` (the shared rate-limit cache) and `storage_cors`, then gunicorn with 3 workers; the scheduler waits until the backend is healthy. The `backup` service writes one `pg_dump` a day to `./data/backups` and keeps 7 days. On a server, follow [docs/deployment.md](docs/deployment.md).

### Scheduler and push notifications

The `scheduler` service runs `python manage.py tick` every 60 seconds with the backend image (it never migrates). A tick bills the sessions whose check-in has closed (PAY-10, NOTE-33), then sends the RPE reminders (NOTE-31). To run it once by hand: `docker compose exec backend python manage.py tick`.

Pushes go through Firebase when `FCM_CREDENTIALS_FILE` (a service-account JSON, mounted into the backend and scheduler containers) is set; otherwise they are only written to the log.

### File storage (SeaweedFS, S3 API)

Recordings and avatars live in one S3 bucket served by SeaweedFS (`storage` service); data is kept in `./data/storage`. The `storage-init` step creates the bucket on every start (safe to repeat). MinIO was the plan, but it no longer publishes container images.

- S3 endpoint: http://localhost:9000 (`STORAGE_PORT`). Phones upload to and play from this address, so `STORAGE_PUBLIC_ENDPOINT` in `.env` must use the same host and port.
- Keys: `STORAGE_ACCESS_KEY` and `STORAGE_SECRET_KEY` from `.env`. Tests never touch it (they use an in-memory fake).
- Moving to a cloud bucket later only changes the `STORAGE_*` values.
- With `STORAGE_ENDPOINT` empty (a local run without Docker, and the test suite) an in-memory fake is used and nothing is really stored.

## Run locally (SQLite, no Docker)

Without `POSTGRES_DB` set, settings fall back to SQLite. `DEBUG=1` allows a dev-only secret key.

```sh
cd backend
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createcachetable   # the rate limit's cache table
.venv/bin/python manage.py runserver
```

Padel, Tennis, Basketball and Pickleball exist after `migrate` (CLUB-36). Seed the other launch sports, default commission rows and placeholder exercises (safe to run again): `python manage.py seed`.

## Tests

```sh
cd backend && DEBUG=1 .venv/bin/python manage.py test
scripts/flutter.sh analyze && scripts/flutter.sh test     # the web app, in Docker
```
