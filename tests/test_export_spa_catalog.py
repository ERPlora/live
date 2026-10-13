"""`manage.py export_spa_catalog`: the `djangojs` gettext catalogs as flat JSON for vue-i18n (plan §4.3).

One `<lang>.json` per language of `settings.LANGUAGES`, merging every installed app's and
`LOCALE_PATHS`' catalogs (LOCALE_PATHS win). English is the source language: its file maps every
known msgid to itself unless an English catalog says otherwise. Plural forms are joined with " | ",
as vue-i18n expects. Keys are sorted so the committed files diff cleanly.
"""

import array
import json
import struct

import pytest
from django.core.management import CommandError, call_command

APP_ES = {
    "Delete item": "Borrar ítem",
    "Save": "Guardar",
    "{n} item": "{n} ítem | {n} ítems",
}
APP_EN = {
    "Delete item": "Delete item",
    "Save": "Save",
    "{n} item": "{n} item | {n} items",
}
HEADER = "Content-Type: text/plain; charset=UTF-8\nPlural-Forms: nplurals=2; plural=(n != 1);\n"


def write_mo(path, messages):
    """Compile ``{msgid: msgstr}`` into a GNU .mo file (the algorithm of CPython's Tools/i18n/msgfmt.py).

    Plural entries are ``"singular\\0plural": "form0\\0form1"``; ``""`` is the header.
    """
    keys = sorted(messages)
    ids = strs = b""
    offsets = []
    for key in keys:
        key_bytes, value_bytes = key.encode(), messages[key].encode()
        offsets.append((len(ids), len(key_bytes), len(strs), len(value_bytes)))
        ids += key_bytes + b"\0"
        strs += value_bytes + b"\0"
    key_start = 7 * 4 + 16 * len(keys)
    value_start = key_start + len(ids)
    key_offsets, value_offsets = [], []
    for id_offset, id_length, str_offset, str_length in offsets:
        key_offsets += [id_length, id_offset + key_start]
        value_offsets += [str_length, str_offset + value_start]
    header = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        header + array.array("i", key_offsets).tobytes() + array.array("i", value_offsets).tobytes() + ids + strs
    )


def export(output, **kwargs):
    call_command("export_spa_catalog", "--output", str(output), **kwargs)
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(output.glob("*.json"))}


class TestExport:
    def test_one_file_per_language(self, tmp_path):
        assert sorted(export(tmp_path)) == ["en", "es"]

    def test_spanish_comes_from_the_installed_apps(self, tmp_path):
        assert export(tmp_path)["es"] == APP_ES

    def test_english_is_the_identity_of_every_known_msgid(self, tmp_path):
        assert export(tmp_path)["en"] == APP_EN

    def test_plural_forms_are_joined_like_vue_i18n(self, tmp_path):
        catalogs = export(tmp_path)

        assert catalogs["es"]["{n} item"] == "{n} ítem | {n} ítems"
        assert catalogs["en"]["{n} item"] == "{n} item | {n} items"

    def test_the_header_is_not_a_message(self, tmp_path):
        assert "" not in export(tmp_path)["es"]

    def test_output_is_sorted_and_deterministic(self, tmp_path):
        export(tmp_path / "first")
        export(tmp_path / "second")
        first = (tmp_path / "first" / "es.json").read_text(encoding="utf-8")

        assert first == (tmp_path / "second" / "es.json").read_text(encoding="utf-8")
        assert list(json.loads(first)) == sorted(APP_ES)
        assert first.endswith("\n")
        assert "Borrar ítem" in first, "UTF-8, not \\u escapes"

    def test_locale_paths_add_and_override_messages(self, tmp_path, settings):
        locale = tmp_path / "locale"
        write_mo(
            locale / "es" / "LC_MESSAGES" / "djangojs.mo",
            {"": HEADER, "Save": "Guardar cambios", "Close": "Cerrar", "{n} line\0{n} lines": "{n} línea\0{n} líneas"},
        )
        settings.LOCALE_PATHS = [str(locale)]

        catalogs = export(tmp_path / "out")

        assert catalogs["es"] == {
            **APP_ES,
            "Save": "Guardar cambios",
            "Close": "Cerrar",
            "{n} line": "{n} línea | {n} líneas",
        }
        assert catalogs["en"] == {**APP_EN, "Close": "Close", "{n} line": "{n} line | {n} lines"}

    def test_an_english_catalog_wins_over_the_identity(self, tmp_path, settings):
        locale = tmp_path / "locale"
        write_mo(locale / "en" / "LC_MESSAGES" / "djangojs.mo", {"": HEADER, "Save": "Save changes"})
        settings.LOCALE_PATHS = [str(locale)]

        assert export(tmp_path / "out")["en"]["Save"] == "Save changes"

    def test_only_the_requested_domain_is_exported(self, tmp_path, settings):
        locale = tmp_path / "locale"
        write_mo(locale / "es" / "LC_MESSAGES" / "django.mo", {"": HEADER, "Server only": "Solo servidor"})
        settings.LOCALE_PATHS = [str(locale)]

        catalogs = export(tmp_path / "out")

        assert "Server only" not in catalogs["es"]
        assert "Server only" not in catalogs["en"]

    def test_a_language_without_catalogs_does_not_borrow_another(self, tmp_path, settings):
        """No gettext fallback: a missing translation stays missing, so en/es parity tests see it."""
        settings.LANGUAGE_CODE = "es"
        settings.LANGUAGES = [("en", "English"), ("es", "Spanish"), ("fr", "French")]

        assert export(tmp_path)["fr"] == {}

    def test_the_output_directory_is_created(self, tmp_path):
        export(tmp_path / "frontend" / "generated" / "locales")

        assert (tmp_path / "frontend" / "generated" / "locales" / "es.json").exists()

    def test_the_output_is_required(self):
        with pytest.raises(CommandError):
            call_command("export_spa_catalog")
