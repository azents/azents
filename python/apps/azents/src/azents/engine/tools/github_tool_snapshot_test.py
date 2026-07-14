"""GitHub Toolkit MCP snapshot fallback tests."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import AsyncContextManager
from unittest.mock import MagicMock, patch

import pytest
from mcp.types import TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.github_credentials import GitHubInstallationTarget
from azents.core.tools import GitHubToolkitConfig, McpToolkitConfig, TurnContext
from azents.engine.run.types import FunctionTool
from azents.engine.tooling.toolkit_state import ToolkitStateIdentity
from azents.engine.tools.github import GitHubInstallationBinding, GitHubToolkit
from azents.engine.tools.mcp_base import McpToolSnapshotItem, McpToolSnapshotState

_GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"


class _FakeToolkitStateHandle:
    """In-memory Toolkit State handle for tests."""

    _states: dict[tuple[str, str, str, str], object] = {}

    def __init__(self, identity: ToolkitStateIdentity) -> None:
        """Create fake handle."""
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
    def save_state(cls, identity: ToolkitStateIdentity, state: object) -> None:
        """Seed state for identity."""
        cls._states[
            (
                identity.agent_id,
                identity.session_id,
                identity.toolkit_namespace,
                identity.state_name,
            )
        ] = state

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


class _FakeSessionContext:
    """Minimal async session context manager."""

    async def __aenter__(self) -> AsyncSession:
        return AsyncSession()

    async def __aexit__(self, *exc: object) -> None:
        pass


class _FakeSessionManager:
    """Minimal async session manager."""

    def __call__(self) -> AsyncContextManager[AsyncSession]:
        return _FakeSessionContext()


class _FakeSelectedInstallationStore:
    """In-memory selected installation store for tests."""

    async def load(self) -> str | None:
        """Load selected installation ID."""
        return None

    async def save(
        self,
        installation_id: str,
        *,
        run_id: str,
        owner_generation: int,
    ) -> None:
        """Save selected installation ID."""
        del installation_id, run_id, owner_generation


@pytest.fixture(autouse=True)
def _toolkit_state_store(  # pyright: ignore[reportUnusedFunction] -- pytest fixture
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch Toolkit State to an in-memory store."""
    _FakeToolkitStateHandle.clear()
    monkeypatch.setattr(
        "azents.engine.tools.github.ToolkitStateStore",
        _FakeToolkitStateStore,
    )


def _make_config() -> GitHubToolkitConfig:
    """Create GitHub App config."""
    return GitHubToolkitConfig(
        github_auth_type="github_app",
        toolsets=["repos"],
        timeout=30.0,
    )


def _make_context() -> TurnContext:
    """Create TurnContext for tests."""
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


def _target(installation_id: str, account_login: str) -> GitHubInstallationTarget:
    """Create GitHub installation target."""
    return GitHubInstallationTarget(
        installation_id=installation_id,
        account_login=account_login,
        account_type="Organization",
        account_avatar_url=None,
    )


def _snapshot(*tool_names: str) -> McpToolSnapshotState:
    """Create MCP tool snapshot."""
    return McpToolSnapshotState(
        server_url=_GITHUB_MCP_URL,
        tool_hash="test",
        tools=[
            McpToolSnapshotItem(
                raw_name=name,
                model_name=name,
                description=f"{name} tool",
                input_schema={"type": "object", "properties": {}},
                server_url=_GITHUB_MCP_URL,
                use_streamable_http=True,
            )
            for name in tool_names
        ],
    )


def _identity(binding: GitHubInstallationBinding) -> ToolkitStateIdentity:
    """Create Toolkit State identity for a binding."""
    return ToolkitStateIdentity(
        agent_id=binding.agent_id,
        session_id=binding.session_id,
        toolkit_namespace="mcp",
        state_name=binding.state_name,
    )


def _binding(
    *,
    target: GitHubInstallationTarget,
    state_name: str,
    token_provider: Callable[[], Awaitable[str | None]],
) -> GitHubInstallationBinding:
    """Create installation binding fixture."""
    return GitHubInstallationBinding(
        target=target,
        mcp_toolkit=None,
        token_provider=token_provider,
        lazy_mcp_config=McpToolkitConfig(
            server_url=_GITHUB_MCP_URL,
            auth_type="bearer",
        ),
        lazy_mcp_secret_provider=token_provider,
        lazy_mcp_proxy_url=None,
        session_manager=_FakeSessionManager(),
        agent_id="agent-1",
        session_id="session-1",
        state_name=state_name,
    )


async def _never() -> None:
    """Never-completing task fixture."""
    await asyncio.Event().wait()


