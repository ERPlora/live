"""A command cut by the database: a write that may have been applied never repeats."""

import asyncio
import threading

import pytest
from django.db import connections
from live.errors import LiveMisuse
from live.operations import INTERNAL, operation

from tests.database_cut.cutting import (
    DatabaseDoor,
    always_cut,
    insert_then_cut_once,
    set_read_only,
    terminate,
    things_in_the_database,
)
from tests.database_cut.project import (
    READ,
    UNAVAILABLE,
    UNKNOWN,
    Answer,
    Empty,
    ProbeBuilder,
    async_request,
    code_of,
    runs,
    script,
)
from tests.testapp.models import Thing

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


@pytest.fixture
def door(settings):
    """The alias ``other``, where the operations now run, reaches Postgres through a door."""
    connection = connections["other"]
    connection.close()
    original = connection.settings_dict["HOST"], connection.settings_dict["PORT"]
    opened = DatabaseDoor(original[0], int(original[1]))
    connection.settings_dict["HOST"], connection.settings_dict["PORT"] = "127.0.0.1", opened.port
    settings.LIVE = {**settings.LIVE, "operation_database": "tests.database_cut.project.on_other"}
    yield opened
    connection.close()
    connection.settings_dict["HOST"], connection.settings_dict["PORT"] = original
    opened.close()


def insert_on_other() -> int:
    with connections["other"].cursor() as cursor:
        cursor.execute("INSERT INTO testapp_thing (name) VALUES ('once')")
    return 1


def test_a_command_cut_in_its_body_is_not_repeated_unless_it_says_so(client):
    """Its database rolled back, but what it did outside (a charge, a mail) is not the database's to undo."""
    script["write"] = insert_then_cut_once

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert int(response["Retry-After"]) > 0
    assert runs["write"] == 1
    assert things_in_the_database() == 0


def test_a_repeatable_command_cut_in_its_body_is_applied_once(client):
    script["repeatable"] = insert_then_cut_once

    response = client.post("/api/repeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert things_in_the_database() == 1


async def test_a_repeatable_command_is_applied_once_on_an_async_route():
    script["repeatable"] = insert_then_cut_once

    response = await async_request("post", "/api/arepeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert await asyncio.to_thread(things_in_the_database) == 1


def read_only_for_the_first_session(attempt: int) -> int:
    if attempt == 1:
        # New sessions write again; this one stays read only, as a connection to the old writer does.
        set_read_only(False)
    Thing.objects.create(name="once")
    return Thing.objects.count()


def test_a_write_refused_as_read_only_on_a_repeatable_command_is_applied_once(client):
    set_read_only(True)
    connections["default"].close()
    script["repeatable"] = read_only_for_the_first_session

    response = client.post("/api/repeatable")

    assert response.status_code == 200, response.content
    assert runs["repeatable"] == 2
    assert things_in_the_database() == 1


def test_a_write_refused_as_read_only_on_any_other_command_is_not_repeated(client):
    set_read_only(True)
    connections["default"].close()
    script["write"] = read_only_for_the_first_session

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert runs["write"] == 1
    assert things_in_the_database() == 0


def test_a_command_that_could_not_connect_repeats_because_its_body_never_ran(client, door):
    """Any command, declared or not: nothing of it has run."""
    door.close()
    threading.Timer(0.3, door.open).start()
    script["write"] = lambda attempt: insert_on_other()

    response = client.post("/api/write")

    assert response.status_code == 200, response.content
    assert runs["write"] == 1
    assert things_in_the_database() == 1


def test_a_command_that_never_connects_answers_503_with_nothing_applied(client, door):
    door.close()
    script["write"] = lambda attempt: insert_on_other()

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert runs["write"] == 0


def test_the_answer_to_a_commit_lost_never_repeats_a_write_already_applied(client, door):
    """The worst cut there is: applied, and nobody can know. Not even a command declared repeatable runs again."""
    door.lose_commit_answer = True
    script["repeatable"] = lambda attempt: insert_on_other()

    response = client.post("/api/repeatable")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert int(response["Retry-After"]) > 0
    assert runs["repeatable"] == 1
    assert things_in_the_database() == 1


def test_a_query_inside_a_command_answers_for_the_command(client):
    """The query alone could repeat; what repeats is the outermost operation, and that one does not say it can."""

    def calls_a_query(attempt):
        script["read"] = always_cut
        READ(ProbeBuilder._context(), Empty())

    script["write"] = calls_a_query

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["read"]) == (1, 1)


def test_a_query_on_another_database_inside_a_command_answers_for_the_command(client, settings):
    """Not in a transaction of its own alias, and still not the one that decides: the command runs once."""
    settings.LIVE = {**settings.LIVE, "operation_database": "tests.database_cut.project.read_on_other"}

    def inserts_then_reads_elsewhere(attempt):
        Thing.objects.create(name="once")
        READ(ProbeBuilder._context(), Empty())

    def reads(attempt):
        terminate("other")
        with connections["other"].cursor() as cursor:
            cursor.execute("SELECT 1")

    script["write"] = inserts_then_reads_elsewhere
    script["read"] = reads

    response = client.post("/api/write")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["read"]) == (1, 1)
    assert things_in_the_database() == 0


def test_repeatable_is_only_for_a_command_that_uses_its_database():
    def body(ctx, data):
        return {}

    body.__module__ = "tests.fakeapp.queries"
    with pytest.raises(LiveMisuse):
        operation("cuttest.probe.badquery", kind="query", permission=None, input=Empty, output=Answer, ai=INTERNAL, repeatable=True)(body)
    body.__module__ = "tests.fakeapp.services"
    with pytest.raises(LiveMisuse):
        operation(
            "cuttest.probe.badnodb",
            kind="command",
            permission=None,
            input=Empty,
            output=Answer,
            ai=INTERNAL,
            database=False,
            repeatable=True,
        )(body)
