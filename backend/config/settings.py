import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DEBUG") == "1"
# No usable default in production: a missing SECRET_KEY fails at startup unless DEBUG=1.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key") if DEBUG else os.environ["SECRET_KEY"]
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "accounts",
    "venues",
    "teams",
    "bookings",
    "billing",
    "wellness",
    "chat",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

if os.environ.get("POSTGRES_DB"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["POSTGRES_DB"],
            "USER": os.environ.get("POSTGRES_USER", ""),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

REST_FRAMEWORK = {
    # ponytail: one non-expiring token per user (logout signs out every device);
    # move to per-device expiring tokens when multi-device sessions matter.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Only views that set throttle_scope are throttled (register/login).
    # ponytail: counters live in per-process memory, so the real limit is rate x gunicorn workers;
    # point CACHES at a shared cache when that matters.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"auth": "10/min"},
    "EXCEPTION_HANDLER": "config.api.exception_handler",  # GEN-1
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",  # GEN-12
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# The Flutter client is generated from this schema (GET /api/schema/).
SPECTACULAR_SETTINGS = {"TITLE": "PASS API", "VERSION": "0.1.0", "SERVE_INCLUDE_SCHEMA": False}

# NOTE-11: path to the Firebase service-account file. Empty = fake sender (logs and records in memory).
FCM_CREDENTIALS_FILE = os.environ.get("FCM_CREDENTIALS_FILE", "")

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# REC-1: S3-compatible object storage (SeaweedFS in docker-compose). Moving to a cloud bucket is a change of these values.
# Empty STORAGE_ENDPOINT = in-memory fake (the test suite, a bare `runserver`); see config/storage.py.
STORAGE_ENDPOINT = os.environ.get("STORAGE_ENDPOINT", "")  # how the backend reaches storage (head, delete)
STORAGE_PUBLIC_ENDPOINT = os.environ.get("STORAGE_PUBLIC_ENDPOINT", STORAGE_ENDPOINT)  # how phones reach it
STORAGE_BUCKET = os.environ.get("STORAGE_BUCKET", "pass")
STORAGE_ACCESS_KEY = os.environ.get("STORAGE_ACCESS_KEY", "")
STORAGE_SECRET_KEY = os.environ.get("STORAGE_SECRET_KEY", "")
STORAGE_REGION = os.environ.get("STORAGE_REGION", "us-east-1")
