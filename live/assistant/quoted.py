"""What a text names by quoting one text for another (``quoted_texts``)."""

import re
from collections.abc import Iterable

from live.assistant.stemming import _concept, _groups

#: A text between quotes, in any of the marks people type.
_QUOTED = r"(?:«[^«»]+»|\"[^\"]+\"|“[^“”]+”|‘[^‘’]+’|'[^']+')"
#: One quoted text said for another: «cambia «A» por «B»», «change "A" to "B"», «pon «B» en vez de «A»».
_FOR_ANOTHER = re.compile(rf"{_QUOTED}\s+(?:por|a|en vez de|en lugar de|to|with|for|instead of)\s+{_QUOTED}")


def quoted_texts(texts: Iterable[str], synonyms: Iterable[Iterable[str]] = ()) -> frozenset[frozenset[str]]:
    """A text, when ``texts`` quote one text said for another: «cambia «Sin cilantro» por «Nada de cilantro»» changes
    a text as «cambia el texto «Sin cilantro» por «Nada de cilantro»» does, though it only says the texts
    (ERPlora/live#167)."""
    if not any(_FOR_ANOTHER.search(text) for text in texts):
        return frozenset()
    return frozenset({_concept("text", _groups(synonyms))})
