"""Live queries of the test-only app: which events re-run them."""

from live.live_registry import live

live("testapp.thing.list", on=["testapp.thing.created"])
