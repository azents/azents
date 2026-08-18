#!/usr/bin/env python3
# ruff: noqa: E501
"""Mock streamable-HTTP MCP server for local and E2E tests.

The server exposes three tools:

- ``echo`` returns its input unchanged.
- ``info`` returns one environment variable from the server process.
- ``error`` raises an intentional exception for failure-path tests.

Run it with ``uv run python fixtures/mock_mcp_server.py``. Configure the bind
address with ``MOCK_MCP_HOST`` and ``MOCK_MCP_PORT``; the MCP endpoint is
available at ``/mcp``.
"""

import os

from mcp.server.fastmcp import FastMCP

_DEFAULT_HOST = os.environ.get("MOCK_MCP_HOST", "0.0.0.0")  # noqa: S104
_DEFAULT_PORT = int(os.environ.get("MOCK_MCP_PORT", "9100"))

server = FastMCP(
    "azents-testenv-mock",
    host=_DEFAULT_HOST,
    port=_DEFAULT_PORT,
    streamable_http_path="/mcp",
)


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
def error() -> str:  # noqa: RET503
    """Always raise RuntimeError.

    Used to verify that the failure path of the MCP tool call surfaces to
    ``function_call_item.output`` with an error-shaped content.
    """
    raise RuntimeError("intentional error from mock_mcp_server")


if __name__ == "__main__":
    server.run(transport="streamable-http")
