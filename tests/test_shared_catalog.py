"""The contract of the ``shared`` schema of the ``saas`` database (round 16, spec §3.1 and §3.2).

The columns are written once, in the abstract models of ``live.shared_catalog``; the SaaS concretes
them as the owner (managed, migrated) and the Hub as a mirror (``managed = False``). Changing a
column breaks these tests on purpose: it has to go through the expand/contract of spec §3.5.

The concrete models live in an isolated app registry, in two test apps, as the two projects do.
No database is needed: the tests read ``_meta`` and the column types of the Postgres backend.
"""

import uuid

import pytest
from django.db import connection, models
from django.test.utils import isolate_apps

from live.shared_catalog import (
    APP_DOC_TABLE,
    APP_TABLE,
    DOC_LANGUAGES,
    AbstractApp,
    AbstractAppDoc,
)

#: (column, Postgres type, null) of shared.app, in the order of spec §3.1.
APP_COLUMNS = [
    ("id", "varchar(63)", False),
    ("name_en", "varchar(80)", False),
    ("name_es", "varchar(80)", False),
    ("summary_en", "varchar(120)", False),
    ("summary_es", "varchar(120)", False),
    ("description_en", "text", False),
    ("description_es", "text", False),
    ("icon", "varchar(100)", False),
    ("icon_svg", "text", False),
    ("category", "varchar(20)", False),
    ("premium", "boolean", False),
    ("requires", "jsonb", False),
    ("verticals", "jsonb", False),
    ("listed", "boolean", False),
    ("hub_version", "varchar(64)", False),
    ("registered_at", "timestamp with time zone", False),
]

#: (column, Postgres type, null) of shared.app_doc, in the order of spec §3.1.
APP_DOC_COLUMNS = [
    ("id", "uuid", False),
    ("app_id", "varchar(63)", False),
    ("lang", "varchar(8)", False),
    ("markdown", "text", False),
    ("source_hash", "varchar(64)", False),
    ("updated_at", "timestamp with time zone", False),
]


def columns(model):
    return [
        (field.column, field.db_type(connection), field.null)
        for field in model._meta.concrete_fields
    ]


def concrete_pair(label, app_meta=None, doc_meta=None):
    """An App and an AppDoc in the test app ``label``, named as the projects name them."""

    def build(name, base, table, meta):
        attrs = {"app_label": label, "db_table": table, **(meta or {})}
        return type(name, (base,), {"__module__": f"tests.{label}.models", "Meta": type("Meta", (), attrs)})

    return build("App", AbstractApp, APP_TABLE, app_meta), build("AppDoc", AbstractAppDoc, APP_DOC_TABLE, doc_meta)


@pytest.fixture
def concrete():
    """The SaaS's owner (testapp) and the Hub's mirror (fakeapp), as spec §3.2 writes them."""
    with isolate_apps("tests.testapp", "tests.fakeapp"):
        yield {
            "testapp": concrete_pair(
                "testapp",
                app_meta={"ordering": ["id"]},
                doc_meta={
                    "constraints": [
                        models.UniqueConstraint(fields=["app", "lang"], name="shared_app_doc_app_lang_unique")
                    ]
                },
            ),
            "fakeapp": concrete_pair("fakeapp", app_meta={"managed": False}, doc_meta={"managed": False}),
        }


def test_the_abstract_models_are_abstract():
    assert AbstractApp._meta.abstract
    assert AbstractAppDoc._meta.abstract


def test_the_tables_are_quoted_in_the_shared_schema():
    assert APP_TABLE == '"shared"."app"'
    assert APP_DOC_TABLE == '"shared"."app_doc"'


def test_the_documentation_languages():
    assert DOC_LANGUAGES == ("es", "en")


def test_the_columns_of_shared_app(concrete):
    app, _doc = concrete["testapp"]

    assert columns(app) == APP_COLUMNS
    assert app._meta.pk.name == "id"
    assert app._meta.db_table == '"shared"."app"'


def test_the_columns_of_shared_app_doc(concrete):
    _app, doc = concrete["testapp"]

    assert columns(doc) == APP_DOC_COLUMNS
    assert doc._meta.db_table == '"shared"."app_doc"'


def test_requires_and_verticals_default_to_a_new_empty_list(concrete):
    app, _doc = concrete["testapp"]
    first, second = app(), app()

    assert first.requires == [] and first.verticals == []
    assert first.requires is not second.requires


def test_category_has_no_choices():
    """The SaaS tolerates a category its live.meta does not know yet (spec §5.3)."""
    assert not AbstractApp._meta.get_field("category").choices


def test_the_doc_key_is_a_uuid7(concrete):
    _app, doc = concrete["testapp"]

    key = doc().id

    assert isinstance(key, uuid.UUID)
    assert key.version == 7


def test_the_doc_language_is_es_or_en():
    assert AbstractAppDoc._meta.get_field("lang").choices == [
        ("es", "es"),
        ("en", "en"),
    ]


def test_the_doc_fk_resolves_to_the_app_of_its_own_project(concrete):
    """A relative "App": each project's AppDoc points at its own App, never at the other's."""
    for label, (app, doc) in concrete.items():
        field = doc._meta.get_field("app")

        assert field.related_model is app, label
        assert field.related_model._meta.app_label == label
        assert field.remote_field.on_delete is models.PROTECT
        assert field.remote_field.related_name == "docs"


def test_owner_and_mirror_share_the_columns(concrete):
    """The mirror cannot diverge from the owner within one commit of live (spec §3.2)."""
    (owner_app, owner_doc), (mirror_app, mirror_doc) = concrete["testapp"], concrete["fakeapp"]

    assert columns(owner_app) == columns(mirror_app) == APP_COLUMNS
    assert columns(owner_doc) == columns(mirror_doc) == APP_DOC_COLUMNS
    assert mirror_app._meta.db_table == owner_app._meta.db_table == APP_TABLE
    assert mirror_doc._meta.db_table == owner_doc._meta.db_table == APP_DOC_TABLE
