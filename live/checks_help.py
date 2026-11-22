"""System check of the help window a module declares (tag ``live``).

``help = Help(...)`` makes a module's help ready; only a module (``kind = "app"``) has one. Each of its optional
videos, the module's own and those of each flow, is a YouTube video id under a language code of
``settings.LANGUAGES`` (E023).
"""

import re
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core import checks

from live.meta import Help, all_live_app_configs

#: The 11 characters after ``watch?v=``.
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
HINT = (
    "Declare help = Help(videos={'es': '<id>'}, flow_videos={'<APP>-F<nn>': {'es': ['<id>', ...]}}) on a module of "
    "apps/: each language a code of settings.LANGUAGES, each video the 11 characters of a YouTube video id (letters, "
    "digits, '-' and '_')."
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
        if not _is_video_id(video):
            problems.append(f"has the help video {video!r} for {language!r}, which is not a YouTube video id")
    for flow, videos_by_language in config.help.flow_videos.items():
        problems += _flow_problems(flow, videos_by_language, languages)
    return problems


def _flow_problems(flow: str, videos_by_language: Any, languages: set[str]) -> list[str]:
    if not isinstance(videos_by_language, Mapping):
        return [f"has the videos {videos_by_language!r} of flow {flow!r}, which are not YouTube video ids by language code"]
    problems = []
    for language, videos in videos_by_language.items():
        if language not in languages:
            problems.append(f"has videos of flow {flow!r} for {language!r}, which is not one of settings.LANGUAGES")
        if not isinstance(videos, list | tuple):
            problems.append(
                f"has the videos {videos!r} of flow {flow!r} for {language!r}, which are not a list of YouTube video ids"
            )
            continue
        problems += [
            f"has the video {video!r} of flow {flow!r} for {language!r}, which is not a YouTube video id"
            for video in videos
            if not _is_video_id(video)
        ]
    return problems


def _is_video_id(video: Any) -> bool:
    return isinstance(video, str) and VIDEO_ID_RE.fullmatch(video) is not None
