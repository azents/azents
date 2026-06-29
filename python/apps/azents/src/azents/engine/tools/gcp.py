"""GCP Toolkit.

Service Toolkit that connects directly to Google Hosted Remote MCP server via HTTPS.
Authenticates by exchanging SA Key -> JWT -> access_token,
and provides integrated tools by connecting to multiple service-specific MCP servers.
"""

import asyncio
import dataclasses
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from textwrap import dedent
from typing import ClassVar

import httpx
import jwt
from azcommon.datetime import tznow
from mcp.types import Tool as McpBaseTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.mcp_transport import (
    call_tool as mcp_call_tool,
)
from azents.core.mcp_transport import (
    extract_network_error,
)
from azents.core.mcp_transport import (
    list_tools as mcp_list_tools,
)
from azents.core.tools import (
    GcpService,
    GcpToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
    ToolkitState,
    ToolkitStatus,
    TurnContext,
)
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
)
from azents.engine.tooling.toolkit_state import (
    ToolkitStateHandle,
    ToolkitStateIdentity,
    ToolkitStateStore,
)
from azents.engine.tools.mcp_base import (
    ArtifactSinkGetter,
    McpArtifactSink,
    McpToolSnapshotItem,
    McpToolSnapshotState,
    _extract_tool_result,  # pyright: ignore[reportPrivateUsage] -- reuse common MCP result extraction for GCP wrapper.
    _is_http_401,  # pyright: ignore[reportPrivateUsage] -- reuse common MCP 401 retry detection.
    build_mcp_artifact_sink,
)
from azents.rdb.session import SessionManager
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

_GCP_TOOLKIT_STATE_NAMESPACE = "gcp"


# ---------------------------------------------------------------------------
# GCP Secrets
# ---------------------------------------------------------------------------


class GcpSecrets(BaseModel):
    """GCP Service Account Key (encrypted storage)."""

    service_account_key: dict[str, str]


_SA_KEY_REQUIRED_FIELDS = {
    "type",
    "project_id",
    "private_key",
    "client_email",
    "token_uri",
}


# ---------------------------------------------------------------------------
# Service metadata
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class GcpServiceMeta:
    """GCP MCP per-service metadata."""

    endpoint: str
    scopes: list[str]
    iam_role: str
    description: str


GCP_SERVICE_CONFIG: dict[GcpService, GcpServiceMeta] = {
    GcpService.LOGGING: GcpServiceMeta(
        endpoint="https://logging.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/logging.read"],
        iam_role="roles/logging.viewer",
        description="Cloud Logging — log queries and analysis",
    ),
    GcpService.MONITORING: GcpServiceMeta(
        endpoint="https://monitoring.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/monitoring.read"],
        iam_role="roles/monitoring.viewer",
        description="Cloud Monitoring — metrics, alerts, PromQL",
    ),
    GcpService.GKE: GcpServiceMeta(
        endpoint="https://container.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/container.viewer",
        description="GKE — cluster and Kubernetes resource status",
    ),
    GcpService.COMPUTE: GcpServiceMeta(
        endpoint="https://compute.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/compute.readonly"],
        iam_role="roles/compute.viewer",
        description="Compute Engine — VM instances, disks, networks",
    ),
    GcpService.CLOUD_RUN: GcpServiceMeta(
        endpoint="https://run.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/run.viewer",
        description="Cloud Run — service status and deployment",
    ),
    GcpService.CLOUD_SQL: GcpServiceMeta(
        endpoint="https://sqladmin.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
        iam_role="roles/cloudsql.viewer",
        description="Cloud SQL — database instances and queries",
    ),
    GcpService.BIGQUERY: GcpServiceMeta(
        endpoint="https://bigquery.googleapis.com/mcp",
        scopes=["https://www.googleapis.com/auth/bigquery"],
        iam_role="roles/bigquery.dataViewer",
        description="BigQuery — data analysis and SQL queries",
    ),
}

# Refresh margin before token expiration
_TOKEN_REFRESH_MARGIN = timedelta(minutes=5)
# JWT validity period
_JWT_LIFETIME = timedelta(hours=1)
# Token endpoint
_GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


# ---------------------------------------------------------------------------
# Access Token Provider
# ---------------------------------------------------------------------------


