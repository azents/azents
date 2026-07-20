"""GitHub Toolkit.

Service Toolkit based on GitHub MCP server (api.githubcopilot.com/mcp/).
Supports PAT and GitHub App (BYOA/Platform) authentication.
"""

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from textwrap import dedent

from mcp.types import Tool as McpBaseTool
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.github_auth import (
    create_github_app_jwt,
    exchange_installation_token,
)
from azents.core.github_credentials import (
    GitHubInstallationTarget,
    GitHubSecretsApp,
    GitHubSecretsAppPlatform,
    GitHubSecretsPAT,
)
from azents.core.mcp_transport import test_mcp_transport
from azents.core.tools import (
    GitHubToolkitConfig,
    McpToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tooling.toolkit_state import (
    ToolkitStateIdentity,
    ToolkitStateModel,
    ToolkitStateStore,
)
from azents.engine.tools.mcp import McpToolkit
from azents.engine.tools.mcp_base import McpToolSnapshotState, wrap_mcp_tool
from azents.rdb.session import SessionManager
from azents.repos.github_user_installation import (
    GithubUserInstallationRepository,
)
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)

logger = logging.getLogger(__name__)

_GitHubSecretsUnion = GitHubSecretsPAT | GitHubSecretsApp | GitHubSecretsAppPlatform
_github_secrets_adapter = TypeAdapter[_GitHubSecretsUnion](_GitHubSecretsUnion)

_GITHUB_SERVER_URL = "https://api.githubcopilot.com/mcp/"
_GITHUB_AUTH_TYPE = "bearer"


def _build_mcp_config(config: GitHubToolkitConfig) -> McpToolkitConfig:
    """Build McpToolkitConfig from GitHubToolkitConfig.

    server_url and auth_type are set to fixed values on server side.

    :param config: GitHub toolkit settings
    :return: MCP toolkit settings
    """
    return McpToolkitConfig(
        server_url=_GITHUB_SERVER_URL,
        auth_type=_GITHUB_AUTH_TYPE,
        timeout=config.timeout,
    )


# ---------------------------------------------------------------------------
# Toolset filtering
# ---------------------------------------------------------------------------

# GitHub MCP server tool name to toolset mapping
# Tools missing from mapping are allowed by default (forward compatibility)
_TOOL_TOOLSET_MAP: dict[str, str] = {
    # repos
    "get_file_contents": "repos",
    "create_or_update_file": "repos",
    "push_files": "repos",
    "search_repositories": "repos",
    "create_repository": "repos",
    "get_repository": "repos",
    "fork_repository": "repos",
    "create_branch": "repos",
    "list_branches": "repos",
    "list_commits": "repos",
    "search_code": "repos",
    # issues
    "get_issue": "issues",
    "create_issue": "issues",
    "list_issues": "issues",
    "update_issue": "issues",
    "add_issue_comment": "issues",
    "list_issue_comments": "issues",
    "search_issues": "issues",
    # pull_requests
    "get_pull_request": "pull_requests",
    "list_pull_requests": "pull_requests",
    "create_pull_request": "pull_requests",
    "update_pull_request": "pull_requests",
    "merge_pull_request": "pull_requests",
    "get_pull_request_diff": "pull_requests",
    "get_pull_request_files": "pull_requests",
    "create_pull_request_review": "pull_requests",
    "list_pull_request_reviews": "pull_requests",
    "add_pull_request_review_comment": "pull_requests",
    "get_pull_request_comments": "pull_requests",
    "get_pull_request_review": "pull_requests",
    # users
    "get_me": "users",
    # actions
    "list_workflow_runs": "actions",
    "get_workflow_run": "actions",
    "list_workflows": "actions",
    "trigger_workflow_dispatch": "actions",
    "get_workflow_run_logs": "actions",
    "rerun_workflow": "actions",
    "cancel_workflow_run": "actions",
    # code_security
    "get_code_scanning_alert": "code_security",
    "list_code_scanning_alerts": "code_security",
    # notifications
    "list_notifications": "notifications",
    "get_notification_details": "notifications",
    "dismiss_notification": "notifications",
    "mark_all_notifications_as_read": "notifications",
    # orgs
    "list_org_members": "orgs",
    # projects (GitHub Projects)
    "list_projects": "projects",
    # discussions
    "list_discussions": "discussions",
    "get_discussion": "discussions",
    "list_discussion_comments": "discussions",
}


def _filter_by_toolsets(
    tools: list[FunctionTool],
    toolsets: list[str],
) -> list[FunctionTool]:
    """Keep only tools included in the selected toolsets.

    Tools without a mapping are allowed for forward compatibility.

    :param tools: Full tool list
    :param toolsets: Enabled toolset list
    :return: Filtered tool list
    """
    allowed = set(toolsets)
    return [
        tool
        for tool in tools
        if _TOOL_TOOLSET_MAP.get(tool.spec.name, None) is None
        or _TOOL_TOOLSET_MAP[tool.spec.name] in allowed
    ]


_INSTALLATION_ENV_PREFIX = "GITHUB_TOKEN_INSTALLATION_"
_SAFE_TOOL_SEGMENT = re.compile(r"[^a-zA-Z0-9_]")
_GITHUB_TOOLKIT_STATE_NAMESPACE = "github"
_SELECTED_INSTALLATION_STATE_NAME = "selected_installation"


