"""Toolkit OAuth2 endpoints.

Provides toolkit-level OAuth2 connection endpoints and connection test endpoints.
"""

import json
import logging
from collections.abc import Mapping
from typing import Annotated, Any, assert_never, cast

import httpx
from azcommon.result import Result
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.core.config import Config
from azents.core.crypto import CredentialCipher
from azents.core.deps import get_config, get_credential_cipher
from azents.core.enums import MCPOAuthConnectionStatus
from azents.core.github_auth import (
    create_github_app_jwt,
    exchange_oauth_code,
    get_app_slug,
    list_user_installations,
    revoke_oauth_token,
)
from azents.core.mcp_credentials import (
    McpSecretsOAuth2,
    McpSecretsOAuth2Dcr,
    McpSecretsOAuth2Token,
)
from azents.core.mcp_discovery import (
    DcrError,
    DiscoveryError,
    OAuthServerMetadata,
    discover_oauth_metadata,
    register_client,
)
from azents.core.oauth2 import (
    OAuthTokenError,
    OAuthTokenResponse,
    build_authorization_url,
    create_agent_github_platform_oauth_state,
    create_agent_toolkit_oauth_state,
    create_platform_oauth_state,
    create_toolkit_oauth_state,
    exchange_authorization_code,
    generate_pkce_pair,
    verify_agent_github_platform_oauth_state,
    verify_agent_toolkit_oauth_state,
    verify_platform_oauth_state,
    verify_toolkit_oauth_state,
)
from azents.core.tools import McpToolkitConfig, ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.github_user_installation import (
    GithubUserInstallationRepository,
)
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.toolkit import ToolkitRepository
from azents.repos.toolkit.data import NotFound
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitOAuthConnectionInput,
    AgentToolkitOAuthContext,
    ToolkitOutput,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_OAuthSecretsUnion = McpSecretsOAuth2 | McpSecretsOAuth2Token | McpSecretsOAuth2Dcr
_oauth_secrets_adapter = TypeAdapter[_OAuthSecretsUnion](_OAuthSecretsUnion)
_credentials_adapter = TypeAdapter(dict[str, object])
_AGENT_TOOLKIT_CALLBACK_TARGET = "agent_toolkits"
_AGENT_GITHUB_CALLBACK_TARGET = "agent_github_installations"


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class OAuthAuthorizeResponse(BaseModel):
    """OAuth authorization URL response."""

    authorization_url: str = Field(description="OAuth2 authorization URL")


class TestConnectionRequest(BaseModel):
    """Connection test request.

    In edit mode, send ``toolkit_config_id`` to load credentials stored in DB,
    then override them with the ``credentials`` field value.
    """

    toolkit_type: str = Field(
        default="mcp", description="Toolkit type, such as mcp or github"
    )
    config: dict[str, object]
    credentials: dict[str, object] | None = None
    toolkit_config_id: str | None = None


class TestConnectionResponse(BaseModel):
    """Test connection response."""

    success: bool = Field(description="Connection success state")
    message: str = Field(description="Result message")
    discovered_auth_url: str | None = Field(
        default=None, description="Discovered authorization URL"
    )
    discovered_token_url: str | None = Field(
        default=None, description="Discovered token URL"
    )
    supports_dcr: bool | None = Field(default=None, description="DCR support state")


class GitHubPlatformInstallUrlResponse(BaseModel):
    """GitHub Platform App installation URL response."""

    install_url: str = Field(description="GitHub App installation page URL")


# ---------------------------------------------------------------------------
# GitHub Platform App endpoints
# ---------------------------------------------------------------------------


