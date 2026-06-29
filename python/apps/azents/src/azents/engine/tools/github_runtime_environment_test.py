"""GitHubToolkit Runtime environment variables injection feature tests.

Validate ``inject_runtime_environment`` toggle + ``expose_env()`` + TTL cache behavior.
"""

import time
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from azents.core.github_credentials import GitHubInstallationTarget
from azents.core.tools import GitHubToolkitConfig, TurnContext
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tools.github import GitHubInstallationBinding, GitHubToolkit


def _make_config(*, inject_runtime_environment: bool = False) -> GitHubToolkitConfig:
    """Test fixture using PAT settings."""
    return GitHubToolkitConfig(
        github_auth_type="pat",
        toolsets=["repos"],
        timeout=30.0,
        inject_runtime_environment=inject_runtime_environment,
    )


def _make_app_config(
    *, inject_runtime_environment: bool = False
) -> GitHubToolkitConfig:
    """Test fixture — GitHub App settings."""
    return GitHubToolkitConfig(
        github_auth_type="github_app",
        toolsets=["repos"],
        timeout=30.0,
        inject_runtime_environment=inject_runtime_environment,
    )


class _FakeSelectedInstallationStore:
    """In-memory selected installation store for tests."""

    def __init__(self, installation_id: str | None = None) -> None:
        """Create fake store."""
        self.installation_id = installation_id

    async def load(self) -> str | None:
        """Load selected installation ID."""
        return self.installation_id

    async def save(self, installation_id: str) -> None:
        """Save selected installation ID."""
        self.installation_id = installation_id


def _make_turn_context() -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id="user-1",
        workspace_id="workspace-1",
        model="test-model",
        run_id="run-1",
        session_id="session-1",
        publish_event=AsyncMock(),
    )


def _find_tool(tools: list[FunctionTool], name: str) -> FunctionTool:
    """Find tool by name."""
    for tool in tools:
        if tool.spec.name == name:
            return tool
    raise AssertionError(f"Tool not found: {name}")


class TestExposeEnvDisabled:
    """Behavior when ``inject_runtime_environment=False``."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_disabled(self) -> None:
        """When toggle is off, return empty dict even if provider exists."""
        provider = AsyncMock(return_value="example_should_not_be_called")
        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=False),
            runtime_environment_token_provider=provider,
        )

        setting = await toolkit.expose_env()

        assert setting == {}
        provider.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_empty_without_provider(self) -> None:
        """When toggle is on, return empty dict if provider is absent."""
        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=None,
        )

        setting = await toolkit.expose_env()

        assert setting == {}


class TestExposeEnvEnabled:
    """Behavior with ``inject_runtime_environment=True`` + provider injection."""

    @pytest.mark.asyncio
    async def test_injects_both_env_names(self) -> None:
        """Set provider result as same value for both GH_TOKEN and GITHUB_TOKEN."""
        provider = AsyncMock(return_value="example_token_xxx")
        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=provider,
        )

        setting = await toolkit.expose_env()

        assert setting == {
            "GH_TOKEN": "example_token_xxx",
            "GITHUB_TOKEN": "example_token_xxx",
        }
        provider.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_empty_when_provider_returns_none(self) -> None:
        """Provider returns None, e.g. user PAT not registered -> empty dict."""
        provider = AsyncMock(return_value=None)
        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=provider,
        )

        setting = await toolkit.expose_env()

        assert setting == {}


class TestExposeEnvCache:
    """TTL cache behavior."""

    @pytest.mark.asyncio
    async def test_second_call_within_ttl_uses_cache(self) -> None:
        """Second call within TTL uses cache without recalling provider."""
        provider = AsyncMock(return_value="example_x")
        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=provider,
            runtime_environment_token_ttl_seconds=60.0,
        )

        await toolkit.expose_env()
        await toolkit.expose_env()

        provider.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_expired_cache_triggers_refresh(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Next call after TTL expiration recalls provider."""
        tokens = iter(["example_first", "example_second"])

        async def provider() -> str:
            return next(tokens)

        current = [1000.0]

        def fake_monotonic() -> float:
            return current[0]

        monkeypatch.setattr(time, "monotonic", fake_monotonic)

        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=provider,
            runtime_environment_token_ttl_seconds=60.0,
        )

        first = await toolkit.expose_env()
        assert first["GH_TOKEN"] == "example_first"

        current[0] = 1070.0  # past TTL (60s)

        second = await toolkit.expose_env()
        assert second["GH_TOKEN"] == "example_second"

    @pytest.mark.asyncio
    async def test_none_result_not_cached(self) -> None:
        """Do not cache provider None result, so next call retries."""
        results = [None, "example_recovered"]
        call_count = 0

        async def provider() -> str | None:
            nonlocal call_count
            call_count += 1
            return results[call_count - 1]

        toolkit = GitHubToolkit(
            config=_make_config(inject_runtime_environment=True),
            runtime_environment_token_provider=provider,
            runtime_environment_token_ttl_seconds=3600.0,
        )

        first = await toolkit.expose_env()
        assert first == {}

        second = await toolkit.expose_env()
        assert second == {
            "GH_TOKEN": "example_recovered",
            "GITHUB_TOKEN": "example_recovered",
        }
        assert call_count == 2


