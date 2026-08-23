"""MCP discovery tests."""

from inspect import signature

from azents.core.mcp_discovery import register_client


def test_register_client_uses_azents_default_name() -> None:
    """Use Azents as the default dynamic client registration name."""
    parameter = signature(register_client).parameters["client_name"]

    assert parameter.default == "Azents"
