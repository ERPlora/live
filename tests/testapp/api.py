"""Ninja routes of the test-only app: each route calls exactly one operation and holds no logic."""

from live.ninja import run_operation
from ninja import Path, Query, Router

from tests.testapp import queries, services
from tests.testapp.schemas import ThingGetIn, ThingIn, ThingListIn, ThingListOut, ThingOut

router = Router(tags=["testapp"])


@router.get("/things", response=ThingListOut, operation_id="testapp.thing.list")
async def list_things(request, params: Query[ThingListIn]):
    return await run_operation(request, queries.list_things, params)


@router.get("/things/{id}", response=ThingOut, operation_id="testapp.thing.get")
async def get_thing(request, params: Path[ThingGetIn]):
    return await run_operation(request, queries.get_thing, params)


@router.post("/things", response={201: ThingOut}, operation_id="testapp.thing.create")
async def create_thing(request, data: ThingIn):
    return await run_operation(request, services.create_thing, data)


# Deliberately bound to no operation: only the parity-negative test mounts it.
unbound_router = Router()


@unbound_router.get("/unbound", response=ThingListOut)
async def unbound(request):
    return {"rows": []}