class GcpAccessTokenProvider:
    """Issue, cache, and refresh access_token from SA Key.

    :param service_account_key: Service Account Key JSON dict
    :param scopes: OAuth2 scope list
    """

    def __init__(
        self,
        service_account_key: dict[str, str],
        scopes: list[str],
    ) -> None:
        self._key = service_account_key
        self._scopes = scopes
        self._token: str | None = None
        self._expires_at: datetime | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return valid access_token with automatic early refresh."""
        if self._is_token_valid():
            # Type system limitation: when _is_token_valid is True, _token is not None
            assert self._token is not None  # noqa: S101
            return self._token

        async with self._lock:
            if self._is_token_valid():
                assert self._token is not None  # noqa: S101
                return self._token
            return await self._refresh_token()

    def invalidate(self) -> None:
        """Invalidate cached token. Refresh on next get_token() call."""
        self._token = None
        self._expires_at = None

    def _is_token_valid(self) -> bool:
        """Check whether token is valid."""
        if self._token is None or self._expires_at is None:
            return False
        return self._expires_at > tznow() + _TOKEN_REFRESH_MARGIN

    async def _refresh_token(self) -> str:
        """Create JWT and obtain access_token."""
        now = tznow()
        payload = {
            "iss": self._key["client_email"],
            "scope": " ".join(self._scopes),
            "aud": _GOOGLE_TOKEN_URL,
            "iat": int(now.timestamp()),
            "exp": int((now + _JWT_LIFETIME).timestamp()),
        }
        signed_jwt = jwt.encode(payload, self._key["private_key"], algorithm="RS256")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": signed_jwt,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        token: str = data["access_token"]
        self._token = token
        self._expires_at = now + timedelta(seconds=data["expires_in"])
        return token


# ---------------------------------------------------------------------------
# GcpToolkit
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _GcpServerConfig:
    """Per-service MCP server connection info."""

    service: GcpService
    endpoint: str
    timeout: float


class GcpToolkit(Toolkit[GcpToolkitConfig]):
    """Provide GCP MCP tools from Toolkit State snapshots."""

    def __init__(
        self,
        *,
        config: GcpToolkitConfig,
        token_provider: GcpAccessTokenProvider,
        server_configs: list[_GcpServerConfig],
        project_id: str,
        writable_services: set[GcpService],
        proxy_url: str | None,
        artifact_service: ArtifactService | None,
        session_manager: SessionManager[AsyncSession] | None,
        agent_id: str,
        session_id: str,
        state_name: str,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._server_configs = server_configs
        self._project_id = project_id
        self._writable_services = writable_services
        self._proxy_url = proxy_url
        self._artifact_service = artifact_service
        self._session_manager = session_manager
        self._agent_id = agent_id
        self._session_id = session_id
        self._state_name = state_name
        self._bg_task: asyncio.Task[None] | None = None
        self._artifact_sink: McpArtifactSink | None = None
        self._entered = False

    def _current_artifact_sink(self) -> McpArtifactSink | None:
        """Return Artifact sink for current run."""
        return self._artifact_sink

    def _refresh_artifact_sink(self, context: TurnContext) -> None:
        """Update Artifact sink for current run from TurnContext."""
        self._artifact_sink = build_mcp_artifact_sink(
            context,
            self._artifact_service,
        )

    async def __aenter__(self) -> GcpToolkit:
        """Start GCP MCP snapshot refresh in background."""
        self._entered = True
        self._ensure_refresh_task()
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel background refresh task."""
        if self._bg_task is not None and not self._bg_task.done():
            self._bg_task.cancel()
            try:
                await self._bg_task
            except asyncio.CancelledError:
                pass
        self._bg_task = None

    def _ensure_refresh_task(self) -> None:
        """Start background refresh unless one is already running."""
        if self._bg_task is not None and not self._bg_task.done():
            return
        self._bg_task = asyncio.create_task(self._refresh_tool_snapshot())

    async def _refresh_tool_snapshot(self) -> None:
        """Refresh the GCP MCP tool snapshot in the background."""
        previous = await self._load_tool_snapshot()
        previous_by_endpoint = _gcp_snapshot_items_by_endpoint(previous)
        refreshed_by_endpoint: dict[str, list[McpToolSnapshotItem]] = {}
        success_count = 0
        for server in sorted(self._server_configs, key=lambda item: item.service.value):
            try:
                items = await self._refresh_service_items(server)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Failed to refresh GCP MCP service snapshot",
                    extra={
                        "service": server.service.value,
                        "endpoint": server.endpoint,
                    },
                )
                continue
            refreshed_by_endpoint[server.endpoint] = items
            success_count += 1

        if success_count == 0 and previous is None:
            return

        merged: list[McpToolSnapshotItem] = []
        for server in sorted(self._server_configs, key=lambda item: item.service.value):
            items = refreshed_by_endpoint.get(server.endpoint)
            if items is None:
                items = previous_by_endpoint.get(server.endpoint, [])
            merged.extend(items)
        if not merged:
            return

        snapshot = _build_gcp_tool_snapshot(items=merged, project_id=self._project_id)
        await self._save_tool_snapshot(snapshot)
        logger.info(
            "GCP MCP tool snapshot refreshed",
            extra={
                "tool_count": len(snapshot.tools),
                "tool_hash": snapshot.tool_hash,
                "refreshed_service_count": success_count,
            },
        )

    async def _refresh_service_items(
        self,
        server: _GcpServerConfig,
    ) -> list[McpToolSnapshotItem]:
        """Refresh one GCP service and return snapshot items."""
        access_token = await self._token_provider.get_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": self._project_id,
        }
        mcp_tools, use_streamable_http = await mcp_list_tools(
            server.endpoint,
            headers,
            server.timeout,
            proxy_url=self._proxy_url,
        )
        writable = server.service in self._writable_services
        items: list[McpToolSnapshotItem] = []
        for tool in sorted(mcp_tools, key=lambda item: item.name):
            if not writable and not _is_read_only_tool(tool):
                continue
            items.append(
                McpToolSnapshotItem(
                    raw_name=tool.name,
                    model_name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                    server_url=server.endpoint,
                    use_streamable_http=use_streamable_http,
                )
            )
        return items

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Return GCP tools from the latest successful Toolkit State snapshot."""
        self._refresh_artifact_sink(context)
        snapshot = await self._load_tool_snapshot()
        tools = self._tools_from_snapshot(snapshot) if snapshot is not None else []
        if self._entered:
            self._ensure_refresh_task()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools)

    async def get_static_prompt(self, context: TurnContext) -> str:
        """Return static GCP toolkit prompt for the current run."""
        del context
        return self._render_config_prompt()

    async def _load_tool_snapshot(self) -> McpToolSnapshotState | None:
        """Load the latest successful GCP MCP tool snapshot."""
        if self._session_manager is None:
            return None
        async with self._session_manager() as session:
            handle = self._tool_snapshot_handle(session)
            if handle is None:
                return None
            snapshot = await handle.load(default_factory=McpToolSnapshotState)
        if not snapshot.tools or snapshot.server_url != self._project_id:
            return None
        return snapshot

    async def _save_tool_snapshot(self, snapshot: McpToolSnapshotState) -> None:
        """Atomically save a successful GCP MCP tool snapshot."""
        if self._session_manager is None:
            return
        async with self._session_manager() as session:
            handle = self._tool_snapshot_handle(session)
            if handle is None:
                return
            await handle.load(default_factory=McpToolSnapshotState)
            await handle.save(snapshot)

    def _tool_snapshot_handle(
        self,
        session: AsyncSession,
    ) -> ToolkitStateHandle[McpToolSnapshotState] | None:
        """Create Toolkit State handle for the GCP MCP snapshot."""
        if not self._agent_id or not self._session_id:
            return None
        identity = ToolkitStateIdentity(
            agent_id=self._agent_id,
            session_id=self._session_id,
            toolkit_namespace=_GCP_TOOLKIT_STATE_NAMESPACE,
            state_name=self._state_name,
        )
        return ToolkitStateStore(session=session).handle(identity, McpToolSnapshotState)

    def _tools_from_snapshot(
        self, snapshot: McpToolSnapshotState
    ) -> list[FunctionTool]:
        """Rebuild GCP tool wrappers from a stored snapshot."""
        server_timeout = {
            server.endpoint: server.timeout for server in self._server_configs
        }
        tools = [
            _wrap_gcp_snapshot_tool(
                item=item,
                timeout=server_timeout[item.server_url],
                token_provider=self._token_provider,
                project_id=self._project_id,
                proxy_url=self._proxy_url,
                artifact_sink_getter=self._current_artifact_sink,
            )
            for item in sorted(snapshot.tools, key=lambda tool: tool.model_name)
            if item.server_url in server_timeout
        ]
        return sorted(tools, key=lambda tool: tool.spec.name)

    def _render_config_prompt(self) -> str:
        """Provide enabled service list as prompt."""
        config = self._config
        service_lines = []
        for svc in sorted(config.services):
            meta = GCP_SERVICE_CONFIG[svc]
            writable = svc in self._writable_services
            mode = "read+write" if writable else "read-only"
            service_lines.append(f"  - {meta.description} ({mode})")
        services_text = "\n".join(service_lines)
        return f"GCP Project: {config.project_id}\nEnabled services:\n{services_text}"


def _is_read_only_tool(tool: McpBaseTool) -> bool:
    """Check whether MCP tool is read-only.

    When annotations.readOnlyHint is absent, treat as read-only for safety.
    """
    if tool.annotations is None:
        return True
    read_only_hint = tool.annotations.readOnlyHint
    if read_only_hint is None:
        return True
    return read_only_hint


def _wrap_gcp_snapshot_tool(
    *,
    item: McpToolSnapshotItem,
    timeout: float,
    token_provider: GcpAccessTokenProvider,
    project_id: str,
    proxy_url: str | None,
    artifact_sink_getter: ArtifactSinkGetter | None,
) -> FunctionTool:
    """Wrap a GCP MCP snapshot item as a FunctionTool."""
    spec = FunctionToolSpec(
        name=item.model_name,
        description=item.description,
        input_schema=item.input_schema,
    )

    async def handler(arguments_json: str) -> str | FunctionToolResult:
        try:
            args: dict[str, object] = (
                json.loads(arguments_json) if arguments_json else {}
            )
        except json.JSONDecodeError as exc:
            raise FunctionToolError(f"Invalid JSON in tool arguments: {exc}") from None
        access_token = await token_provider.get_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": project_id,
        }
        try:
            result = await mcp_call_tool(
                item.server_url,
                headers,
                timeout,
                item.raw_name,
                args,
                use_streamable_http=item.use_streamable_http,
                proxy_url=proxy_url,
            )
        except Exception as exc:
            if _is_http_401(exc):
                refreshed_token = await token_provider.get_token()
                retry_headers = {
                    "Authorization": f"Bearer {refreshed_token}",
                    "x-goog-user-project": project_id,
                }
                result = await mcp_call_tool(
                    item.server_url,
                    retry_headers,
                    timeout,
                    item.raw_name,
                    args,
                    use_streamable_http=item.use_streamable_http,
                    proxy_url=proxy_url,
                )
            else:
                raise
        return await _extract_tool_result(
            result,
            tool_name=item.raw_name,
            artifact_sink=(
                artifact_sink_getter() if artifact_sink_getter is not None else None
            ),
        )

    return FunctionTool(spec=spec, handler=handler)


def _gcp_snapshot_items_by_endpoint(
    snapshot: McpToolSnapshotState | None,
) -> dict[str, list[McpToolSnapshotItem]]:
    """Group a previous GCP snapshot by endpoint."""
    grouped: dict[str, list[McpToolSnapshotItem]] = {}
    if snapshot is None:
        return grouped
    for item in snapshot.tools:
        grouped.setdefault(item.server_url, []).append(item)
    return grouped


def _build_gcp_tool_snapshot(
    *,
    items: list[McpToolSnapshotItem],
    project_id: str,
) -> McpToolSnapshotState:
    """Build a deterministic GCP MCP tool snapshot."""
    ordered = sorted(items, key=lambda item: (item.server_url, item.model_name))
    payload = [item.model_dump(mode="json") for item in ordered]
    tool_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return McpToolSnapshotState(
        loaded_at=datetime.now(UTC).isoformat(),
        server_url=project_id,
        tool_hash=tool_hash,
        tools=ordered,
    )


def _gcp_snapshot_state_name(*, toolkit_id: str, config: GcpToolkitConfig) -> str:
    """Return stable Toolkit State name for a GCP MCP tool snapshot."""
    payload = {
        "toolkit_id": toolkit_id,
        "project_id": config.project_id,
        "services": sorted(config.services),
        "writable_services": sorted(config.writable_services),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"tool_snapshot:{digest}"


# ---------------------------------------------------------------------------
# GcpToolkitProvider
# ---------------------------------------------------------------------------


class GcpToolkitProvider(ToolkitProvider[GcpToolkitConfig]):
    """GCP Toolkit Provider.

    Direct HTTP connection to Google Hosted Remote MCP server.
    Provide integrated tools by connecting to selected service MCP servers.
    """

    slug: ClassVar[str] = "gcp"
    name: ClassVar[str] = "GCP"
    description: ClassVar[str] = (
        "Google Cloud Platform — Logging, Monitoring, GKE, "
        "Compute Engine, Cloud Run, Cloud SQL"
    )
    system_prompt: ClassVar[str] = dedent("""\
        You have access to Google Cloud Platform tools.
        Use them to query logs, metrics, alerts, Kubernetes resources,
        VM instances, and other GCP infrastructure from the configured project.""")
    config_model: ClassVar[type[BaseModel]] = GcpToolkitConfig

    def __init__(
        self,
        *,
        artifact_service: ArtifactService | None = None,
        session_manager: SessionManager[AsyncSession] | None = None,
    ) -> None:
        """Initialize GcpToolkitProvider."""
        self._artifact_service = artifact_service
        self._session_manager = session_manager

    async def resolve(
        self,
        config: GcpToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[GcpToolkitConfig]:
        """Decrypt SA Key and configure multiple MCP server connections."""
        if context.credentials_json is None:
            msg = "GCP toolkit requires Service Account Key credentials"
            raise ValueError(msg)

        secrets = GcpSecrets.model_validate_json(context.credentials_json)

        # Collect required scopes
        all_scopes: set[str] = set()
        for svc in config.services:
            all_scopes.update(GCP_SERVICE_CONFIG[svc].scopes)

        token_provider = GcpAccessTokenProvider(
            service_account_key=secrets.service_account_key,
            scopes=sorted(all_scopes),
        )

        server_configs = [
            _GcpServerConfig(
                service=svc,
                endpoint=GCP_SERVICE_CONFIG[svc].endpoint,
                timeout=config.timeout,
            )
            for svc in config.services
        ]

        return GcpToolkit(
            config=config,
            token_provider=token_provider,
            server_configs=server_configs,
            project_id=config.project_id,
            writable_services=set(config.writable_services),
            proxy_url=context.mcp_proxy_url,
            artifact_service=self._artifact_service,
            session_manager=self._session_manager,
            agent_id=context.agent_id,
            session_id=context.session_id,
            state_name=_gcp_snapshot_state_name(
                toolkit_id=context.toolkit_id,
                config=config,
            ),
        )

    async def validate_credentials(
        self,
        session: AsyncSession,
        user_id: str,
        credentials: dict[str, object] | None,
    ) -> str | None:
        """Validate Service Account Key JSON structure."""
        if credentials is None:
            return "Service Account Key is required"

        try:
            secrets = GcpSecrets.model_validate(credentials)
        except ValidationError as e:
            return f"Invalid credentials format: {e}"

        key = secrets.service_account_key
        missing = _SA_KEY_REQUIRED_FIELDS - key.keys()
        if missing:
            return f"Service Account Key missing fields: {', '.join(sorted(missing))}"

        if key.get("type") != "service_account":
            return f"Expected type 'service_account', got '{key.get('type')}'"

        return None

    async def test_connection(
        self,
        config: GcpToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test connection with token issuance + per-service tools/list call."""
        if not credentials_json:
            return TestConnectionResult(
                success=False,
                message="No credentials provided",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        try:
            secrets = GcpSecrets.model_validate_json(credentials_json)
        except ValidationError as e:
            return TestConnectionResult(
                success=False,
                message=f"Invalid credentials: {e}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )

        key = secrets.service_account_key

        # 1. Token issuance test
        all_scopes: set[str] = set()
        for svc in config.services:
            all_scopes.update(GCP_SERVICE_CONFIG[svc].scopes)

        try:
            provider = GcpAccessTokenProvider(key, sorted(all_scopes))
            token = await provider.get_token()
        except Exception as exc:
            net_msg = extract_network_error(exc)
            if net_msg is not None:
                return TestConnectionResult(
                    success=False,
                    message=f"Authentication failed: {net_msg}",
                    discovered_auth_url=None,
                    discovered_token_url=None,
                    supports_dcr=None,
                )
            raise

        # 2. Per-service connection test
        headers = {
            "Authorization": f"Bearer {token}",
            "x-goog-user-project": config.project_id,
        }
        results: list[str] = []
        any_failed = False
        for svc in config.services:
            meta = GCP_SERVICE_CONFIG[svc]
            try:
                tools, _ = await mcp_list_tools(
                    meta.endpoint, headers, 10.0, proxy_url=proxy_url
                )
                results.append(f"{svc.value}: {len(tools)} tools")
            except Exception as exc:
                net_msg = extract_network_error(exc)
                if net_msg is None:
                    raise
                results.append(f"{svc.value}: FAILED ({net_msg})")
                any_failed = True

        detail = ", ".join(results)
        client_email = key.get("client_email", "unknown")
        if any_failed:
            return TestConnectionResult(
                success=False,
                message=f"Partial failure as {client_email}: {detail}",
                discovered_auth_url=None,
                discovered_token_url=None,
                supports_dcr=None,
            )
        return TestConnectionResult(
            success=True,
            message=f"Connected to '{config.project_id}' as {client_email}: {detail}",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )
