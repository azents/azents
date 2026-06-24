"""Notion Toolkit tests."""

from azents.core.tools import (
    NotionToolkitConfig,
)
from azents.engine.tools.notion import NotionToolkitProvider

# ---------------------------------------------------------------------------
# NotionToolkitConfig tests
# ---------------------------------------------------------------------------


class TestNotionToolkitConfig:
    """Validate config defaults."""

    def test_defaults(self) -> None:
        """Check that defaults are correct."""
        config = NotionToolkitConfig()
        assert config.timeout == 30.0

    def test_custom_timeout(self) -> None:
        """Check that timeout can be customized."""
        config = NotionToolkitConfig(timeout=60.0)
        assert config.timeout == 60.0

    def test_no_server_url_field(self) -> None:
        """Check that server_url field is absent (fixed by server)."""
        assert "server_url" not in NotionToolkitConfig.model_fields


# ---------------------------------------------------------------------------
# NotionToolkitProvider tests
# ---------------------------------------------------------------------------


class TestNotionToolkitProvider:
    """NotionToolkitProvider default property tests."""

    def test_slug(self) -> None:
        """slug is 'notion'check."""
        assert NotionToolkitProvider.slug == "notion"

    def test_config_model(self) -> None:
        """config_model is NotionToolkitConfigcheck."""
        assert NotionToolkitProvider.config_model is NotionToolkitConfig

    def test_to_mcp_config_returns_correct_server_url(self) -> None:
        """to_mcp_config returns Notion fixed server_url."""
        provider = NotionToolkitProvider()
        config = NotionToolkitConfig()
        mcp_config = provider.to_mcp_config(config)
        assert mcp_config.server_url == "https://mcp.notion.com/mcp"
        assert mcp_config.auth_type == "oauth2"

    def test_to_mcp_config_preserves_timeout(self) -> None:
        """to_mcp_config preserves timeout."""
        provider = NotionToolkitProvider()
        config = NotionToolkitConfig(timeout=60.0)
        mcp_config = provider.to_mcp_config(config)
        assert mcp_config.timeout == 60.0
