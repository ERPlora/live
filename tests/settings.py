"""Django settings for the erplora-live test suite (Postgres only, never SQLite)."""

import os

SECRET_KEY = "test"
DEBUG = False
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
ROOT_URLCONF = "tests.urls"

INSTALLED_APPS = [
    "live",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "tests.testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "hub"),
        "USER": os.environ.get("DB_USER", "hub"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "hub"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    }
}