def _find_tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    """Find tool by name."""
    for tool in tools:
        if tool.spec.name == name:
            return tool
    raise AssertionError(f"Tool not found: {name}")


def _make_call_tool_result(text: str) -> MagicMock:
    """Create MCP CallToolResult-like object."""
    result = MagicMock()
    result.content = [TextContent(type="text", text=text)]
    result.isError = False
    return result


async def test_multi_installation_uses_snapshot_while_lazy_mcp_is_pending() -> None:
    """Previous installation snapshots are exposed before lazy MCP setup finishes."""

    async def provide_azents() -> str:
        return "ghs_azents"

    async def provide_hardtack() -> str:
        return "ghs_hardtack"

    azents = _binding(
        target=_target("101", "azents"),
        state_name="tool_snapshot:azents",
        token_provider=provide_azents,
    )
    hardtack = _binding(
        target=_target("202", "Hardtack"),
        state_name="tool_snapshot:hardtack",
        token_provider=provide_hardtack,
    )
    _FakeToolkitStateHandle.save_state(
        _identity(azents),
        _snapshot("create_or_update_file"),
    )
    _FakeToolkitStateHandle.save_state(
        _identity(hardtack),
        _snapshot("get_file_contents"),
    )
    azents.lazy_mcp_task = asyncio.create_task(_never())
    hardtack.lazy_mcp_task = asyncio.create_task(_never())
    toolkit = GitHubToolkit(
        config=_make_config(),
        installation_bindings=[hardtack, azents],
        selected_installation_store=_FakeSelectedInstallationStore(),  # type: ignore[arg-type]
    )

    try:
        state = await toolkit.update_context(_make_context())
        names = [tool.spec.name for tool in state.tools]

        assert names == [
            "azents__create_or_update_file",
            "hardtack__get_file_contents",
            "switch_installation",
        ]
        assert "Current default installation" in (
            await toolkit.get_static_prompt(_make_context())
        )

        second_state = await toolkit.update_context(_make_context())
        assert [tool.spec.name for tool in second_state.tools] == names
    finally:
        for task in (azents.lazy_mcp_task, hardtack.lazy_mcp_task):
            task.cancel()


async def test_multi_installation_without_snapshot_keeps_switch_tool_only() -> None:
    """No snapshot preserves existing switch-only behavior while MCP prepares."""

    async def provide_token() -> str:
        return "ghs_token"

    azents = _binding(
        target=_target("101", "azents"),
        state_name="tool_snapshot:azents",
        token_provider=provide_token,
    )
    hardtack = _binding(
        target=_target("202", "Hardtack"),
        state_name="tool_snapshot:hardtack",
        token_provider=provide_token,
    )
    azents.lazy_mcp_task = asyncio.create_task(_never())
    hardtack.lazy_mcp_task = asyncio.create_task(_never())
    toolkit = GitHubToolkit(
        config=_make_config(),
        installation_bindings=[azents, hardtack],
        selected_installation_store=_FakeSelectedInstallationStore(),  # type: ignore[arg-type]
    )

    try:
        state = await toolkit.update_context(_make_context())

        assert [tool.spec.name for tool in state.tools] == ["switch_installation"]
    finally:
        for task in (azents.lazy_mcp_task, hardtack.lazy_mcp_task):
            task.cancel()


async def test_snapshot_tool_handler_gets_installation_token_at_call_time() -> None:
    """Snapshot tools defer token issuance until the tool is actually called."""
    token_calls = 0

    async def provide_token() -> str:
        nonlocal token_calls
        token_calls += 1
        return "ghs_snapshot"

    binding = _binding(
        target=_target("101", "azents"),
        state_name="tool_snapshot:azents",
        token_provider=provide_token,
    )
    _FakeToolkitStateHandle.save_state(
        _identity(binding),
        _snapshot("create_or_update_file"),
    )
    binding.lazy_mcp_task = asyncio.create_task(_never())
    toolkit = GitHubToolkit(
        config=_make_config(),
        installation_bindings=[binding],
    )

    try:
        state = await toolkit.update_context(_make_context())
        tool = _find_tool(state.tools, "azents__create_or_update_file")
        assert token_calls == 0

        with patch(
            "azents.engine.tools.mcp_base.mcp_call_tool",
            return_value=_make_call_tool_result("ok"),
        ) as call_tool:
            result = await tool.handler("{}")

        assert result == "ok"
        assert token_calls == 1
        call_args = call_tool.call_args.args
        assert call_args[1] == {"Authorization": "Bearer ghs_snapshot"}
    finally:
        binding.lazy_mcp_task.cancel()