class GitHubSelectedInstallationState(ToolkitStateModel):
    """Selected GitHub installation for Runtime environment defaults."""

    schema_version: int = 1
    installation_id: str = Field(min_length=1, description="GitHub installation ID")


class GitHubSwitchInstallationInput(BaseModel):
    """Input for selecting the default GitHub installation."""

    installation: str = Field(
        min_length=1,
        description="Installation ID or account login to select for gh CLI defaults",
    )


class GitHubSelectedInstallationStore:
    """Session-bound GitHub selected installation Toolkit State store."""

    def __init__(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        agent_id: str,
        session_id: str,
    ) -> None:
        """Create selected installation store."""
        self.session_manager = session_manager
        self._agent_id = agent_id
        self._session_id = session_id

    async def load(self) -> str | None:
        """Load selected installation ID."""
        if not self._agent_id or not self._session_id:
            return None
        async with self.session_manager() as session:
            handle = ToolkitStateStore(session=session).handle(
                self._identity(),
                GitHubSelectedInstallationState,
            )
            state = await handle.load(
                default_factory=lambda: GitHubSelectedInstallationState(
                    installation_id="__unset__"
                )
            )
            if state.installation_id == "__unset__":
                return None
            return state.installation_id

    async def save(self, installation_id: str) -> None:
        """Persist selected installation ID."""
        if not self._agent_id or not self._session_id:
            return
        async with self.session_manager() as session:
            handle = ToolkitStateStore(session=session).handle(
                self._identity(),
                GitHubSelectedInstallationState,
            )
            await handle.save(
                GitHubSelectedInstallationState(installation_id=installation_id)
            )

    def _identity(self) -> ToolkitStateIdentity:
        """Create Toolkit State identity."""
        return ToolkitStateIdentity(
            agent_id=self._agent_id,
            session_id=self._session_id,
            toolkit_namespace=_GITHUB_TOOLKIT_STATE_NAMESPACE,
            state_name=_SELECTED_INSTALLATION_STATE_NAME,
        )


@dataclass
class GitHubInstallationBinding:
    """Runtime binding state for one GitHub installation."""

    target: GitHubInstallationTarget
    mcp_toolkit: McpToolkit | None
    token_provider: Callable[[], Awaitable[str | None]]
    lazy_mcp_config: McpToolkitConfig | None
    lazy_mcp_secret_provider: Callable[[], Awaitable[str | None]] | None
    lazy_mcp_proxy_url: str | None
    session_manager: SessionManager[AsyncSession] | None
    agent_id: str
    session_id: str
    state_name: str
    lazy_mcp_task: asyncio.Task[None] | None = None
    lazy_mcp_error: str | None = None


def _installation_tool_prefix(target: GitHubInstallationTarget) -> str:
    """Convert an installation account login to a tool name segment."""
    normalized = target.account_login.lower().replace("-", "_")
    normalized = _SAFE_TOOL_SEGMENT.sub("_", normalized).strip("_")
    if normalized:
        return normalized
    return f"installation_{target.installation_id}"


def _installation_env_name(installation_id: str) -> str:
    """Build the environment variable name for an installation token."""
    safe_id = _SAFE_TOOL_SEGMENT.sub("_", installation_id).strip("_")
    return f"{_INSTALLATION_ENV_PREFIX}{safe_id}"


def _installation_map_json(targets: list[GitHubInstallationTarget]) -> str:
    """Build account-login to installation metadata JSON for runtime helpers."""
    mapping = {
        target.account_login.lower(): {
            "installation_id": target.installation_id,
            "account_login": target.account_login,
            "account_type": target.account_type,
            "env": _installation_env_name(target.installation_id),
        }
        for target in targets
    }
    return json.dumps(mapping, sort_keys=True)


def _with_tool_prefix(
    tool: FunctionTool, target: GitHubInstallationTarget
) -> FunctionTool:
    """Add the installation account prefix to a tool name."""
    return tool.with_prefix(f"{_installation_tool_prefix(target)}__")


