"""A read cut by the database waits and tries again, within one limit for the whole request."""

import asyncio
import time

import pytest
from django.db import OperationalError, connections

from tests.database_cut.cutting import always_cut, cut_once
from tests.database_cut.project import MIDDLEWARE, UNAVAILABLE, WAIT_SECONDS, async_request, code_of, runs, script

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


def test_a_read_cut_halfway_waits_and_answers(client):
    script["read"] = cut_once

    response = client.get("/api/read")

    assert response.status_code == 200, response.content
    assert response.json() == {"rows": 7}
    assert runs["read"] == 2


def test_a_read_that_stays_cut_answers_503_with_retry_after_within_the_limit(client):
    script["read"] = always_cut

    started = time.monotonic()
    response = client.get("/api/read")
    took = time.monotonic() - started

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["read"] > 1
    assert WAIT_SECONDS * 0.5 <= took < WAIT_SECONDS + 2


def test_the_limit_is_shared_by_every_try_of_the_request(client):
    """The route's own tries spend the limit: the middleware that receives its 503 does not wait it all over again."""
    script["read"] = always_cut

    started = time.monotonic()
    client.get("/api/read")

    assert time.monotonic() - started < WAIT_SECONDS + 2


def test_without_the_setting_nothing_changes(client, settings, caplog):
    """A project that has not asked for it keeps the plain 500 and the driver's error in its log: nothing waits."""
    settings.LIVE = {key: value for key, value in settings.LIVE.items() if key != "database_cut"}
    script["read"] = cut_once

    response = client.get("/api/read")

    assert response.status_code == 500
    assert code_of(response) == "internal_error"
    assert "Retry-After" not in response
    assert runs["read"] == 1
    assert [record.exc_info[0] for record in caplog.records if record.exc_info] == [OperationalError]


@pytest.mark.parametrize(
    "statements",
    [
        pytest.param(["SET LOCAL statement_timeout = '10ms'", "SELECT pg_sleep(1)"], id="a statement timeout (57014)"),
        pytest.param(["SELECT 1 / 0"], id="a division by zero (22012)"),
        pytest.param(["SELECT * FROM no_such_table"], id="a missing table (42P01)"),
    ],
)
def test_a_failure_that_is_no_cut_stays_the_error_it_was(client, statements):
    def fails(attempt):
        with connections["default"].cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    script["read"] = fails

    response = client.get("/api/read")

    assert response.status_code == 500
    assert code_of(response) == "internal_error"
    assert runs["read"] == 1


def test_the_context_of_the_operation_is_read_again_after_a_cut(client):
    """Who is asking is the first read of a request: a cut there is a cut of the read."""
    script["builder"] = lambda attempt: cut_once(attempt)
    script["read"] = lambda attempt: 1

    response = client.get("/api/read")

    assert response.status_code == 200, response.content
    assert (runs["builder"], runs["read"]) == (2, 1)


@pytest.mark.parametrize(
    ("url", "piece"),
    [pytest.param("/api/aread", "read", id="an async route"), pytest.param("/page", "page", id="the async middleware")],
)
async def test_waiting_does_not_hold_the_event_loop(settings, url, piece):
    settings.MIDDLEWARE = MIDDLEWARE[:1]  # Only async-capable: the chain runs on the loop, no thread of its own to sleep in.
    script[piece] = always_cut
    gaps = []

    async def ticker():
        last = time.monotonic()
        while True:
            await asyncio.sleep(0.02)
            now = time.monotonic()
            gaps.append(now - last)
            last = now

    ticking = asyncio.ensure_future(ticker())
    response = await async_request("get", url)
    ticking.cancel()

    assert response.status_code == 503, response.content
    assert runs[piece] > 1
    # Waits reach 0.5 s and more: a loop asleep for one of them would show here.
    assert max(gaps) < 0.4


async def test_an_async_route_answers_after_the_cut():
    script["read"] = cut_once

    response = await async_request("get", "/api/aread")

    assert response.status_code == 200, response.content
    assert runs["read"] == 2
