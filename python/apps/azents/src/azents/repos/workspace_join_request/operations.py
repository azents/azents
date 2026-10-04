"""Complete database operations for Workspace join requests."""

import datetime
from dataclasses import dataclass
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import JoinRequestStatus, WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_join_request import WorkspaceJoinRequestRepository
from azents.repos.workspace_join_request.data import (
    WorkspaceJoinRequest,
    WorkspaceJoinRequestCreate,
    WorkspaceJoinRequestList,
)
from azents.repos.workspace_join_request.operation_data import (
    AlreadyMember,
    ApprovedJoin,
    JoinRequestNotFound,
    PendingRequestExists,
    RequestedJoin,
    WorkspaceNotFound,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate

NOTIFICATION_COOLDOWN = datetime.timedelta(hours=24)


@dataclass
class WorkspaceJoinRequestOperationRepository:
    """Compose join-request database work without exposing live sessions."""

    join_request_repo: Annotated[WorkspaceJoinRequestRepository, Depends()]
    workspace_repo: Annotated[WorkspaceRepository, Depends()]
    workspace_user_repo: Annotated[WorkspaceUserRepository, Depends()]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    async def request_join(
        self, *, user_id: str, workspace_handle: str, message: str | None
    ) -> Result[
        RequestedJoin, WorkspaceNotFound | AlreadyMember | PendingRequestExists
    ]:
        """Commit a new or unmuted request and notification timestamp together."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))
            existing_member = await self.workspace_user_repo.get_by_workspace_and_user(
                session, workspace_id, user_id
            )
            if existing_member is not None:
                return Failure(AlreadyMember(user_id=user_id))
            existing = await self.join_request_repo.get_by_workspace_and_user(
                session, workspace_id, user_id
            )
            should_send_notification = False
            if existing is not None:
                if existing.status == JoinRequestStatus.PENDING:
                    return Failure(PendingRequestExists(join_request_id=existing.id))
                result = await self.join_request_repo.update(
                    session,
                    existing.id,
                    {"status": JoinRequestStatus.PENDING, "message": message},
                )
                match result:
                    case Success(value):
                        join_request = value
                    case Failure():
                        return Failure(
                            PendingRequestExists(join_request_id=existing.id)
                        )
                    case _:
                        assert_never(result)
            else:
                create = WorkspaceJoinRequestCreate(
                    workspace_id=workspace_id, user_id=user_id
                )
                if message is not None:
                    create["message"] = message
                join_request = await self.join_request_repo.create_or_rerequest(
                    session, create
                )
                now = datetime.datetime.now(datetime.UTC)
                cooldown_passed = (
                    join_request.last_notified_at is None
                    or now - join_request.last_notified_at > NOTIFICATION_COOLDOWN
                )
                if cooldown_passed:
                    await self.join_request_repo.update(
                        session, join_request.id, {"last_notified_at": now}
                    )
                    should_send_notification = True
            return Success(
                RequestedJoin(
                    join_request=join_request,
                    should_send_notification=should_send_notification,
                )
            )

    async def list_by_workspace(self, workspace_id: str) -> WorkspaceJoinRequestList:
        """Read the existing Workspace request listing in a completed scope."""
        async with self.session_manager() as session:
            return await self.join_request_repo.list_by_workspace(session, workspace_id)

    async def get_my_request(
        self, *, user_id: str, workspace_handle: str
    ) -> Result[WorkspaceJoinRequest | None, WorkspaceNotFound]:
        """Resolve the Workspace and requester record in a completed scope."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))
            return Success(
                await self.join_request_repo.get_by_workspace_and_user(
                    session, workspace_id, user_id
                )
            )

    async def approve(
        self, join_request_id: str
    ) -> Result[ApprovedJoin, JoinRequestNotFound]:
        """Commit membership creation and join-request deletion atomically."""
        async with self.session_manager() as session:
            join_request = await self.join_request_repo.get(session, join_request_id)
            if join_request is None:
                return Failure(JoinRequestNotFound(join_request_id=join_request_id))
            await self.workspace_user_repo.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=join_request.workspace_id,
                    user_id=join_request.user_id,
                    name=join_request.user_id[:8],
                    role=WorkspaceUserRole.MEMBER,
                ),
            )
            await self.join_request_repo.delete(session, join_request_id)
            return Success(
                ApprovedJoin(
                    workspace_id=join_request.workspace_id, user_id=join_request.user_id
                )
            )

    async def reject(self, join_request_id: str) -> Result[None, JoinRequestNotFound]:
        """Validate and delete a join request in a completed transaction."""
        async with self.session_manager() as session:
            join_request = await self.join_request_repo.get(session, join_request_id)
            if join_request is None:
                return Failure(JoinRequestNotFound(join_request_id=join_request_id))
            await self.join_request_repo.delete(session, join_request_id)
            return Success(None)

    async def mute(self, join_request_id: str) -> Result[None, JoinRequestNotFound]:
        """Mute a join request in a completed transaction."""
        async with self.session_manager() as session:
            result = await self.join_request_repo.update(
                session, join_request_id, {"status": JoinRequestStatus.MUTED}
            )
            match result:
                case Success():
                    return Success(None)
                case Failure(error):
                    return Failure(
                        JoinRequestNotFound(join_request_id=error.join_request_id)
                    )
                case _:
                    assert_never(result)

    async def delete(self, join_request_id: str) -> None:
        """Delete a join request in a completed transaction."""
        async with self.session_manager() as session:
            await self.join_request_repo.delete(session, join_request_id)

    async def get_workspace_name(self, handle: str) -> str:
        """Read Workspace name for post-commit notification delivery."""
        async with self.session_manager() as session:
            workspace = await self.workspace_repo.get_by_handle(session, handle)
            return workspace.name if workspace else handle

    async def get_workspace_name_by_id(self, workspace_id: str) -> str:
        """Read Workspace name for post-commit approval delivery."""
        async with self.session_manager() as session:
            workspace = await self.workspace_repo.get_by_id(session, workspace_id)
            return workspace.name if workspace else "workspace"
