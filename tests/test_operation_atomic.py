"""``live.operations.atomic``: a savepoint (or a transaction) on the alias the code running now works on.

What a ``services.py`` writes instead of ``transaction.atomic()``, whose alias is ``default``: with
``LIVE["operation_database"]`` the operation's transaction is not on ``default`` (hub-next phase 2: the hub's own
database), and a bare ``transaction.atomic()`` around a write that may fail (``try: with atomic(): create… except
IntegrityError:``) opens another transaction on ``default`` instead of a savepoint of the operation's: the error aborts
the operation's transaction and every write after it fails. The alias is the project's ``LIVE["current_database"]``
(hub-next: the active ``use_hub``'s, ``HubContextMissing`` without one; inside an operation, the one its transaction is
open on), else the running operation's, else ``default``, as the SaaS keeps it. Never ``default`` by omission.
"""

import threading
from contextlib import contextmanager
from contextvars import ContextVar

import pytest
from django.db import IntegrityError, connections, transaction
from ninja import Schema

from live import operations
from live.context import OperationContext, Scope
from live.errors import LiveMisuse
from live.operations import atomic, current_alias, operation, registry
from tests.testapp.models import Thing

OPERATION_HOOK = "tests.test_operation_atomic.on_the_active_alias"
CURRENT_HOOK = "tests.test_operation_atomic.the_active_alias"
SCOPE = Scope("host", "a")

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)

#: The test's database context, as the Hub's ``use_hub``: unset, the project's hook refuses to guess.
_active: ContextVar[str | None] = ContextVar("test_active_alias", default=None)


class NoContext(RuntimeError):
    """The test project's ``HubContextMissing``."""


def the_active_alias() -> str:
    """The test's ``LIVE["current_database"]``: the active context's alias, an error without one."""
    alias = _active.get()
    if alias is None:
        raise NoContext("no database context")
    return alias


@contextmanager
def on_the_active_alias(op, ctx):
    """The test's ``LIVE["operation_database"]``: the operation runs on ``other`` and the context says so."""
    token = _active.set("other")
    try:
        yield "other"
    finally:
        _active.reset(token)


@contextmanager
def entered(alias: str):
    token = _active.set(alias)
    try:
        yield
    finally:
        _active.reset(token)


class Empty(Schema):
    pass


class Seen(Schema):
    default_atomic: bool = False
    other_atomic: bool = False
    other_savepoints: int = 0


@pytest.fixture(autouse=True)
def isolated_registry():
    saved = dict(registry)
    yield
    registry.clear()
    registry.update(saved)


@pytest.fixture
def hooked(settings):
    settings.LIVE = {**settings.LIVE, "operation_database": OPERATION_HOOK, "current_database": CURRENT_HOOK}


def declare(name: str, fn, *, database: bool = True):
    fn.__module__ = "tests.fakeapp.services"
    declared = operation(
        name, kind="command", permission=None, input=Empty, output=Seen, ai=operations.INTERNAL, database=database
    )
    return declared(fn)


def ctx() -> OperationContext:
    return OperationContext(scope=SCOPE, actor="system", permissions=frozenset({"*"}))


def seen(**extra) -> dict:
    return {
        "default_atomic": connections["default"].in_atomic_block,
        "other_atomic": connections["other"].in_atomic_block,
        "other_savepoints": len(connections["other"].savepoint_ids),
        **extra,
    }


def test_without_the_settings_it_opens_on_default_as_the_saas_keeps_it():
    with atomic():
        inside = seen()

    assert current_alias() == "default"
    assert (inside["default_atomic"], inside["other_atomic"]) == (True, False)


def test_with_only_the_operation_database_it_opens_on_the_running_operations_alias(settings):
    settings.LIVE = {**settings.LIVE, "operation_database": OPERATION_HOOK}

    def probe(ctx, data):
        with atomic():
            return seen()

    op = declare("testapp.atomic.operation_alias", probe)

    result = op(ctx(), Empty())
    assert (result.default_atomic, result.other_atomic, result.other_savepoints) == (False, True, 1)


@pytest.mark.usefixtures("hooked")
def test_inside_an_operation_it_is_a_savepoint_of_the_operations_transaction_never_on_default():
    def probe(ctx, data):
        before = len(connections["other"].savepoint_ids)
        with atomic():
            inside = seen()
        return {**inside, "other_savepoints": inside["other_savepoints"] - before}

    op = declare("testapp.atomic.savepoint", probe)

    result = op(ctx(), Empty())
    assert (result.default_atomic, result.other_atomic, result.other_savepoints) == (False, True, 1)


