"""MCP snapshot lifecycle tests."""

import asyncio
from unittest.mock import patch

from mcp.types import Tool as McpBaseTool

from azents.core.tools import McpToolkitConfig, TurnContext
from azents.engine.tools.mcp import McpToolkit


def _tool(name: str) -> McpBaseTool:
    """Create MCP tool fixture."""
    return McpBaseTool(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


def _context() -> TurnContext:
    """Create turn context fixture."""
    return TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="model",
        run_id="run-1",
        session_id="session-1",
        publish_event=_publish,
    )


async def _publish(_event: object) -> None:
    """No-op event publish."""


async def _wait_refresh(toolkit: McpToolkit) -> None:
    """Wait for MCP background refresh task."""
    task = toolkit._bg_task  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    if task is not None:
        await task


async def test_update_context_returns_immediately_without_snapshot() -> None:
    """Slow MCP list_tools does not block request preparation."""
    started = asyncio.Event()
    continue_list = asyncio.Event()

    async def slow_list_tools(
        *_args: object, **_kwargs: object
    ) -> tuple[list[object], bool]:
        started.set()
        await continue_list.wait()
        return ([_tool("alpha")], False)

    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none")
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        side_effect=slow_list_tools,
    ):
        async with toolkit:
            await asyncio.wait_for(started.wait(), timeout=1)
            state = await asyncio.wait_for(
                toolkit.update_context(_context()), timeout=1
            )
            assert state.tools == []
            assert state.prompt == ""

            continue_list.set()


async def test_background_refresh_success_exposes_sorted_tools_next_turn() -> None:
    """Successful background refresh exposes deterministic tool order."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none")
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        return_value=([_tool("zeta"), _tool("alpha")], False),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)

    state = await toolkit.update_context(_context())

    assert [tool.spec.name for tool in state.tools] == ["alpha", "zeta"]
    assert state.prompt == ""


async def test_refresh_failure_preserves_previous_successful_snapshot() -> None:
    """Failed refresh keeps the previous successful tool snapshot."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none")
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        return_value=([_tool("alpha")], False),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        side_effect=RuntimeError("boom"),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)

    state = await toolkit.update_context(_context())

    assert [tool.spec.name for tool in state.tools] == ["alpha"]
    assert state.prompt == ""


async def test_failed_refresh_without_snapshot_exposes_no_retry_tool_or_prompt() -> (
    None
):
    """Initial MCP failure exposes no loading/retry/status pseudo-tool."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none")
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        side_effect=RuntimeError("boom"),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)

    state = await toolkit.update_context(_context())

    assert state.tools == []
    assert state.prompt == ""
