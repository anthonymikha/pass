FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# collectstatic needs no DB or real secret; the dummy key exists only during this build step.
RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && useradd --no-create-home app

USER app
EXPOSE 8000
# Deployment: migrations, the shared rate-limit cache table and the bucket's CORS rule first, then 3 workers.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && python manage.py storage_cors && exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 3"]
