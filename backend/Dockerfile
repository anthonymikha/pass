# One image (FE-13): the Flutter web build (stage 1) served by Django + WhiteNoise + gunicorn (stage 2).
# Build context: the repository root.

# ---- Stage 1: Flutter web build (the same pinned SDK as scripts/flutter.sh) ----
FROM ghcr.io/cirruslabs/flutter:3.35.7 AS web
RUN git config --system --add safe.directory '*'
WORKDIR /src/frontend
# Dependencies first so the layer is cached until pubspec changes.
COPY frontend/pubspec.yaml frontend/pubspec.lock ./
RUN flutter --no-version-check --suppress-analytics pub get --enforce-lockfile
COPY frontend/ ./
# No CDN (the app asks no other host) and no service worker (a deploy shows on the next load).
RUN flutter --no-version-check --suppress-analytics pub get --enforce-lockfile --offline \
 && flutter --no-version-check --suppress-analytics build web --release --no-web-resources-cdn --pwa-strategy=none

# ---- Stage 2: runtime ----
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FRONTEND_DIR=/app/frontend_build
WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY --from=web /src/frontend/build/web /app/frontend_build
# Pre-compress the web app (.br and .gz next to each file); WhiteNoise serves them to browsers that accept them.
# collectstatic needs no DB or real secret; the dummy key exists only during this build step.
RUN python -m whitenoise.compress /app/frontend_build \
    && SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && useradd --no-create-home app

USER app
EXPOSE 8000
# Deployment: migrations, the shared rate-limit cache table and the bucket's CORS rule first, then 3 workers.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && python manage.py storage_cors && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3"]
