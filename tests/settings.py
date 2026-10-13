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

# --- SPA, CSP and Vite (P6a: live.spa, live.csp, runserver, export_spa_catalog) -----------------
from pathlib import Path  # noqa: E402

from live.csp import base_policy  # noqa: E402

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]
# The suite always runs under the production policy.
SECURE_CSP = base_policy()
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.template.context_processors.csp",
            ],
        },
    }
]
STATIC_URL = "/static/"
LANGUAGES = [("en", "English"), ("es", "Spanish")]
LIVE = {
    **globals().get("LIVE", {}),
    "spa": {
        "entry": "frontend/main.ts",
        # Tests that render the SPA point this at a temporary manifest.
        "manifest": Path(__file__).resolve().parent / "missing" / "manifest.json",
        "dev_server": "http://localhost:5173",
        "palettes": ["default", "ocean"],
        "palette_default": "default",
    },
    "vite": {"command": ["pnpm", "--filter", "hub", "dev"], "cwd": Path(__file__).resolve().parent},
}
# --- end P6a -------------------------------------------------------------------------------------
