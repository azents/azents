"""GitHub Toolkit per_user_pat tests."""

from unittest.mock import AsyncMock

import pytest

from azents.core.tools import GitHubToolkitConfig, SessionType, TurnContext
from azents.engine.tools.github import GitHubToolkit


def _make_context(
    *,
    user_id: str | None = "test-user",
) -> TurnContext:
    """Create TurnContext for tests."""
    return TurnContext(
        user_id=user_id,
        workspace_id="test-workspace",
        model="test-model",
        run_id="test-run",
        publish_event=AsyncMock(),
    )


def _make_config() -> GitHubToolkitConfig:
    """Create per_user_pat settings."""
    return GitHubToolkitConfig(
        github_auth_type="per_user_pat",
        toolsets=["repos", "issues"],
        timeout=30.0,
    )


class TestGitHubToolkitPerUserPatSystemSession:
    """per_user_pat tool creation tests in system session."""

    @pytest.mark.asyncio
    async def test_system_session_returns_empty(self) -> None:
        """Return empty list for SYSTEM session."""
        config = _make_config()
        toolkit = GitHubToolkit(
            config=config,
            mcp_toolkit=None,
            setup_url="https://example.com/setup",
            toolkit_name="GitHub",
            toolkit_id="tk-1",
            toolsets=["repos"],
            session_type=SessionType.SYSTEM,
        )
        context = _make_context()

        state = await toolkit.update_context(context)
        tools = state.tools

        assert tools == []


class TestGitHubToolkitPerUserPatSetupTool:
    """setup_github tool creation tests when PAT is not registered."""

    @pytest.mark.asyncio
    async def test_no_secret_returns_setup_tool(self) -> None:
        """Return only setup_github tool when mcp_toolkit is absent."""
        config = _make_config()
        toolkit = GitHubToolkit(
            config=config,
            mcp_toolkit=None,
            setup_url="https://example.com/setup",
            toolkit_name="GitHub",
            toolkit_id="tk-1",
            toolsets=["repos"],
        )
        context = _make_context()

        state = await toolkit.update_context(context)
        tools = state.tools

        assert len(tools) == 1
        assert tools[0].spec.name == "setup_github"

    @pytest.mark.asyncio
    async def test_setup_tool_publishes_event(self) -> None:
        """Emit AuthorizationRequestEvent when setup_github tool is called."""
        config = _make_config()
        toolkit = GitHubToolkit(
            config=config,
            mcp_toolkit=None,
            setup_url="https://example.com/setup",
            toolkit_name="GitHub",
            toolkit_id="tk-1",
            toolsets=["repos"],
        )
        context = _make_context()

        state = await toolkit.update_context(context)
        tools = state.tools
        result = await tools[0].handler("{}")

        assert isinstance(result, str)
        assert "setup" in result.lower()
        context.publish_event.assert_called_once()  # pyright: ignore[reportFunctionMemberAccess]  # AsyncMock