@router.get("/workspaces/{handle}/github/platform-install-url")
async def get_github_platform_install_url(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    *,
    handle: str,
) -> GitHubPlatformInstallUrlResponse:
    """Return the GitHub Platform App installation URL.

    Creates a JWT with Platform App credentials configured on the server,
    calls the GitHub API to fetch the App slug, then builds the installation URL.
    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )
    platform = await platform_runtime.resolve()
    if platform.app_id is None or platform.private_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App is not configured.",
        )

    try:
        jwt_token = create_github_app_jwt(
            platform.app_id,
            platform.private_key,
        )
        slug = await get_app_slug(jwt_token)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch GitHub App info: HTTP {exc.response.status_code}"
        ) from exc

    install_url = f"https://github.com/apps/{slug}/installations/new"
    return GitHubPlatformInstallUrlResponse(install_url=install_url)


class GitHubInstallationItem(BaseModel):
    """GitHub App installation item."""

    id: int = Field(description="Installation ID")
    account_login: str = Field(description="Installed account/organization name")
    account_type: str = Field(description="Account type (User/Organization)")
    account_avatar_url: str = Field(description="Account avatar URL")


class GitHubPlatformOAuthUrlResponse(BaseModel):
    """GitHub Platform App OAuth URL response."""

    oauth_url: str = Field(description="GitHub OAuth authorization URL")


@router.get("/workspaces/{handle}/github/platform-oauth-url")
async def get_github_platform_oauth_url(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    *,
    handle: str,
) -> GitHubPlatformOAuthUrlResponse:
    """Return the GitHub Platform App OAuth authorization URL.

    Starts an OAuth flow so the user can log in to GitHub and list their own
    installations. Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )
    platform = await platform_runtime.resolve()
    if platform.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App OAuth is not configured.",
        )

    redirect_uri = f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    state = create_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation=platform.effective_generation,
    )
    oauth_url = (
        "https://github.com/login/oauth/authorize"
        f"?client_id={platform.client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return GitHubPlatformOAuthUrlResponse(oauth_url=oauth_url)


class GitHubPlatformInstallationsRequest(BaseModel):
    """GitHub Platform App installation list request."""

    code: str = Field(description="GitHub OAuth authorization code")
    state: str = Field(description="OAuth state parameter for CSRF validation")


class GitHubPlatformInstallationsResponse(BaseModel):
    """GitHub Platform App installation list response."""

    installations: list[GitHubInstallationItem] = Field(description="Installation list")


@router.post("/workspaces/{handle}/github/platform-installations")
async def get_github_platform_installations(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    body: GitHubPlatformInstallationsRequest,
    *,
    handle: str,
) -> GitHubPlatformInstallationsResponse:
    """Return installations accessible with the user GitHub OAuth token.

    Exchanges GitHub App OAuth code for an access token, calls
    ``GET /user/installations``, and returns only installations the user can access.
    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )

    oauth_state = verify_platform_oauth_state(
        body.state,
        config.credential_encryption.key,
    )
    if oauth_state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter.",
        )

    platform = await platform_runtime.resolve()
    if oauth_state.effective_generation != platform.effective_generation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "system_setting_changed",
                "message": "Platform GitHub App settings changed. Restart OAuth.",
            },
        )
    if (
        platform.app_id is None
        or platform.client_id is None
        or platform.client_secret is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App OAuth is not configured.",
        )

    # Exchange OAuth code for access token
    try:
        user_token = await exchange_oauth_code(
            platform.client_id,
            platform.client_secret,
            body.code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"GitHub OAuth token exchange failed: HTTP {exc.response.status_code}"
        ) from exc

    # List installations accessible by the user
    try:
        raw_installations = await list_user_installations(user_token)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch user installations: HTTP {exc.response.status_code}"
        ) from exc

    # Sync user installation list to DB for ownership validation
    install_repo = GithubUserInstallationRepository()
    async with session_manager() as session:
        await install_repo.sync(
            session,
            member.user_id,
            platform.app_id,
            raw_installations,
        )

    # Immediately revoke the temporary token after use
    await revoke_oauth_token(
        platform.client_id,
        platform.client_secret,
        user_token,
    )

    items: list[GitHubInstallationItem] = []
    for inst in raw_installations:
        account = inst.get("account")
        if not isinstance(account, dict):
            continue
        login = account.get("login")
        account_type = account.get("type")
        avatar_url = account.get("avatar_url")
        inst_id = inst.get("id")
        if (
            isinstance(inst_id, int)
            and isinstance(login, str)
            and isinstance(account_type, str)
            and isinstance(avatar_url, str)
        ):
            items.append(
                GitHubInstallationItem(
                    id=inst_id,
                    account_login=login,
                    account_type=account_type,
                    account_avatar_url=avatar_url,
                )
            )

    return GitHubPlatformInstallationsResponse(installations=items)


@router.get("/workspaces/{handle}/agents/{agent_id}/github/platform-install-url")
async def get_agent_github_platform_install_url(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    *,
    handle: str,
    agent_id: str,
) -> GitHubPlatformInstallUrlResponse:
    """Return the Platform GitHub App install URL for Agent Toolkit setup."""
    del handle
    await _authorize_agent_management_or_error(
        service,
        member,
        agent_id=agent_id,
    )
    platform = await platform_runtime.resolve()
    if platform.app_id is None or platform.private_key is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App is not configured.",
        )
    try:
        jwt_token = create_github_app_jwt(
            platform.app_id,
            platform.private_key,
        )
        slug = await get_app_slug(jwt_token)
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Failed to fetch GitHub App info: HTTP {exc.response.status_code}"
        ) from exc
    return GitHubPlatformInstallUrlResponse(
        install_url=f"https://github.com/apps/{slug}/installations/new"
    )


@router.get("/workspaces/{handle}/agents/{agent_id}/github/platform-oauth-url")
async def get_agent_github_platform_oauth_url(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    *,
    handle: str,
    agent_id: str,
) -> GitHubPlatformOAuthUrlResponse:
    """Return the Platform GitHub user OAuth URL for Agent Toolkit setup."""
    await _authorize_agent_management_or_error(
        service,
        member,
        agent_id=agent_id,
    )
    platform = await platform_runtime.resolve()
    if platform.client_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App OAuth is not configured.",
        )
    redirect_uri = f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    state = create_agent_github_platform_oauth_state(
        config.credential_encryption.key,
        effective_generation=platform.effective_generation,
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        user_id=member.user_id,
        redirect_uri=redirect_uri,
        callback_target=_AGENT_GITHUB_CALLBACK_TARGET,
    )
    return GitHubPlatformOAuthUrlResponse(
        oauth_url=(
            "https://github.com/login/oauth/authorize"
            f"?client_id={platform.client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&state={state}"
        )
    )


@router.post("/workspaces/{handle}/agents/{agent_id}/github/platform-installations")
async def get_agent_github_platform_installations(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    body: GitHubPlatformInstallationsRequest,
    *,
    handle: str,
    agent_id: str,
) -> GitHubPlatformInstallationsResponse:
    """Return GitHub installations for authorized Agent Toolkit setup."""
    await _authorize_agent_management_or_error(
        service,
        member,
        agent_id=agent_id,
    )
    oauth_state = verify_agent_github_platform_oauth_state(
        body.state,
        config.credential_encryption.key,
    )
    expected_redirect_uri = (
        f"{config.web_url}/oauth/github/callback" if config.web_url else ""
    )
    if (
        oauth_state is None
        or oauth_state.workspace_id != member.workspace_id
        or oauth_state.agent_id != agent_id
        or oauth_state.user_id != member.user_id
        or oauth_state.redirect_uri != expected_redirect_uri
        or oauth_state.callback_target != _AGENT_GITHUB_CALLBACK_TARGET
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state does not match Agent GitHub setup.",
        )
    platform = await platform_runtime.resolve()
    if oauth_state.effective_generation != platform.effective_generation:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "system_setting_changed",
                "message": "Platform GitHub App settings changed. Restart OAuth.",
            },
        )
    if (
        platform.app_id is None
        or platform.client_id is None
        or platform.client_secret is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App OAuth is not configured.",
        )
    try:
        user_token = await exchange_oauth_code(
            platform.client_id,
            platform.client_secret,
            body.code,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"GitHub OAuth token exchange failed: HTTP {exc.response.status_code}"
        ) from exc
    try:
        try:
            raw_installations = await list_user_installations(user_token)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Failed to fetch user installations: HTTP {exc.response.status_code}"
            ) from exc
        sync_result = await service.sync_agent_github_installations(
            agent_id,
            workspace_id=member.workspace_id,
            workspace_user_id=member.workspace_user_id,
            user_id=member.user_id,
            role=member.role,
            platform_app_id=platform.app_id,
            installations=raw_installations,
        )
        _raise_agent_management_error(sync_result)
    finally:
        await revoke_oauth_token(
            platform.client_id,
            platform.client_secret,
            user_token,
        )
    items: list[GitHubInstallationItem] = []
    for installation in raw_installations:
        account = installation.get("account")
        if not isinstance(account, dict):
            continue
        installation_id = installation.get("id")
        login = account.get("login")
        account_type = account.get("type")
        avatar_url = account.get("avatar_url")
        if (
            isinstance(installation_id, int)
            and isinstance(login, str)
            and isinstance(account_type, str)
            and isinstance(avatar_url, str)
        ):
            items.append(
                GitHubInstallationItem(
                    id=installation_id,
                    account_login=login,
                    account_type=account_type,
                    account_avatar_url=avatar_url,
                )
            )
    return GitHubPlatformInstallationsResponse(installations=items)


# ---------------------------------------------------------------------------
# OAuth connection endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connect",
)
async def connect_oauth(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    config: Annotated[Config, Depends(get_config)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    handle: str,
    toolkit_config_id: str,
) -> OAuthAuthorizeResponse:
    """Create a manager-owned toolkit OAuth authorization URL.

    Requires Toolkit write permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )

    toolkit_repo = ToolkitRepository(cipher=cipher)
    connection_repo = MCPOAuthConnectionRepository(cipher=cipher)
    async with session_manager() as session:
        toolkit = await toolkit_repo.get_shared_by_id(session, toolkit_config_id)
        existing = await connection_repo.get_by_toolkit_id(session, toolkit_config_id)

    if toolkit is None or toolkit.workspace_id != member.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toolkit config not found.",
        )

    mcp_config = _resolve_mcp_config(toolkit.toolkit_type, toolkit.config, registry)
    if mcp_config.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Toolkit does not use OAuth2 authentication.",
        )

    metadata = await _discover_required_metadata(mcp_config, config.mcp_proxy_url)
    redirect_uri = (
        f"{config.web_url}/oauth/mcp/callback"
        f"?handle={handle}&toolkit_config_id={toolkit_config_id}"
        if config.web_url
        else ""
    )
    client_id = existing.client_id if existing is not None else None
    client_secret = existing.client_secret if existing is not None else None
    registration_endpoint = metadata.registration_endpoint

    if client_id is None:
        manual = _extract_oauth_client_credentials(toolkit.credentials)
        if manual is not None:
            client_id, client_secret = manual
        elif metadata.registration_endpoint is not None:
            try:
                dcr = await register_client(
                    metadata.registration_endpoint,
                    redirect_uri,
                    proxy_url=config.mcp_proxy_url,
                )
            except DcrError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dynamic client registration failed: {exc}",
                ) from exc
            client_id = dcr.client_id
            client_secret = dcr.client_secret
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "OAuth2 client credentials are not configured "
                    "and server does not support DCR."
                ),
            )

    code_verifier, code_challenge = generate_pkce_pair()
    oauth_state = create_toolkit_oauth_state(
        toolkit_id=toolkit_config_id,
        workspace_id=member.workspace_id,
        user_id=member.user_id,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        secret_key=config.credential_encryption.key,
    )
    scope = " ".join(mcp_config.scopes) if mcp_config.scopes else None
    async with session_manager() as session:
        await connection_repo.upsert_connected(
            session,
            toolkit_id=toolkit_config_id,
            issuer=metadata.issuer,
            resource=mcp_config.server_url,
            server_url=mcp_config.server_url,
            authorization_endpoint=metadata.authorization_endpoint,
            token_endpoint=metadata.token_endpoint,
            registration_endpoint=registration_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method="client_secret_post"
            if client_secret is not None
            else "none",
            scope=scope,
            access_token=existing.access_token if existing is not None else None,
            refresh_token=existing.refresh_token if existing is not None else None,
            expires_at=existing.expires_at if existing is not None else None,
        )

    authorization_url = build_authorization_url(
        auth_url=metadata.authorization_endpoint,
        client_id=client_id,
        redirect_uri=redirect_uri,
        scopes=mcp_config.scopes,
        state=oauth_state,
        code_challenge=code_challenge,
        resource=mcp_config.server_url,
    )
    return OAuthAuthorizeResponse(authorization_url=authorization_url)