class TestExposeEnvMultiInstallation:
    """Multi-installation runtime environment exposure behavior."""

    @pytest.mark.asyncio
    async def test_injects_installation_tokens_and_routing_map(self) -> None:
        """Return each installation token and owner routing map in the env."""

        async def provide_azents() -> str:
            return "example_installation_token_azents"

        async def provide_hardtack() -> str:
            return "example_installation_token_hardtack"

        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=provide_azents,
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="202",
                        account_login="hardtack",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=provide_hardtack,
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
            ],
        )

        setting = await toolkit.expose_env()

        assert (
            setting["GITHUB_TOKEN_INSTALLATION_101"]
            == "example_installation_token_azents"
        )
        assert (
            setting["GITHUB_TOKEN_INSTALLATION_202"]
            == "example_installation_token_hardtack"
        )
        assert setting["GH_TOKEN"] == "example_installation_token_azents"
        assert setting["GITHUB_TOKEN"] == "example_installation_token_azents"
        assert '"azents"' in setting["GITHUB_INSTALLATION_MAP"]
        assert '"hardtack"' in setting["GITHUB_INSTALLATION_MAP"]

    @pytest.mark.asyncio
    async def test_single_installation_keeps_legacy_env_names(self) -> None:
        """A single installation also keeps legacy GH_TOKEN/GITHUB_TOKEN names."""

        async def provide_token() -> str:
            return "ghs_only"

        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=provide_token,
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                )
            ],
        )

        setting = await toolkit.expose_env()

        assert setting["GITHUB_TOKEN_INSTALLATION_101"] == "ghs_only"
        assert setting["GH_TOKEN"] == "ghs_only"
        assert setting["GITHUB_TOKEN"] == "ghs_only"

    @pytest.mark.asyncio
    async def test_selected_installation_sets_legacy_env_names(self) -> None:
        """Selected installation controls GH_TOKEN/GITHUB_TOKEN for gh CLI."""

        async def provide_azents() -> str:
            return "example_installation_token_azents"

        async def provide_hardtack() -> str:
            return "example_installation_token_hardtack"

        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=provide_azents,
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="202",
                        account_login="Hardtack",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=provide_hardtack,
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
            ],
            selected_installation_store=cast(
                Any,
                _FakeSelectedInstallationStore("202"),
            ),
        )

        setting = await toolkit.expose_env()

        assert setting["GH_TOKEN"] == "example_installation_token_hardtack"
        assert setting["GITHUB_TOKEN"] == "example_installation_token_hardtack"

    @pytest.mark.asyncio
    async def test_switch_installation_by_login_updates_state(self) -> None:
        """switch_installation accepts account login and updates selection."""
        store = _FakeSelectedInstallationStore()
        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_azents"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="202",
                        account_login="Hardtack",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_hardtack"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
            ],
            selected_installation_store=cast(Any, store),
        )
        state = await toolkit.update_context(_make_turn_context())
        tool = _find_tool(state.tools, "switch_installation")

        result = await tool.handler('{"installation":"hardtack"}')

        assert store.installation_id == "202"
        assert "Hardtack (202)" in str(result)
        assert "Current default installation" in (
            await toolkit.get_static_prompt(_make_turn_context())
        )

    @pytest.mark.asyncio
    async def test_switch_installation_by_id_updates_state(self) -> None:
        """switch_installation accepts installation ID."""
        store = _FakeSelectedInstallationStore()
        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_azents"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="202",
                        account_login="Hardtack",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_hardtack"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
            ],
            selected_installation_store=cast(Any, store),
        )
        state = await toolkit.update_context(_make_turn_context())
        tool = _find_tool(state.tools, "switch_installation")

        await tool.handler('{"installation":"101"}')

        assert store.installation_id == "101"

    @pytest.mark.asyncio
    async def test_switch_installation_rejects_unknown_selection(self) -> None:
        """switch_installation lists options for unknown selection."""
        toolkit = GitHubToolkit(
            config=_make_app_config(inject_runtime_environment=True),
            installation_bindings=[
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="101",
                        account_login="azents",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_azents"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
                GitHubInstallationBinding(
                    target=GitHubInstallationTarget(
                        installation_id="202",
                        account_login="Hardtack",
                        account_type="Organization",
                        account_avatar_url=None,
                    ),
                    mcp_toolkit=None,
                    token_provider=AsyncMock(
                        return_value="example_installation_token_hardtack"
                    ),
                    lazy_mcp_config=None,
                    lazy_mcp_secret_provider=None,
                    lazy_mcp_proxy_url=None,
                    session_manager=None,
                    agent_id="agent-1",
                    session_id="session-1",
                    state_name="tool_snapshot:test",
                ),
            ],
            selected_installation_store=cast(Any, _FakeSelectedInstallationStore()),
        )
        state = await toolkit.update_context(_make_turn_context())
        tool = _find_tool(state.tools, "switch_installation")

        with pytest.raises(FunctionToolError, match="azents \\(101\\)"):
            await tool.handler('{"installation":"unknown"}')
