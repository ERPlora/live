"""Input and output schemas of the test-only app."""

from ninja import Field, Schema


class ThingIn(Schema):
    name: str


class ThingOut(Schema):
    id: int
    name: str


class ThingGetIn(Schema):
    id: int


class ThingListIn(Schema):
    limit: int = Field(50, ge=1, le=100)


class ThingListOut(Schema):
    rows: list[ThingOut]