class OAuthExchangeRequest(BaseModel):
    """OAuth2 token exchange request."""

    code: str = Field(description="OAuth2 authorization code")
    state: str = Field(description="OAuth2 state parameter")


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/exchange",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def exchange_oauth_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    config: Annotated[Config, Depends(get_config)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    body: OAuthExchangeRequest,
    *,
    handle: str,
    toolkit_config_id: str,
) -> None:
    """Exchange authorization code for a toolkit-level OAuth connection."""
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )
    _ = handle

    verified = verify_toolkit_oauth_state(body.state, config.credential_encryption.key)
    if verified is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter.",
        )
    state_toolkit_id, state_workspace_id, _user_id, redirect_uri, code_verifier = (
        verified
    )
    if (
        state_toolkit_id != toolkit_config_id
        or state_workspace_id != member.workspace_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state does not match toolkit.",
        )

    toolkit_repo = ToolkitRepository(cipher=cipher)
    connection_repo = MCPOAuthConnectionRepository(cipher=cipher)
    async with session_manager() as session:
        toolkit = await toolkit_repo.get_shared_by_id(session, toolkit_config_id)
        connection = await connection_repo.get_by_toolkit_id(session, toolkit_config_id)

    if toolkit is None or toolkit.workspace_id != member.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toolkit config not found.",
        )
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth connection not found. Start connect again.",
        )

    mcp_config = _resolve_mcp_config(toolkit.toolkit_type, toolkit.config, registry)
    if mcp_config.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Toolkit does not use OAuth2 authentication.",
        )

    token_response = await _exchange_and_handle_errors(
        token_url=connection.token_endpoint,
        client_id=connection.client_id,
        client_secret=connection.client_secret,
        code=body.code,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        resource=connection.resource or mcp_config.server_url,
        proxy_url=config.mcp_proxy_url,
        toolkit_id=toolkit_config_id,
        user_id=member.user_id,
    )
    async with session_manager() as session:
        await connection_repo.upsert_connected(
            session,
            toolkit_id=toolkit_config_id,
            issuer=connection.issuer,
            resource=connection.resource,
            server_url=connection.server_url,
            authorization_endpoint=connection.authorization_endpoint,
            token_endpoint=connection.token_endpoint,
            registration_endpoint=connection.registration_endpoint,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            token_endpoint_auth_method=connection.token_endpoint_auth_method,
            scope=connection.scope,
            access_token=token_response.access_token,
            refresh_token=token_response.refresh_token,
            expires_at=token_response.expires_at,
        )


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_oauth_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    *,
    handle: str,
    toolkit_config_id: str,
) -> None:
    """Delete a toolkit-level OAuth connection."""
    if not member.has_permission(Permissions.TOOLKITS_WRITE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit write permission required.",
        )
    _ = handle

    toolkit_repo = ToolkitRepository(cipher=cipher)
    connection_repo = MCPOAuthConnectionRepository(cipher=cipher)
    async with session_manager() as session:
        toolkit = await toolkit_repo.get_shared_by_id(session, toolkit_config_id)
        if toolkit is None or toolkit.workspace_id != member.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Toolkit config not found.",
            )
        await connection_repo.delete_by_toolkit_id(session, toolkit_config_id)


