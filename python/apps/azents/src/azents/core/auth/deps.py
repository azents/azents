"""Authentication dependencies."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.auth.jwt import InvalidTokenError, decode_access_token
from azents.core.auth.permissions import Permission, has_permission
from azents.core.auth.roles import get_permissions_for_role
from azents.core.config import AuthConfig
from azents.core.deps import get_auth_config
from azents.core.enums import WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """Current authenticated user context."""

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


async def get_current_user(
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
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

    return CurrentUser(
        user_id=payload.user_id,
        session_id=payload.session_id,
        elevated=payload.elevated,
    )


async def get_current_user_optional(
    auth_config: Annotated[AuthConfig, Depends(get_auth_config)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
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


async def get_workspace_member(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_repo: Annotated[WorkspaceRepository, Depends()],
    user_repo: Annotated[WorkspaceUserRepository, Depends()],
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ],
    *,
    handle: str,
) -> WorkspaceMember:
    """Validate and return the current user workspace membership.

    :param handle: Workspace handle injected from path parameter
    :raises HTTPException: 403 when not a member, 404 when workspace is missing
    """
    async with session_manager() as session:
        workspace_id = await workspace_repo.resolve_id(session, handle)
        if workspace_id is None:
            raise HTTPException(
                status_code=404,
                detail="Workspace not found.",
            )

        workspace_user = await user_repo.get_by_workspace_and_user(
            session, workspace_id, current_user.user_id
        )
        if workspace_user is None:
            raise HTTPException(
                status_code=403,
                detail="Not a member of this workspace.",
            )

    role = workspace_user.role
    permissions = get_permissions_for_role(role)

    return WorkspaceMember(
        user_id=current_user.user_id,
        workspace_id=workspace_id,
        workspace_user_id=workspace_user.id,
        role=role,
        permissions=permissions,
        session_id=current_user.session_id,
    )