def _build_installation_prompt(
    targets: list[GitHubInstallationTarget],
    selected_target: GitHubInstallationTarget | None,
) -> str:
    """Build the model-visible GitHub installation routing prompt."""
    if not targets:
        return ""
    lines = [
        "GitHub App installations available in this toolkit:",
        "Use the installation-specific GitHub tools according to repository owner.",
    ]
    if selected_target is not None and len(targets) > 1:
        lines.append(
            "Current default installation for gh CLI commands: "
            f"{selected_target.account_login} "
            f"({selected_target.installation_id}). "
            "Call switch_installation to change GH_TOKEN and GITHUB_TOKEN."
        )
    for target in targets:
        prefix = _installation_tool_prefix(target)
        lines.append(
            "- "
            f"{target.account_login} ({target.account_type}) uses installation "
            f"{target.installation_id}; call tools prefixed with `{prefix}__` "
            f"for repositories owned by `{target.account_login}`."
        )
    lines.append(
        "For shell git commands, authentication is selected automatically from "
        "the repository owner when runtime environment injection is enabled. "
        "For GitHub CLI commands, GH_TOKEN and GITHUB_TOKEN use the current "
        "default installation."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GitHubToolkit
# ---------------------------------------------------------------------------


class GitHubToolkit(Toolkit[GitHubToolkitConfig]):
    """GitHub MCP-based Toolkit execution instance.

    Delegate to McpToolkit to communicate with MCP server (composition).
    Handle GitHubToolkitConfig -> McpToolkitConfig conversion internally and apply
    toolset filtering.
    """

    def __init__(
        self,
        *,
        config: GitHubToolkitConfig,
        mcp_toolkit: McpToolkit | None = None,
        toolsets: list[str] | None = None,
        runtime_environment_token_provider: Callable[[], Awaitable[str | None]]
        | None = None,
        runtime_environment_token_ttl_seconds: float = 3300.0,
        lazy_mcp_config: McpToolkitConfig | None = None,
        lazy_mcp_secret_provider: Callable[[], Awaitable[str | None]] | None = None,
        lazy_mcp_proxy_url: str | None = None,
        installation_bindings: list[GitHubInstallationBinding] | None = None,
        selected_installation_store: GitHubSelectedInstallationStore | None = None,
    ) -> None:
        """Initialize GitHubToolkit.

        :param config: GitHub toolkit settings
        :param mcp_toolkit: Credential-bound McpToolkit
        :param toolsets: Toolset list to enable (no filtering when None)
        :param runtime_environment_token_provider:
            When inject_runtime_environment=True, callable that issues GitHub
            token to inject into Runtime environment variables.
            If None, expose_env() returns empty dict. Provider injects an
            appropriate callable per auth mode.
        :param runtime_environment_token_ttl_seconds:
            Maximum time to memoize ``runtime_environment_token_provider`` result.
            GitHub App installation token 1h TTL
            Set slightly shorter (default 55 minutes) to reissue before expiration.
            Same value applies to long-lived tokens such as PAT, but session
            is usually shorter, so actual expiration is not a problem.
        """
        self._config = config
        self._mcp = mcp_toolkit
        self._toolsets = toolsets
        self.runtime_environment_token_provider = runtime_environment_token_provider
        self._runtime_environment_token_ttl_seconds = (
            runtime_environment_token_ttl_seconds
        )
        self._runtime_environment_token_cache: tuple[str, float] | None = None
        self._lazy_mcp_config = lazy_mcp_config
        self._lazy_mcp_secret_provider = lazy_mcp_secret_provider
        self._lazy_mcp_proxy_url = lazy_mcp_proxy_url
        self._lazy_mcp_task: asyncio.Task[None] | None = None
        self._lazy_mcp_error: str | None = None
        self._installation_targets = [
            binding.target for binding in installation_bindings or []
        ]
        self._installation_token_providers = {
            binding.target.installation_id: binding.token_provider
            for binding in installation_bindings or []
        }
        self._installation_bindings = installation_bindings or []
        self._installation_token_cache: dict[str, tuple[str, float]] = {}
        self.selected_installation_store = selected_installation_store

    async def expose_env(self) -> dict[str, str]:
        """Inject GH_TOKEN / GITHUB_TOKEN as Runtime environment variables.

        Empty dict when disabled or token provider is absent.
        Memoize within TTL; do not reissue on every runtime command.
        """
        if not self._config.inject_runtime_environment:
            return {}
        if self._installation_token_providers:
            return await self._expose_multi_installation_env()
        if self.runtime_environment_token_provider is None:
            return {}
        token = await self._get_cached_runtime_environment_token()
        if not token:
            return {}
        return {"GH_TOKEN": token, "GITHUB_TOKEN": token}

    async def _get_cached_runtime_environment_token(self) -> str | None:
        """Check the TTL cache and reissue a token through the provider if needed."""
        now = time.monotonic()
        if self._runtime_environment_token_cache is not None:
            cached_token, expires_at = self._runtime_environment_token_cache
            if expires_at > now:
                return cached_token
        assert self.runtime_environment_token_provider is not None  # noqa: S101
        token = await self.runtime_environment_token_provider()
        if token is not None:
            self._runtime_environment_token_cache = (
                token,
                now + self._runtime_environment_token_ttl_seconds,
            )
        return token

    async def _get_cached_installation_token(
        self,
        installation_id: str,
        provider: Callable[[], Awaitable[str | None]],
    ) -> str | None:
        """Check the per-installation TTL cache and return a token."""
        now = time.monotonic()
        cached = self._installation_token_cache.get(installation_id)
        if cached is not None:
            cached_token, expires_at = cached
            if expires_at > now:
                return cached_token
        token = await provider()
        if token is not None:
            self._installation_token_cache[installation_id] = (
                token,
                now + self._runtime_environment_token_ttl_seconds,
            )
        return token

    async def _expose_multi_installation_env(self) -> dict[str, str]:
        """Expose per-installation GitHub tokens as runtime environment variables."""
        env: dict[str, str] = {
            "GITHUB_INSTALLATION_MAP": _installation_map_json(
                self._installation_targets
            )
        }
        for installation_id, provider in self._installation_token_providers.items():
            token = await self._get_cached_installation_token(installation_id, provider)
            if token:
                env[_installation_env_name(installation_id)] = token
        if len(env) == 1:
            return {}
        selected_target = await self._get_selected_installation_target()
        if selected_target is not None:
            token = env.get(_installation_env_name(selected_target.installation_id))
            if token:
                env["GH_TOKEN"] = token
                env["GITHUB_TOKEN"] = token
        return env

    async def _get_selected_installation_target(
        self,
    ) -> GitHubInstallationTarget | None:
        """Return selected installation target with first target fallback."""
        if not self._installation_targets:
            return None
        selected_id: str | None = None
        if self.selected_installation_store is not None:
            selected_id = await self.selected_installation_store.load()
        if selected_id is not None:
            for target in self._installation_targets:
                if target.installation_id == selected_id:
                    return target
        return self._installation_targets[0]

    def _resolve_installation_selection(
        self,
        selection: str,
    ) -> GitHubInstallationTarget | None:
        """Resolve installation by ID or account login."""
        normalized = selection.strip().lower()
        if not normalized:
            return None
        for target in self._installation_targets:
            if target.installation_id == selection.strip():
                return target
        for target in self._installation_targets:
            if target.account_login.lower() == normalized:
                return target
        return None

    def _installation_options_text(self) -> str:
        """Return available installations as user-facing text."""
        return ", ".join(
            f"{target.account_login} ({target.installation_id})"
            for target in self._installation_targets
        )

    async def __aenter__(self) -> GitHubToolkit:
        """Delegate to internal McpToolkit to start background connection."""
        if self._installation_bindings:
            for binding in self._installation_bindings:
                await self._enter_installation_binding(binding)
        elif self._mcp is not None:
            await self._mcp.__aenter__()
        elif (
            self._lazy_mcp_config is not None
            and self._lazy_mcp_secret_provider is not None
            and self._lazy_mcp_task is None
        ):
            self._lazy_mcp_task = asyncio.create_task(self._prepare_lazy_mcp())
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Delegate to internal McpToolkit to clean up background connection."""
        for binding in self._installation_bindings:
            await self._exit_installation_binding(binding, *exc)
        if self._lazy_mcp_task is not None and not self._lazy_mcp_task.done():
            self._lazy_mcp_task.cancel()
            try:
                await self._lazy_mcp_task
            except asyncio.CancelledError:
                pass
        self._lazy_mcp_task = None
        if self._mcp is not None:
            await self._mcp.__aexit__(*exc)

    async def _enter_installation_binding(
        self, binding: GitHubInstallationBinding
    ) -> None:
        """Start MCP connection for an installation binding."""
        if binding.mcp_toolkit is not None:
            await binding.mcp_toolkit.__aenter__()
        elif (
            binding.lazy_mcp_config is not None
            and binding.lazy_mcp_secret_provider is not None
            and binding.lazy_mcp_task is None
        ):
            binding.lazy_mcp_task = asyncio.create_task(
                self._prepare_installation_mcp(binding)
            )

    async def _exit_installation_binding(
        self,
        binding: GitHubInstallationBinding,
        *exc: object,
    ) -> None:
        """Clean up MCP connection for an installation binding."""
        if binding.lazy_mcp_task is not None and not binding.lazy_mcp_task.done():
            binding.lazy_mcp_task.cancel()
            try:
                await binding.lazy_mcp_task
            except asyncio.CancelledError:
                pass
        binding.lazy_mcp_task = None
        if binding.mcp_toolkit is not None:
            await binding.mcp_toolkit.__aexit__(*exc)

    async def _prepare_installation_mcp(
        self, binding: GitHubInstallationBinding
    ) -> None:
        """Issue an installation token and start the lazy MCP connection."""
        assert binding.lazy_mcp_config is not None  # noqa: S101
        assert binding.lazy_mcp_secret_provider is not None  # noqa: S101
        try:
            secret = await binding.lazy_mcp_secret_provider()
            if secret is None:
                binding.lazy_mcp_error = (
                    "GitHub credential is unavailable for "
                    f"{binding.target.account_login}."
                )
                return
            binding.mcp_toolkit = McpToolkit(
                config=binding.lazy_mcp_config,
                secret=secret,
                on_auth_failure=binding.lazy_mcp_secret_provider,
                proxy_url=binding.lazy_mcp_proxy_url,
                session_manager=binding.session_manager,
                agent_id=binding.agent_id,
                session_id=binding.session_id,
                state_name=binding.state_name,
            )
            await binding.mcp_toolkit.__aenter__()
            binding.lazy_mcp_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Failed to prepare GitHub MCP toolkit",
                extra={
                    "installation_id": binding.target.installation_id,
                    "account_login": binding.target.account_login,
                },
            )
            binding.lazy_mcp_error = f"GitHub toolkit preparation failed: {exc}"

    async def _installation_update_context(
        self,
        binding: GitHubInstallationBinding,
        context: TurnContext,
    ) -> ToolkitState:
        """Return MCP state for one installation binding."""
        if binding.mcp_toolkit is None:
            if (
                binding.lazy_mcp_config is not None
                and binding.lazy_mcp_secret_provider is not None
                and binding.lazy_mcp_task is None
            ):
                binding.lazy_mcp_task = asyncio.create_task(
                    self._prepare_installation_mcp(binding)
                )
            if binding.lazy_mcp_task is not None and not binding.lazy_mcp_task.done():
                return await self._installation_snapshot_update_context(
                    binding,
                    context,
                )
            if binding.lazy_mcp_error is not None:
                return await self._installation_snapshot_update_context(
                    binding,
                    context,
                )
            return await self._installation_snapshot_update_context(
                binding,
                context,
            )
        return await binding.mcp_toolkit.update_context(context)

    async def _installation_snapshot_update_context(
        self,
        binding: GitHubInstallationBinding,
        context: TurnContext,
    ) -> ToolkitState:
        """Return tools from a previous installation MCP snapshot if available."""
        del context
        snapshot = await _load_installation_tool_snapshot(binding)
        tools = (
            self._tools_from_installation_snapshot(binding, snapshot)
            if snapshot is not None
            else []
        )
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    def _tools_from_installation_snapshot(
        self,
        binding: GitHubInstallationBinding,
        snapshot: McpToolSnapshotState,
    ) -> list[FunctionTool]:
        """Rebuild installation MCP tools before the lazy McpToolkit exists."""
        config = binding.lazy_mcp_config
        if config is None:
            return []

        async def headers_provider() -> dict[str, str]:
            return await self._installation_auth_headers(binding)

        tools: list[FunctionTool] = []
        for item in sorted(snapshot.tools, key=lambda tool: tool.model_name):
            mcp_tool = McpBaseTool(
                name=item.raw_name,
                description=item.description,
                inputSchema=item.input_schema,
            )
            tool = wrap_mcp_tool(
                mcp_tool,
                item.server_url,
                {},
                config.timeout,
                use_streamable_http=item.use_streamable_http,
                on_auth_failure=binding.lazy_mcp_secret_provider,
                proxy_url=binding.lazy_mcp_proxy_url,
                headers_provider=headers_provider,
            )
            if item.model_name != item.raw_name:
                tool = replace(
                    tool,
                    spec=replace(tool.spec, name=item.model_name),
                )
            tools.append(tool)
        return tools

    async def _installation_auth_headers(
        self,
        binding: GitHubInstallationBinding,
    ) -> dict[str, str]:
        """Build auth headers for an installation MCP tool call."""
        token = await self._get_cached_installation_token(
            binding.target.installation_id,
            binding.token_provider,
        )
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def _prepare_lazy_mcp(self) -> None:
        """Issue GitHub token in background and start MCP lazy load."""
        assert self._lazy_mcp_config is not None
        assert self._lazy_mcp_secret_provider is not None
        try:
            secret = await self._lazy_mcp_secret_provider()
            if secret is None:
                self._lazy_mcp_error = "GitHub credential is unavailable."
                return
            self._mcp = McpToolkit(
                config=self._lazy_mcp_config,
                secret=secret,
                on_auth_failure=self._lazy_mcp_secret_provider,
                proxy_url=self._lazy_mcp_proxy_url,
            )
            await self._mcp.__aenter__()
            self._lazy_mcp_error = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Failed to prepare GitHub MCP toolkit")
            self._lazy_mcp_error = f"GitHub toolkit preparation failed: {exc}"

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Fetch tools from GitHub MCP server and filter by toolset.

        :param context: Context passed each turn
        :return: Current state (tools + prompt)
        """
        if self._installation_bindings:
            return await self._update_context_multi_installation(context)

        state = await self._mcp_update_context(context)
        tools = state.tools
        if self._toolsets is not None:
            tools = _filter_by_toolsets(tools, self._toolsets)
        return ToolkitState(status=state.status, tools=tools)

    async def _update_context_multi_installation(
        self, context: TurnContext
    ) -> ToolkitState:
        """Merge and return MCP state for all installations."""
        tools: list[FunctionTool] = []
        for binding in sorted(
            self._installation_bindings,
            key=lambda item: (
                item.target.account_login,
                item.target.installation_id,
            ),
        ):
            state = await self._installation_update_context(binding, context)
            if state.status != ToolkitStatus.ENABLED:
                continue
            installation_tools = state.tools
            if self._toolsets is not None:
                installation_tools = _filter_by_toolsets(
                    installation_tools,
                    self._toolsets,
                )
            tools.extend(
                _with_tool_prefix(tool, binding.target) for tool in installation_tools
            )
        if len(self._installation_targets) > 1 and self.selected_installation_store:
            tools.append(self._create_switch_installation_tool())
        return ToolkitState(
            status=ToolkitStatus.ENABLED,
            tools=sorted(tools, key=lambda tool: tool.spec.name),
        )

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static GitHub prompt for the current run."""
        if self._installation_bindings:
            selected_target = await self._get_selected_installation_target()
            return _build_installation_prompt(
                self._installation_targets, selected_target
            )
        if self._mcp is None:
            return ""
        return await self._mcp.get_static_prompt(context)

    def _create_switch_installation_tool(self) -> FunctionTool:
        """Create switch_installation tool."""

        async def switch_installation(args: GitHubSwitchInstallationInput) -> str:
            """Select the default GitHub App installation for gh CLI commands."""
            target = self._resolve_installation_selection(args.installation)
            if target is None:
                raise FunctionToolError(
                    "Unknown GitHub installation. Available installations: "
                    f"{self._installation_options_text()}."
                )
            if self.selected_installation_store is None:
                raise FunctionToolError("GitHub installation selection is unavailable.")
            await self.selected_installation_store.save(target.installation_id)
            return (
                "Selected GitHub installation: "
                f"{target.account_login} ({target.installation_id}). "
                "GH_TOKEN and GITHUB_TOKEN now use this installation for "
                "runtime commands."
            )

        return make_tool(switch_installation, name="switch_installation")

    async def _mcp_update_context(self, context: TurnContext) -> ToolkitState:
        """Delegate to McpToolkit and return state.

        :param context: Context passed each turn
        :return: Tool state
        """
        if self._mcp is None:
            if (
                self._lazy_mcp_config is not None
                and self._lazy_mcp_secret_provider is not None
                and self._lazy_mcp_task is None
            ):
                self._lazy_mcp_task = asyncio.create_task(self._prepare_lazy_mcp())
            if self._lazy_mcp_task is not None and not self._lazy_mcp_task.done():
                return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
            if self._lazy_mcp_error is not None:
                return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
            return ToolkitState(status=ToolkitStatus.ENABLED, tools=[])
        return await self._mcp.update_context(context)


# ---------------------------------------------------------------------------
# GitHubToolkitProvider
# ---------------------------------------------------------------------------


class GitHubToolkitProvider(ToolkitProvider[GitHubToolkitConfig]):
    """GitHub Toolkit Provider.

    Supports three auth types (PAT, GitHub App BYOA, GitHub App Platform), and creates
    appropriate GitHubToolkit in resolve() based on auth type. Builds and uses
    McpToolkitConfig internally at resolve time.
    """

    slug = "github"
    name = "GitHub"
    description = "GitHub repository management via MCP"
    system_prompt = dedent("""\
        You have access to GitHub tools provided via the GitHub MCP server.
        Use the available tools to interact with GitHub repositories, issues,
        pull requests, and other resources as needed.""")
    config_model = GitHubToolkitConfig

    def __init__(
        self,
        *,
        platform_runtime: PlatformGitHubAppRuntimeService,
        session_manager: SessionManager[AsyncSession] | None = None,
    ) -> None:
        """Initialize GitHubToolkitProvider.

        :param platform_runtime: Operation-boundary Platform App resolver
        :param session_manager: DB session manager for Toolkit State
        """
        self.platform_runtime = platform_runtime
        self.session_manager = session_manager

    def to_mcp_config(self, config: GitHubToolkitConfig) -> McpToolkitConfig:
        """Convert to fixed GitHub MCP settings."""
        return _build_mcp_config(config)

    async def test_connection(
        self,
        config: GitHubToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test GitHub MCP server connection.

        Convert credential to bearer token by auth type, then test MCP transport.

        :param config: GitHub toolkit settings
        :param credentials_json: Decrypted credentials JSON
        :param proxy_url: egress proxy URL; direct connection when None
        :return: Connection test result
        """
        mcp_config = _build_mcp_config(config)
        try:
            token = await self._resolve_test_token(credentials_json)
        except ValueError as exc:
            return TestConnectionResult(
                success=False,
                message=str(exc),
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return await test_mcp_transport(
            mcp_config.server_url, headers, mcp_config.timeout, proxy_url=proxy_url
        )

    async def _resolve_test_token(
        self,
        credentials_json: str | None,
    ) -> str | None:
        """Resolve GitHub bearer token for tests.

        :param credentials_json: Decrypted credentials JSON
        :return: Bearer token or None
        """
        if credentials_json is None:
            return None

        try:
            secrets = _github_secrets_adapter.validate_json(credentials_json)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid GitHub credentials: {exc.error_count()} validation error(s)"
            ) from exc

        match secrets:
            case GitHubSecretsPAT():
                return secrets.token
            case GitHubSecretsApp():
                first = secrets.installations[0]
                return await _exchange_app_token(
                    secrets.app_id, secrets.private_key, first.installation_id
                )
            case GitHubSecretsAppPlatform():
                platform = await self.platform_runtime.resolve()
                if platform.app_id is None or platform.private_key is None:
                    raise ValueError("GitHub Platform App is not configured.")
                if secrets.app_id != platform.app_id:
                    raise ValueError("GitHub Platform App reconnect is required.")
                first = secrets.installations[0]
                return await _exchange_app_token(
                    platform.app_id,
                    platform.private_key,
                    first.installation_id,
                )
            case _:
                return None

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate ownership of installation_id for GitHub Platform App.

        :param session: DB session
        :param user_id: User ID
        :param credentials: Toolkit credentials
        :return: Error message or None
        """
        if credentials is None:
            return None

        if credentials.get("type") == "github_app_platform":
            platform = await self.platform_runtime.resolve()
            if platform.app_id is None:
                return "GitHub Platform App is not configured."
            credentials["app_id"] = platform.app_id

        try:
            secrets = _github_secrets_adapter.validate_python(credentials)
        except ValidationError as exc:
            return (
                f"Invalid GitHub credentials: {exc.error_count()} validation error(s)"
            )

        if not isinstance(secrets, GitHubSecretsAppPlatform):
            return None

        installations_raw = credentials.get("installations")
        if not isinstance(installations_raw, list):
            return "At least one GitHub installation must be selected."

        repo = GithubUserInstallationRepository()
        for item in installations_raw:
            if not isinstance(item, dict):
                return "GitHub installation is not accessible to this user."
            installation_id_raw = item.get("installation_id")
            if not isinstance(installation_id_raw, (int, str)):
                return "GitHub installation is not accessible to this user."
            try:
                installation_id = int(installation_id_raw)
            except ValueError:
                return "GitHub installation is not accessible to this user."
            has_access = await repo.has_access(
                session,
                user_id,
                secrets.app_id,
                installation_id,
            )
            if not has_access:
                return "GitHub installation is not accessible to this user."

        return None

    async def resolve(
        self,
        config: GitHubToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[GitHubToolkitConfig]:
        """Resolve credential according to auth type and return GitHubToolkit.

        Create McpToolkit directly and delegate to GitHubToolkit.
        GitHub resolves bearer/PAT/App authentication by itself.

        :param config: Validated GitHub Toolkit settings
        :param context: Resolve context
        :return: Credential-bound GitHubToolkit instance
        """
        mcp_config = _build_mcp_config(config)

        proxy_url = context.mcp_proxy_url

        if context.credentials_json is None:
            mcp_toolkit = McpToolkit(
                config=mcp_config,
                proxy_url=proxy_url,
                session_manager=self.session_manager,
                agent_id=context.agent_id,
                session_id=context.session_id,
                state_name=_github_snapshot_state_name(
                    toolkit_id=context.toolkit_id,
                    suffix="anonymous",
                ),
            )
            return GitHubToolkit(
                config=config, mcp_toolkit=mcp_toolkit, toolsets=config.toolsets
            )

        secrets = _github_secrets_adapter.validate_json(context.credentials_json)

        match secrets:
            case GitHubSecretsPAT():
                return self._resolve_pat(secrets, config, context, proxy_url=proxy_url)
            case GitHubSecretsApp():
                return await self._resolve_github_app(
                    secrets,
                    config,
                    context,
                    proxy_url=proxy_url,
                )
            case GitHubSecretsAppPlatform():
                return await self._resolve_github_app_platform(
                    secrets,
                    config,
                    context,
                    proxy_url=proxy_url,
                )
            case _:
                raise ValueError(f"Unknown GitHub secret type: {type(secrets)}")

    def _resolve_pat(
        self,
        secrets: GitHubSecretsPAT,
        config: GitHubToolkitConfig,
        context: ResolveContext,
        *,
        proxy_url: str | None = None,
    ) -> GitHubToolkit:
        """Create GitHubToolkit with PAT auth type.

        :param secrets: PAT credentials
        :param config: GitHub Toolkit settings
        :param proxy_url: MCP egress proxy URL; direct connection when None
        :return: GitHubToolkit instance
        """
        mcp_config = _build_mcp_config(config)
        mcp_toolkit = McpToolkit(
            config=mcp_config,
            secret=secrets.token,
            proxy_url=proxy_url,
            session_manager=self.session_manager,
            agent_id=context.agent_id,
            session_id=context.session_id,
            state_name=_github_snapshot_state_name(
                toolkit_id=context.toolkit_id,
                suffix="pat",
            ),
        )

        # workspace-shared PAT is fixed in config credentials, so same value every time.
        runtime_environment_token_provider: (
            Callable[[], Awaitable[str | None]] | None
        ) = None
        if config.inject_runtime_environment:
            pat_token = secrets.token

            async def _provide_static_pat() -> str:
                return pat_token

            runtime_environment_token_provider = _provide_static_pat

        return GitHubToolkit(
            config=config,
            mcp_toolkit=mcp_toolkit,
            toolsets=config.toolsets,
            runtime_environment_token_provider=runtime_environment_token_provider,
        )

    def _make_selected_installation_store(
        self,
        context: ResolveContext,
    ) -> GitHubSelectedInstallationStore | None:
        """Create selected installation store when session identity is available."""
        if self.session_manager is None:
            return None
        return GitHubSelectedInstallationStore(
            session_manager=self.session_manager,
            agent_id=context.agent_id,
            session_id=context.session_id,
        )

    async def _resolve_github_app(
        self,
        secrets: GitHubSecretsApp,
        config: GitHubToolkitConfig,
        context: ResolveContext,
        *,
        proxy_url: str | None = None,
    ) -> GitHubToolkit:
        """Create GitHubToolkit with GitHub App (BYOA) auth type.

        Create JWT, exchange for installation token, and bind to McpToolkit.

        :param secrets: GitHub App credentials
        :param config: GitHub Toolkit settings
        :param proxy_url: MCP egress proxy URL; direct connection when None
        :return: GitHubToolkit instance
        """
        mcp_config = _build_mcp_config(config)
        bindings = _build_installation_bindings(
            config=config,
            mcp_config=mcp_config,
            app_id=secrets.app_id,
            private_key=secrets.private_key,
            targets=secrets.installations,
            proxy_url=proxy_url,
            session_manager=self.session_manager,
            agent_id=context.agent_id,
            session_id=context.session_id,
            toolkit_id=context.toolkit_id,
        )
        return GitHubToolkit(
            config=config,
            toolsets=config.toolsets,
            installation_bindings=bindings,
            selected_installation_store=self._make_selected_installation_store(context),
        )

    async def _resolve_github_app_platform(
        self,
        secrets: GitHubSecretsAppPlatform,
        config: GitHubToolkitConfig,
        context: ResolveContext,
        *,
        proxy_url: str | None = None,
    ) -> GitHubToolkit:
        """Create GitHubToolkit with GitHub App (Platform) auth type.

        Exchange installation tokens using current effective System Settings.

        :param secrets: Platform App credentials (installation_id only)
        :param config: GitHub Toolkit settings
        :param proxy_url: MCP egress proxy URL; direct connection when None
        :return: GitHubToolkit instance
        :raises ValueError: When Platform App settings are absent
        """
        platform = await self.platform_runtime.resolve()
        if platform.app_id is None or platform.private_key is None:
            raise ValueError("GitHub Platform App is not configured.")
        if secrets.app_id != platform.app_id:
            raise ValueError("GitHub Platform App reconnect is required.")

        mcp_config = _build_mcp_config(config)
        bindings = _build_platform_installation_bindings(
            config=config,
            mcp_config=mcp_config,
            expected_app_id=secrets.app_id,
            targets=secrets.installations,
            proxy_url=proxy_url,
            session_manager=self.session_manager,
            agent_id=context.agent_id,
            session_id=context.session_id,
            toolkit_id=context.toolkit_id,
            platform_runtime=self.platform_runtime,
        )
        logger.info(
            "GitHub github_app_platform installations resolved",
            extra={
                "event": "github_toolkit.installations_resolved",
                "auth_type": "github_app_platform",
                "installation_count": len(secrets.installations),
                "inject_runtime_environment_config": config.inject_runtime_environment,
            },
        )
        return GitHubToolkit(
            config=config,
            toolsets=config.toolsets,
            installation_bindings=bindings,
            selected_installation_store=self._make_selected_installation_store(context),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_installation_bindings(
    *,
    config: GitHubToolkitConfig,
    mcp_config: McpToolkitConfig,
    app_id: str,
    private_key: str,
    targets: list[GitHubInstallationTarget],
    proxy_url: str | None,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    session_id: str,
    toolkit_id: str,
) -> list[GitHubInstallationBinding]:
    """Build bindings for each GitHub App installation."""
    bindings: list[GitHubInstallationBinding] = []
    for target in targets:
        installation_id = target.installation_id

        async def provide_token(
            *,
            captured_installation_id: str = installation_id,
        ) -> str:
            """Issue an installation token."""
            return await _exchange_app_token(
                app_id,
                private_key,
                captured_installation_id,
            )

        bindings.append(
            GitHubInstallationBinding(
                target=target,
                mcp_toolkit=None,
                token_provider=provide_token,
                lazy_mcp_config=mcp_config,
                lazy_mcp_secret_provider=provide_token,
                lazy_mcp_proxy_url=proxy_url,
                session_manager=session_manager,
                agent_id=agent_id,
                session_id=session_id,
                state_name=_github_snapshot_state_name(
                    toolkit_id=toolkit_id,
                    suffix=f"installation:{target.installation_id}",
                ),
            )
        )
    return bindings


def _build_platform_installation_bindings(
    *,
    config: GitHubToolkitConfig,
    mcp_config: McpToolkitConfig,
    expected_app_id: str,
    targets: list[GitHubInstallationTarget],
    proxy_url: str | None,
    session_manager: SessionManager[AsyncSession] | None,
    agent_id: str,
    session_id: str,
    toolkit_id: str,
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> list[GitHubInstallationBinding]:
    """Build Platform bindings that re-resolve settings per token issuance."""
    bindings: list[GitHubInstallationBinding] = []
    for target in targets:
        installation_id = target.installation_id

        async def provide_token(
            *,
            captured_installation_id: str = installation_id,
        ) -> str:
            platform = await platform_runtime.resolve()
            if platform.app_id != expected_app_id:
                raise ValueError("GitHub Platform App reconnect is required.")
            if platform.private_key is None:
                raise ValueError("GitHub Platform App is not configured.")
            return await _exchange_app_token(
                expected_app_id,
                platform.private_key,
                captured_installation_id,
            )

        bindings.append(
            GitHubInstallationBinding(
                target=target,
                mcp_toolkit=None,
                token_provider=provide_token,
                lazy_mcp_config=mcp_config,
                lazy_mcp_secret_provider=provide_token,
                lazy_mcp_proxy_url=proxy_url,
                session_manager=session_manager,
                agent_id=agent_id,
                session_id=session_id,
                state_name=_github_snapshot_state_name(
                    toolkit_id=toolkit_id,
                    suffix=f"installation:{target.installation_id}",
                ),
            )
        )
    return bindings


async def _load_installation_tool_snapshot(
    binding: GitHubInstallationBinding,
) -> McpToolSnapshotState | None:
    """Load a previous MCP tool snapshot before lazy GitHub MCP setup finishes."""
    config = binding.lazy_mcp_config
    if (
        config is None
        or binding.session_manager is None
        or not binding.agent_id
        or not binding.session_id
    ):
        return None
    identity = ToolkitStateIdentity(
        agent_id=binding.agent_id,
        session_id=binding.session_id,
        toolkit_namespace="mcp",
        state_name=binding.state_name,
    )
    async with binding.session_manager() as session:
        handle = ToolkitStateStore(session=session).handle(
            identity,
            McpToolSnapshotState,
        )
        snapshot = await handle.load(default_factory=McpToolSnapshotState)
    if not snapshot.tools:
        return None
    if snapshot.server_url != config.server_url:
        return None
    return snapshot


def _github_snapshot_state_name(*, toolkit_id: str, suffix: str) -> str:
    """Return stable Toolkit State name for a GitHub MCP tool snapshot."""
    digest = hashlib.sha256(f"{toolkit_id}:{suffix}".encode("utf-8")).hexdigest()[:16]
    return f"tool_snapshot:{digest}"


async def _exchange_app_token(
    app_id: str, private_key: str, installation_id: str
) -> str:
    """GitHub App JWT -> installation token exchange.

    :param app_id: GitHub App ID
    :param private_key: Private key in PEM format
    :param installation_id: Installation ID
    :return: Installation access token
    """
    jwt_token = create_github_app_jwt(app_id, private_key)
    return await exchange_installation_token(jwt_token, installation_id)
