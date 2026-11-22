"""eventcalendar settings. Everything that differs between machines comes from the environment (.env)."""
from pathlib import Path
import os

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    return default if v is None else v.strip().lower() in ("1", "true", "yes", "on")


def env_list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in env(name, default).split(",") if x.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("dev-insecure-key" if DEBUG else "")
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is not set")

# Sites are resolved from the Host header against portals.SiteDomain; this list is the outer gate.
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "unfold",
    "unfold.contrib.filters",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.core",
    "apps.portals",
    "apps.geo",
    "apps.catalog",
    "apps.intake",
    "apps.organizers",
    "apps.subscriptions",
    "apps.audit",
    "apps.public",
    "apps.feedback",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.portals.middleware.CurrentSiteMiddleware",
    "apps.core.middleware.AdminLanguageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL", "postgres://eventcalendar:eventcalendar@localhost:5432/eventcalendar"),
        conn_max_age=60,
    )
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]

# Interface languages (spec §3 «Локализация»): Ukrainian is the default.
LANGUAGE_CODE = "uk"
LANGUAGES = [("uk", "Українська"), ("en", "English"), ("pl", "Polski")]
LOCALE_PATHS = [BASE_DIR / "locale"]
# The moderation admin is in Russian (the owner's choice); the public site stays uk / en / pl.
ADMIN_LANGUAGE = "ru"
USE_I18N = True
TIME_ZONE = "Europe/Kyiv"
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Background jobs
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_TIMEZONE = TIME_ZONE

# Cache: rate limits for public forms. Redis in production, memory locally / in tests.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
          if env("REDIS_URL") else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Intake API: max items in one POST
INTAKE_MAX_BATCH = int(env("INTAKE_MAX_BATCH", "200"))

# Security behind Caddy
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
}

# Django 6 default; silences the transitional warning
FORMS_URLFIELD_ASSUME_HTTPS = True

# ── Admin look (django-unfold) ─────────────────────────────────────────────
from django.templatetags.static import static  # noqa: E402
from django.urls import reverse_lazy  # noqa: E402

UNFOLD = {
    "SITE_TITLE": "EventCalendar",
    "SITE_HEADER": "EventCalendar",
    "SITE_SUBHEADER": "модерация",
    "SITE_SYMBOL": "calendar_month",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "STYLES": [lambda request: static("admin_extra/admin.css")],
    "SHOW_VIEW_ON_SITE": False,
    "DASHBOARD_CALLBACK": "apps.core.dashboard.dashboard_callback",
    "COLORS": {
        "primary": {"50": "oklch(97.7% .014 308.299)", "100": "oklch(94.6% .033 307.174)",
                    "200": "oklch(90.2% .063 306.703)", "300": "oklch(82.7% .119 306.383)",
                    "400": "oklch(71.4% .203 305.504)", "500": "oklch(62.7% .265 303.9)",
                    "600": "oklch(55.8% .288 302.321)", "700": "oklch(49.6% .265 301.924)",
                    "800": "oklch(43.8% .218 303.724)", "900": "oklch(38.1% .176 304.987)",
                    "950": "oklch(29.1% .149 302.717)"},
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": False,
        "navigation": [
            {"title": "Модерация", "items": [
                {"title": "Обзор", "icon": "dashboard", "link": reverse_lazy("admin:index")},
                {"title": "Очередь модерации", "icon": "pending_actions",
                 "link": lambda request: reverse_lazy("admin:catalog_event_changelist") + "?state__exact=pending"},
                {"title": "Все события", "icon": "event", "link": reverse_lazy("admin:catalog_event_changelist")},
                {"title": "Предложенные изменения", "icon": "difference",
                 "link": reverse_lazy("admin:catalog_eventrevision_changelist")},
                {"title": "Записи импорта", "icon": "input", "link": reverse_lazy("admin:intake_intakeitem_changelist")},
                {"title": "Сообщения об ошибках", "icon": "report",
                 "link": reverse_lazy("admin:feedback_errorreport_changelist")},
            ]},
            {"title": "Справочники", "items": [
                {"title": "Типы событий", "icon": "category", "link": reverse_lazy("admin:catalog_eventtype_changelist")},
                {"title": "Тематики", "icon": "sell", "link": reverse_lazy("admin:catalog_topic_changelist")},
                {"title": "Города", "icon": "location_city", "link": reverse_lazy("admin:geo_city_changelist")},
                {"title": "Регионы", "icon": "map", "link": reverse_lazy("admin:geo_region_changelist")},
                {"title": "Страны", "icon": "public", "link": reverse_lazy("admin:geo_country_changelist")},
            ]},
            {"title": "Организаторы и подписки", "collapsible": True, "items": [
                {"title": "Организации", "icon": "business", "link": reverse_lazy("admin:organizers_organization_changelist")},
                {"title": "Запросы «Это моё событие»", "icon": "verified_user",
                 "link": reverse_lazy("admin:organizers_claim_changelist")},
                {"title": "Подписки", "icon": "mail", "link": reverse_lazy("admin:subscriptions_subscription_changelist")},
                {"title": "Журнал отправок", "icon": "outbox", "link": reverse_lazy("admin:subscriptions_delivery_changelist")},
            ]},
            {"title": "Настройки", "collapsible": True, "items": [
                {"title": "Сайты", "icon": "language", "link": reverse_lazy("admin:portals_site_changelist")},
                {"title": "Источники", "icon": "hub", "link": reverse_lazy("admin:intake_eventsource_changelist")},
                {"title": "Пользователи", "icon": "person", "link": reverse_lazy("admin:auth_user_changelist")},
                {"title": "Журнал действий", "icon": "history", "link": reverse_lazy("admin:audit_auditlog_changelist")},
            ]},
        ],
    },
}

LOGIN_URL = "/cabinet/login/"
LOGIN_REDIRECT_URL = "/admin/"
