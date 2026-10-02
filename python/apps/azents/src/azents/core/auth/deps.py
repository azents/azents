"""Authentication dependencies."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from azents.core.account_access import ActiveAccountSubjectStatus
from azents.core.auth.jwt import InvalidTokenError, decode_access_token
from azents.core.auth.permissions import Permission, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import AuthConfig
from azents.core.deps import get_auth_config
from azents.core.enums import WorkspaceUserRole
from azents.services.account_access import AccountAccessService
from azents.services.system_user_role.service import SystemUserRoleService

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """Current authenticated user context."""

    user_id: str
    session_id: str
    elevated: bool = False


@dataclass
class SystemAdmin:
    """Authenticated instance system administrator context."""

    user_id: str
    session_id: str
    elevated: bool = False


@dataclass
class WorkspaceMember:
    """Workspace member context."""

    user_id: str
    workspace_id: str
    workspace_user_id: str
    role: WorkspaceUserRole
    permissions: set[Permission]
    session_id: str

    def has_permission(self, required: Permission) -> bool:
        """Check whether the user has the required permission."""
        return has_permission(self.permissions, required)


async def _require_active_user_session(
    *,
    access_service: AccountAccessService,
    user_id: str,
    session_id: str,
) -> None:
    """Reject disabled accounts and revoked/expired auth sessions.

    :param access_service: Service returning a completed exact subject read
    :param user_id: Authenticated user ID from JWT
    :param session_id: Auth session ID from JWT
    :raises HTTPException: 401 when the account or auth session is not active
    """
    status = await access_service.read_active_subject(
        user_id=user_id, session_id=session_id
    )
    if status is not ActiveAccountSubjectStatus.ACTIVE:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    access_service: Annotated[AccountAccessService, Depends(AccountAccessService)],
) -> CurrentUser:
    """Return the current authenticated user.

    :raises HTTPException: 401 when unauthenticated
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(auth_config.jwt, credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    await _require_active_user_session(
        access_service=access_service,
        user_id=payload.user_id,
        session_id=payload.session_id,
    )
    return CurrentUser(
        user_id=payload.user_id,
        session_id=payload.session_id,
        elevated=payload.elevated,
    )


async def get_current_user_optional(
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    access_service: Annotated[AccountAccessService, Depends(AccountAccessService)],
) -> CurrentUser | None:
    """Return the current authenticated user, or None when unauthenticated.

    Used by endpoints that behave differently based on login state.
    """
    if credentials is None:
        return None

    try:
        payload = decode_access_token(auth_config.jwt, credentials.credentials)
    except InvalidTokenError:
        return None

    try:
        await _require_active_user_session(
            access_service=access_service,
            user_id=payload.user_id,
            session_id=payload.session_id,
        )
    except HTTPException:
        return None

    return CurrentUser(
        user_id=payload.user_id,
        session_id=payload.session_id,
        elevated=payload.elevated,
    )


async def get_elevated_user(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    """Return a user that requires elevated permission.

    :raises HTTPException: 403 when elevation is required
    """
    if not current_user.elevated:
        raise HTTPException(
            status_code=403,
            detail="Elevated access required",
        )
    return current_user


async def get_system_admin(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    system_role_service: Annotated[SystemUserRoleService, Depends()],
) -> SystemAdmin:
    """Return the current User as a system administrator.

    :raises HTTPException: 403 when the User lacks system-admin authority
    """
    if not await system_role_service.require_system_admin(current_user.user_id):
        raise HTTPException(
            status_code=403,
            detail="System administrator access required",
        )
    return SystemAdmin(
        user_id=current_user.user_id,
        session_id=current_user.session_id,
        elevated=current_user.elevated,
    )


async def get_workspace_member(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    access_service: Annotated[AccountAccessService, Depends(AccountAccessService)],
    *,
    handle: str,
) -> WorkspaceMember:
    """Validate and return the current user workspace membership.

    :param handle: Workspace handle injected from path parameter
    :raises HTTPException: 403 when not a member, 404 when workspace is missing
    """
    access = await access_service.read_workspace_membership(
        handle=handle, user_id=current_user.user_id
    )
    if access.workspace_id is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if access.membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this workspace.")
    role = access.membership.role
    permissions = get_permissions_for_role(role)

    return WorkspaceMember(
        user_id=current_user.user_id,
        workspace_id=access.workspace_id,
        workspace_user_id=access.membership.workspace_user_id,
        role=role,
        permissions=permissions,
        session_id=current_user.session_id,
    )
