"""MCP tool factory.

Create tools injected into agents with MCP Toolkit.
Connect to MCP server, fetch tool list, and wrap each as azents Tool.
"""

import datetime
import hashlib
import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.mcp_credentials import (
    McpSecretsBearer,
    McpSecretsHeader,
    McpSecretsNone,
    McpSecretsOAuth2,
    McpSecretsOAuth2Dcr,
    McpSecretsOAuth2Token,
)
from azents.core.mcp_discovery import DiscoveryError, discover_oauth_metadata
from azents.core.mcp_transport import test_mcp_transport
from azents.core.oauth2 import OAuthTokenError, refresh_access_token
from azents.core.tools import (
    McpToolkitConfig,
    ResolveContext,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
)
from azents.engine.tools.mcp_base import McpBasedToolkit, _build_auth_headers
from azents.repos.engine_tool_repositories import (
    EngineMcpSnapshotFactory,
    EngineToolRepositories,
)
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
from azents.repos.mcp_oauth_connection.operations import (
    MCPOAuthRuntimeOperationRepository,
)
from azents.services.artifact import ArtifactService

logger = logging.getLogger(__name__)

_McpSecretsUnion = (
    McpSecretsNone
    | McpSecretsHeader
    | McpSecretsBearer
    | McpSecretsOAuth2
    | McpSecretsOAuth2Token
    | McpSecretsOAuth2Dcr
)
_mcp_secrets_adapter = TypeAdapter[_McpSecretsUnion](_McpSecretsUnion)
_OAUTH_REFRESH_SKEW = datetime.timedelta(minutes=5)


class McpToolkit(McpBasedToolkit[McpToolkitConfig]):
    """MCP toolkit execution instance.

    Created with credential bound in resolve().
    """

    def __init__(
        self,
        *,
        config: McpToolkitConfig | None = None,
        secret: str | None = None,
        on_auth_failure: (Callable[[], Awaitable[str | None]] | None) = None,
        proxy_url: str | None = None,
        artifact_service: ArtifactService | None = None,
        snapshot_factory: EngineMcpSnapshotFactory | None,
        agent_id: str | None,
        session_id: str | None,
        state_name: str = "tool_snapshot",
    ) -> None:
        """Initialize McpToolkit.

        :param config: MCP toolkit settings; empty delegation config when None
        :param secret: Decrypted authentication secret
        :param on_auth_failure: Token reissue callback on 401; no retry when None
        :param proxy_url: MCP egress proxy URL; direct connection when None
        :param artifact_service: MCP binary output storage service
        """
        if agent_id == "" or session_id == "":
            raise ValueError("MCP identities must be nonempty or absent.")
        self._config = config or McpToolkitConfig(server_url="", auth_type="none")
        self._secret = secret
        self.on_auth_failure = on_auth_failure
        self._proxy_url = proxy_url
        self.artifact_service = artifact_service
        self.snapshot_factory = snapshot_factory
        self._agent_id = agent_id
        self._session_id = session_id
        self._state_namespace = "mcp"
        self._state_name = state_name
        self._init_bg_state()


