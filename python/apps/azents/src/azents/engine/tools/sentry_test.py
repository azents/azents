"""Sentry Toolkit tests."""

from unittest.mock import AsyncMock

from azents.core.tools import McpToolkitConfig, SentryToolkitConfig
from azents.engine.run.types import FunctionTool, FunctionToolSpec
from azents.engine.tools.mcp import McpToolkitProvider
from azents.engine.tools.sentry import SentryToolkitProvider, filter_tools_by_skills

# For SentryToolkit creation (tests use McpToolkit without credential)
_SENTRY_CONFIG = SentryToolkitConfig()

# ---------------------------------------------------------------------------
# SentryToolkitConfig tests
# ---------------------------------------------------------------------------


class TestSentryToolkitConfig:
    """Validate config defaults."""

    def test_defaults(self) -> None:
        """Check that defaults are correct."""
        config = SentryToolkitConfig()
        assert config.timeout == 30.0
        assert config.enabled_skills == ["inspect", "seer"]

    def test_custom_timeout(self) -> None:
        """Check that timeout can be customized."""
        config = SentryToolkitConfig(timeout=60.0)
        assert config.timeout == 60.0

    def test_custom_enabled_skills(self) -> None:
        """Check that enabled_skills can be customized."""
        config = SentryToolkitConfig(
            enabled_skills=["inspect", "seer", "triage"],
        )
        assert config.enabled_skills == ["inspect", "seer", "triage"]

    def test_no_server_url_field(self) -> None:
        """Check that server_url field is absent (fixed by server)."""
        assert "server_url" not in SentryToolkitConfig.model_fields


# ---------------------------------------------------------------------------
# Skill group filtering tests
# ---------------------------------------------------------------------------


def _make_tool(name: str) -> FunctionTool:
    """Create FunctionTool for tests."""
    spec = FunctionToolSpec(
        name=name,
        description=f"Test tool {name}",
        input_schema={"type": "object", "properties": {}},
    )
    return FunctionTool(spec=spec, handler=AsyncMock())


class TestFilterToolsBySkills:
    """Skill group filtering tests."""

    def test_filter_inspect_only(self) -> None:
        """When only inspect is enabled, only inspect tools are returned."""
        tools = [
            _make_tool("list_issues"),
            _make_tool("analyze_issue_with_seer"),
            _make_tool("update_issue"),
        ]
        result = filter_tools_by_skills(tools, ["inspect"])
        assert len(result) == 1
        assert result[0].spec.name == "list_issues"

    def test_filter_multiple_skills(self) -> None:
        """Multiple skill groups enabled."""
        tools = [
            _make_tool("list_issues"),
            _make_tool("analyze_issue_with_seer"),
            _make_tool("update_issue"),
            _make_tool("get_doc"),
        ]
        result = filter_tools_by_skills(tools, ["inspect", "seer"])
        names = {t.spec.name for t in result}
        assert names == {"list_issues", "analyze_issue_with_seer"}

    def test_unknown_tool_defaults_to_inspect(self) -> None:
        """Tools not in mapping are allowed as default inspect."""
        tools = [_make_tool("unknown_new_tool")]
        result = filter_tools_by_skills(tools, ["inspect"])
        assert len(result) == 1

    def test_empty_skills_returns_empty(self) -> None:
        """Return empty list when enabled_skills is empty."""
        tools = [_make_tool("list_issues")]
        result = filter_tools_by_skills(tools, [])
        assert result == []


# ---------------------------------------------------------------------------
# SentryToolkitProvider tests
# ---------------------------------------------------------------------------


class TestSentryToolkitProvider:
    """SentryToolkitProvider default property tests."""

    def test_slug(self) -> None:
        """slug is 'sentry'check."""
        assert SentryToolkitProvider.slug == "sentry"

    def test_config_model(self) -> None:
        """config_model is SentryToolkitConfigcheck."""
        assert SentryToolkitProvider.config_model is SentryToolkitConfig

    def test_to_mcp_config_returns_correct_server_url(self) -> None:
        """to_mcp_config returns Sentry fixed server_url."""
        provider = SentryToolkitProvider()
        config = SentryToolkitConfig()
        mcp_config = provider.to_mcp_config(config)
        assert mcp_config.server_url == "https://mcp.sentry.dev/mcp"
        assert mcp_config.auth_type == "oauth2"

    def test_to_mcp_config_preserves_timeout(self) -> None:
        """to_mcp_config preserves timeout."""
        provider = SentryToolkitProvider()
        config = SentryToolkitConfig(timeout=60.0)
        mcp_config = provider.to_mcp_config(config)
        assert mcp_config.timeout == 60.0


# ---------------------------------------------------------------------------
# McpToolkitProvider passthrough tests
# ---------------------------------------------------------------------------


class TestMcpToolkitProviderToMcpConfig:
    """Default MCP provider to_mcp_config passthrough tests."""

    def test_mcp_provider_to_mcp_config_passthrough(self) -> None:
        """Default MCP provider to_mcp_config returns config as-is."""
        provider = McpToolkitProvider()
        config = McpToolkitConfig(
            server_url="https://example.com/mcp", auth_type="bearer"
        )
        mcp_config = provider.to_mcp_config(config)
        assert mcp_config.server_url == "https://example.com/mcp"
        assert mcp_config.auth_type == "bearer"
