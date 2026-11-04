"""The partial index of the events a relay has not taken yet (hub#704).

``live`` declares it, under the name it was deployed with: until now a migration of the Hub's ``base`` made it, on every
database the Hub has. So ``live/0003`` takes the index it finds as it is, and only a database without one gets it.
"""

from io import StringIO

import psycopg
import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.models import Q
from live.models import OutboxEvent

NAME = "base_outbox_pending"
BEFORE = ("live", "0002_outboxevent_verbose_names")
AFTER = ("live", "0003_outbox_pending_index")
#: As the Hub's ``base/0006`` made it on every database deployed before ``live`` declared it.
DEPLOYED = f"CREATE INDEX {NAME} ON live_outboxevent (created_at, id) WHERE delivered_at IS NULL"
#: What PostgreSQL says that statement made.
DEFINITION = f"CREATE INDEX {NAME} ON public.live_outboxevent USING btree (created_at, id) WHERE (delivered_at IS NULL)"


def migrate(node: tuple[str, str]) -> None:
    MigrationExecutor(connection).migrate([node])


def execute(statement: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement)


def partial_indexes() -> list[tuple[int, str]]:
    """``(oid, definition)`` of every partial index of the outbox, whatever its name: two would be one too many."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT indexrelid::oid, pg_get_indexdef(indexrelid) FROM pg_index "
            "WHERE indrelid = 'live_outboxevent'::regclass AND indpred IS NOT NULL"
        )
        return cursor.fetchall()


def declared_index():
    [index] = [index for index in OutboxEvent._meta.indexes if index.name == NAME]
    return index


def test_the_outbox_declares_the_index_of_the_pending_events():
    index = declared_index()

    assert index.fields == ["created_at", "id"]
    assert index.condition == Q(delivered_at__isnull=True)


@pytest.mark.django_db
def test_makemigrations_has_nothing_to_write():
    call_command("makemigrations", "live", "--check", "--dry-run", stdout=StringIO())


@pytest.mark.django_db
def test_what_the_model_declares_is_the_index_deployed():
    migrate(BEFORE)

    with connection.schema_editor() as editor:
        editor.add_index(OutboxEvent, declared_index())

    assert [definition for _oid, definition in partial_indexes()] == [DEFINITION]


@pytest.mark.django_db
def test_a_database_without_it_gets_it():
    migrate(BEFORE)
    assert partial_indexes() == []

    migrate(AFTER)

    assert [definition for _oid, definition in partial_indexes()] == [DEFINITION]


@pytest.mark.django_db
def test_a_database_that_already_has_it_keeps_that_one():
    migrate(BEFORE)
    execute(DEPLOYED)
    deployed = partial_indexes()

    migrate(AFTER)

    assert partial_indexes() == deployed


@pytest.mark.django_db
def test_going_back_drops_it_and_forward_makes_it_again():
    assert [definition for _oid, definition in partial_indexes()] == [DEFINITION]

    migrate(BEFORE)
    assert partial_indexes() == []

    migrate(AFTER)
    assert [definition for _oid, definition in partial_indexes()] == [DEFINITION]


@pytest.mark.django_db
def test_going_back_when_it_is_already_gone_is_no_error():
    execute(f"DROP INDEX {NAME}")

    migrate(BEFORE)

    assert partial_indexes() == []


@pytest.mark.django_db(transaction=True)
def test_a_database_that_already_has_it_never_waits_for_the_outbox(db_dsn):
    """Every deployed database goes through this migration in a deploy, with its outbox in use. ``CREATE INDEX … IF NOT
    EXISTS`` takes its SHARE lock and asks to own the table before it looks: it waits for a write in progress, and the
    writes behind it wait for it, to do nothing."""
    migrate(BEFORE)
    execute(DEPLOYED)
    try:
        with psycopg.connect(db_dsn) as writing:
            writing.execute("LOCK TABLE live_outboxevent IN ROW EXCLUSIVE MODE")
            execute("SET lock_timeout = '500ms'")

            migrate(AFTER)
    finally:
        execute("RESET lock_timeout")
        migrate(AFTER)
