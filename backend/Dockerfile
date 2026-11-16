FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# collectstatic needs no DB or real secret; the dummy key exists only during this build step.
RUN SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput \
    && useradd --no-create-home app \
    && mkdir media && chown app media

USER app
EXPOSE 8000
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi --bind 0.0.0.0:8000"]
