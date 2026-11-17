"""System check of the help window a module declares (tag ``live``).

``help = Help(...)`` makes a module's help ready; only a module (``kind = "app"``) has one. Each of its optional
videos is a YouTube video id under a language code of ``settings.LANGUAGES`` (E023).
"""

import re
from typing import Any

from django.conf import settings
from django.core import checks

from live.meta import Help, all_live_app_configs

#: The 11 characters after ``watch?v=``.
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HINT = (
    "Declare help = Help(videos={'es': '<id>'}) on a module of apps/: each key a language code of "
    "settings.LANGUAGES, each value the 11 characters of a YouTube video id (letters, digits, '-' and '_')."
)


@checks.register("live")
def check_app_help(app_configs: Any = None, **kwargs: Any) -> list[checks.CheckMessage]:
    """E023: the ``help`` of every app of ours that declares one."""
    languages = {code for code, _name in settings.LANGUAGES}
    return [
        checks.Error(f"App {config.label!r} {problem}.", hint=HINT, obj=config, id="live.E023")
        for config in all_live_app_configs()
        if config.help is not None
        for problem in _help_problems(config, languages)
    ]


def _help_problems(config: Any, languages: set[str]) -> list[str]:
    if not isinstance(config.help, Help):
        return [f"declares help={config.help!r}, which is not a live.meta.Help"]
    problems = [] if config.kind == "app" else ["declares help, which only a module (kind = 'app') has"]
    for language, video in config.help.videos.items():
        if language not in languages:
            problems.append(f"has a help video for {language!r}, which is not one of settings.LANGUAGES")
        if not (isinstance(video, str) and VIDEO_ID_RE.fullmatch(video)):
            problems.append(f"has the help video {video!r} for {language!r}, which is not a YouTube video id")
    return problems
