"""What a cut of the database leaves in ``django.request``: the answer the client gets, once, and no try before it.

Django logs a 503 where it turns the cut into a response, inside the chain, before ``DatabaseCutMiddleware`` decides to
repeat the request: a read that waited and answered 200 must not leave an error behind. The project is the one of
``tests/test_database_cut.py``, against the real Postgres.
"""

import pytest
from django.db import OperationalError

from tests.test_database_cut import (  # noqa: F401 - its fixtures set up the project these requests run in
    MIDDLEWARE,
    always_cut,
    async_request,
    client,
    cut_once,
    project,
    runs,
    script,
)

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


def logged(caplog) -> list[tuple[str, type | None]]:
    """What ``django.request`` logged: its message and the error it carries."""
    return [
        (record.getMessage(), record.exc_info[0] if record.exc_info else None)
        for record in caplog.records
        if record.name == "django.request"
    ]


def answers(attempt: int) -> int:
    return 7


@pytest.mark.parametrize(
    "cut, url",
    [("page", "/page"), ("before", "/page"), ("raw", "/api/raw")],
    ids=["a page", "a read before the view", "a route outside its operation"],
)
def test_a_request_that_waits_and_answers_logs_no_error(client, caplog, cut, url):
    script.update({"page": answers, "raw": answers, cut: cut_once})

    response = client.get(url)

    assert response.status_code == 200, response.content
    assert runs[cut] == 2
    assert logged(caplog) == []


@pytest.mark.parametrize(
    "cut, url",
    [("page", "/page"), ("before", "/page"), ("read", "/api/read"), ("builder", "/api/live")],
    ids=["a page", "a read before the view", "a route's operation", "a live stream"],
)
def test_a_request_that_stays_cut_logs_its_503_once_with_the_error_that_cut_it(client, caplog, cut, url):
    script.update({"page": answers, cut: always_cut})

    response = client.get(url)

    assert response.status_code == 503, response.content
    assert runs[cut] > 1
    assert logged(caplog) == [(f"Service Unavailable: {url}", OperationalError)]


@pytest.mark.parametrize(
    "chain", [MIDDLEWARE[:1], MIDDLEWARE], ids=["all of it async", "with a sync middleware inside"]
)
async def test_the_async_chain_logs_only_its_answer_too(settings, caplog, chain):
    settings.MIDDLEWARE = chain
    script["page"] = cut_once

    answered = await async_request("get", "/page")
    script["page"] = always_cut
    unavailable = await async_request("get", "/page")

    assert (answered.status_code, unavailable.status_code) == (200, 503)
    assert logged(caplog) == [("Service Unavailable: /page", OperationalError)]


def test_without_the_middleware_django_logs_the_503_as_ever(client, settings, caplog):
    """A project that answers a cut with its 503 but never repeats the request: nobody else would log it."""
    settings.MIDDLEWARE = MIDDLEWARE[1:]
    script["page"] = cut_once

    response = client.get("/page")

    assert response.status_code == 503, response.content
    assert runs["page"] == 1
    assert logged(caplog) == [("Service Unavailable: /page", OperationalError)]
