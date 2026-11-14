"""The package's __init__ does not import this module, so its operation is never registered (live.E021)."""

from live.context import OperationContext
from live.operations import INTERNAL, operation

from tests.packagedoors.schemas import Level


@operation("packagedoors.forgotten.level", kind="query", permission=None, input=Level, output=Level, ai=INTERNAL)
def level(ctx: OperationContext, params: Level) -> Level:
    return params
