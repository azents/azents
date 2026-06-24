#!/usr/bin/env python3
# ruff: noqa: E501
"""Mock HTTP MCP server — Stage 3 MCP translated translated translated.

MCP server translated testtranslated translated translated **translated translated translated HTTP MCP servertranslated
translated connectiontranslated tool translated calltranslated translated translated** translated verifytranslated translated translated server.
`mcp` SDK translated FastMCP + streamable HTTP transport translated usetranslated prod translated translated
path (public toolkit_type="mcp", auth_type="none") translated translated translated translated.

3 translated tool translated:

- ``echo(text: str) -> str`` — translated text translated translated translated.
- ``info(key: str) -> str`` — server translated environment translated `key` translated valuetranslated translated.
  credential / config translated path verifytranslated.
- ``error() -> None`` — translated exceptiontranslated raise. failure path translated.

### run

::

    uv run python fixtures/mock_mcp_server.py

environment translated port / host translated translated: ``MOCK_MCP_PORT=9100``,
``MOCK_MCP_HOST=0.0.0.0``. default translated pathtranslated ``/mcp``.

### connection

translated translated translated azents translated MCP toolkit config translated
``server_url="http://host.docker.internal:9100/mcp"`` +
``auth_type="none"`` translated registertranslated (translated ``http://localhost:9100/mcp`` —
devserver translated host translated translated translated).

translated document: ``docs/azents/design/llm-tool-execution.md``
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
    # streamable HTTP transport — mcp==1.26.0 translated
    server.run(transport="streamable-http")
