"""Completed database reads for account and Workspace admission."""

import dataclasses
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.account_access import (
    AccountWorkspaceMembership,
    ActiveAccountSubjectStatus,
    WorkspaceMembershipAccess,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.session import SessionRepository
from azents.repos.user import UserRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository


async def evaluate_active_subject(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    user_repository: UserRepository,
    session_repository: SessionRepository,
) -> ActiveAccountSubjectStatus:
    """Evaluate the canonical exact User and Session predicates in an owned scope."""
    user = await user_repository.get(session, user_id)
    if user is None:
        return ActiveAccountSubjectStatus.USER_MISSING
    if user.access_disabled_at is not None:
        return ActiveAccountSubjectStatus.USER_DISABLED
    auth_session = await session_repository.get(session, session_id)
    if auth_session is None:
        return ActiveAccountSubjectStatus.SESSION_MISSING
    if auth_session.user_id != user_id:
        return ActiveAccountSubjectStatus.SESSION_FOREIGN
    if auth_session.is_revoked:
        return ActiveAccountSubjectStatus.SESSION_REVOKED
    if auth_session.is_expired:
        return ActiveAccountSubjectStatus.SESSION_EXPIRED
    return ActiveAccountSubjectStatus.ACTIVE


@dataclasses.dataclass(frozen=True)
class AccountAccessOperationRepository:
    """Own exact subject and membership reads without HTTP or credential policy."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    user_repository: Annotated[UserRepository, Depends(UserRepository)]
    session_repository: Annotated[SessionRepository, Depends(SessionRepository)]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def read_active_subject(
        self, *, user_id: str, session_id: str
    ) -> ActiveAccountSubjectStatus:
        """Return current User and exact Session eligibility after DB closure."""
        async with self.session_manager() as session:
            return await evaluate_active_subject(
                session,
                user_id=user_id,
                session_id=session_id,
                user_repository=self.user_repository,
                session_repository=self.session_repository,
            )

    async def read_workspace_membership(
        self, *, handle: str, user_id: str
    ) -> WorkspaceMembershipAccess:
        """Resolve handle and current membership in one completed read."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(session, handle)
            if workspace_id is None:
                return WorkspaceMembershipAccess(workspace_id=None, membership=None)
            member = await self.workspace_user_repository.get_by_workspace_and_user(
                session, workspace_id, user_id
            )
            return WorkspaceMembershipAccess(
                workspace_id=workspace_id,
                membership=(
                    AccountWorkspaceMembership(
                        workspace_user_id=member.id, role=member.role
                    )
                    if member is not None
                    else None
                ),
            )
