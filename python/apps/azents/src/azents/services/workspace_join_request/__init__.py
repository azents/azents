"""WorkspaceJoinRequest service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.email.service import EmailService
from azents.repos.workspace_join_request.operation_data import (
    AlreadyMember as RepositoryAlreadyMember,
)
from azents.repos.workspace_join_request.operation_data import (
    PendingRequestExists as RepositoryPendingRequestExists,
)
from azents.repos.workspace_join_request.operation_data import (
    WorkspaceNotFound as RepositoryWorkspaceNotFound,
)
from azents.repos.workspace_join_request.operations import (
    WorkspaceJoinRequestOperationRepository,
)

from .data import (
    AlreadyMember,
    JoinRequestListOutput,
    JoinRequestNotFound,
    JoinRequestOutput,
    MyJoinRequestOutput,
    PendingRequestExists,
    WorkspaceNotFound,
)


@dataclasses.dataclass
class WorkspaceJoinRequestService:
    """Orchestrate completed join-request operations and post-commit delivery."""

    operation_repo: Annotated[WorkspaceJoinRequestOperationRepository, Depends()]
    email_service: Annotated[EmailService, Depends()]

    async def request_join(
        self, user_id: str, workspace_handle: str, message: str | None = None
    ) -> Result[
        JoinRequestOutput, WorkspaceNotFound | AlreadyMember | PendingRequestExists
    ]:
        """Request membership and deliver notification after commit."""
        result = await self.operation_repo.request_join(
            user_id=user_id, workspace_handle=workspace_handle, message=message
        )
        match result:
            case Success(value):
                requested = value
            case Failure(error):
                match error:
                    case RepositoryWorkspaceNotFound(handle=handle):
                        return Failure(WorkspaceNotFound(handle=handle))
                    case RepositoryAlreadyMember(user_id=member_id):
                        return Failure(AlreadyMember(user_id=member_id))
                    case RepositoryPendingRequestExists(join_request_id=request_id):
                        return Failure(PendingRequestExists(join_request_id=request_id))
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)
        if requested.should_send_notification:
            workspace_name = await self.operation_repo.get_workspace_name(
                workspace_handle
            )
            await self.email_service.send_join_request_notification(
                workspace_name=workspace_name, workspace_handle=workspace_handle
            )
        return Success(JoinRequestOutput.convert_from(requested.join_request))

    async def list_by_workspace(self, workspace_id: str) -> JoinRequestListOutput:
        """Fetch the existing Workspace request listing."""
        result = await self.operation_repo.list_by_workspace(workspace_id)
        return JoinRequestListOutput(
            items=[JoinRequestOutput.convert_from(item) for item in result.items],
            total=result.total,
        )

    async def get_my_request(
        self, user_id: str, workspace_handle: str
    ) -> Result[MyJoinRequestOutput | None, WorkspaceNotFound]:
        """Fetch the requester's join-request status."""
        result = await self.operation_repo.get_my_request(
            user_id=user_id, workspace_handle=workspace_handle
        )
        match result:
            case Success(value):
                return Success(
                    None if value is None else MyJoinRequestOutput.convert_from(value)
                )
            case Failure(error):
                return Failure(WorkspaceNotFound(handle=error.handle))
            case _:
                assert_never(result)

    async def approve(self, join_request_id: str) -> Result[None, JoinRequestNotFound]:
        """Commit membership and request deletion before approval delivery."""
        result = await self.operation_repo.approve(join_request_id)
        match result:
            case Success(value):
                approved = value
            case Failure(error):
                return Failure(
                    JoinRequestNotFound(join_request_id=error.join_request_id)
                )
            case _:
                assert_never(result)
        workspace_name = await self.operation_repo.get_workspace_name_by_id(
            approved.workspace_id
        )
        await self.email_service.send_join_request_approved(
            user_id=approved.user_id, workspace_name=workspace_name
        )
        return Success(None)

    async def reject(self, join_request_id: str) -> Result[None, JoinRequestNotFound]:
        """Reject a join request through a completed operation."""
        result = await self.operation_repo.reject(join_request_id)
        match result:
            case Success():
                return Success(None)
            case Failure(error):
                return Failure(
                    JoinRequestNotFound(join_request_id=error.join_request_id)
                )
            case _:
                assert_never(result)

    async def mute(self, join_request_id: str) -> Result[None, JoinRequestNotFound]:
        """Mute a join request through a completed operation."""
        result = await self.operation_repo.mute(join_request_id)
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
        """Delete a join request through a completed operation."""
        await self.operation_repo.delete(join_request_id)
