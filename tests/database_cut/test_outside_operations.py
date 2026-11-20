"""A cut outside any operation, in a page or in a route's own code: the request repeats only while nothing can have
been applied, and the answer says what was saved."""

import pytest
from live.database_cut import DatabaseCut
from live.errors import Conflict

from tests.database_cut.cutting import always_cut, cut_once, insert_then_cut_once, terminate, things_in_the_database
from tests.database_cut.project import (
    APPLIED,
    MIDDLEWARE,
    UNAVAILABLE,
    UNKNOWN,
    async_request,
    code_of,
    runs,
    script,
)
from tests.testapp.models import Thing

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


def test_a_page_cut_halfway_waits_and_answers(client):
    script["page"] = cut_once

    response = client.get("/page")

    assert response.status_code == 200, response.content
    assert response.content == b"7"
    assert runs["page"] == 2


def test_a_page_that_stays_cut_answers_503_with_retry_after(client):
    script["page"] = always_cut

    response = client.get("/page")

    assert response.status_code == 503, response.content
    assert response.content == UNAVAILABLE.encode()
    assert int(response["Retry-After"]) > 0
    assert runs["page"] > 1


@pytest.mark.parametrize("chain", [MIDDLEWARE[:1], MIDDLEWARE], ids=["all of it async", "with a sync middleware inside"])
async def test_a_page_waits_on_the_async_chain_too(settings, chain):
    settings.MIDDLEWARE = chain
    script["page"] = cut_once

    response = await async_request("get", "/page")

    assert response.status_code == 200, response.content
    assert runs["page"] == 2


def test_a_route_read_outside_its_operation_waits_too(client):
    """Whatever a route reads before its operation, an API key for instance."""
    script["raw"] = cut_once

    response = client.get("/api/raw")

    assert response.status_code == 200, response.content
    assert runs["raw"] == 2


def test_a_post_cut_while_reading_who_asks_is_applied_once(client):
    """The first read of a route on the panel. It writes only through its operation, and that one has not started."""
    script["auth"] = cut_once
    script["write"] = inserts

    response = client.post("/api/after-auth")

    assert response.status_code == 200, response.content
    assert (runs["auth"], runs["write"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_with_no_command_started_repeats_while_it_can(client):
    script["raw"] = always_cut

    response = client.post("/api/raw")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNAVAILABLE
    assert int(response["Retry-After"]) > 0
    assert runs["raw"] > 1


def inserts(attempt: int) -> int:
    return Thing.objects.create(name="once") and 1


def test_a_route_cut_after_its_command_committed_says_it_was_saved(client):
    """A route writes only through its operation: once its one command committed, what the cut stopped is the answer."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-write")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert response.json()["error"]["message"] == DatabaseCut(repeatable=False, applied=True).message
    assert int(response["Retry-After"]) > 0
    assert (runs["write"], runs["raw"]) == (1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_a_call_to_a_third_party_says_it_was_done(client):
    """A command with no database has no transaction to undo what it did on the network: it answered, so it was done."""
    script["thirdparty"] = lambda attempt: 1
    script["raw"] = always_cut

    response = client.post("/api/after-third-party")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["thirdparty"], runs["raw"]) == (1, 1)


def test_a_route_cut_after_its_command_was_tried_again_says_it_was_saved(client):
    """The try a cut rolled back left nothing: the command was applied once, by the try after it."""
    script["repeatable"] = insert_then_cut_once
    script["raw"] = always_cut

    response = client.post("/api/after-repeatable")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["repeatable"], runs["raw"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_a_command_that_ran_another_one_says_it_was_saved(client):
    """The one inside commits with the outer one: the route still ran one command."""
    script["write"] = inserts
    script["outer"] = lambda attempt: 1
    script["raw"] = always_cut

    response = client.post("/api/after-nested")

    assert response.status_code == 503, response.content
    assert code_of(response) == APPLIED
    assert (runs["write"], runs["outer"], runs["raw"]) == (1, 1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_two_commands_does_not_say_what_was_saved(client):
    """With a second command that failed, the first one alone was applied: the person checks."""

    def inserts_then_refuses(attempt):
        if attempt == 2:
            raise Conflict("refused", code="cuttest.refused")
        return inserts(attempt)

    script["write"] = inserts_then_refuses
    script["raw"] = always_cut

    response = client.post("/api/after-two-writes")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["raw"]) == (2, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_after_two_commands_applied_does_not_say_it_was_saved_either(client):
    """One route, one operation: more than one, and the answer cannot tell what the person asked for."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-two-writes")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert things_in_the_database() == 2


def test_a_command_cut_inside_someone_elses_transaction_is_never_repeated(client):
    """The second command runs inside the route's transaction: the cut rolled all of it back, so no try of it can stand
    on its own. It is the route's transaction to answer for, and the first command already committed: the person
    checks."""

    def inserts_then_cut(attempt):
        Thing.objects.create(name="rolled back")
        terminate()
        return Thing.objects.count()

    script["write"] = inserts
    script["repeatable"] = inserts_then_cut

    response = client.post("/api/after-write-then-one-in-a-transaction")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["repeatable"]) == (1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_in_its_transaction_after_a_command_committed_does_not_say_it_was_saved(client):
    """The first command committed, the second answered inside the route's transaction, and the cut rolled that one
    back: saved would be half true."""
    script["write"] = inserts
    script["repeatable"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-write-then-one-in-a-transaction")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert (runs["write"], runs["repeatable"], runs["raw"]) == (1, 1, 1)
    assert things_in_the_database() == 1


def test_a_route_cut_inside_the_transaction_its_command_ran_in_does_not_say_it_was_saved(client):
    """A command inside someone else's transaction commits with it: the cut rolled it back, and only a cut at the
    right moment could tell."""
    script["write"] = inserts
    script["raw"] = always_cut

    response = client.post("/api/after-write-in-its-transaction")

    assert response.status_code == 503, response.content
    assert code_of(response) == UNKNOWN
    assert things_in_the_database() == 0


def test_a_cut_of_what_answers_at_once_does_not_wait(client):
    """Who calls ``no_wait_prefixes`` tries again on its own (the Hub's /internal calls, Stripe's webhooks)."""
    script["page"] = always_cut

    response = client.get("/internal/page")

    assert response.status_code == 503
    assert int(response["Retry-After"]) > 0
    assert runs["page"] == 1


@pytest.mark.parametrize("method", ["get", "post"])
def test_a_cut_before_the_view_repeats_the_request_whatever_its_method(client, method):
    """No view ran: nothing can have been applied."""
    script["before"] = cut_once
    script["page"] = lambda attempt: 1

    response = getattr(client, method)("/page")

    assert response.status_code == 200, response.content
    assert (runs["before"], runs["page"]) == (2, 1)


def test_a_post_cut_inside_its_view_is_never_repeated(client):
    """A view that is no operation may have written anything before the cut."""
    script["page"] = always_cut

    response = client.post("/page")

    assert response.status_code == 503
    assert response.content == UNKNOWN.encode()
    assert int(response["Retry-After"]) > 0
    assert runs["page"] == 1


def test_a_get_that_ran_a_command_is_never_repeated(client):
    """A GET is safe to repeat only while it writes nothing: the command already committed stays once. A page may write
    outside its operations, so it never says it was saved."""
    script["write"] = inserts
    script["page"] = always_cut

    response = client.get("/page-after-a-command")

    assert response.status_code == 503
    assert response.content == UNKNOWN.encode()
    assert (runs["write"], runs["page"]) == (1, 1)
    assert things_in_the_database() == 1
