"""The moments of a tool's result, told on the clock of whoever asks (``run_tool``'s ``zone``).

The model repeats an hour as it reads it: a result in UTC made the assistant tell a bar in Madrid «15:18» for what
happened at 16:18 there. Given a zone, every moment of the result reaches the model on that clock, each with the offset
of its own date; everything else reads as ``model_dump_json`` writes it.
"""

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from live import assistant
from ninja import Schema

from tests.test_assistant import ctx, op

MADRID = ZoneInfo("Europe/Madrid")
#: 15:18 in UTC: 16:18 in Madrid in winter.
WINTER = dt.datetime(2026, 11, 22, 15, 18, tzinfo=dt.UTC)
#: 10:00 in UTC: 12:00 in Madrid in summer, with its own offset.
SUMMER = dt.datetime(2026, 7, 1, 10, 0, tzinfo=dt.UTC)


class VisitOut(Schema):
    at: dt.datetime
    by: str


class ReportOut(Schema):
    id: uuid.UUID
    opened_at: dt.datetime
    closed_at: dt.datetime | None
    day: dt.date
    total: Decimal
    state: Literal["open", "closed"]
    visits: list[VisitOut]
    extra: dict[str, dt.datetime]
    noted: dt.datetime


REPORT = {
    "id": uuid.UUID("0190a3b4-0000-7000-8000-000000000001"),
    "opened_at": WINTER,
    "closed_at": None,
    "day": dt.date(2026, 11, 22),
    "total": Decimal("12.50"),
    "state": "open",
    "visits": [{"at": SUMMER, "by": "Ana"}],
    "extra": {"last": WINTER},
    # A moment with no zone is told as it comes: nobody knows on which clock it was written.
    "noted": dt.datetime(2026, 11, 22, 9, 0),
}


def read(**kwargs) -> str:
    report = op("testapp.probe.report", kind="query", output=ReportOut, fn=lambda ctx, data: REPORT)
    outcome = assistant.run_tool(ctx("testapp.manage"), report, "{}", **kwargs)
    assert outcome.outcome == "ok"
    return outcome.content


def test_every_moment_of_a_result_reaches_the_model_on_the_clock_it_is_given():
    told = json.loads(read(zone=MADRID))
    assert told["opened_at"] == "2026-11-22T16:18:00+01:00"
    assert told["visits"][0]["at"] == "2026-07-01T12:00:00+02:00"
    assert told["extra"]["last"] == "2026-11-22T16:18:00+01:00"


def test_another_clock_tells_its_own_hour():
    told = json.loads(read(zone=ZoneInfo("America/Mexico_City")))
    assert told["opened_at"] == "2026-11-22T09:18:00-06:00"


def test_without_a_clock_a_result_reads_as_its_operation_wrote_it():
    assert read() == ReportOut.model_validate(REPORT).model_dump_json()


def test_on_a_clock_only_the_moments_change():
    as_written = json.loads(ReportOut.model_validate(REPORT).model_dump_json())
    told = json.loads(read(zone=MADRID))
    moments = {"opened_at", "visits", "extra"}
    assert {key: value for key, value in told.items() if key not in moments} == {
        key: value for key, value in as_written.items() if key not in moments
    }
    assert told["visits"][0]["by"] == "Ana"
    assert told["noted"] == "2026-11-22T09:00:00"
