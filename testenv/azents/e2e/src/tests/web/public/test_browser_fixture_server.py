"""Synthetic Browser page servers must tolerate accepted idle connections."""

import ast
import http.client
import socket
import socketserver
import threading
from contextlib import closing

import pytest

from tests.web.public.test_session_browser import _APP as BROWSER_APP
from tests.web.public.test_session_browser_confidential import _APP as CONFIDENTIAL_APP


def _fixture_server(application: str) -> socketserver.TCPServer:
    """Run the actual fixture declarations and server constructor on a free port."""
    module = ast.parse(application)
    serving = module.body.pop()
    assert isinstance(serving, ast.With)
    constructor = serving.items[0].context_expr
    assert isinstance(constructor, ast.Call)
    # Keep the actual server class and handler; change only the test's bind port.
    constructor.args[0] = ast.Tuple(
        elts=[ast.Constant("127.0.0.1"), ast.Constant(0)], ctx=ast.Load()
    )
    namespace: dict[str, object] = {}
    exec(compile(module, "<browser-fixture>", "exec"), namespace)
    expression = ast.fix_missing_locations(ast.Expression(constructor))
    server = eval(compile(expression, "<browser-fixture-server>", "eval"), namespace)
    assert isinstance(server, socketserver.TCPServer)
    return server


@pytest.mark.parametrize("application", [BROWSER_APP, CONFIDENTIAL_APP])
def test_browser_fixture_serves_navigation_with_an_accepted_idle_connection(
    application: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cross the real listener boundary without Docker or a browser process."""
    server = _fixture_server(application)
    accepted = threading.Event()
    get_request = server.get_request

    def record_accept() -> tuple[socket.socket, tuple[str, int]]:
        connection = get_request()
        accepted.set()
        return connection

    monkeypatch.setattr(server, "get_request", record_accept)
    host, port = server.server_address[:2]
    assert isinstance(host, str)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    idle: socket.socket | None = None
    try:
        idle = socket.create_connection((host, port), timeout=5)
        assert accepted.wait(5), "The speculative connection was not accepted"
        # The receipt proves the first connection is accepted before GET is sent.
        # A serial TCPServer blocks here until that idle connection is closed.
        with closing(http.client.HTTPConnection(host, port, timeout=5)) as client:
            client.request("GET", "/navigation")
            response = client.getresponse()
            assert response.status == 200
            assert b"<!doctype html>" in response.read()
    finally:
        if idle is not None:
            idle.close()
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive(), "The fixture server did not stop"
