"""``manage.py export_spa_catalog``: the SPA's gettext catalogs as flat JSON for vue-i18n (plan §4.3).

For every language of ``settings.LANGUAGES`` it merges the ``djangojs`` catalogs of all installed
apps and ``LOCALE_PATHS`` (Django's own precedence: LOCALE_PATHS first, then apps in order) and
writes ``<output>/<lang>.json`` as ``{msgid: msgstr}``, keys sorted. Plural forms are joined with
``" | "``, as vue-i18n expects. English is the source language: its file maps every msgid any
catalog knows to itself unless an English catalog translates it. Other languages carry only their
own translations, with no gettext fallback, so an en/es parity test sees what is missing.
"""

from __future__ import annotations

import gettext
import json
import struct
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import to_locale
from django.utils.translation.trans_real import DjangoTranslation

#: Language of the msgids (code in English, PLAN §5).
SOURCE_LANGUAGE = "en"
#: Separator of plural forms in a vue-i18n message.
PLURAL_SEPARATOR = " | "


def language_catalog(language: str, domain: str) -> dict[str, str]:
    """``{msgid: msgstr}`` of one language, plural forms joined, without the header or fallbacks."""
    translation = DjangoTranslation(language, domain=domain)
    catalog: dict[str, str] = {}
    plurals: dict[str, dict[int, str]] = {}
    # Like JavaScriptCatalog.get_catalog(), minus the walk to the default language's fallback.
    for key, value in translation._catalog.items():
        if key == "":
            continue
        if isinstance(key, tuple):
            msgid, index = key
            plurals.setdefault(msgid, {}).setdefault(index, value)
        else:
            catalog.setdefault(key, value)
    for msgid, forms in plurals.items():
        catalog.setdefault(msgid, PLURAL_SEPARATOR.join(forms.get(i, "") for i in range(max(forms) + 1)))
    return catalog


def _locale_dirs() -> list[Path]:
    dirs = [Path(path) for path in settings.LOCALE_PATHS]
    dirs += [Path(config.path) / "locale" for config in apps.get_app_configs()]
    return dirs


def _read_plural_msgids(mo_path: Path) -> dict[str, str]:
    """``{msgid: msgid_plural}`` of a GNU .mo file (gettext keeps only the singular)."""
    data = mo_path.read_bytes()
    order = "<" if data[:4] == b"\xde\x12\x04\x95" else ">"
    count, originals = struct.unpack(f"{order}II", data[8:16])
    found = {}
    for i in range(count):
        length, offset = struct.unpack(f"{order}II", data[originals + 8 * i : originals + 8 * i + 8])
        raw = data[offset : offset + length]
        if b"\0" in raw:
            singular, plural = raw.split(b"\0", 1)
            found[singular.decode("utf-8")] = plural.decode("utf-8")
    return found


def plural_msgids(domain: str, languages: list[str]) -> dict[str, str]:
    """Every ``msgid -> msgid_plural`` the ``domain`` catalogs of ``languages`` contain."""
    found: dict[str, str] = {}
    for localedir in _locale_dirs():
        for language in languages:
            mo_path = gettext.find(domain, str(localedir), languages=[to_locale(language)])
            if mo_path:
                for singular, plural in _read_plural_msgids(Path(mo_path)).items():
                    found.setdefault(singular, plural)
    return found


def _is_source(language: str) -> bool:
    return language.split("-")[0].lower() == SOURCE_LANGUAGE


class Command(BaseCommand):
    help = "Export the SPA's gettext catalogs as one flat JSON file per language, for vue-i18n."

    def add_arguments(self, parser):
        parser.add_argument("--domain", default="djangojs", help="gettext domain (default: djangojs).")
        parser.add_argument("--output", required=True, type=Path, help="Directory for <lang>.json.")

    def handle(self, *args, domain: str, output: Path, **options):
        languages = [code for code, _name in settings.LANGUAGES]
        catalogs = {language: language_catalog(language, domain) for language in languages}
        plurals = plural_msgids(domain, languages)
        known = set().union(*catalogs.values())
        output.mkdir(parents=True, exist_ok=True)
        for language, catalog in catalogs.items():
            if _is_source(language):
                catalog = {msgid: catalog.get(msgid) or self._identity(msgid, plurals) for msgid in known}
            path = output / f"{language}.json"
            path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            self.stdout.write(f"{language}: {len(catalog)} messages -> {path}")

    @staticmethod
    def _identity(msgid: str, plurals: dict[str, str]) -> str:
        return f"{msgid}{PLURAL_SEPARATOR}{plurals[msgid]}" if msgid in plurals else msgid
