"""What a cut of the database answers: each outcome its own code, translated message and wait before trying
again."""

import pytest
from django.utils import translation
from live.database_cut import DatabaseCut
from live.errors import LiveMisuse

from tests.database_cut.project import APPLIED, UNAVAILABLE, UNKNOWN

pytestmark = pytest.mark.django_db(databases=["default", "other"], transaction=True)


@pytest.mark.parametrize("outcome", [{"repeatable": True}, {"repeatable": False}, {"repeatable": False, "applied": True}])
def test_the_message_is_translated(outcome):
    with translation.override("en"):
        english = DatabaseCut(**outcome).message
    with translation.override("es"):
        spanish = DatabaseCut(**outcome).message

    assert english and spanish and english != spanish


def test_each_outcome_says_its_own_thing():
    """Nothing applied, applied with its answer lost, or nobody can know: three codes, three messages."""
    outcomes = [DatabaseCut(repeatable=True), DatabaseCut(repeatable=False), DatabaseCut(repeatable=False, applied=True)]

    assert [cut.code for cut in outcomes] == [UNAVAILABLE, UNKNOWN, APPLIED]
    assert len({cut.message for cut in outcomes}) == 3


def test_applied_is_never_repeatable():
    with pytest.raises(LiveMisuse):
        DatabaseCut(repeatable=True, applied=True)


def test_only_what_ran_nothing_says_when_to_try_again_to_the_live_executor():
    """``OperationError.retry_after``: always ``None`` for a failure that may have done something."""
    assert DatabaseCut(repeatable=True).retry_after is not None
    assert DatabaseCut(repeatable=False).retry_after is None
    assert DatabaseCut(repeatable=False, applied=True).retry_after is None
