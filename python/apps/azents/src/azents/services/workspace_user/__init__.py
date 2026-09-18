"""WorkspaceUser service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.enums import WorkspaceUserRole
from azents.repos.workspace_user.data import NotFound as RepositoryNotFound
from azents.repos.workspace_user.data import UserNotFound as RepositoryUserNotFound
from azents.repos.workspace_user.data import (
    WorkspaceNotFound as RepositoryWorkspaceNotFound,
)
from azents.repos.workspace_user.data import (
    WorkspaceUserAlreadyExists as RepositoryWorkspaceUserAlreadyExists,
)
from azents.repos.workspace_user.operations import (
    WorkspaceOwnershipTransfer,
    WorkspaceUserOperationRepository,
    WorkspaceUserOutsideWorkspace,
    WorkspaceUserOwnerAlreadyExists,
    WorkspaceUserOwnerLocked,
)
from azents.services.runtime_terminal.invalidation import (
    RuntimeTerminalInvalidationPublisherDependency,
)

from .data import (
    CannotModifyOwner,
    CannotModifySelf,
    InvalidRole,
    NotFound,
    NotMemberOfWorkspace,
    OwnerAlreadyExists,
    UserNotFound,
    WorkspaceNotFound,
    WorkspaceUserAlreadyExists,
    WorkspaceUserCreateInput,
    WorkspaceUserListOutput,
    WorkspaceUserOutput,
    WorkspaceUserUpdateInput,
)


@dataclasses.dataclass
class WorkspaceUserService:
    """WorkspaceUser CRUD service."""

    operations: Annotated[
        WorkspaceUserOperationRepository, Depends(WorkspaceUserOperationRepository)
    ]
    terminal_invalidation_publisher: RuntimeTerminalInvalidationPublisherDependency

    async def create(
        self, create: WorkspaceUserCreateInput
    ) -> Result[
        WorkspaceUserOutput,
        (
            WorkspaceNotFound
            | UserNotFound
            | WorkspaceUserAlreadyExists
            | OwnerAlreadyExists
        ),
    ]:
        """Create WorkspaceUser."""
        result = await self.operations.create_by_handle(
            workspace_handle=create.workspace_handle,
            user_id=create.user_id,
            name=create.name,
            role=create.role,
        )
        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                match error:
                    case RepositoryWorkspaceNotFound(workspace_id):
                        return Failure(WorkspaceNotFound(workspace_id=workspace_id))
                    case RepositoryUserNotFound(user_id):
                        return Failure(UserNotFound(user_id=user_id))
                    case RepositoryWorkspaceUserAlreadyExists(
                        workspace_id=workspace_id,
                        user_id=user_id,
                    ):
                        return Failure(
                            WorkspaceUserAlreadyExists(
                                workspace_id=workspace_id,
                                user_id=user_id,
                            )
                        )
                    case WorkspaceUserOwnerAlreadyExists(
                        workspace_user_id=workspace_user_id
                    ):
                        return Failure(
                            OwnerAlreadyExists(workspace_user_id=workspace_user_id)
                        )
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def get(self, workspace_user_id: str) -> WorkspaceUserOutput | None:
        """Fetch WorkspaceUser by ID."""
        workspace_user = await self.operations.get(workspace_user_id=workspace_user_id)
        if workspace_user is None:
            return None
        return WorkspaceUserOutput.convert_from(workspace_user)

    async def list_by_workspace(self, handle: str) -> WorkspaceUserListOutput:
        """Fetch WorkspaceUsers in Workspace."""
        workspace_users = await self.operations.list_by_workspace_handle(
            workspace_handle=handle
        )
        return WorkspaceUserListOutput(
            items=[WorkspaceUserOutput.convert_from(u) for u in workspace_users.items]
        )

    async def update(
        self, workspace_user_id: str, update: WorkspaceUserUpdateInput
    ) -> Result[WorkspaceUserOutput, NotFound]:
        """Update WorkspaceUser."""
        result = await self.operations.update(
            workspace_user_id=workspace_user_id,
            update=update,
        )
        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(RepositoryNotFound(missing_id)):
                return Failure(NotFound(workspace_user_id=missing_id))
            case _:
                assert_never(result)

    async def update_role(
        self,
        actor_workspace_user_id: str,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        WorkspaceUserOutput,
        NotFound | CannotModifySelf | CannotModifyOwner | InvalidRole,
    ]:
        """Change role of WorkspaceUser."""
        if actor_workspace_user_id == workspace_user_id:
            return Failure(CannotModifySelf())
        result = await self._update_non_owner_role(workspace_user_id, role)
        match result:
            case Success(value):
                return Success(value)
            case Failure(error):
                match error:
                    case NotFound():
                        return Failure(error)
                    case CannotModifyOwner():
                        return Failure(error)
                    case InvalidRole():
                        return Failure(error)
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def delete(
        self,
        actor_workspace_user_id: str,
        workspace_user_id: str,
    ) -> Result[None, CannotModifySelf | CannotModifyOwner | NotFound]:
        """Delete WorkspaceUser."""
        if actor_workspace_user_id == workspace_user_id:
            return Failure(CannotModifySelf())
        result = await self._delete_non_owner(workspace_user_id)
        match result:
            case Success():
                return Success(None)
            case Failure(error):
                match error:
                    case NotFound():
                        return Failure(error)
                    case CannotModifyOwner():
                        return Failure(error)
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def update_role_admin(
        self,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[
        WorkspaceUserOutput,
        NotFound | CannotModifyOwner | InvalidRole,
    ]:
        """Change a non-Owner WorkspaceUser role from the Admin API."""
        return await self._update_non_owner_role(workspace_user_id, role)

    async def delete_force(
        self, workspace_user_id: str
    ) -> Result[None, NotFound | CannotModifyOwner]:
        """Delete a non-Owner WorkspaceUser from the Admin API."""
        return await self._delete_non_owner(workspace_user_id)

    async def transfer_ownership(
        self,
        workspace_id: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceUserOutput,
        WorkspaceNotFound | NotFound | NotMemberOfWorkspace,
    ]:
        """Change Workspace Owner."""
        result = await self.operations.transfer_ownership(
            workspace_id=workspace_id,
            new_owner_workspace_user_id=new_owner_workspace_user_id,
        )
        return await self._finish_ownership_transfer(result)

    async def transfer_ownership_by_handle(
        self,
        handle: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceUserOutput, WorkspaceNotFound | NotFound | NotMemberOfWorkspace
    ]:
        """Change Workspace Owner after resolving its handle."""
        result = await self.operations.transfer_ownership_by_handle(
            workspace_handle=handle,
            new_owner_workspace_user_id=new_owner_workspace_user_id,
        )
        return await self._finish_ownership_transfer(result)

    async def _update_non_owner_role(
        self,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[WorkspaceUserOutput, NotFound | CannotModifyOwner | InvalidRole]:
        """Validate a role request and publish its committed invalidation."""
        if role == WorkspaceUserRole.OWNER:
            return Failure(InvalidRole())
        result = await self.operations.update_non_owner_role(
            workspace_user_id=workspace_user_id,
            role=role,
        )
        match result:
            case Success(value):
                publisher = self.terminal_invalidation_publisher
                await publisher.publish_user_terminal_invalidation(value.user_id)
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                match error:
                    case RepositoryNotFound(missing_id):
                        return Failure(NotFound(workspace_user_id=missing_id))
                    case WorkspaceUserOwnerLocked():
                        return Failure(CannotModifyOwner())
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def _delete_non_owner(
        self,
        workspace_user_id: str,
    ) -> Result[None, NotFound | CannotModifyOwner]:
        """Delete one membership and publish its committed invalidation."""
        result = await self.operations.delete_non_owner(
            workspace_user_id=workspace_user_id
        )
        match result:
            case Success(deleted):
                publisher = self.terminal_invalidation_publisher
                await publisher.publish_user_terminal_invalidation(deleted.user_id)
                return Success(None)
            case Failure(error):
                match error:
                    case RepositoryNotFound(missing_id):
                        return Failure(NotFound(workspace_user_id=missing_id))
                    case WorkspaceUserOwnerLocked():
                        return Failure(CannotModifyOwner())
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)

    async def _finish_ownership_transfer(
        self,
        result: Result[
            WorkspaceOwnershipTransfer,
            RepositoryWorkspaceNotFound
            | RepositoryNotFound
            | WorkspaceUserOutsideWorkspace,
        ],
    ) -> Result[
        WorkspaceUserOutput, WorkspaceNotFound | NotFound | NotMemberOfWorkspace
    ]:
        """Map a committed ownership transfer and publish invalidations."""
        match result:
            case Success(transfer):
                publisher = self.terminal_invalidation_publisher
                if transfer.changed:
                    if transfer.previous_owner_user_id is not None:
                        await publisher.publish_user_terminal_invalidation(
                            transfer.previous_owner_user_id
                        )
                    await publisher.publish_user_terminal_invalidation(
                        transfer.owner.user_id
                    )
                return Success(WorkspaceUserOutput.convert_from(transfer.owner))
            case Failure(error):
                match error:
                    case RepositoryWorkspaceNotFound(workspace_id):
                        return Failure(WorkspaceNotFound(workspace_id=workspace_id))
                    case RepositoryNotFound(workspace_user_id):
                        return Failure(NotFound(workspace_user_id=workspace_user_id))
                    case WorkspaceUserOutsideWorkspace(workspace_user_id):
                        return Failure(
                            NotMemberOfWorkspace(workspace_user_id=workspace_user_id)
                        )
                    case _:
                        assert_never(error)
            case _:
                assert_never(result)