class McpToolkitProvider(ToolkitProvider[McpToolkitConfig]):
    """MCP toolkit provider.

    Connect to external MCP server and provide tools.
    Return McpToolkit whose credential is resolved by resolve().
    """

    slug = "mcp"
    name = "MCP"
    description = "External MCP server integration"
    system_prompt = (
        "You have access to external tools provided via MCP "
        "(Model Context Protocol). Use the available tools to "
        "accomplish the user's request."
    )
    config_model = McpToolkitConfig

    @classmethod
    def source_identity(
        cls,
        config: McpToolkitConfig,
    ) -> tuple[tuple[str, str], ...]:
        """Return a credential-free MCP server origin."""
        parsed = urlsplit(config.server_url)
        if not parsed.scheme or parsed.hostname is None:
            return ()
        try:
            parsed_port = parsed.port
        except ValueError:
            return ()
        port = f":{parsed_port}" if parsed_port is not None else ""
        return (("server", f"{parsed.scheme}://{parsed.hostname}{port}"),)

    def __init__(
        self,
        *,
        repositories: EngineToolRepositories | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        """Initialize McpToolkitProvider.

        :param repositories: Completed MCP OAuth and snapshot repositories
            :param artifact_service: MCP binary output storage service
        """
        self.repositories = repositories
        self.artifact_service = artifact_service

    async def test_connection(
        self,
        config: McpToolkitConfig,
        credentials_json: str | None,
        *,
        proxy_url: str | None = None,
    ) -> TestConnectionResult:
        """Test MCP server connection.

        `oauth2` tests OAuth metadata discovery. Other auth modes test MCP server
        connection and list_tools.

        :param config: MCP toolkit settings
        :param credentials_json: Decrypted credentials JSON
        :param proxy_url: egress proxy URL; direct connection when None
        :return: Connection test result
        """
        if config.auth_type == "oauth2":
            return await _test_oauth2_discovery(
                config, credentials_json, proxy_url=proxy_url
            )

        headers = _build_test_auth_headers(config, credentials_json)
        return await test_mcp_transport(
            config.server_url, headers, config.timeout, proxy_url=proxy_url
        )

    async def resolve(
        self,
        config: McpToolkitConfig,
        context: ResolveContext,
    ) -> Toolkit[McpToolkitConfig]:
        """Resolve per-config credential and return executable Provider.

        :param config: Validated MCP settings
        :param context: Resolve context
        :return: McpToolkit instance with credential resolved
        """
        secret: str | None = None
        on_auth_failure: Callable[[], Awaitable[str | None]] | None = None

        if config.auth_type == "oauth2" and self.repositories is not None:
            connection = await _ensure_oauth_connection_token(
                operations=self.repositories.mcp_oauth,
                toolkit_id=context.toolkit_id,
                proxy_url=context.mcp_proxy_url,
            )
            if (
                connection is not None
                and connection.status == MCPOAuthConnectionStatus.CONNECTED
            ):
                secret = connection.access_token
            on_auth_failure = _make_oauth_refresh_callback(
                toolkit_id=context.toolkit_id,
                operations=self.repositories.mcp_oauth,
                proxy_url=context.mcp_proxy_url,
            )
        else:
            secret = _extract_static_secret(config, context.credentials_json)

        return McpToolkit(
            config=config,
            secret=secret,
            on_auth_failure=on_auth_failure,
            proxy_url=context.mcp_proxy_url,
            artifact_service=self.artifact_service,
            snapshot_factory=(
                self.repositories.snapshots if self.repositories is not None else None
            ),
            agent_id=context.agent_id,
            session_id=context.session_id,
            state_name=_mcp_snapshot_state_name(
                toolkit_id=context.toolkit_id,
                server_url=config.server_url,
            ),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_oauth_refresh_callback(
    *,
    toolkit_id: str,
    operations: MCPOAuthRuntimeOperationRepository,
    proxy_url: str | None = None,
) -> Callable[[], Awaitable[str | None]]:
    """Create callback that attempts toolkit OAuth refresh on 401.

    :param toolkit_id: Toolkit ID
    :param operations: Completed OAuth connection operations
    :param proxy_url: egress proxy URL
    :return: Callback called on 401; new access_token or None
    """

    async def _refresh() -> str | None:
        connection = await _refresh_oauth_connection(
            operations=operations,
            toolkit_id=toolkit_id,
            proxy_url=proxy_url,
            force=True,
        )
        if (
            connection is None
            or connection.status != MCPOAuthConnectionStatus.CONNECTED
        ):
            return None
        return connection.access_token

    return _refresh


def _mcp_snapshot_state_name(*, toolkit_id: str, server_url: str) -> str:
    """Return stable Toolkit State name for an MCP tool snapshot."""
    raw = toolkit_id or server_url
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"tool_snapshot:{digest}"


def _extract_static_secret(
    config: McpToolkitConfig,
    credentials_json: str | None,
) -> str | None:
    """Extract static authentication secret from credential JSON.

    :param config: MCP toolkit settings
    :param credentials_json: Decrypted MCP credentials JSON; no auth when None
    :return: Header/bearer access token or None
    """
    if credentials_json is None or config.auth_type == "none":
        return None

    secrets = _mcp_secrets_adapter.validate_json(credentials_json)
    if isinstance(secrets, McpSecretsHeader):
        return secrets.value
    if isinstance(secrets, McpSecretsBearer):
        return secrets.token
    if isinstance(secrets, McpSecretsOAuth2Token):
        return secrets.access_token
    return None


def _token_needs_refresh(connection: MCPOAuthConnection) -> bool:
    """Check whether the OAuth connection token needs refresh."""
    if connection.access_token is None:
        return connection.refresh_token is not None
    if connection.expires_at is None:
        return False
    return (
        connection.expires_at
        <= datetime.datetime.now(datetime.UTC) + _OAUTH_REFRESH_SKEW
    )


async def _ensure_oauth_connection_token(
    *,
    operations: MCPOAuthRuntimeOperationRepository,
    toolkit_id: str,
    proxy_url: str | None,
) -> MCPOAuthConnection | None:
    """Load OAuth connection and refresh it when needed.

    :param operations: Completed OAuth connection operations
    :param toolkit_id: Toolkit ID
    :param proxy_url: egress proxy URL
    :return: OAuth connection or None
    """
    connection = await operations.load(toolkit_id=toolkit_id)
    if connection is None or connection.status != MCPOAuthConnectionStatus.CONNECTED:
        return connection
    if not _token_needs_refresh(connection):
        return connection
    return await _refresh_oauth_connection(
        operations=operations,
        toolkit_id=toolkit_id,
        proxy_url=proxy_url,
        force=False,
        connection=connection,
    )


async def _refresh_oauth_connection(
    *,
    operations: MCPOAuthRuntimeOperationRepository,
    toolkit_id: str,
    proxy_url: str | None,
    force: bool,
    connection: MCPOAuthConnection | None = None,
) -> MCPOAuthConnection | None:
    """Refresh OAuth outside DB and conditionally persist the result.

    :param operations: Completed OAuth connection operations
    :param toolkit_id: Toolkit ID
    :param proxy_url: egress proxy URL
    :param force: Refresh even when token is not near expiry
    :return: Refreshed or existing OAuth connection
    """
    if connection is None:
        connection = await operations.load(toolkit_id=toolkit_id)
    if connection is None or connection.status != MCPOAuthConnectionStatus.CONNECTED:
        return connection
    if not force and not _token_needs_refresh(connection):
        return connection
    if connection.refresh_token is None:
        return await _persist_refresh_failure(
            operations=operations,
            connection=connection,
            toolkit_id=toolkit_id,
            reconnect_required=True,
        )

    try:
        refreshed = await refresh_access_token(
            token_url=connection.token_endpoint,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            refresh_token=connection.refresh_token,
            proxy_url=proxy_url,
        )
    except httpx.HTTPStatusError as exc:
        reconnect_required = _refresh_failure_requires_reconnect(exc)
        if not reconnect_required:
            logger.warning(
                "Failed to refresh MCP OAuth connection",
                extra={
                    "toolkit_id": toolkit_id,
                    "status_code": exc.response.status_code,
                },
                exc_info=True,
            )
        return await _persist_refresh_failure(
            operations=operations,
            connection=connection,
            toolkit_id=toolkit_id,
            reconnect_required=reconnect_required,
        )
    except OAuthTokenError as exc:
        reconnect_required = "invalid_grant" in str(exc)
        if not reconnect_required:
            logger.warning(
                "Failed to refresh MCP OAuth connection",
                extra={"toolkit_id": toolkit_id},
                exc_info=True,
            )
        return await _persist_refresh_failure(
            operations=operations,
            connection=connection,
            toolkit_id=toolkit_id,
            reconnect_required=reconnect_required,
        )
    except httpx.HTTPError, KeyError, ValidationError:
        logger.warning(
            "Failed to refresh MCP OAuth connection",
            extra={"toolkit_id": toolkit_id},
            exc_info=True,
        )
        return await _persist_refresh_failure(
            operations=operations,
            connection=connection,
            toolkit_id=toolkit_id,
            reconnect_required=False,
        )

    return await operations.finalize_refresh(
        before=connection,
        toolkit_id=toolkit_id,
        access_token=refreshed.access_token,
        refresh_token=refreshed.refresh_token,
        expires_at=refreshed.expires_at,
    )


async def _persist_refresh_failure(
    *,
    operations: MCPOAuthRuntimeOperationRepository,
    connection: MCPOAuthConnection,
    toolkit_id: str,
    reconnect_required: bool,
) -> MCPOAuthConnection | None:
    """Keep a concurrent refresh or persist this refresh failure."""
    return await operations.finalize_failure(
        before=connection,
        toolkit_id=toolkit_id,
        reconnect_required=reconnect_required,
    )


class _OAuthRefreshFailurePayload(BaseModel):
    """Decode an extensible provider error without coercing its error code."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    error: str | None = None

    @field_validator("error", mode="before")
    @classmethod
    def decode_error(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


def _refresh_failure_requires_reconnect(exc: httpx.HTTPStatusError) -> bool:
    """Return whether an HTTP refresh failure requires reconnect."""
    if exc.response.status_code not in {400, 401}:
        return False
    try:
        payload = _OAuthRefreshFailurePayload.model_validate_json(exc.response.content)
    except ValidationError:
        return True
    return payload.error == "invalid_grant"


async def _test_oauth2_discovery(
    config: McpToolkitConfig,
    credentials_json: str | None,
    *,
    proxy_url: str | None = None,
) -> TestConnectionResult:
    """Test OAuth2 AS discovery.

    :param config: MCP toolkit settings
    :param credentials_json: Decrypted credentials JSON
    :param proxy_url: egress proxy URL; direct connection when None
    :return: Discovery test result
    """
    try:
        metadata = await discover_oauth_metadata(
            config.server_url, config.discovery_url, proxy_url=proxy_url
        )
    except DiscoveryError as exc:
        if config.auth_url is not None and config.token_url is not None:
            return TestConnectionResult(
                success=True,
                message="OAuth endpoints are configured explicitly.",
                discovered_auth_url=config.auth_url,
                discovered_token_url=config.token_url,
                supports_dcr=None,
            )
        return TestConnectionResult(
            success=False,
            message=f"OAuth metadata discovery failed: {exc}",
            discovered_auth_url=None,
            discovered_token_url=None,
            supports_dcr=None,
        )

    supports_dcr = metadata.registration_endpoint is not None
    has_manual_credentials = _has_oauth_client_credentials(credentials_json)
    if not supports_dcr and not has_manual_credentials:
        return TestConnectionResult(
            success=False,
            message=(
                "Server does not support Dynamic Client Registration and "
                "client credentials are not configured."
            ),
            discovered_auth_url=metadata.authorization_endpoint,
            discovered_token_url=metadata.token_endpoint,
            supports_dcr=False,
        )

    return TestConnectionResult(
        success=True,
        message="OAuth metadata discovery successful.",
        discovered_auth_url=metadata.authorization_endpoint,
        discovered_token_url=metadata.token_endpoint,
        supports_dcr=supports_dcr,
    )


def _has_oauth_client_credentials(credentials_json: str | None) -> bool:
    """Check whether credentials JSON contains OAuth client credentials."""
    if credentials_json is None:
        return False
    try:
        secrets = _mcp_secrets_adapter.validate_json(credentials_json)
    except ValidationError:
        return False
    return isinstance(
        secrets, McpSecretsOAuth2 | McpSecretsOAuth2Dcr | McpSecretsOAuth2Token
    )


def _build_test_auth_headers(
    config: McpToolkitConfig,
    credentials_json: str | None,
) -> dict[str, str]:
    """Create authentication headers for test connection.

    :param config: MCP toolkit settings
    :param credentials_json: Decrypted credentials JSON
    :return: Authentication headers
    """
    if credentials_json is None or config.auth_type == "none":
        return {}

    try:
        secret = _extract_static_secret(config, credentials_json)
    except ValidationError:
        return {}
    return _build_auth_headers(config, secret)


__all__ = ["McpToolkit", "McpToolkitProvider"]
