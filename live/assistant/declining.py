"""What the model hears of a write whose card the person answered without a yes: nothing ran, and why."""

from typing import Protocol

from live.assistant.cards import confirmed
from live.assistant.running import ToolOutcome, error_content

#: A «Cancel», or the word of a dangerous card typed wrong. Said as «not confirmed», the model told it as a yes that
#: never arrived («the confirmation did not reach the system») or asked to confirm on a card no longer on the screen.
NOT_CONFIRMED = (
    "The person said no on the card and the card is closed: nothing was done. Say it was not done, and do not tell them "
    "to confirm it."
)
STOPPED = "The person stopped this request: nothing more was done."
NOT_FROM_THE_CHAT = "This cannot be done from the chat (it names no record): nothing was done. Say where it is done."


class Decision(Protocol):
    """The person's answer to a card: ``accepted``, the word typed when the card asks for one, «Cancel all» (``stop``)."""

    accepted: bool
    typed: str
    stop: bool


def refusal(outcome: str, code: str, message: str) -> ToolOutcome:
    """A tool that did not run, told to the model in the same envelope as an operation's error."""
    return ToolOutcome(outcome, code, error_content(code, message))


def stopped() -> ToolOutcome:
    """«Cancel all»: the write it answers and every one the request still had pending."""
    return refusal("cancelled", "base.assistant_stopped", STOPPED)


def declined(card: dict, decision: Decision) -> ToolOutcome | None:
    """What ``decision`` leaves undone of the write behind ``card``: one that names no record, «Cancel all», a «no» or a
    word typed wrong; ``None`` when it is a yes to run."""
    if card["blocked"]:
        return refusal("cancelled", "base.assistant_not_from_chat", NOT_FROM_THE_CHAT)
    if decision.stop:
        return stopped()
    if not decision.accepted or not confirmed(card, decision.typed):
        return refusal("cancelled", "base.assistant_not_confirmed", NOT_CONFIRMED)
    return None
