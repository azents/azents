"""Mock MCP server fixture compatibility tests."""

from mcp.server.mcpserver import MCPServer

from fixtures.mock_mcp_server import server


def test_mock_mcp_server_uses_v2_server_api() -> None:
    """The fixture imports and constructs the MCP v2 server."""
    assert isinstance(server, MCPServer)