@pytest.mark.usefixtures("hooked")
def test_an_integrity_error_caught_around_it_leaves_the_operations_transaction_usable():
    def recover(ctx, data):
        things = Thing.objects.db_manager("other")
        first = things.create(name="first")
        try:
            with atomic():
                things.create(pk=first.pk, name="again")
        except IntegrityError:
            pass
        things.create(name="after")
        return seen()

    op = declare("testapp.atomic.recover", recover)

    op(ctx(), Empty())
    assert sorted(Thing.objects.using("other").values_list("name", flat=True)) == ["after", "first"]


@pytest.mark.usefixtures("hooked")
def test_outside_an_operation_the_projects_current_database_decides():
    with entered("other"), atomic():
        inside = seen()

    assert (inside["default_atomic"], inside["other_atomic"]) == (False, True)


@pytest.mark.usefixtures("hooked")
def test_without_a_context_the_projects_error_comes_through_and_nothing_opens():
    ran = []

    with pytest.raises(NoContext), atomic():
        ran.append("body")

    assert ran == []
    assert connections["default"].in_atomic_block is False


@pytest.mark.usefixtures("hooked")
def test_a_context_entered_inside_an_operation_is_where_it_opens():
    def nested(ctx, data):
        with entered("default"), atomic():
            return seen()

    op = declare("testapp.atomic.nested", nested)

    result = op(ctx(), Empty())
    assert (result.default_atomic, result.other_atomic) == (True, True)


@pytest.mark.usefixtures("hooked")
def test_an_operation_that_touches_no_database_has_nothing_to_open_it_in():
    def wait(ctx, data):
        with atomic():
            return seen()

    op = declare("testapp.atomic.wait", wait, database=False)

    with pytest.raises(LiveMisuse, match=r"testapp\.atomic\.wait touches no database"):
        op(ctx(), Empty())


def test_a_current_database_that_cannot_be_imported_is_a_misuse(settings):
    settings.LIVE = {**settings.LIVE, "current_database": "tests.nowhere.at_all"}

    with pytest.raises(LiveMisuse, match=r'LIVE\["current_database"\]'):
        current_alias()


def test_as_a_decorator_it_reads_the_alias_when_called_not_when_declared(settings):
    @atomic
    def bare(depth: int) -> list[dict]:
        here = [seen()]
        return here + (bare(depth - 1) if depth else [])

    @atomic()
    def called() -> dict:
        return seen()

    settings.LIVE = {**settings.LIVE, "current_database": CURRENT_HOOK}
    with entered("other"):
        levels = bare(1)
        once = called()

    assert [(level["other_atomic"], level["other_savepoints"]) for level in levels] == [(True, 0), (True, 1)]
    assert (once["default_atomic"], once["other_atomic"]) == (False, True)
    assert bare.__name__ == "bare"


def test_savepoint_and_durable_go_through_to_django():
    def savepoints() -> list[str]:
        # Django notes a block without a savepoint as None.
        return [sid for sid in connections["default"].savepoint_ids if sid is not None]

    with transaction.atomic():
        before = len(savepoints())
        with atomic(savepoint=False):
            without_savepoint = len(savepoints()) - before
        with atomic():
            with_savepoint = len(savepoints()) - before
        with pytest.raises(RuntimeError, match="durable"), atomic(durable=True):
            pass

    assert (without_savepoint, with_savepoint) == (0, 1)


def test_it_takes_no_alias():
    with pytest.raises(LiveMisuse, match="takes no alias"):
        atomic("other")


def test_a_decorated_function_called_from_two_threads_keeps_each_ones_alias(settings):
    settings.LIVE = {**settings.LIVE, "current_database": CURRENT_HOOK}
    first_in, second_in, first_out = threading.Event(), threading.Event(), threading.Event()
    results: dict[str, dict] = {}
    errors: list[BaseException] = []

    @atomic
    def hold(alias: str) -> dict:
        if alias == "default":
            first_in.set()
            second_in.wait(5)
        else:
            second_in.set()
            first_out.wait(5)
        return seen()

    def run(alias: str) -> None:
        try:
            with entered(alias):
                results[alias] = hold(alias)
                # Each thread's block ends on its own connection: none is left open.
                results[alias]["left_open"] = connections[alias].in_atomic_block
        except BaseException as exc:  # noqa: BLE001 - handed to the test's thread
            errors.append(exc)
        finally:
            if alias == "default":
                first_out.set()
            connections.close_all()

    first = threading.Thread(target=run, args=("default",))
    first.start()
    first_in.wait(5)
    second = threading.Thread(target=run, args=("other",))
    second.start()
    first.join(10)
    second.join(10)

    assert errors == []
    assert {
        alias: (seen_["default_atomic"], seen_["other_atomic"], seen_["left_open"]) for alias, seen_ in results.items()
    } == {"default": (True, False, False), "other": (False, True, False)}