# ---------------------------------------------------------------------------
# Agent-owned OAuth connection endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{handle}/agents/{agent_id}"
    "/toolkit-configs/{toolkit_config_id}/oauth/connect",
)
async def connect_agent_oauth(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    handle: str,
    agent_id: str,
    toolkit_config_id: str,
) -> OAuthAuthorizeResponse:
    """Create an OAuth authorization URL for an Agent-owned Toolkit."""
    context = await _get_agent_oauth_context_or_404(
        service,
        member,
        agent_id=agent_id,
        toolkit_config_id=toolkit_config_id,
    )
    toolkit = context.toolkit
    existing = context.connection
    mcp_config = _resolve_mcp_config(toolkit.toolkit_type, toolkit.config, registry)
    if mcp_config.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Toolkit does not use OAuth2 authentication.",
        )
    metadata = await _discover_required_metadata(mcp_config, config.mcp_proxy_url)
    redirect_uri = (
        f"{config.web_url}/oauth/mcp/callback"
        f"?handle={handle}&agent_id={agent_id}"
        f"&toolkit_config_id={toolkit_config_id}"
        if config.web_url
        else ""
    )
    client_id = existing.client_id if existing is not None else None
    client_secret = existing.client_secret if existing is not None else None
    if client_id is None:
        manual = _extract_oauth_client_credentials(toolkit.credentials)
        if manual is not None:
            client_id, client_secret = manual
        elif metadata.registration_endpoint is not None:
            try:
                dcr = await register_client(
                    metadata.registration_endpoint,
                    redirect_uri,
                    proxy_url=config.mcp_proxy_url,
                )
            except DcrError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Dynamic client registration failed: {exc}",
                ) from exc
            client_id = dcr.client_id
            client_secret = dcr.client_secret
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "OAuth2 client credentials are not configured "
                    "and server does not support DCR."
                ),
            )

    code_verifier, code_challenge = generate_pkce_pair()
    oauth_state = create_agent_toolkit_oauth_state(
        toolkit_id=toolkit_config_id,
        workspace_id=member.workspace_id,
        agent_id=agent_id,
        user_id=member.user_id,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        callback_target=_AGENT_TOOLKIT_CALLBACK_TARGET,
        secret_key=config.credential_encryption.key,
    )
    scope = " ".join(mcp_config.scopes) if mcp_config.scopes else None
    store_result = await service.store_agent_oauth_connection(
        agent_id,
        toolkit_config_id,
        AgentToolkitOAuthConnectionInput(
            issuer=metadata.issuer,
            resource=mcp_config.server_url,
            server_url=mcp_config.server_url,
            authorization_endpoint=metadata.authorization_endpoint,
            token_endpoint=metadata.token_endpoint,
            registration_endpoint=metadata.registration_endpoint,
            client_id=client_id,
            client_secret=client_secret,
            token_endpoint_auth_method=(
                "client_secret_post" if client_secret is not None else "none"
            ),
            scope=scope,
            access_token=existing.access_token if existing is not None else None,
            refresh_token=existing.refresh_token if existing is not None else None,
            expires_at=existing.expires_at if existing is not None else None,
        ),
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        connected=(
            existing is not None
            and existing.status is MCPOAuthConnectionStatus.CONNECTED
            and existing.access_token is not None
        ),
    )
    _raise_agent_item_error(store_result)
    return OAuthAuthorizeResponse(
        authorization_url=build_authorization_url(
            auth_url=metadata.authorization_endpoint,
            client_id=client_id,
            redirect_uri=redirect_uri,
            scopes=mcp_config.scopes,
            state=oauth_state,
            code_challenge=code_challenge,
            resource=mcp_config.server_url,
        )
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}"
    "/toolkit-configs/{toolkit_config_id}/oauth/exchange",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def exchange_agent_oauth_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    body: OAuthExchangeRequest,
    *,
    handle: str,
    agent_id: str,
    toolkit_config_id: str,
) -> None:
    """Exchange OAuth code for an Agent-owned Toolkit connection."""
    verified = verify_agent_toolkit_oauth_state(
        body.state,
        config.credential_encryption.key,
    )
    expected_redirect_uri = (
        f"{config.web_url}/oauth/mcp/callback"
        f"?handle={handle}&agent_id={agent_id}"
        f"&toolkit_config_id={toolkit_config_id}"
        if config.web_url
        else ""
    )
    if (
        verified is None
        or verified.toolkit_id != toolkit_config_id
        or verified.workspace_id != member.workspace_id
        or verified.agent_id != agent_id
        or verified.user_id != member.user_id
        or verified.redirect_uri != expected_redirect_uri
        or verified.callback_target != _AGENT_TOOLKIT_CALLBACK_TARGET
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state does not match Agent toolkit.",
        )
    context = await _get_agent_oauth_context_or_404(
        service,
        member,
        agent_id=agent_id,
        toolkit_config_id=toolkit_config_id,
    )
    toolkit = context.toolkit
    connection = context.connection
    if connection is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="OAuth connection not found. Start connect again.",
        )
    mcp_config = _resolve_mcp_config(toolkit.toolkit_type, toolkit.config, registry)
    if mcp_config.auth_type != "oauth2":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Toolkit does not use OAuth2 authentication.",
        )
    token_response = await _exchange_and_handle_errors(
        token_url=connection.token_endpoint,
        client_id=connection.client_id,
        client_secret=connection.client_secret,
        code=body.code,
        redirect_uri=verified.redirect_uri,
        code_verifier=verified.code_verifier,
        resource=connection.resource or mcp_config.server_url,
        proxy_url=config.mcp_proxy_url,
        toolkit_id=toolkit_config_id,
        user_id=member.user_id,
    )
    store_result = await service.store_agent_oauth_connection(
        agent_id,
        toolkit_config_id,
        AgentToolkitOAuthConnectionInput(
            issuer=connection.issuer,
            resource=connection.resource,
            server_url=connection.server_url,
            authorization_endpoint=connection.authorization_endpoint,
            token_endpoint=connection.token_endpoint,
            registration_endpoint=connection.registration_endpoint,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            token_endpoint_auth_method=connection.token_endpoint_auth_method,
            scope=connection.scope,
            access_token=token_response.access_token,
            refresh_token=token_response.refresh_token,
            expires_at=token_response.expires_at,
        ),
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
        connected=True,
    )
    _raise_agent_item_error(store_result)


