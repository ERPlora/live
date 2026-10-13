"""Django app configuration of the live package."""

from django.apps import AppConfig
from django.utils.module_loading import autodiscover_modules

# Modules of every installed app that declare operations, live queries and event reactions.
DISCOVERED_MODULES = ("queries", "services", "live", "events")


class LiveConfig(AppConfig):
    name = "live"
    label = "live"
    verbose_name = "Live"

    def ready(self) -> None:
        # Importing live.checks registers the app metadata checks (tag "live").
        from live import checks, operations, outbox  # noqa: F401

        operations.notify_hook = outbox.notify
        # Importing registers the operations; a second ready() hits Python's import cache and
        # registers nothing again. A module that exists but fails to import raises here.
        autodiscover_modules(*DISCOVERED_MODULES)
