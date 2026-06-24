"""GCP Toolkit.

Service Toolkit that connects directly to Google Hosted Remote MCP server via HTTPS.
Authenticates by exchanging SA Key -> JWT -> access_token,
and provides integrated tools by connecting to multiple service-specific MCP servers.
"""

import asyncio
import dataclasses
import logging
from datetime import datetime, timedelta
from textwrap import dedent
from typing import ClassVar

import httpx
import jwt
from azcommon.datetime import tznow
from mcp.types import Tool as McpBaseTool
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

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
from azents.engine.run.types import FunctionTool
from azents.engine.tools.mcp_base import (
    ArtifactSinkGetter,
    McpArtifactSink,
    build_mcp_artifact_sink,
    wrap_mcp_tool,
)
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)


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
    """Provide integrated tools from multiple GCP MCP servers.

    **Dynamic status transition (state machine)**:
    - ``__aenter__``: Start per-service background parallel connection
    - ``update_context()``: Return ready service tools; others get loading prompt
    - ``__aexit__``: Cancel all background tasks

    :param token_provider: access_token issuer
    :param server_configs: Per-service MCP server settings
    :param project_id: GCP project ID for x-goog-user-project header
    :param writable_services: Service set allowing write access
    :param proxy_url: MCP egress proxy URL
    """

    def __init__(
        self,
        *,
        config: GcpToolkitConfig,
        token_provider: GcpAccessTokenProvider,
        server_configs: list[_GcpServerConfig],
        project_id: str,
        writable_services: set[GcpService],
        proxy_url: str | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        self._config = config
        self._token_provider = token_provider
        self._server_configs = server_configs
        self._project_id = project_id
        self._writable_services = writable_services
        self._proxy_url = proxy_url
        self._artifact_service = artifact_service
        # Background connection status
        self._bg_tasks: dict[GcpService, asyncio.Task[None]] = {}
        self._bg_results: dict[GcpService, list[FunctionTool]] = {}
        self._bg_errors: dict[GcpService, str] = {}
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
        """Start per-service background parallel MCP connections."""
        self._entered = True
        for server in self._server_configs:
            task = asyncio.create_task(self._connect_service(server))
            self._bg_tasks[server.service] = task
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Cancel all background connection tasks."""
        for task in self._bg_tasks.values():
            if not task.done():
                task.cancel()
        for task in self._bg_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._bg_tasks.clear()

    async def _connect_service(self, server: _GcpServerConfig) -> None:
        """Connect to MCP server for a single service and collect tools.

        :param server: Per-service MCP server settings
        """
        try:
            access_token = await self._token_provider.get_token()
        except Exception:
            logger.exception(
                "Failed to get GCP access token",
                extra={"service": server.service.value},
            )
            self._bg_errors[server.service] = (
                f"GCP token acquisition failed for {server.service.value}"
            )
            return

        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": self._project_id,
        }

        try:
            mcp_tools, use_streamable_http = await mcp_list_tools(
                server.endpoint,
                headers,
                server.timeout,
                proxy_url=self._proxy_url,
            )
        except Exception as exc:
            logger.exception(
                "Failed to list tools from GCP MCP server",
                extra={
                    "service": server.service.value,
                    "endpoint": server.endpoint,
                },
            )
            self._bg_errors[server.service] = (
                f"GCP {server.service.value} connection failed: {exc}"
            )
            return

        is_writable = server.service in self._writable_services
        tools: list[FunctionTool] = []
        for mcp_tool in mcp_tools:
            if not is_writable and not _is_read_only_tool(mcp_tool):
                continue
            tools.append(
                _wrap_gcp_tool(
                    mcp_tool=mcp_tool,
                    server_url=server.endpoint,
                    headers=headers,
                    timeout=server.timeout,
                    use_streamable_http=use_streamable_http,
                    token_provider=self._token_provider,
                    project_id=self._project_id,
                    proxy_url=self._proxy_url,
                    artifact_sink_getter=self._current_artifact_sink,
                )
            )
        self._bg_results[server.service] = tools

    async def update_context(self, context: TurnContext) -> ToolkitState:
        """Collect and return tools from enabled per-service MCP servers.

        After __aenter__: return ready service tools; others get loading prompt.
        Without __aenter__: parallel collection in sync mode (backward compatibility).
        """
        self._refresh_artifact_sink(context)
        if not self._entered:
            return await self._sync_update_context()

        # Collect from background status
        tools: list[FunctionTool] = []
        loading_services: list[str] = []

        for server in self._server_configs:
            svc = server.service
            task = self._bg_tasks.get(svc)

            if svc in self._bg_results:
                # Connection complete: collect tools
                tools.extend(self._bg_results[svc])
            elif svc in self._bg_errors:
                # Connection failure: skip (error already logged)
                pass
            elif task is not None and not task.done():
                # Connection in progress
                meta = GCP_SERVICE_CONFIG.get(svc)
                desc = meta.description if meta else svc.value
                loading_services.append(desc)

        prompt = self._render_config_prompt()
        if loading_services:
            loading_text = ", ".join(loading_services)
            prompt = f"{prompt}\nLoading: {loading_text}"

        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools, prompt=prompt)

    async def _sync_update_context(self) -> ToolkitState:
        """Collect tools synchronously in parallel from per-service MCP servers."""
        access_token = await self._token_provider.get_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "x-goog-user-project": self._project_id,
        }

        async def _fetch_tools(
            server: _GcpServerConfig,
        ) -> tuple[_GcpServerConfig, list[McpBaseTool], bool]:
            mcp_tools, use_streamable_http = await mcp_list_tools(
                server.endpoint,
                headers,
                server.timeout,
                proxy_url=self._proxy_url,
            )
            return server, mcp_tools, use_streamable_http

        tasks = [_fetch_tools(s) for s in self._server_configs]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        tools: list[FunctionTool] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.exception(
                    "Failed to list tools from GCP MCP server",
                    exc_info=result,
                )
                continue

            server, mcp_tools, use_streamable_http = result
            is_writable = server.service in self._writable_services
            for mcp_tool in mcp_tools:
                if not is_writable and not _is_read_only_tool(mcp_tool):
                    continue

                tools.append(
                    _wrap_gcp_tool(
                        mcp_tool=mcp_tool,
                        server_url=server.endpoint,
                        headers=headers,
                        timeout=server.timeout,
                        use_streamable_http=use_streamable_http,
                        token_provider=self._token_provider,
                        project_id=self._project_id,
                        proxy_url=self._proxy_url,
                        artifact_sink_getter=self._current_artifact_sink,
                    )
                )

        prompt = self._render_config_prompt()
        return ToolkitState(status=ToolkitStatus.ENABLED, tools=tools, prompt=prompt)

    def _render_config_prompt(self) -> str:
        """Provide enabled service list as prompt."""
        config = self._config
        service_lines = []
        for svc in config.services:
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


def _wrap_gcp_tool(
    *,
    mcp_tool: McpBaseTool,
    server_url: str,
    headers: dict[str, str],
    timeout: float,
    use_streamable_http: bool,
    token_provider: GcpAccessTokenProvider,
    project_id: str,
    proxy_url: str | None,
    artifact_sink_getter: ArtifactSinkGetter | None,
) -> FunctionTool:
    """Wrap GCP MCP tool as azents Tool.

    Refresh token and retry once on 401 response.
    """

    async def on_auth_failure() -> str | None:
        """Return new token after refresh."""
        new_token = await token_provider.get_token()
        return new_token

    return wrap_mcp_tool(
        mcp_tool=mcp_tool,
        server_url=server_url,
        headers=headers,
        timeout=timeout,
        use_streamable_http=use_streamable_http,
        on_auth_failure=on_auth_failure,
        proxy_url=proxy_url,
        artifact_sink_getter=artifact_sink_getter,
    )


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

    def __init__(self, artifact_service: ArtifactService | None = None) -> None:
        """Initialize GcpToolkitProvider."""
        self._artifact_service = artifact_service

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
