#!/usr/bin/env python3
# ruff: noqa: E501
"""Mock streamable-HTTP MCP server for local and E2E tests.

The server exposes four tools:

- ``echo`` returns its input unchanged.
- ``info`` returns one environment variable from the server process.
- ``instance`` returns the fixture instance identity.
- ``error`` raises an intentional exception for failure-path tests.

Run it with ``uv run python fixtures/mock_mcp_server.py``. Configure the bind
address with ``MOCK_MCP_HOST`` and ``MOCK_MCP_PORT``; the MCP endpoint is
available at ``/mcp``.
"""

import os
import select
import threading

from mcp.server.mcpserver import MCPServer


class OneShotInstanceBarrier:
    """Hold one fixture call until its parent explicitly releases it."""

    def __init__(self, reached_fd: int | None, release_fd: int | None, timeout: float) -> None:
        if (reached_fd is None) != (release_fd is None):
            raise ValueError("MCP instance barrier requires both control descriptors.")
        self.reached_fd = reached_fd
        self.release_fd = release_fd
        self.timeout = timeout
        self.lock = threading.Lock()
        self.consumed = False

    def wait_once(self) -> None:
        """Announce the first call and wait for release, bounding hangs only."""
        with self.lock:
            if self.consumed:
                return
            self.consumed = True
        if self.reached_fd is None or self.release_fd is None:
            return
        os.write(self.reached_fd, b"R")
        readable, _, _ = select.select([self.release_fd], [], [], self.timeout)
        if not readable:
            raise TimeoutError("MCP instance barrier was not released.")
        if os.read(self.release_fd, 1) != b"R":
            raise RuntimeError("MCP instance barrier release channel was closed.")


_DEFAULT_HOST = os.environ.get("MOCK_MCP_HOST", "0.0.0.0")  # noqa: S104
_DEFAULT_PORT = int(os.environ.get("MOCK_MCP_PORT", "9100"))
_REACHED_FD = os.environ.get("MOCK_MCP_INSTANCE_REACHED_FD")
_RELEASE_FD = os.environ.get("MOCK_MCP_INSTANCE_RELEASE_FD")
_INSTANCE_BARRIER = OneShotInstanceBarrier(
    int(_REACHED_FD) if _REACHED_FD is not None else None,
    int(_RELEASE_FD) if _RELEASE_FD is not None else None,
    timeout=60,
)

server = MCPServer("azents-testenv-mock")


@server.tool()
def echo(text: str) -> str:
    """Echo the given text back unchanged.

    Used to verify the HTTP pipe between azents's MCP toolkit and this
    server is working end-to-end.
    """
    return text


@server.tool()
def info(key: str) -> str:
    """Return the value of a process environment variable on this server.

    Used to verify that server-side configuration is observable by the
    client when the toolkit is wired correctly. Returns an empty string
    when the variable is not set.
    """
    return os.environ.get(key, "")


@server.tool()
def instance() -> str:
    """Return a safe identity that distinguishes parallel fixture instances."""
    _INSTANCE_BARRIER.wait_once()
    return os.environ.get("MOCK_MCP_INSTANCE", "default")


@server.tool()
def error() -> str:  # noqa: RET503
    """Always raise RuntimeError.

    Used to verify that the failure path of the MCP tool call surfaces to
    ``function_call_item.output`` with an error-shaped content.
    """
    raise RuntimeError("intentional error from mock_mcp_server")


if __name__ == "__main__":
    server.run(
        transport="streamable-http",
        host=_DEFAULT_HOST,
        port=_DEFAULT_PORT,
        streamable_http_path="/mcp",
    )
