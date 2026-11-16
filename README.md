# PASS (Performance Analytics and Sports Solutions)

## Layout

- `backend/` Django project: `config/` (settings, urls) and 7 apps: `accounts`, `venues`, `teams`, `bookings`, `billing`, `wellness`, `chat`. Foreign keys only point to apps earlier in that list.
- `frontend/` placeholder for the Flutter app (web, iOS, Android).
- `docker-compose.yml` Postgres + backend.

- `data/` created by Docker for container data (database files); gitignored, root-owned.

## Run with Docker

```sh
cp .env.example .env   # then edit the secrets
docker compose up --build
docker compose exec backend python manage.py createsuperuser
```

Admin: http://localhost:8000/admin/

## Run locally (SQLite, no Docker)

Without `POSTGRES_DB` set, settings fall back to SQLite. `DEBUG=1` allows a dev-only secret key.

```sh
cd backend
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
export DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

## Tests

```sh
cd backend && DEBUG=1 .venv/bin/python manage.py test
```
