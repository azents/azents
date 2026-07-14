"""MCP tool factory.

Create tools injected into agents with MCP Toolkit.
Connect to MCP server, fetch tool list, and wrap each as azents Tool.
"""

import datetime
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable

import httpx
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

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
    SessionType,
    TestConnectionResult,
    Toolkit,
    ToolkitProvider,
)
from azents.engine.tools.mcp_base import McpBasedToolkit
from azents.rdb.session import SessionManager
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.mcp_oauth_connection.data import MCPOAuthConnection
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
        session_type: SessionType = SessionType.USER,
        artifact_service: ArtifactService | None = None,
        session_manager: SessionManager[AsyncSession] | None = None,
        agent_id: str = "",
        session_id: str = "",
        state_name: str = "tool_snapshot",
    ) -> None:
        """Initialize McpToolkit.

        :param config: MCP toolkit settings; empty delegation config when None
        :param secret: Decrypted authentication secret
        :param on_auth_failure: Token reissue callback on 401; no retry when None
        :param proxy_url: MCP egress proxy URL; direct connection when None
        :param session_type: Session type used by the base state machine
        :param artifact_service: MCP binary output storage service
        """
        self._config = config or McpToolkitConfig(server_url="", auth_type="none")
        self._secret = secret
        self._on_auth_failure = on_auth_failure
        self._proxy_url = proxy_url
        self._session_type = session_type
        self._artifact_service = artifact_service
        self._session_manager = session_manager
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

    def __init__(
        self,
        *,
        connection_repo: MCPOAuthConnectionRepository | None = None,
        session_manager: SessionManager[AsyncSession] | None = None,
        artifact_service: ArtifactService | None = None,
    ) -> None:
        """Initialize McpToolkitProvider.

        :param connection_repo: MCP OAuth connection repository
        :param session_manager: DB session manager
        :param artifact_service: MCP binary output storage service
        """
        self._connection_repo = connection_repo
        self._session_manager = session_manager
        self._artifact_service = artifact_service

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

        if config.auth_type == "oauth2" and self._connection_repo is not None:
            if self._session_manager is None:
                raise RuntimeError("MCP OAuth requires a DB session manager")
            connection = await _ensure_oauth_connection_token(
                connection_repo=self._connection_repo,
                session_manager=self._session_manager,
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
                connection_repo=self._connection_repo,
                session_manager=self._session_manager,
                proxy_url=context.mcp_proxy_url,
            )
        else:
            secret = _extract_static_secret(config, context.credentials_json)

        return McpToolkit(
            config=config,
            secret=secret,
            on_auth_failure=on_auth_failure,
            proxy_url=context.mcp_proxy_url,
            session_type=SessionType.SYSTEM
            if context.user_id is None
            else SessionType.USER,
            artifact_service=self._artifact_service,
            session_manager=self._session_manager,
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
    connection_repo: MCPOAuthConnectionRepository,
    session_manager: SessionManager[AsyncSession],
    proxy_url: str | None = None,
) -> Callable[[], Awaitable[str | None]]:
    """Create callback that attempts toolkit OAuth refresh on 401.

    :param toolkit_id: Toolkit ID
    :param connection_repo: OAuth connection repository
    :param session_manager: DB session manager
    :param proxy_url: egress proxy URL
    :return: Callback called on 401; new access_token or None
    """

    async def _refresh() -> str | None:
        connection = await _refresh_oauth_connection(
            connection_repo=connection_repo,
            session_manager=session_manager,
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
    connection_repo: MCPOAuthConnectionRepository,
    session_manager: SessionManager[AsyncSession],
    toolkit_id: str,
    proxy_url: str | None,
) -> MCPOAuthConnection | None:
    """Load OAuth connection and refresh it when needed.

    :param connection_repo: OAuth connection repository
    :param session_manager: Database session factory
    :param toolkit_id: Toolkit ID
    :param proxy_url: egress proxy URL
    :return: OAuth connection or None
    """
    async with session_manager() as session:
        connection = await connection_repo.get_by_toolkit_id(session, toolkit_id)
    if connection is None or connection.status != MCPOAuthConnectionStatus.CONNECTED:
        return connection
    if not _token_needs_refresh(connection):
        return connection
    return await _refresh_oauth_connection(
        connection_repo=connection_repo,
        session_manager=session_manager,
        toolkit_id=toolkit_id,
        proxy_url=proxy_url,
        force=False,
        connection=connection,
    )


