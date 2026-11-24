"""What the model hears of a write whose card the person answered without a yes (``live.assistant.declined``): nothing
ran, and why — their no on a card that is closed, «Cancel all», or a dangerous write that names no record."""

import json
from dataclasses import dataclass

from live import assistant


@dataclass(frozen=True)
class Decision:
    accepted: bool = True
    typed: str = ""
    stop: bool = False


def card(*, word: str = "", blocked: bool = False) -> dict:
    return {"confirm_word": word, "blocked": blocked}


def heard(outcome: assistant.ToolOutcome) -> tuple[str, dict]:
    return outcome.outcome, json.loads(outcome.content)["error"]


def test_a_cancel_is_the_persons_no_on_a_card_that_is_closed():
    """«Not confirmed by the person» read as a yes that never arrived, or as a card still waiting to be confirmed."""
    outcome, error = heard(assistant.declined(card(), Decision(accepted=False)))

    assert (outcome, error["code"]) == ("cancelled", "base.assistant_not_confirmed")
    said = error["message"]
    assert "The person said no on the card" in said
    assert "the card is closed" in said
    assert "nothing was done" in said
    assert "do not tell them to confirm it" in said
    assert not said.startswith("Not confirmed")


def test_the_word_of_a_dangerous_card_typed_wrong_is_a_no_as_well():
    no = assistant.declined(card(), Decision(accepted=False))

    assert assistant.declined(card(word="CONFIRM"), Decision(typed="CONFIRMA")) == no


def test_a_yes_leaves_nothing_undone():
    assert assistant.declined(card(), Decision()) is None
    assert assistant.declined(card(word="CONFIRM"), Decision(typed=" confirm ")) is None


def test_cancel_all_stops_the_request():
    outcome, error = heard(assistant.declined(card(), Decision(accepted=False, stop=True)))

    assert (outcome, error["code"]) == ("cancelled", "base.assistant_stopped")
    assert assistant.declined(card(), Decision(stop=True)) == assistant.stopped()


def test_a_dangerous_write_that_names_no_record_is_not_done_from_the_chat_whatever_the_answer():
    for decision in (Decision(typed="CONFIRM"), Decision(accepted=False), Decision(stop=True)):
        outcome, error = heard(assistant.declined(card(word="CONFIRM", blocked=True), decision))
        assert (outcome, error["code"]) == ("cancelled", "base.assistant_not_from_chat")


def test_a_refusal_goes_in_the_envelope_of_an_operations_error():
    told = assistant.refusal("refused", "not_available", "Not here.")

    assert (told.outcome, told.code) == ("refused", "not_available")
    assert json.loads(told.content) == {"error": {"code": "not_available", "message": "Not here."}}
