"""
Django settings for fuel_router.

This is a small, single-purpose service so the settings file stays flat —
no profile splitting, just env-driven overrides for the handful of things
that change between local and prod (secret key, debug, allowed hosts,
external service URLs).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    # Insecure default — fine for local dev / the assessment reviewer. Override
    # via env in any real deployment.
    "django-insecure-assessment-only-do-not-use-in-production",
)
DEBUG = _env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", "*")

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.staticfiles",
    "rest_framework",
    "routing.apps.RoutingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fuel_router.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "fuel_router.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
    "DEFAULT_THROTTLE_RATES": {"anon": os.getenv("ANON_THROTTLE", "60/min")},
}

# ---------------------------------------------------------------------------
# App-specific
# ---------------------------------------------------------------------------

# Where the precomputed station list lives. Loaded once at startup.
STATIONS_JSON_PATH = BASE_DIR / os.getenv("STATIONS_JSON", "fuel_stations.json")

# Vehicle parameters from the assessment spec.
VEHICLE_RANGE_MILES = float(os.getenv("VEHICLE_RANGE_MILES", "500"))
VEHICLE_MPG = float(os.getenv("VEHICLE_MPG", "10"))

# How far off-route (perpendicular miles) we'll still consider a station.
STATION_CORRIDOR_MILES = float(os.getenv("STATION_CORRIDOR_MILES", "30"))

# External services
# Default to FOSSGIS's free OSRM demo (the same backend that router.project-osrm.org
# CNAMEs to — but the .de hostname stays reachable even where the project-osrm.org
# DNS entry is filtered). Override via env for a self-hosted OSRM.
OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "https://routing.openstreetmap.de/routed-car")
NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
HTTP_USER_AGENT = os.getenv("HTTP_USER_AGENT", "spotter-fuel-router/1.0 (assessment)")
HTTP_TIMEOUT_SECONDS = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django.server": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "routing": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