async def _refresh_oauth_connection(
    *,
    connection_repo: MCPOAuthConnectionRepository,
    session_manager: SessionManager[AsyncSession],
    toolkit_id: str,
    proxy_url: str | None,
    force: bool,
    connection: MCPOAuthConnection | None = None,
) -> MCPOAuthConnection | None:
    """Refresh OAuth outside DB and conditionally persist the result.

    :param connection_repo: OAuth connection repository
    :param session_manager: Database session factory
    :param toolkit_id: Toolkit ID
    :param proxy_url: egress proxy URL
    :param force: Refresh even when token is not near expiry
    :return: Refreshed or existing OAuth connection
    """
    if connection is None:
        async with session_manager() as session:
            connection = await connection_repo.get_by_toolkit_id(session, toolkit_id)
    if connection is None or connection.status != MCPOAuthConnectionStatus.CONNECTED:
        return connection
    if not force and not _token_needs_refresh(connection):
        return connection
    if connection.refresh_token is None:
        return await _persist_refresh_failure(
            connection_repo=connection_repo,
            session_manager=session_manager,
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
            connection_repo=connection_repo,
            session_manager=session_manager,
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
            connection_repo=connection_repo,
            session_manager=session_manager,
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
            connection_repo=connection_repo,
            session_manager=session_manager,
            connection=connection,
            toolkit_id=toolkit_id,
            reconnect_required=False,
        )

    async with session_manager() as session:
        current = await connection_repo.get_by_toolkit_id_for_update(
            session, toolkit_id
        )
        if current is None:
            return None
        if _connection_changed(connection, current):
            return current
        return await connection_repo.update_tokens(
            session,
            toolkit_id=toolkit_id,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token,
            expires_at=refreshed.expires_at,
        )


async def _persist_refresh_failure(
    *,
    connection_repo: MCPOAuthConnectionRepository,
    session_manager: SessionManager[AsyncSession],
    connection: MCPOAuthConnection,
    toolkit_id: str,
    reconnect_required: bool,
) -> MCPOAuthConnection | None:
    """Keep a concurrent refresh or persist this refresh failure."""
    async with session_manager() as session:
        current = await connection_repo.get_by_toolkit_id_for_update(
            session, toolkit_id
        )
        if current is None:
            return None
        if _connection_changed(connection, current):
            return current
        if reconnect_required:
            await connection_repo.mark_reconnect_required(
                session, toolkit_id=toolkit_id
            )
        return await connection_repo.get_by_toolkit_id(session, toolkit_id)


def _connection_changed(
    before: MCPOAuthConnection,
    current: MCPOAuthConnection,
) -> bool:
    """Return whether another transaction changed the credential snapshot."""
    return (
        current.updated_at != before.updated_at
        or current.refresh_token != before.refresh_token
        or current.access_token != before.access_token
        or current.status != before.status
    )


def _refresh_failure_requires_reconnect(exc: httpx.HTTPStatusError) -> bool:
    """Return whether an HTTP refresh failure requires reconnect."""
    should_reconnect = exc.response.status_code in {400, 401}
    if should_reconnect:
        try:
            payload = exc.response.json()
            if isinstance(payload, dict):
                should_reconnect = payload.get("error") == "invalid_grant"
        except ValueError:
            pass
    return should_reconnect


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
        cred_data: object = json.loads(credentials_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(cred_data, dict):
        return {}

    if config.auth_type == "api_key":
        api_key = cred_data.get("api_key")
        if isinstance(api_key, str):
            header_name = config.header_name or "X-API-Key"
            return {header_name: api_key}

    if config.auth_type == "bearer":
        token = cred_data.get("token")
        if isinstance(token, str):
            return {"Authorization": f"Bearer {token}"}

    return {}


__all__ = ["McpToolkit", "McpToolkitProvider"]
