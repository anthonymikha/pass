# Deployment

**Status: planned** (owner's review of 2026-11-20, build step T18). How the compose stack runs in production. Nothing on this page is built yet; until it is, the stack runs only locally.

## Hosts

Two hostnames, both DNS **A records** at GoDaddy pointing at the server's IP. The names come from `.env`, so the domain is never written in the repo.

| Setting | Example | Serves |
|---|---|---|
| `PASS_HOST` | `pass.example.com` | Django: `/api/`, `/admin/`, `/static/`, `/account/` (password reset pages, ACC-32). Later `/` serves the Flutter web build, on the same origin, so the API needs no CORS |
| `FILES_HOST` | `files.example.com` | SeaweedFS S3: the signed upload and playback links (REC-1). It needs its own host because a signed link is tied to the host it was signed for. `STORAGE_PUBLIC_ENDPOINT` = `https://FILES_HOST` |

HTTPS is ended at the reverse proxy; the containers speak plain HTTP inside the compose network.

## Two ways to run it

`docker-compose.yml` stays the base file for local and production. One of two override files is added on a server:

**Behind an existing Traefik** (the owner's server):

```sh
docker compose -f docker-compose.yml -f docker-compose.traefik.yml up -d --build
```

`docker-compose.traefik.yml` adds Traefik labels to `backend` (rule `Host(PASS_HOST)`) and `storage` (rule `Host(FILES_HOST)`), joins both to Traefik's external network, and removes their published host ports (`ports: !reset []`). Traefik's names come from `.env`:

| Setting | Default |
|---|---|
| `TRAEFIK_NETWORK` | `traefik` |
| `TRAEFIK_ENTRYPOINT` | `websecure` |
| `TRAEFIK_CERTRESOLVER` | `letsencrypt` |

**On a server with no proxy:**

```sh
docker compose -f docker-compose.yml -f docker-compose.caddy.yml up -d --build
```

`docker-compose.caddy.yml` adds a `caddy` service on ports 80 and 443 with a short Caddyfile: `PASS_HOST` goes to `backend:8000`, `FILES_HOST` to `storage:8333`, and certificates are automatic. Caddy's data goes in `./data/caddy`.

## Production settings

All from `.env`; `DEBUG=0`.

- `ALLOWED_HOSTS` = `PASS_HOST`; `CSRF_TRUSTED_ORIGINS` = `https://PASS_HOST` (the admin and the reset pages post forms).
- `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`: the proxy ends HTTPS. Secure session and CSRF cookies, HSTS. `manage.py check --deploy` reports nothing.
- `/admin/` stays at `/admin/`, protected by strong passwords only.
- gunicorn runs **3 workers**. The login rate limit (10 a minute per IP) moves to Django's `DatabaseCache`, so the workers share one count. It is one table made by `manage.py createcachetable`, run at start next to `migrate`, and it works on SQLite and Postgres.
- Email: `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`. Brevo's free SMTP at launch. With `EMAIL_HOST` empty, emails are only logged.
- Push: `FCM_CREDENTIALS_FILE`, empty until the Firebase project exists (NOTE-11).

## Storage

- One bucket, as now. Its **CORS** rule allows only `https://PASS_HOST` (methods `GET`, `POST`, `HEAD`), so the Flutter web build can upload and play in the browser. Phones need no CORS.
- Video and avatars are **not backed up** in this version: they are large, and losing a clip loses no money.

## Database backups

A `backup` service in compose runs `pg_dump` once a night into `./data/backups`, one compressed file per day, and deletes files older than 7 days. Copying them off the server is the owner's job for now.

## Start order

`backend` gets a healthcheck (an HTTP request to itself that succeeds once migrations are applied and gunicorn answers). `scheduler` waits for `service_healthy`, so its first tick never runs before migrations (NOTE-30).

## DNS and accounts the owner sets up

1. GoDaddy DNS: A records for `PASS_HOST` and `FILES_HOST` to the server's IP.
2. Brevo: an account, the sending domain verified, and its SPF and DKIM records added at GoDaddy (without them reset emails land in spam). Copy the SMTP login into `.env`.
3. Firebase, for push only: a project, a service-account key file mounted into the `backend` and `scheduler` containers (`FCM_CREDENTIALS_FILE`). For iPhones, also an Apple Developer account and an APNs key uploaded in the Firebase console. Firebase does not host the backend; Firebase Hosting serves static files only.
