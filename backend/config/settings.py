import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DEBUG") == "1"
# No usable default in production: a missing SECRET_KEY fails at startup unless DEBUG=1.
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key") if DEBUG else os.environ["SECRET_KEY"]
# Deployment: the public host name of the API (also ACC-32's reset links). Set in .env; the domain is never in the repo.
PASS_HOST = os.environ.get("PASS_HOST", "localhost:8000")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", PASS_HOST.split(":")[0]).split(",")
CSRF_TRUSTED_ORIGINS = [f"https://{PASS_HOST}"]  # the admin and the password reset pages post forms

# On a server the reverse proxy (Traefik or Caddy) ends HTTPS, redirects plain http to https, and says so in
# X-Forwarded-Proto. HTTPS=0 only for a local stack on plain http (secure cookies would never come back).
HTTPS = os.environ.get("HTTPS", "0" if DEBUG else "1") == "1"
# The proxy already redirects http to https; a second redirect here would also catch the healthcheck and the test client.
SILENCED_SYSTEM_CHECKS = ["security.W008"]
if HTTPS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True  # only takes effect if the owner submits the domain to the preload list

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
    # ponytail: one non-expiring token per user (ACC-30: logout keeps it; a password reset or deleting the account
    # signs out every device); move to per-device expiring tokens when "sign out everywhere" matters.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.TokenAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    # Only views that set throttle_scope are throttled (register, login, password reset). The counters live in the
    # shared DatabaseCache below, so the gunicorn workers count together.
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.ScopedRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"auth": "10/min"},
    "EXCEPTION_HANDLER": "config.api.exception_handler",  # GEN-1
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",  # GEN-12
    "PAGE_SIZE": 50,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# Deployment: one table (`manage.py createcachetable`, run at start next to `migrate`) shared by the gunicorn workers.
# ponytail: a database round-trip per throttled request; move to Redis if login traffic ever matters.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "cache"}}

# The Flutter client is generated from this schema (GET /api/schema/).
SPECTACULAR_SETTINGS = {
    "TITLE": "PASS API",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Several models have fields named status / type / kind; name each value set so the generated client is stable.
    "ENUM_NAME_OVERRIDES": {
        "ConnectionStatusEnum": "accounts.models.Connection.Status",
        "ConnectionTypeEnum": "accounts.models.Connection.Type",
        "ClubMemberStatusEnum": "venues.models.ClubMember.Status",
        "GroupTypeEnum": "teams.models.Group.Type",
        "GroupMemberStatusEnum": "teams.models.GroupMember.Status",
        "SessionStatusEnum": "bookings.models.Session.Status",
        "SessionKindEnum": "bookings.models.Session.Kind",
        "ParticipantStatusEnum": "bookings.models.SessionParticipant.Status",
        "RentalStatusEnum": "bookings.models.SessionRental.Status",
        "ExerciseKindEnum": "wellness.models.Exercise.Kind",
        "ChatTypeEnum": "chat.models.Chat.Type",
    },
}

# ACC-32: the reset link (https://PASS_HOST/account/reset/...) is valid 1 hour.
PASSWORD_RESET_TIMEOUT = 3600

# Email (ACC-32): SMTP from .env (Brevo at launch). EMAIL_HOST empty = emails are written to the log (stdout).
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_BACKEND = ("django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
                 else "django.core.mail.backends.console.EmailBackend")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"  # STARTTLS on 587
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "PASS <no-reply@localhost>")

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
