"""Named like the other door: its command passes for one of an app's services.py, so it is live.E022."""

from live.context import OperationContext
from live.operations import INTERNAL, operation

from tests.packagedoors.schemas import Level


@operation("packagedoors.misplaced.adjust", kind="command", permission=None, input=Level, output=Level, ai=INTERNAL)
def adjust(ctx: OperationContext, data: Level) -> Level:
    return data