@router.delete(
    "/workspaces/{handle}/agents/{agent_id}"
    "/toolkit-configs/{toolkit_config_id}/oauth/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_agent_oauth_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    *,
    handle: str,
    agent_id: str,
    toolkit_config_id: str,
) -> None:
    """Delete an Agent-owned Toolkit OAuth connection."""
    del handle
    result = await service.delete_agent_oauth_connection(
        agent_id=agent_id,
        toolkit_id=toolkit_config_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    _raise_agent_item_error(result)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_agent_toolkit_or_404(
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> ToolkitOutput:
    """Load one currently authorized Agent-owned Toolkit without disclosure."""
    result = await service.get_agent_owned(
        agent_id,
        toolkit_config_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toolkit config not found.",
        )
    return result.value


async def _get_agent_oauth_context_or_404(
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> AgentToolkitOAuthContext:
    """Load Agent-owned OAuth state through the authorization-aware service."""
    result = await service.get_agent_oauth_context(
        agent_id,
        toolkit_config_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toolkit config not found.",
        )
    return result.value


def _resolve_mcp_config(
    toolkit_type: str,
    config: dict[str, Any],
    registry: Mapping[str, ToolkitProvider[Any]] | None = None,
) -> McpToolkitConfig:
    """Build McpToolkitConfig from toolkit_type."""
    if registry is not None:
        provider = registry.get(toolkit_type)
        if provider is not None:
            typed_config = provider.validate_config(config)
            return provider.to_mcp_config(typed_config)
    return McpToolkitConfig.model_validate(config)


def _extract_oauth_client_credentials(
    credentials_json: str | None,
) -> tuple[str, str | None] | None:
    """Extract OAuth client credentials from encrypted Toolkit credentials JSON."""
    if credentials_json is None:
        return None
    try:
        secrets = _oauth_secrets_adapter.validate_json(credentials_json)
    except ValidationError:
        return None
    return (secrets.client_id, secrets.client_secret)


async def _discover_required_metadata(
    mcp_config: McpToolkitConfig,
    proxy_url: str | None,
) -> OAuthServerMetadata:
    """Discover OAuth metadata and apply explicit endpoint overrides."""
    try:
        metadata = await discover_oauth_metadata(
            mcp_config.server_url,
            mcp_config.discovery_url,
            proxy_url=proxy_url,
        )
    except DiscoveryError as exc:
        if mcp_config.auth_url is None or mcp_config.token_url is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"OAuth metadata discovery failed: {exc}",
            ) from exc
        return OAuthServerMetadata(
            authorization_endpoint=mcp_config.auth_url,
            token_endpoint=mcp_config.token_url,
            registration_endpoint=None,
            scopes_supported=[],
            issuer=None,
        )

    return OAuthServerMetadata(
        authorization_endpoint=mcp_config.auth_url or metadata.authorization_endpoint,
        token_endpoint=mcp_config.token_url or metadata.token_endpoint,
        registration_endpoint=metadata.registration_endpoint,
        scopes_supported=metadata.scopes_supported,
        issuer=metadata.issuer,
    )


async def _exchange_and_handle_errors(
    *,
    token_url: str,
    client_id: str,
    client_secret: str | None,
    code: str,
    redirect_uri: str,
    code_verifier: str | None,
    resource: str | None,
    proxy_url: str | None,
    toolkit_id: str,
    user_id: str,
) -> OAuthTokenResponse:
    """Perform OAuth2 code-to-token exchange and handle common errors."""
    try:
        return await exchange_authorization_code(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret,
            code=code,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            resource=resource,
            proxy_url=proxy_url,
        )
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Token exchange rejected by provider:"
                    f" HTTP {exc.response.status_code}"
                ),
            ) from exc
        raise
    except OAuthTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Token exchange failed: {exc}",
        ) from exc
    except ValidationError as exc:
        logger.warning(
            "Invalid token response from provider",
            extra={"toolkit_id": toolkit_id, "user_id": user_id},
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid token response from provider: {exc}",
        ) from exc


