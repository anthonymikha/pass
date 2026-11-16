# PASS (Performance Analytics and Sports Solutions)

## Layout

- `backend/` Django project: `config/` (settings, urls) and 7 apps: `accounts`, `venues`, `teams`, `bookings`, `billing`, `wellness`, `chat`. Foreign keys only point to apps earlier in that list.
- `frontend/` placeholder for the Flutter app (web, iOS, Android).
- `docker-compose.yml` Postgres + backend.

- `data/` created by Docker for container data (database files); gitignored, root-owned.

URLs: Django admin at `/admin/`, REST API under `/api/`.

## API

JSON only. Send `Authorization: Token <token>` on every call except register and login (those two are limited to 10 requests a minute per IP).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register/` | `email`, `password`, `full_name` | 201 `{token, user}` |
| POST | `/api/auth/login/` | `email`, `password` | 200 `{token, user}` |
| POST | `/api/auth/logout/` | none | 204; the token stops working on every device |
| GET | `/api/me/` | none | own profile |
| PATCH | `/api/me/` | any of `full_name`, `phone`, `timezone`, `date_of_birth`, `sex`, `height_cm`, `weight_kg`, `nationality`, `dominant_hand`, `is_coach`, `coach_bio`, `coach_rate`, `coach_currency` | updated profile |

## Run with Docker

```sh
cp .env.example .env   # then edit the secrets
docker compose up --build
docker compose exec backend python manage.py createsuperuser
```

Admin: http://localhost:8000/admin/

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
.venv/bin/python manage.py runserver
```

Seed the launch sports, default commission rows and placeholder exercises (safe to run again): `python manage.py seed`.

## Tests

```sh
cd backend && DEBUG=1 .venv/bin/python manage.py test
```
