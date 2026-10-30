"""Write operations of the test-only app."""

from live.context import OperationContext
from live.errors import Conflict
from live.operations import AI, INTERNAL, operation
from live.outbox import record_event

from tests.testapp.models import Thing
from tests.testapp.schemas import ThingIn, ThingOut


@operation(
    "testapp.thing.create",
    kind="command",
    permission="testapp.manage",
    input=ThingIn,
    output=ThingOut,
    ai=AI(description="Creates a thing with its name."),
)
def create_thing(ctx: OperationContext, data: ThingIn) -> Thing:
    thing = Thing.objects.create(name=data.name)
    record_event(ctx, "testapp.thing.created", {"id": thing.id})
    return thing


@operation(
    "testapp.thing.create_twice_event",
    kind="command",
    permission="testapp.manage",
    input=ThingIn,
    output=ThingOut,
    ai=INTERNAL,
)
def create_thing_twice_event(ctx: OperationContext, data: ThingIn) -> Thing:
    """Records the same event twice: two outbox rows, one name in the notification."""
    thing = Thing.objects.create(name=data.name)
    record_event(ctx, "testapp.thing.created", {"id": thing.id})
    record_event(ctx, "testapp.thing.created", {"id": thing.id})
    return thing


@operation(
    "testapp.thing.fail_after_event",
    kind="command",
    permission="testapp.manage",
    input=ThingIn,
    output=ThingOut,
    ai=INTERNAL,
)
def fail_after_event(ctx: OperationContext, data: ThingIn) -> Thing:
    """Records an event and then fails, so the whole command rolls back."""
    thing = Thing.objects.create(name=data.name)
    record_event(ctx, "testapp.thing.created", {"id": thing.id})
    raise Conflict("The thing was rejected.", code="testapp.thing_rejected")
