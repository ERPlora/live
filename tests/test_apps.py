"""The live package registers its own AppConfig."""

from django.apps import apps


def test_live_app_config_is_registered_with_label_live():
    config = apps.get_app_config("live")

    assert type(config).__name__ == "LiveConfig"
    assert type(config).__module__ == "live.apps"
    assert config.name == "live"
    assert config.label == "live"
