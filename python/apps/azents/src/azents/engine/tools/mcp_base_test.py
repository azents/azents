"""MCP snapshot lifecycle tests."""

import asyncio
from typing import AsyncContextManager
from unittest.mock import patch

import pytest
from mcp.types import Tool as McpBaseTool
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import McpToolkitConfig, TurnContext
from azents.engine.tooling.toolkit_state import ToolkitStateIdentity
from azents.engine.tools.mcp import McpToolkit


class _FakeToolkitStateHandle:
    """In-memory Toolkit State handle for tests."""

    _states: dict[tuple[str, str, str, str], object] = {}

    def __init__(self, identity: ToolkitStateIdentity) -> None:
        self.identity = identity

    async def load(self, default_factory: object) -> object:
        """Load state from in-memory store."""
        key = self._key()
        if key not in self._states:
            return default_factory()  # type: ignore[operator]
        return self._states[key]

    async def save(self, state: object) -> object:
        """Save state to in-memory store."""
        self._states[self._key()] = state
        return object()

    @classmethod
    def clear(cls) -> None:
        """Clear stored Toolkit State."""
        cls._states.clear()

    def _key(self) -> tuple[str, str, str, str]:
        return (
            self.identity.agent_id,
            self.identity.session_id,
            self.identity.toolkit_namespace,
            self.identity.state_name,
        )


class _FakeToolkitStateStore:
    """In-memory Toolkit State store for tests."""

    def __init__(self, *, session: object) -> None:
        del session

    def handle(
        self, identity: ToolkitStateIdentity, _model_type: object
    ) -> _FakeToolkitStateHandle:
        """Return fake handle."""
        return _FakeToolkitStateHandle(identity)


@pytest.fixture(autouse=True)
def _toolkit_state_store(  # pyright: ignore[reportUnusedFunction] -- pytest autouse fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch Toolkit State to an in-memory store."""
    _FakeToolkitStateHandle.clear()
    monkeypatch.setattr(
        "azents.engine.tools.mcp_base.ToolkitStateStore",
        _FakeToolkitStateStore,
    )


def _tool(name: str) -> McpBaseTool:
    """Create MCP tool fixture."""
    return McpBaseTool(
        name=name,
        description=f"{name} tool",
        inputSchema={"type": "object", "properties": {}},
    )


class _FakeSessionContext:
    """Minimal async session context manager for tests."""

    async def __aenter__(self) -> AsyncSession:
        return AsyncSession()

    async def __aexit__(self, *exc: object) -> None:
        pass


class _FakeSessionManager:
    """Minimal async context manager factory for tests."""

    def __call__(self) -> AsyncContextManager[AsyncSession]:
        return _FakeSessionContext()


_session_manager = _FakeSessionManager()


def _context() -> TurnContext:
    """Create turn context fixture."""
    return TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="model",
        run_id="run-1",
        owner_generation=1,
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
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none"),
        session_manager=_session_manager,
        agent_id="agent-1",
        session_id="session-1",
        state_name="tool_snapshot:test",
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
            assert (await toolkit.get_static_prompt(_context())) == ""

            continue_list.set()


async def test_background_refresh_success_exposes_sorted_tools_next_turn() -> None:
    """Successful background refresh exposes deterministic tool order."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none"),
        session_manager=_session_manager,
        agent_id="agent-1",
        session_id="session-1",
        state_name="tool_snapshot:test",
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        return_value=([_tool("zeta"), _tool("alpha")], False),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)

    state = await toolkit.update_context(_context())

    assert [tool.spec.name for tool in state.tools] == ["alpha", "zeta"]
    assert (await toolkit.get_static_prompt(_context())) == ""


async def test_refresh_failure_preserves_previous_successful_snapshot() -> None:
    """Failed refresh keeps the previous successful tool snapshot."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none"),
        session_manager=_session_manager,
        agent_id="agent-1",
        session_id="session-1",
        state_name="tool_snapshot:test",
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
    assert (await toolkit.get_static_prompt(_context())) == ""


async def test_failed_refresh_without_snapshot_exposes_no_retry_tool_or_prompt() -> (
    None
):
    """Initial MCP failure exposes no loading/retry/status pseudo-tool."""
    toolkit = McpToolkit(
        config=McpToolkitConfig(server_url="https://example.com/mcp", auth_type="none"),
        session_manager=_session_manager,
        agent_id="agent-1",
        session_id="session-1",
        state_name="tool_snapshot:test",
    )
    with patch(
        "azents.engine.tools.mcp_base.mcp_list_tools",
        side_effect=RuntimeError("boom"),
    ):
        async with toolkit:
            await _wait_refresh(toolkit)

    state = await toolkit.update_context(_context())

    assert state.tools == []
    assert (await toolkit.get_static_prompt(_context())) == ""
