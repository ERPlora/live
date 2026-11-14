from live.context import OperationContext
from live.operations import INTERNAL, operation

from tests.packagedoors.schemas import Level


@operation("packagedoors.stock.level", kind="query", permission=None, input=Level, output=Level, ai=INTERNAL)
def level(ctx: OperationContext, params: Level) -> Level:
    return params
