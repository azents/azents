"""Live MCP helpers for mock HTTP MCP server toolkit config.

Stage 3 MCP tests verify that a tool call can connect to a real HTTP-based MCP
server. Production ``toolkit_type="mcp"`` uses streamable HTTP transport, and
this fixture exercises that same transport path.

stdio MCP providers such as Sentry or Notion rely on internal toolkit paths and
are not verified by this testenv helper; they belong in dedicated toolkit E2E
tests.

Provided helpers:

- ``MOCK_MCP_SCRIPT`` — path to ``testenv/azents/fixtures/mock_mcp_server.py``
- ``DEFAULT_MOCK_PORT`` — default 9100; env ``MOCK_MCP_PORT`` may override it
- ``Mcp.server_url(port)`` — returns the mock server streamable HTTP URL
- ``Mcp.toolkit_config(server_url)`` — returns the public API
  ``ToolkitConfigCreateRequest.config`` dict
  (``{"server_url", "auth_type"}``)

This module does not start or stop the mock server. The caller should run it,
for example with ``uv run python fixtures/mock_mcp_server.py`` or
``subprocess.Popen``, and own its lifecycle.
"""

from dataclasses import dataclass
from pathlib import Path

from testenv.runtime_config import TestenvConfig

_TESTENV_ROOT = Path(__file__).resolve().parent.parent.parent

#: Path to the mock MCP server fixture.
MOCK_MCP_SCRIPT: Path = _TESTENV_ROOT / "fixtures" / "mock_mcp_server.py"

#: Default bind port for the fixture.
DEFAULT_MOCK_PORT = 9100

#: FastMCP streamable HTTP path used by the fixture.
DEFAULT_STREAMABLE_PATH = "/mcp"


@dataclass(frozen=True)
class Mcp:
    """Mock HTTP MCP helper that builds toolkit_config payloads.

    Used as ``TestenvClient.mcp``. It is stateless.
    """

    config: TestenvConfig
    script_path: Path = MOCK_MCP_SCRIPT
    default_port: int = DEFAULT_MOCK_PORT
    default_path: str = DEFAULT_STREAMABLE_PATH

    def server_url(
        self,
        *,
        host: str = "localhost",
        port: int | None = None,
    ) -> str:
        """Return the mock MCP server streamable HTTP URL.

        The devserver usually reaches the testenv host through ``localhost``.
        Container-internal callers can override the host, for example with
        ``host.docker.internal``.
        """
        effective_port = port if port is not None else self.default_port
        return f"http://{host}:{effective_port}{self.default_path}"

    def toolkit_config(
        self,
        *,
        server_url: str | None = None,
        auth_type: str = "none",
    ) -> dict[str, object]:
        """Return the dict used as ``ToolkitConfigCreateRequest.config``.

        This matches the production ``McpToolkitConfig`` wire format, where
        ``server_url`` and ``auth_type`` are required fields.
        """
        return {
            "server_url": server_url or self.server_url(),
            "auth_type": auth_type,
        }
