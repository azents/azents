"""Notion Toolkit.

Notion official MCP server (mcp.notion.com/mcp) based Service Toolkit.
Supports toolkit-level OAuth2 + DCR authentication.
Provides a dedicated Toolkit with fixed server URL and authentication method.
"""

import logging
from textwrap import dedent

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    McpToolkitConfig,
    NotionToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    TurnContext,
)
from azents.engine.tools.mcp import McpToolkit, McpToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

_NOTION_SERVER_URL = "https://mcp.notion.com/mcp"
_NOTION_AUTH_TYPE = "oauth2"


def _build_mcp_config(config: NotionToolkitConfig) -> McpToolkitConfig:
    """Build McpToolkitConfig from NotionToolkitConfig.

    server_url and auth_type are set to fixed values on server side.

    :param config: Notion toolkit settings
    :return: MCP toolkit settings
    """
    return McpToolkitConfig(
        server_url=_NOTION_SERVER_URL,
        auth_type=_NOTION_AUTH_TYPE,
        timeout=config.timeout,
    )


# ---------------------------------------------------------------------------
# NotionToolkit
# ---------------------------------------------------------------------------


class NotionToolkit(Toolkit[NotionToolkitConfig]):
    """Notion MCP-based Toolkit execution instance.

    Delegate to McpToolkit to communicate with MCP server (composition).
    NotionHandle ToolkitConfig -> McpToolkitConfig conversion internally.
    """

    def __init__(self, *, mcp_toolkit: McpToolkit) -> None:
        """NotionToolkit initialization.

        :param mcp_toolkit: Credential-bound McpToolkit
        """
        self.mcp = mcp_toolkit

    async def __aenter__(self) -> NotionToolkit:
        """Delegate to internal McpToolkit to start background connection."""
        await self.mcp.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Delegate to internal McpToolkit to clean up background connection."""
        await self.mcp.__aexit__(*exc)

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Delegate to McpToolkit to return tools and prompt."""
        return await self.mcp.update_context(context)


# ---------------------------------------------------------------------------
# NotionToolkitProvider
# ---------------------------------------------------------------------------


class NotionToolkitProvider(ToolkitProvider[NotionToolkitConfig]):
    """Notion Toolkit Provider.

    Supports only toolkit-level OAuth2 + DCR authentication.
    Build McpToolkitConfig at resolve time and delegate to McpToolkitProvider.
    """

    slug = "notion"
    name = "Notion"
    description = "Notion workspace management via MCP"
    system_prompt = dedent("""\
        You have access to Notion tools provided via the Notion MCP server.
        Use the available tools to interact with Notion pages, databases,
        and other resources as needed.""")
    config_model = NotionToolkitConfig

    def __init__(
        self,
        *,
        connection_repo: MCPOAuthConnectionRepository | None = None,
        session_manager: SessionManager[AsyncSession] | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        """NotionToolkitProvider initialization.

        :param connection_repo: MCP OAuth connection repository
        :param session_manager: DB session manager
        :param artifact_service: MCP binary output storage service
        """
        self.mcp_provider = McpToolkitProvider(
            connection_repo=connection_repo,
            session_manager=session_manager,
            artifact_service=artifact_service,
        )

    def to_mcp_config(self, config: NotionToolkitConfig) -> McpToolkitConfig:
        """Convert to fixed Notion MCP settings."""
        return _build_mcp_config(config)

    async def test_connection(
        self,
        config: NotionToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Notion Test MCP server connection.

        :param config: Notion toolkit settings
        :param credentials_json: Decrypted credentials JSON
        :param proxy_url: egress proxy URL (direct connection when None)
        :return: Connection test result
        """
        mcp_config = _build_mcp_config(config)
        return await self.mcp_provider.test_connection(
            mcp_config, credentials_json, proxy_url=proxy_url
        )

    async def resolve(
        self,
        config: NotionToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[NotionToolkitConfig]:
        """Resolve credential and return NotionToolkit.

        Delegate to McpToolkitProvider to bind credential, then wrap with
        NotionToolkit and return.

        :param config: Validated Notion Toolkit settings
        :param context: Resolve context
        :return: Credential-bound NotionToolkit instance
        """
        mcp_config = _build_mcp_config(config)
        resolved = await self.mcp_provider.resolve(mcp_config, context)
        if not isinstance(resolved, McpToolkit):
            msg = f"Expected McpToolkit, got {type(resolved).__name__}"
            raise TypeError(msg)
        return NotionToolkit(mcp_toolkit=resolved)
