"""``live.asgi.ignore_root_path``: the client never decides the script prefix (ERPlora/hub#2, ERPlora/saas#2).

Daphne copies its client's own ``Daphne-Root-Path`` header into ``scope["root_path"]``, and Django
strips that prefix from the path and puts it in front of every URL it builds. The wrapper hands the
inner app a scope whose ``root_path`` is always empty, so a request is answered for its real path.
"""

from live.asgi import ignore_root_path


class RecordingApp:
    """An inner ASGI app that keeps what it was called with."""

    def __init__(self):
        self.calls = []

    async def __call__(self, scope, receive, send):
        self.calls.append((scope, receive, send))


async def receive():
    return {"type": "http.request", "body": b"", "more_body": False}


async def send(message):
    return None


def http_scope(**extra):
    return {
        "type": "http",
        "method": "GET",
        "path": "/x/admin/",
        "headers": [(b"host", b"localhost")],
        **extra,
    }


async def test_a_root_path_from_the_client_reaches_the_app_empty():
    inner = RecordingApp()
    scope = http_scope(root_path="/x")

    await ignore_root_path(inner)(scope, receive, send)

    [(seen, _, _)] = inner.calls
    assert seen["root_path"] == ""
    assert {**seen, "root_path": "/x"} == scope


async def test_the_callers_scope_is_left_as_it_was():
    inner = RecordingApp()
    scope = http_scope(root_path="/x")

    await ignore_root_path(inner)(scope, receive, send)

    assert scope["root_path"] == "/x"
    assert inner.calls[0][0] is not scope


async def test_a_websocket_root_path_reaches_the_app_empty():
    inner = RecordingApp()
    scope = {
        "type": "websocket",
        "path": "/x/ws/print",
        "headers": [],
        "root_path": "/x",
    }

    await ignore_root_path(inner)(scope, receive, send)

    assert inner.calls[0][0]["root_path"] == ""
    assert inner.calls[0][0]["path"] == "/x/ws/print"


async def test_a_scope_without_root_path_reaches_the_app_with_an_empty_one():
    inner = RecordingApp()

    await ignore_root_path(inner)(http_scope(), receive, send)

    assert inner.calls[0][0]["root_path"] == ""


async def test_a_lifespan_scope_passes_untouched():
    inner = RecordingApp()
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}

    await ignore_root_path(inner)(scope, receive, send)

    assert inner.calls[0][0] is scope


async def test_receive_and_send_are_the_callers_own():
    inner = RecordingApp()

    await ignore_root_path(inner)(http_scope(root_path="/x"), receive, send)

    [(_, seen_receive, seen_send)] = inner.calls
    assert seen_receive is receive
    assert seen_send is send
