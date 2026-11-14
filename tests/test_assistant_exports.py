"""Code outside the package reads the assistant's names from ``live.assistant``, whichever of its modules defines them."""

from live import assistant

#: What the Hub and the SaaS import from ``live.assistant`` or read as an attribute of it, and what the rest of
#: ``live`` imports from it (``live.assistant_qa``, ``live.checks``).
READ_FROM_OUTSIDE = (
    "CHOICES_OF",
    "LEFT_OUT",
    "MAX_ROUNDS",
    "MAX_TOOLS",
    "MONEY",
    "NAMED",
    "NAME_OF",
    "PlainWords",
    "REFERS",
    "SEPARATOR",
    "ToolOutcome",
    "Words",
    "_asks_stems",
    "_relevant",
    "_stems_of",
    "app_words",
    "asked",
    "asks_of",
    "card",
    "catalog",
    "choice_label",
    "choices_of",
    "config_of",
    "confirmed",
    "description",
    "error_content",
    "field",
    "generated_title",
    "input_schema",
    "invalid_arguments",
    "is_money",
    "is_signed",
    "is_tool",
    "label",
    "named",
    "operation_of",
    "output_schema",
    "own_title",
    "preview",
    "preview_of",
    "refers_of",
    "relevant",
    "resolved",
    "risk",
    "rounds",
    "run",
    "run_tool",
    "sends_amount",
    "stem",
    "stems",
    "tool_name",
    "tool_spec",
    "verbose_name",
)


def test_every_name_read_from_outside_is_exported_by_the_package():
    assert [name for name in READ_FROM_OUTSIDE if not hasattr(assistant, name)] == []


def test_a_name_read_from_outside_is_never_one_of_the_packages_modules():
    assert [name for name in READ_FROM_OUTSIDE if type(getattr(assistant, name, None)) is type(assistant)] == []
