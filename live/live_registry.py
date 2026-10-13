"""Which queries can be subscribed to over ``/api/live`` and which events re-run them.

Each app declares its live queries in ``live.py``::

    live("demo.item.list", on=["demo.item.created", "demo.item.updated"])

``LiveConfig.ready()`` imports every app's ``live.py``. An app may import its ``live.py`` before its
``queries.py``, so whether the operation exists, is a query and has a permission is validated later,
by :meth:`LiveRegistry.check` (system check E004), not at declaration time.
"""

from collections.abc import Iterable

from live.errors import LiveMisuse
from live.operations import NAME_RE, registry

#: Event name meaning "anything may have changed" (e.g. a notification too big to list its events).
ALL_EVENTS = "*"


class LiveRegistry:
    def __init__(self) -> None:
        self.subscribable: dict[str, list[str]] = {}
        self._by_event: dict[str, set[str]] | None = None

    def register(self, op_name: str, *, on: list[str]) -> None:
        if not isinstance(on, list) or not on or not all(isinstance(event, str) for event in on):
            raise LiveMisuse(f"live({op_name!r}): 'on' must be a non-empty list of event names.")
        if op_name in self.subscribable:
            raise LiveMisuse(f"live({op_name!r}) is already declared; list all its events in one call.")
        self.subscribable[op_name] = list(on)
        self._by_event = None

    def affected(self, names: Iterable[str]) -> set[str]:
        """The live queries that one of ``names`` may change; ``"*"`` affects all of them."""
        names = set(names)
        if ALL_EVENTS in names:
            return set(self.subscribable)
        index = self._index()
        return {op_name for name in names for op_name in index.get(name, ())}

    def is_subscribable(self, op_name: str) -> bool:
        return op_name in self.subscribable

    def check(self) -> list[str]:
        """Every misdeclared live query, as one message each (empty when all is well)."""
        errors = []
        for op_name, events in self.subscribable.items():
            op = registry.get(op_name)
            if op is None:
                errors.append(f"live({op_name!r}): unknown operation.")
            else:
                if op.kind != "query":
                    errors.append(f"live({op_name!r}): only a query can be live, not a {op.kind}.")
                if op.permission is None:
                    errors.append(f"live({op_name!r}): a live query needs a permission.")
            errors.extend(
                f"live({op_name!r}): event {event!r} must be <app>.<entity>.<fact>."
                for event in events
                if not NAME_RE.match(event)
            )
        return errors

    def clear(self) -> None:
        """Forget every live query (tests only)."""
        self.subscribable.clear()
        self._by_event = None

    def _index(self) -> dict[str, set[str]]:
        if self._by_event is None:
            index: dict[str, set[str]] = {}
            for op_name, events in self.subscribable.items():
                for event in events:
                    index.setdefault(event, set()).add(op_name)
            self._by_event = index
        return self._by_event


live_registry = LiveRegistry()


def live(op_name: str, *, on: list[str]) -> None:
    """Declare ``op_name`` as a live query, re-run after any of the events ``on``."""
    live_registry.register(op_name, on=on)
