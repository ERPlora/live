"""The assistant's mechanics that do not depend on a gateway:
the Hub's assistant and the SaaS's panel use the same ones, each with its own tools and its own words.

- **Its tools** (``catalog``) are the operations of the apps on (``active_labels``) that this person may run (the
  operation's own permission), told to the model by their ``ai=`` (``is_tool``: an ``AI``, never ``INTERNAL``) and
  never what the project keeps out of the chat (``not_from_chat``). A turn offers only the few of what was asked
  (``relevant``, at most ``MAX_TOOLS``), never the whole catalogue. A tool runs as the person, by its own operation
  (``run_tool``): the same permission, transaction and refusals as the button on the screen.
- **A write never runs without the person's yes**: its card (``card``) says what it will send, each datum by its name
  in the person's language (the title its schema gives it, else the name its app's models give that field: their
  metadata, no query) and in words (``Words``: a moment, a record, an amount, as the project says them; a value of a
  closed list by the label its app's models give it); a secret hidden; an attempt key left out. ``risk="high"`` asks to
  type a word in the person's language (``CONFIRM_WORD``) or, over records named by ``ids``, how many; such a write
  that names no record is not done from the chat (``blocked``). Such a write may show what it will do (``preview``): a
  read of its own app its ``ai=`` names, run as the person before the card. A card is drawn only for data its operation
  takes (``invalid_arguments``): what it would refuse goes back to the model, which asks again with it corrected.
  A card answered without a yes runs nothing, and the model hears why (``declined``): the person's no on a card that is
  closed, «Cancel all» (``stopped``) or a write not done from the chat, in the envelope of an operation's error
  (``refusal``).
- **Words** (``Words``): the project says a moment, a record and an amount its own way (the Hub: at its business's
  hour, by the read a schema marks, in its business's currency); ``PlainWords`` reads nothing — amounts in euros with
  two decimals, moments at UTC as Django's formats of the language write them, a record left out.
"""

from live.assistant.cards import (
    PlainWords,
    Words,
    blocked,
    card,
    confirmed,
    field,
    said,
)
from live.assistant.declining import (
    declined,
    refusal,
    stopped,
)
from live.assistant.fields import (
    ATTEMPT_KEY,
    CHOICES_OF,
    HIDDEN,
    LEFT_OUT,
    MOMENTS,
    MONEY,
    NAME_OF,
    NAMED,
    OWN_WORDS,
    REFERS,
    choice_label,
    choices_of,
    fitting,
    generated_title,
    hidden,
    is_attempt_key,
    is_money,
    is_signed,
    is_uuid,
    label,
    model_fields,
    own_title,
    refers_of,
    resolved,
    sends_amount,
    verbose_name,
)
from live.assistant.money import _as_present
from live.assistant.ranking import (
    _asks_stems,
    _relevant,
    app_words,
    relevant,
)
from live.assistant.reading import (
    Asked,
    asked,
)
from live.assistant.running import (
    NOT_FITTING,
    ToolOutcome,
    error_content,
    invalid_arguments,
    preview,
    rounds,
    run,
    run_tool,
)
from live.assistant.stemming import (
    _concept,
    _plain,
    _sentences,
    _stems_of,
    stem,
    stems,
)
from live.assistant.tools import (
    CONFIRM_WORD,
    MAX_RESULT_CHARS,
    MAX_ROUNDS,
    MAX_TOOLS,
    SEPARATOR,
    asks_of,
    catalog,
    config_of,
    description,
    input_schema,
    is_tool,
    named,
    operation_of,
    output_schema,
    preview_of,
    risk,
    tool_name,
    tool_spec,
)
from live.assistant.vocabulary import (
    HOWTO_POINTS,
    QUESTION_WORDS,
    READ_VERBS,
    STOP_WORDS,
    SWITCHES,
    SYNONYMS,
    VERBS,
)
