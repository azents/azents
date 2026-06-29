"""Sentry Toolkit.

Sentry official MCP server (mcp.sentry.dev/mcp) based Service Toolkit.
Supports toolkit-level OAuth2 + DCR authentication.
Provides a dedicated Toolkit with fixed server URL and authentication method.

Adds skill group filtering to the same pattern as Notion Toolkit.
"""

import logging
from textwrap import dedent

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.tools import (
    McpToolkitConfig,
    ResolveContext,
    SentryToolkitConfig,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    TurnContext,
)
from azents.engine.run.types import FunctionTool
from azents.engine.tools.mcp import McpToolkit, McpToolkitProvider
from azents.rdb.session import SessionManager
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

_SENTRY_SERVER_URL = "https://mcp.sentry.dev/mcp"
_SENTRY_AUTH_TYPE = "oauth2"

# ---------------------------------------------------------------------------
# Skill group filtering (GitHub toolset pattern)
# ---------------------------------------------------------------------------

# Tool name to skill group mapping
_TOOL_SKILL_MAP: dict[str, str] = {
    # inspect
    "find_organizations": "inspect",
    "find_projects": "inspect",
    "find_releases": "inspect",
    "find_teams": "inspect",
    "get_event_attachment": "inspect",
    "get_issue_tag_values": "inspect",
    "get_sentry_resource": "inspect",
    "list_events": "inspect",
    "list_issue_events": "inspect",
    "list_issues": "inspect",
    "whoami": "inspect",
    # seer
    "analyze_issue_with_seer": "seer",
    # docs
    "get_doc": "docs",
    "search_docs": "docs",
    # triage
    "update_issue": "triage",
    # manage
    "create_dsn": "manage",
    "create_project": "manage",
    "create_team": "manage",
    "find_dsns": "manage",
    "update_project": "manage",
    # ai_search (controlled separately)
    "search_events": "ai_search",
    "search_issues": "ai_search",
    "search_issue_events": "ai_search",
}


def _build_mcp_config(config: SentryToolkitConfig) -> McpToolkitConfig:
    """Build McpToolkitConfig from SentryToolkitConfig.

    server_url and auth_type are set to fixed values on server side.

    :param config: Sentry toolkit settings
    :return: MCP toolkit settings
    """
    return McpToolkitConfig(
        server_url=_SENTRY_SERVER_URL,
        auth_type=_SENTRY_AUTH_TYPE,
        timeout=config.timeout,
    )


# ---------------------------------------------------------------------------
# SentryToolkit
# ---------------------------------------------------------------------------


class SentryToolkit(Toolkit[SentryToolkitConfig]):
    """Sentry MCP-based Toolkit execution instance.

    Delegate to McpToolkit to communicate with MCP server (composition).
    Handle SentryToolkitConfig -> McpToolkitConfig conversion internally and
    apply skill group filtering.
    """

    def __init__(
        self,
        *,
        mcp_toolkit: McpToolkit,
        enabled_skills: list[str],
    ) -> None:
        """SentryToolkit initialization.

        :param mcp_toolkit: Credential-bound McpToolkit
        :param enabled_skills: Skill group list to enable
        """
        self._mcp = mcp_toolkit
        self._enabled_skills = enabled_skills

    async def __aenter__(self) -> SentryToolkit:
        """Delegate to internal McpToolkit to start background connection."""
        await self._mcp.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Delegate to internal McpToolkit to clean up background connection."""
        await self._mcp.__aexit__(*exc)

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Apply skill group filtering to MCP tool list."""
        state = await self._mcp.update_context(context)
        if not self._enabled_skills:
            return state
        filtered = filter_tools_by_skills(state.tools, self._enabled_skills)
        return ToolkitState(status=state.status, tools=filtered)


def filter_tools_by_skills(
    tools: list[FunctionTool],
    enabled_skills: list[str],
) -> list[FunctionTool]:
    """Return only tools included in enabled_skills from FunctionTool list.

    :param tools: FunctionTool list
    :param enabled_skills: Skill group name list to enable
    :return: Filtered tool list
    """
    enabled = set(enabled_skills)
    return [
        tool
        for tool in tools
        if _TOOL_SKILL_MAP.get(tool.spec.name, "inspect") in enabled
    ]


# ---------------------------------------------------------------------------
# SentryToolkitProvider
# ---------------------------------------------------------------------------


class SentryToolkitProvider(ToolkitProvider[SentryToolkitConfig]):
    """Sentry Toolkit Provider.

    Supports only toolkit-level OAuth2 + DCR authentication.
    Build McpToolkitConfig at resolve time and delegate to McpToolkitProvider.
    """

    slug = "sentry"
    name = "Sentry"
    description = "Sentry error tracking and performance monitoring via MCP"
    system_prompt = dedent("""\
        You have access to Sentry error tracking tools.
        Use these to investigate issues, search events, analyze errors,
        and view traces. When investigating a bug, start by searching
        for relevant issues using list_issues, then drill into specific
        events and stacktraces using get_sentry_resource.""")
    config_model = SentryToolkitConfig

    def __init__(
        self,
        *,
        connection_repo: MCPOAuthConnectionRepository | None = None,
        session_manager: SessionManager[AsyncSession] | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        """SentryToolkitProvider initialization.

        :param connection_repo: MCP OAuth connection repository
        :param session_manager: DB session manager
        :param artifact_service: MCP binary output storage service
        """
        self._mcp_provider = McpToolkitProvider(
            connection_repo=connection_repo,
            session_manager=session_manager,
            artifact_service=artifact_service,
        )

    def to_mcp_config(self, config: SentryToolkitConfig) -> McpToolkitConfig:
        """Convert to fixed Sentry MCP settings."""
        return _build_mcp_config(config)

    async def test_connection(
        self,
        config: SentryToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Sentry Test MCP server connection.

        :param config: Sentry toolkit settings
        :param credentials_json: Decrypted credentials JSON
        :param proxy_url: egress proxy URL (direct connection when None)
        :return: Connection test result
        """
        mcp_config = _build_mcp_config(config)
        return await self._mcp_provider.test_connection(
            mcp_config, credentials_json, proxy_url=proxy_url
        )

    async def resolve(
        self,
        config: SentryToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[SentryToolkitConfig]:
        """Resolve credential and return SentryToolkit.

        Delegate to McpToolkitProvider to bind credential, then wrap with
        SentryToolkit and apply skill group filtering.

        :param config: Validated Sentry Toolkit settings
        :param context: Resolve context
        :return: Credential-bound SentryToolkit instance
        """
        mcp_config = _build_mcp_config(config)
        resolved = await self._mcp_provider.resolve(mcp_config, context)
        if not isinstance(resolved, McpToolkit):
            msg = f"Expected McpToolkit, got {type(resolved).__name__}"
            raise TypeError(msg)
        return SentryToolkit(
            mcp_toolkit=resolved,
            enabled_skills=config.enabled_skills,
        )
