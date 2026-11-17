"""``live.E023``: the help window a module declares (``help = Help(...)``).

A module's help is ready once it declares ``help``; its video is optional. Each video is a YouTube video id by
language code, and only a module (``kind = "app"``) has a help window.
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.core import checks
from django.core.checks.registry import registry
from live.checks_help import check_app_help
from live.meta import Help

VIDEO = "dQw4w9WgXcQ"


def app(label="stock", *, kind="app", help=None):
    return SimpleNamespace(label=label, kind=kind, help=help)


@pytest.fixture
def run(monkeypatch):
    """Run the check over the given stand-ins, as if they were the installed apps."""

    def run(*configs):
        monkeypatch.setattr("live.checks_help.all_live_app_configs", lambda: list(configs))
        return check_app_help(app_configs=None)

    return run


def test_the_check_is_registered_with_the_live_tag():
    assert check_app_help in registry.get_checks()
    assert check_app_help.tags == ("live",)


def test_django_setup_registers_the_check_without_anyone_importing_it():
    """A fresh process, where no test imported ``live.checks_help`` first: the live app's startup does."""
    script = (
        "import django; django.setup()\n"
        "from django.core.checks.registry import registry\n"
        "print(sorted(f'{check.__module__}.{check.__name__}' for check in registry.get_checks()))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parent.parent,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "tests.settings"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "live.checks_help.check_app_help" in result.stdout


@pytest.mark.parametrize(
    "declared",
    [None, Help(), Help(videos={"es": VIDEO}), Help(videos={"es": VIDEO, "en": "aqz-KE-bpKQ"}), Help({"en": "A1_-b2c3D4e"})],
)
def test_a_module_without_help_or_with_a_well_declared_one_passes(run, declared):
    assert run(app(help=declared)) == []


def test_a_platform_app_without_help_passes(run):
    assert run(app("base", kind="platform")) == []


@pytest.mark.parametrize("kind", ["platform", "plugin"])
def test_help_on_an_app_that_is_no_module_is_e023(run, kind):
    config = app("base", kind=kind, help=Help())

    [message] = run(config)

    assert (message.id, message.obj, message.level) == ("live.E023", config, checks.ERROR)
    assert message.msg == "App 'base' declares help, which only a module (kind = 'app') has."


@pytest.mark.parametrize("language", ["fr", "ES", "es-es", ""])
def test_a_video_for_a_language_of_no_settings_language_is_e023(run, language):
    config = app(help=Help(videos={language: VIDEO}))

    [message] = run(config)

    assert (message.id, message.obj) == ("live.E023", config)
    assert message.msg == f"App 'stock' has a help video for {language!r}, which is not one of settings.LANGUAGES."


@pytest.mark.parametrize(
    "video",
    [
        "dQw4w9WgXc",
        "dQw4w9WgXcQQ",
        "dQw4w9WgXc!",
        "dQw4w9 gXcQ",
        "dQw4w9WgXcQ\n",
        "https://youtu.be/dQw4w9WgXcQ",
        "",
        None,
        12345678901,
    ],
)
def test_a_video_that_is_no_youtube_video_id_is_e023(run, video):
    config = app(help=Help(videos={"es": video}))

    [message] = run(config)

    assert (message.id, message.obj) == ("live.E023", config)
    assert message.msg == f"App 'stock' has the help video {video!r} for 'es', which is not a YouTube video id."


@pytest.mark.parametrize("declared", [True, {"es": VIDEO}, VIDEO])
def test_help_that_is_no_help_value_is_e023(run, declared):
    [message] = run(app(help=declared))

    assert message.id == "live.E023"
    assert message.msg == f"App 'stock' declares help={declared!r}, which is not a live.meta.Help."


def test_each_problem_is_its_own_message_on_its_app(run):
    platform = app("base", kind="platform", help=Help(videos={"fr": "bad"}))
    module = app("stock", help=Help(videos={"es": VIDEO, "en": "bad"}))

    messages = run(platform, module)

    assert [(message.id, message.obj) for message in messages] == [
        ("live.E023", platform),
        ("live.E023", platform),
        ("live.E023", platform),
        ("live.E023", module),
    ]
    assert all(message.hint for message in messages)


def test_the_installed_apps_pass():
    assert [message for message in checks.run_checks(tags=["live"]) if message.id == "live.E023"] == []
