"""Cutting the database for real, against the real Postgres, without mocking what can be provoked.

``pg_terminate_backend`` is the server cutting a connection, ``default_transaction_read_only`` the writer refusing
writes, and ``DatabaseDoor`` (a TCP door in front of Postgres) the network going down and the answer to a COMMIT that
never comes back.
"""

import socket
import threading
import time

import psycopg
from django.db import connections
from psycopg import sql

from tests.testapp.models import Thing

#: The DSN of the test database, for the connection that cuts the others (never the one being cut).
admin_dsn: list[str] = []


def _admin() -> psycopg.Connection:
    """The connection that cuts the others: never read only itself, or it could not undo ``set_read_only``."""
    return psycopg.connect(admin_dsn[0], autocommit=True, options="-c default_transaction_read_only=off")


def terminate(alias: str = "default") -> None:
    """The server cuts this thread's connection, as a restart or a switchover does (57P01)."""
    connections[alias].ensure_connection()
    pid = connections[alias].connection.info.backend_pid
    with _admin() as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
        deadline = time.monotonic() + 5
        while admin.execute("SELECT 1 FROM pg_stat_activity WHERE pid = %s", (pid,)).fetchone():
            assert time.monotonic() < deadline, "the backend outlived pg_terminate_backend"
            time.sleep(0.01)


def set_read_only(on: bool) -> None:
    """New sessions of the test database are read only, as the old writer is during a switchover."""
    name = sql.Identifier(connections["default"].settings_dict["NAME"])
    statement = "ALTER DATABASE {} SET default_transaction_read_only = on" if on else "ALTER DATABASE {} RESET default_transaction_read_only"
    with _admin() as admin:
        admin.execute(sql.SQL(statement).format(name))


def things_in_the_database() -> int:
    with _admin() as admin:
        return admin.execute("SELECT count(*) FROM testapp_thing").fetchone()[0]


class DatabaseDoor:
    """A TCP door in front of Postgres: closing it is the network going down; ``lose_commit_answer`` lets a COMMIT reach
    the server, which applies it, and closes everything before its answer comes back."""

    def __init__(self, host: str, port: int) -> None:
        self.target = (host, port)
        self.lose_commit_answer = False
        self.port = 0
        self._listener: socket.socket | None = None
        self._sockets: list[socket.socket] = []
        self._answers_lost = threading.Event()
        self.open()

    def open(self) -> None:
        self._listener = socket.create_server(("127.0.0.1", self.port))
        self.port = self._listener.getsockname()[1]
        threading.Thread(target=self._accept, args=(self._listener,), daemon=True).start()

    def close(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            # On Linux a close alone leaves the blocked accept, and with it the port, alive: the shutdown wakes it
            # (EINVAL). macOS wakes it on close and refuses the shutdown of a listening socket (ENOTCONN).
            try:
                listener.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            listener.close()
        for each in self._sockets:
            try:
                each.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            each.close()
        self._sockets.clear()

    def _accept(self, listener: socket.socket) -> None:
        while True:
            try:
                client, _ = listener.accept()
            except OSError:
                return
            if self._listener is not listener:
                # Slipped in while the door was closing: the door is closed.
                client.close()
                return
            server = socket.create_connection(self.target)
            self._sockets += [client, server]
            threading.Thread(target=self._to_server, args=(client, server), daemon=True).start()
            threading.Thread(target=self._to_client, args=(server, client), daemon=True).start()

    def _to_server(self, client: socket.socket, server: socket.socket) -> None:
        try:
            while chunk := client.recv(65536):
                if self.lose_commit_answer and b"COMMIT" in chunk:
                    self._answers_lost.set()
                    server.sendall(chunk)
                    # The server reads it and applies it; the client only ever sees the connection go.
                    time.sleep(0.2)
                    self.close()
                    return
                server.sendall(chunk)
        except OSError:
            pass

    def _to_client(self, server: socket.socket, client: socket.socket) -> None:
        try:
            while chunk := server.recv(65536):
                if not self._answers_lost.is_set():
                    client.sendall(chunk)
        except OSError:
            pass


def cut_once(attempt: int) -> int:
    """Cut on the first run, a good answer after it."""
    if attempt == 1:
        terminate()
    return Thing.objects.count() + 7


def always_cut(attempt: int) -> int:
    terminate()
    return Thing.objects.count()


def insert_then_cut_once(attempt: int) -> int:
    Thing.objects.create(name="once")
    if attempt == 1:
        terminate()
    return Thing.objects.count()
