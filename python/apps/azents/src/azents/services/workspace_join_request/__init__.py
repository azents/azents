"""WorkspaceJoinRequest service."""

import dataclasses
import datetime
import logging
from datetime import timezone
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.email.service import EmailService
from azents.core.enums import JoinRequestStatus, WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_join_request import WorkspaceJoinRequestRepository
from azents.repos.workspace_join_request.data import WorkspaceJoinRequestCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate

from .data import (
    AlreadyMember,
    JoinRequestListOutput,
    JoinRequestNotFound,
    JoinRequestOutput,
    MyJoinRequestOutput,
    PendingRequestExists,
    WorkspaceNotFound,
)

logger = logging.getLogger(__name__)

# Notification cooldown: 24 hours
NOTIFICATION_COOLDOWN = datetime.timedelta(hours=24)


@dataclasses.dataclass
class WorkspaceJoinRequestService:
    """Workspace join request service."""

    join_request_repo: Annotated[WorkspaceJoinRequestRepository, Depends()]
    workspace_repo: Annotated[WorkspaceRepository, Depends()]
    workspace_user_repo: Annotated[WorkspaceUserRepository, Depends()]
    email_service: Annotated[EmailService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def request_join(
        self,
        user_id: str,
        workspace_handle: str,
        message: str | None = None,
    ) -> Result[
        JoinRequestOutput,
        WorkspaceNotFound | AlreadyMember | PendingRequestExists,
    ]:
        """Request to join workspace.

        :param user_id: Requesting user ID
        :param workspace_handle: Workspace handle
        :param message: Join reason (optional)
        :return: Join request or error
        """
        async with self.session_manager() as session:
            # 1. Check workspace existence
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))

            # 2. Check whether already member
            existing_member = await self.workspace_user_repo.get_by_workspace_and_user(
                session, workspace_id, user_id
            )
            if existing_member is not None:
                return Failure(AlreadyMember(user_id=user_id))

            # 3. Fetch existing request
            existing = await self.join_request_repo.get_by_workspace_and_user(
                session, workspace_id, user_id
            )

            should_send_notification = False

            if existing is not None:
                if existing.status == JoinRequestStatus.PENDING:
                    # pending status → duplicate request is disallowed
                    return Failure(PendingRequestExists(join_request_id=existing.id))

                # muted status → change to pending, do not send notification
                update_result = await self.join_request_repo.update(
                    session,
                    existing.id,
                    {
                        "status": JoinRequestStatus.PENDING,
                        "message": message,
                    },
                )
                match update_result:
                    case Success(value):
                        join_request = value
                    case Failure():
                        # Unreachable because this record was just fetched
                        return Failure(
                            PendingRequestExists(join_request_id=existing.id)
                        )
                    case _:
                        assert_never(update_result)
            else:
                # Create new request
                create_data = WorkspaceJoinRequestCreate(
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
                if message is not None:
                    create_data["message"] = message
                join_request = await self.join_request_repo.create_or_rerequest(
                    session, create_data
                )

                # 4. Decide notification sending (only for new request)
                now = datetime.datetime.now(timezone.utc)
                cooldown_passed = (
                    join_request.last_notified_at is None
                    or (now - join_request.last_notified_at) > NOTIFICATION_COOLDOWN
                )
                if cooldown_passed:
                    await self.join_request_repo.update(
                        session,
                        join_request.id,
                        {"last_notified_at": now},
                    )
                    should_send_notification = True

        # Send email (outside session — request remains valid even on failure)
        if should_send_notification:
            ws_name = await self._get_workspace_name(workspace_handle)
            await self.email_service.send_join_request_notification(
                workspace_name=ws_name,
                workspace_handle=workspace_handle,
            )

        return Success(JoinRequestOutput.convert_from(join_request))

    async def list_by_workspace(self, workspace_id: str) -> JoinRequestListOutput:
        """Fetch workspace join request list (pending only).

        :param workspace_id: Workspace ID
        :return: Join request list
        """
        async with self.session_manager() as session:
            result = await self.join_request_repo.list_by_workspace(
                session, workspace_id
            )
        return JoinRequestListOutput(
            items=[JoinRequestOutput.convert_from(r) for r in result.items],
            total=result.total,
        )

    async def get_my_request(
        self, user_id: str, workspace_handle: str
    ) -> Result[MyJoinRequestOutput | None, WorkspaceNotFound]:
        """Fetch my join request status.

        :param user_id: User ID
        :param workspace_handle: Workspace handle
        :return: My join request or None (no request)
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repo.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(handle=workspace_handle))

            existing = await self.join_request_repo.get_by_workspace_and_user(
                session, workspace_id, user_id
            )

        if existing is None:
            return Success(None)
        return Success(MyJoinRequestOutput.convert_from(existing))

    async def approve(
        self,
        join_request_id: str,
    ) -> Result[None, JoinRequestNotFound]:
        """Approve join request.

        :param join_request_id: Join request ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            join_request = await self.join_request_repo.get(session, join_request_id)
            if join_request is None:
                return Failure(JoinRequestNotFound(join_request_id=join_request_id))

            # Create WorkspaceUser (role=member)
            await self.workspace_user_repo.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=join_request.workspace_id,
                    user_id=join_request.user_id,
                    name=join_request.user_id[:8],
                    role=WorkspaceUserRole.MEMBER,
                ),
            )

            # Delete join request
            await self.join_request_repo.delete(session, join_request_id)

            workspace_id = join_request.workspace_id

        # Send approval email
        workspace_name = await self._get_workspace_name_by_id(workspace_id)
        await self.email_service.send_join_request_approved(
            user_id=join_request.user_id,
            workspace_name=workspace_name,
        )

        return Success(None)

    async def reject(
        self,
        join_request_id: str,
    ) -> Result[None, JoinRequestNotFound]:
        """Reject join request.

        :param join_request_id: Join request ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            join_request = await self.join_request_repo.get(session, join_request_id)
            if join_request is None:
                return Failure(JoinRequestNotFound(join_request_id=join_request_id))

            await self.join_request_repo.delete(session, join_request_id)

        return Success(None)

    async def mute(
        self,
        join_request_id: str,
    ) -> Result[None, JoinRequestNotFound]:
        """Mute join request.

        :param join_request_id: Join request ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            result = await self.join_request_repo.update(
                session,
                join_request_id,
                {"status": JoinRequestStatus.MUTED},
            )

        match result:
            case Success():
                return Success(None)
            case Failure(error):
                return Failure(
                    JoinRequestNotFound(join_request_id=error.join_request_id)
                )

    async def delete(self, join_request_id: str) -> None:
        """Delete join request (for unmute).

        :param join_request_id: Join request ID
        """
        async with self.session_manager() as session:
            await self.join_request_repo.delete(session, join_request_id)

    async def auto_approve_if_pending(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """Auto-approve when pending join request exists.

        Called by InvitationService when creating invitation.

        :param session: Database session (inside caller transaction)
        :param workspace_id: Workspace ID
        :param user_id: User ID
        :return: Auto-approval flag
        """
        existing = await self.join_request_repo.get_by_workspace_and_user(
            session, workspace_id, user_id
        )
        if existing is None or existing.status != JoinRequestStatus.PENDING:
            return False

        # Create WorkspaceUser + delete join request
        await self.workspace_user_repo.create(
            session,
            WorkspaceUserCreate(
                workspace_id=workspace_id,
                user_id=user_id,
                name=user_id[:8],
                role=WorkspaceUserRole.MEMBER,
            ),
        )
        await self.join_request_repo.delete(session, existing.id)
        return True

    async def _get_workspace_name(self, handle: str) -> str:
        """Fetch name by Workspace handle."""
        async with self.session_manager() as session:
            workspace = await self.workspace_repo.get_by_handle(session, handle)
        return workspace.name if workspace else handle

    async def _get_workspace_name_by_id(self, workspace_id: str) -> str:
        """Fetch name by workspace ID."""
        async with self.session_manager() as session:
            workspace = await self.workspace_repo.get_by_id(session, workspace_id)
        return workspace.name if workspace else "workspace"
