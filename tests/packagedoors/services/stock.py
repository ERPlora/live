from live.context import OperationContext
from live.operations import INTERNAL, operation

from tests.packagedoors.schemas import Level


@operation("packagedoors.stock.adjust", kind="command", permission=None, input=Level, output=Level, ai=INTERNAL)
def adjust(ctx: OperationContext, data: Level) -> Level:
    return data
