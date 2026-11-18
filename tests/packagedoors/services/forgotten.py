"""The package's __init__ does not import this module, so its operation is never registered (live.E021)."""

from live.context import OperationContext
from live.operations import INTERNAL, operation

from tests.packagedoors.schemas import Level


@operation("packagedoors.forgotten.adjust", kind="command", permission=None, input=Level, output=Level, ai=INTERNAL)
def adjust(ctx: OperationContext, data: Level) -> Level:
    return data
