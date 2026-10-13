"""Toolkit OAuth2 endpoints.

Provides toolkit-level OAuth2 connection endpoints and connection test endpoints.
"""

from typing import Annotated, Any, NoReturn, assert_never

from azcommon.result import Result
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from azents.core.auth.deps import WorkspaceMember, get_workspace_member
from azents.core.auth.permissions import Permissions
from azents.core.config import Config
from azents.core.deps import get_config
from azents.core.toolkit_errors import NotFound
from azents.core.tools import ToolkitProvider
from azents.engine.tools.deps import get_toolkit_registry
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit import ToolkitService
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
)
from azents.services.toolkit_oauth import service as toolkit_oauth_service
from azents.services.toolkit_oauth.data import (
    ToolkitConnectionTestInput,
    ToolkitOAuthError,
    ToolkitOAuthFailureReason,
)
from azents.services.toolkit_oauth.service import ToolkitOAuthService

router = APIRouter()

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
    try:
        value = await toolkit_oauth_service.platform_install_url(platform_runtime)
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformInstallUrlResponse(install_url=value)


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
    try:
        value = await toolkit_oauth_service.platform_oauth_url(config, platform_runtime)
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformOAuthUrlResponse(oauth_url=value)


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
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        installations = await service.platform_installations(
            user_id=member.user_id,
            session_id=member.session_id,
            workspace_id=member.workspace_id,
            code=body.code,
            state=body.state,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformInstallationsResponse(
        installations=[
            GitHubInstallationItem(
                id=item.id,
                account_login=item.account_login,
                account_type=item.account_type,
                account_avatar_url=item.account_avatar_url,
            )
            for item in installations
        ]
    )


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
    try:
        value = await toolkit_oauth_service.agent_platform_install_url(
            member, service, platform_runtime, agent_id=agent_id
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformInstallUrlResponse(install_url=value)


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
    try:
        value = await toolkit_oauth_service.agent_platform_oauth_url(
            member, service, config, platform_runtime, handle=handle, agent_id=agent_id
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformOAuthUrlResponse(oauth_url=value)


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
    try:
        value = await toolkit_oauth_service.agent_platform_installations(
            member,
            service,
            config,
            platform_runtime,
            body.code,
            state=body.state,
            agent_id=agent_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return GitHubPlatformInstallationsResponse(
        installations=[
            GitHubInstallationItem(
                id=item.id,
                account_login=item.account_login,
                account_type=item.account_type,
                account_avatar_url=item.account_avatar_url,
            )
            for item in value
        ]
    )


# ---------------------------------------------------------------------------
# OAuth connection endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connect",
)
async def connect_oauth(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        authorization_url = await service.connect(
            user_id=member.user_id,
            session_id=member.session_id,
            workspace_id=member.workspace_id,
            handle=handle,
            toolkit_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
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
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        await service.exchange(
            user_id=member.user_id,
            session_id=member.session_id,
            workspace_id=member.workspace_id,
            toolkit_id=toolkit_config_id,
            code=body.code,
            state=body.state,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)


@router.delete(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/oauth/connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_oauth_connection(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        await service.disconnect(
            workspace_id=member.workspace_id,
            toolkit_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)


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
    try:
        value = await toolkit_oauth_service.connect_agent(
            member,
            service,
            config,
            registry,
            handle=handle,
            agent_id=agent_id,
            toolkit_config_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return OAuthAuthorizeResponse(authorization_url=value)


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
    try:
        await toolkit_oauth_service.exchange_agent(
            member,
            service,
            config,
            registry,
            body.code,
            state=body.state,
            handle=handle,
            agent_id=agent_id,
            toolkit_config_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)


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


def _raise_toolkit_oauth_error(error: ToolkitOAuthError) -> NoReturn:
    """Project only expected completed-service failures to the existing API."""
    match error.reason:
        case ToolkitOAuthFailureReason.INACTIVE_SUBJECT:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=error.detail,
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        case (
            ToolkitOAuthFailureReason.WORKSPACE_NOT_FOUND
            | ToolkitOAuthFailureReason.TOOLKIT_NOT_FOUND
            | ToolkitOAuthFailureReason.RESOURCE_NOT_FOUND
        ):
            code = status.HTTP_404_NOT_FOUND
        case (
            ToolkitOAuthFailureReason.MEMBERSHIP_REQUIRED
            | ToolkitOAuthFailureReason.WRITE_PERMISSION_REQUIRED
        ):
            code = status.HTTP_403_FORBIDDEN
        case ToolkitOAuthFailureReason.INVALID_REQUEST:
            code = status.HTTP_400_BAD_REQUEST
        case ToolkitOAuthFailureReason.TOKEN_REJECTED:
            code = status.HTTP_422_UNPROCESSABLE_ENTITY
        case ToolkitOAuthFailureReason.PLATFORM_SETTINGS_CHANGED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "system_setting_changed",
                    "message": "Platform GitHub App settings changed. Restart OAuth.",
                },
            ) from error
        case _:
            assert_never(error.reason)
    raise HTTPException(status_code=code, detail=error.detail) from error


# ---------------------------------------------------------------------------
# Test connection endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{handle}/toolkit-configs/{toolkit_config_id}/test-connection",
)
async def test_connection_saved(
    member: Annotated[WorkspaceMember, Depends(get_workspace_member)],
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        result = await service.test_saved(
            workspace_id=member.workspace_id,
            toolkit_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
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
    service: Annotated[ToolkitOAuthService, Depends()],
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

    try:
        result = await service.test_unsaved(
            workspace_id=member.workspace_id,
            request=ToolkitConnectionTestInput(
                toolkit_type=body.toolkit_type,
                config=body.config,
                credentials=body.credentials,
                toolkit_config_id=body.toolkit_config_id,
            ),
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
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
    try:
        value = await toolkit_oauth_service.test_agent_saved(
            member,
            service,
            config,
            registry,
            agent_id=agent_id,
            toolkit_config_id=toolkit_config_id,
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return TestConnectionResponse(
        success=value.success,
        message=value.message,
        discovered_auth_url=value.discovered_auth_url,
        discovered_token_url=value.discovered_token_url,
        supports_dcr=value.supports_dcr,
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
    try:
        value = await toolkit_oauth_service.test_agent_unsaved(
            member,
            service,
            config,
            platform_runtime,
            registry,
            agent_id=agent_id,
            request=ToolkitConnectionTestInput(
                toolkit_type=body.toolkit_type,
                config=body.config,
                credentials=body.credentials,
                toolkit_config_id=body.toolkit_config_id,
            ),
        )
    except ToolkitOAuthError as exc:
        _raise_toolkit_oauth_error(exc)
    return TestConnectionResponse(
        success=value.success,
        message=value.message,
        discovered_auth_url=value.discovered_auth_url,
        discovered_token_url=value.discovered_token_url,
        supports_dcr=value.supports_dcr,
    )


# ---------------------------------------------------------------------------
# Test connection helpers
# ---------------------------------------------------------------------------


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
