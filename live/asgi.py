"""ASGI wrapper shared by hub-next and saas-next (ERPlora/hub#2, ERPlora/saas#2).

Daphne copies its client's own ``Daphne-Root-Path`` header into ``scope["root_path"]``, over the
server's ``--root-path``. Django takes that value as the script prefix: it strips it from the path it
resolves and puts it in front of every URL it builds (``reverse()``, redirects), so any client would
decide both. Both projects are served at the root of their host, so the wrapper empties
``root_path`` for every request. Serving under a prefix one day would be ``FORCE_SCRIPT_NAME``,
which Django reads before the scope.
"""

SCOPES_WITH_A_PATH = frozenset({"http", "websocket"})


def ignore_root_path(app):
    """``app`` with an empty ``root_path`` on HTTP and WebSocket scopes; anything else passes untouched."""

    async def application(scope, receive, send):
        if scope["type"] in SCOPES_WITH_A_PATH:
            scope = {**scope, "root_path": ""}
        return await app(scope, receive, send)

    return application
