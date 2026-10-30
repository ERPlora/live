"""Read operations of the test-only app."""

from django.utils.translation import gettext
from live.context import OperationContext
from live.errors import NotFound
from live.operations import AI, INTERNAL, operation

from tests.testapp.models import Thing
from tests.testapp.schemas import ThingGetIn, ThingIn, ThingListIn, ThingListOut, ThingOut


@operation(
    "testapp.thing.list",
    kind="query",
    permission="testapp.view",
    input=ThingListIn,
    output=ThingListOut,
    ai=AI(description="Lists the things, by name."),
)
def list_things(ctx: OperationContext, params: ThingListIn) -> dict:
    return {"rows": list(Thing.objects.order_by("id")[: params.limit])}


@operation(
    "testapp.thing.get",
    kind="query",
    permission="testapp.view",
    input=ThingGetIn,
    output=ThingOut,
    ai=AI(description="One thing, by its id."),
)
def get_thing(ctx: OperationContext, params: ThingGetIn) -> Thing:
    """Its NotFound message is translated (tests/testapp/locale/es/LC_MESSAGES/django.po)."""
    thing = Thing.objects.filter(id=params.id).first()
    if thing is None:
        raise NotFound(gettext("Thing not found."))
    return thing


@operation(
    "testapp.thing.sneaky_write",
    kind="query",
    permission="testapp.view",
    input=ThingIn,
    output=ThingOut,
    ai=INTERNAL,
)
def sneaky_write(ctx: OperationContext, data: ThingIn) -> Thing:
    """Deliberately broken: a query that writes, so the READ ONLY test can see it fail."""
    return Thing.objects.create(name=data.name)