# ---------------------------------------------------------------------------
# Test connection endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/test-connection",
)
async def test_connection_saved(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    config: Annotated[Config, Depends(get_config)],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    toolkit_config_id: str,
) -> TestConnectionResponse:
    """Test the connection of a stored Toolkit.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    toolkit_repo = ToolkitRepository(cipher=cipher)

    async with session_manager() as session:
        toolkit = await toolkit_repo.get_shared_by_id(session, toolkit_config_id)

    if toolkit is None or toolkit.workspace_id != member.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toolkit config not found.",
        )

    provider = registry.get(toolkit.toolkit_type)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown toolkit type: {toolkit.toolkit_type}",
        )

    validated_config = provider.validate_config(toolkit.config)
    result = await provider.test_connection(
        validated_config, toolkit.credentials, proxy_url=config.mcp_proxy_url
    )
    return TestConnectionResponse(
        success=result.success,
        message=result.message,
        discovered_auth_url=result.discovered_auth_url,
        discovered_token_url=result.discovered_token_url,
        supports_dcr=result.supports_dcr,
    )


@router.post(
    "/workspaces/{handle}/toolkit-configs/test-connection",
)
async def test_connection_unsaved(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    cipher: Annotated[CredentialCipher, Depends(get_credential_cipher)],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    body: TestConnectionRequest,
) -> TestConnectionResponse:
    """Test the connection for Toolkit settings.

    When ``toolkit_config_id`` exists, load credentials stored in DB and override
    them with credentials from the body, prioritizing form values in edit mode.

    Requires Toolkit read permission.
    """
    if not member.has_permission(Permissions.TOOLKITS_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Toolkit read permission required.",
        )

    provider = registry.get(body.toolkit_type)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown toolkit type: {body.toolkit_type}",
        )

    validated_config = provider.validate_config(body.config)
    credentials_json = await _resolve_test_credentials(
        body, cipher, session_manager, member.workspace_id
    )
    credentials_json = await _bind_platform_app_test_credentials(
        credentials_json,
        platform_runtime,
    )

    result = await provider.test_connection(
        validated_config, credentials_json, proxy_url=config.mcp_proxy_url
    )
    return TestConnectionResponse(
        success=result.success,
        message=result.message,
        discovered_auth_url=result.discovered_auth_url,
        discovered_token_url=result.discovered_token_url,
        supports_dcr=result.supports_dcr,
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}"
    "/toolkit-configs/{toolkit_config_id}/test-connection",
)
async def test_agent_connection_saved(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    agent_id: str,
    toolkit_config_id: str,
) -> TestConnectionResponse:
    """Test one stored Agent-owned Toolkit connection."""
    toolkit = await _get_agent_toolkit_or_404(
        service,
        member,
        agent_id=agent_id,
        toolkit_config_id=toolkit_config_id,
    )
    provider = registry.get(toolkit.toolkit_type)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown toolkit type: {toolkit.toolkit_type}",
        )
    validated_config = provider.validate_config(toolkit.config)
    result = await provider.test_connection(
        validated_config,
        toolkit.credentials,
        proxy_url=config.mcp_proxy_url,
    )
    return TestConnectionResponse(
        success=result.success,
        message=result.message,
        discovered_auth_url=result.discovered_auth_url,
        discovered_token_url=result.discovered_token_url,
        supports_dcr=result.supports_dcr,
    )


@router.post(
    "/workspaces/{handle}/agents/{agent_id}/toolkit-configs/test-connection",
)
async def test_agent_connection_unsaved(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitService, Depends()],
    config: Annotated[Config, Depends(get_config)],
    platform_runtime: Annotated[PlatformGitHubAppRuntimeService, Depends()],
    registry: Annotated[dict[str, ToolkitProvider[Any]], Depends(get_toolkit_registry)],
    *,
    agent_id: str,
    body: TestConnectionRequest,
) -> TestConnectionResponse:
    """Test unsaved Agent-owned Toolkit settings without creating a resource."""
    await _authorize_agent_management_or_error(
        service,
        member,
        agent_id=agent_id,
    )
    provider = registry.get(body.toolkit_type)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown toolkit type: {body.toolkit_type}",
        )
    validated_config = provider.validate_config(body.config)
    credentials_json = await _resolve_agent_test_credentials(
        body,
        service,
        member,
        agent_id=agent_id,
    )
    credentials_json = await _bind_platform_app_test_credentials(
        credentials_json,
        platform_runtime,
    )
    result = await provider.test_connection(
        validated_config,
        credentials_json,
        proxy_url=config.mcp_proxy_url,
    )
    return TestConnectionResponse(
        success=result.success,
        message=result.message,
        discovered_auth_url=result.discovered_auth_url,
        discovered_token_url=result.discovered_token_url,
        supports_dcr=result.supports_dcr,
    )


# ---------------------------------------------------------------------------
# Test connection helpers
# ---------------------------------------------------------------------------


async def _authorize_agent_management_or_error(
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
) -> None:
    """Require current Agent management authority without exposing Toolkit state."""
    result = await service.authorize_agent_management(
        agent_id,
        workspace_id=member.workspace_id,
        workspace_user_id=member.workspace_user_id,
        role=member.role,
    )
    _raise_agent_management_error(result)


def _raise_agent_management_error(
    result: Result[None, AgentNotBelongToWorkspace | NotAdmin],
) -> None:
    """Map Agent-level management authorization without item disclosure."""
    if result.success:
        return
    error = result.error
    match error:
        case AgentNotBelongToWorkspace():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent not found.",
            )
        case NotAdmin():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Agent administrator or workspace owner access required.",
            )
        case _:
            assert_never(error)


def _raise_agent_item_error(
    result: Result[
        None,
        AgentNotBelongToWorkspace | NotAdmin | NotFound,
    ],
) -> None:
    """Map every Agent-owned item mismatch to the same 404 boundary."""
    if result.success:
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Toolkit config not found.",
    )


async def _resolve_agent_test_credentials(
    body: TestConnectionRequest,
    service: ToolkitService,
    member: WorkspaceMember,
    *,
    agent_id: str,
) -> str | None:
    """Merge saved Agent-owned credentials with unsaved non-empty values."""
    if body.toolkit_config_id is not None:
        toolkit = await _get_agent_toolkit_or_404(
            service,
            member,
            agent_id=agent_id,
            toolkit_config_id=body.toolkit_config_id,
        )
        saved: dict[str, object] = {}
        if toolkit.credentials is not None:
            try:
                saved = _credentials_adapter.validate_json(toolkit.credentials)
            except ValidationError:
                pass
        if body.credentials is not None:
            for key, value in body.credentials.items():
                if isinstance(value, str) and value == "":
                    continue
                saved[key] = value
        return json.dumps(saved) if saved else None
    if body.credentials is not None:
        return json.dumps(body.credentials)
    return None


async def _bind_platform_app_test_credentials(
    credentials_json: str | None,
    platform_runtime: PlatformGitHubAppRuntimeService,
) -> str | None:
    """Bind unsaved Platform GitHub credentials to the server App identity."""
    if credentials_json is None:
        return None
    parsed: object = json.loads(credentials_json)
    if not isinstance(parsed, dict) or parsed.get("type") != "github_app_platform":
        return credentials_json
    platform = await platform_runtime.resolve()
    if platform.app_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="GitHub Platform App is not configured.",
        )
    return json.dumps({**parsed, "app_id": platform.app_id})


async def _resolve_test_credentials(
    body: TestConnectionRequest,
    cipher: CredentialCipher,
    session_manager: SessionManager[AsyncSession],
    workspace_id: str,
) -> str | None:
    """Resolve credentials for tests.

    When ``toolkit_config_id`` exists, load stored credentials from DB, then
    override with non-empty values from the body.

    :param body: Test request body
    :param cipher: Credential decryption utility
    :param session_manager: DB session manager
    :param workspace_id: Workspace ID for ownership validation
    :return: Merged credentials JSON or None
    """
    # When stored credentials must be loaded from DB
    if body.toolkit_config_id is not None:
        toolkit_repo = ToolkitRepository(cipher=cipher)
        async with session_manager() as session:
            toolkit = await toolkit_repo.get_shared_by_id(
                session, body.toolkit_config_id
            )

        if toolkit is not None and toolkit.workspace_id == workspace_id:
            saved: dict[str, object] = {}
            if toolkit.credentials is not None:
                try:
                    parsed: object = json.loads(toolkit.credentials)
                    if isinstance(parsed, dict):
                        saved = cast(dict[str, object], parsed)
                except json.JSONDecodeError, TypeError:
                    pass

            # Override with form-entered values, ignoring empty strings
            if body.credentials is not None:
                for key, value in body.credentials.items():
                    if isinstance(value, str) and value == "":
                        continue
                    saved[key] = value

            if saved:
                return json.dumps(saved)
            return None

    # Without toolkit_config_id, use only form values in create mode
    if body.credentials is not None:
        return json.dumps(body.credentials)
    return None
