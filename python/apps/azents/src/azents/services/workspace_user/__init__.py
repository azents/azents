"""WorkspaceUser service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import (
    NotFound,
    WorkspaceNotFound,
    WorkspaceUserCreate,
)

from .data import (
    CannotModifyOwner,
    CannotModifySelf,
    InvalidRole,
    NotMemberOfWorkspace,
    WorkspaceUserCreateInput,
    WorkspaceUserListOutput,
    WorkspaceUserOutput,
    WorkspaceUserUpdateInput,
)


@dataclasses.dataclass
class WorkspaceUserService:
    """WorkspaceUser CRUD service."""

    user_repository: Annotated[WorkspaceUserRepository, Depends()]
    workspace_repository: Annotated[WorkspaceRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self, create: WorkspaceUserCreateInput
    ) -> Result[WorkspaceUserOutput, WorkspaceNotFound]:
        """Create WorkspaceUser.

        :param create: Create data
        :return: Created WorkspaceUser or error
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(
                session, create.workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(workspace_id=create.workspace_handle))
            result = await self.user_repository.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=create.user_id,
                    name=create.name,
                    role=create.role,
                ),
            )

        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def get(self, workspace_user_id: str) -> WorkspaceUserOutput | None:
        """Fetch WorkspaceUser by ID.

        :param workspace_user_id: WorkspaceUser ID
        :return: WorkspaceUser or None
        """
        async with self.session_manager() as session:
            workspace_user = await self.user_repository.get(session, workspace_user_id)
        if workspace_user is None:
            return None
        return WorkspaceUserOutput.convert_from(workspace_user)

    async def list_by_workspace(self, handle: str) -> WorkspaceUserListOutput:
        """Fetch WorkspaceUsers in Workspace.

        :param handle: Workspace handle
        :return: WorkspaceUser list
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(session, handle)
            if workspace_id is None:
                return WorkspaceUserListOutput(items=[])
            workspace_users = await self.user_repository.list_by_workspace(
                session, workspace_id
            )
        return WorkspaceUserListOutput(
            items=[WorkspaceUserOutput.convert_from(u) for u in workspace_users.items]
        )

    async def update(
        self, workspace_user_id: str, update: WorkspaceUserUpdateInput
    ) -> Result[WorkspaceUserOutput, NotFound]:
        """Update WorkspaceUser.

        :param workspace_user_id: WorkspaceUser ID
        :param update: Update data
        :return: Updated WorkspaceUser or error
        """
        async with self.session_manager() as session:
            result = await self.user_repository.update(
                session, workspace_user_id, update
            )

        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
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
        """Change role of WorkspaceUser.

        :param actor_workspace_user_id: WorkspaceUser ID performing change
        :param workspace_user_id: Target WorkspaceUser ID
        :param role: Role to change
        :return: Updated WorkspaceUser or error
        """
        # Cannot change own role
        if actor_workspace_user_id == workspace_user_id:
            return Failure(CannotModifySelf())

        # Cannot change to Owner role
        if role == WorkspaceUserRole.OWNER:
            return Failure(InvalidRole())

        async with self.session_manager() as session:
            # Fetch target user and check Owner status
            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            if target.role == WorkspaceUserRole.OWNER:
                return Failure(CannotModifyOwner())

            result = await self.user_repository.update_role(
                session, workspace_user_id, role
            )

        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def delete(
        self,
        actor_workspace_user_id: str,
        workspace_user_id: str,
    ) -> Result[None, CannotModifySelf | CannotModifyOwner | NotFound]:
        """Delete WorkspaceUser.

        :param actor_workspace_user_id: WorkspaceUser ID performing deletion
        :param workspace_user_id: Target WorkspaceUser ID
        :return: Success or error
        """
        # Cannot delete self
        if actor_workspace_user_id == workspace_user_id:
            return Failure(CannotModifySelf())

        async with self.session_manager() as session:
            # Fetch target user and check Owner status
            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            if target.role == WorkspaceUserRole.OWNER:
                return Failure(CannotModifyOwner())

            await self.user_repository.delete(session, workspace_user_id)
        return Success(None)

    async def delete_force(
        self, workspace_user_id: str
    ) -> Result[None, NotFound | CannotModifyOwner]:
        """Force delete WorkspaceUser (Admin only).

        Blocks only Owner deletion without self-deletion validation.

        :param workspace_user_id: Target WorkspaceUser ID
        :return: Success or error
        """
        async with self.session_manager() as session:
            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            if target.role == WorkspaceUserRole.OWNER:
                return Failure(CannotModifyOwner())

            await self.user_repository.delete(session, workspace_user_id)
        return Success(None)

    async def transfer_ownership(
        self,
        workspace_id: str,
        new_owner_workspace_user_id: str,
    ) -> Result[WorkspaceUserOutput, NotFound | NotMemberOfWorkspace]:
        """Change workspace Owner.

        Change existing Owner to Manager and new Owner to Owner.

        :param workspace_id: Workspace ID
        :param new_owner_workspace_user_id: WorkspaceUser ID of new Owner
        :return: New Owner WorkspaceUser or error
        """
        async with self.session_manager() as session:
            # Fetch new Owner
            new_owner = await self.user_repository.get(
                session, new_owner_workspace_user_id
            )
            if new_owner is None:
                return Failure(NotFound(workspace_user_id=new_owner_workspace_user_id))

            # Check whether same workspace member
            if new_owner.workspace_id != workspace_id:
                return Failure(
                    NotMemberOfWorkspace(workspace_user_id=new_owner_workspace_user_id)
                )

            # Fetch current Owner and change to Manager
            current_owner = await self.user_repository.get_owner_by_workspace(
                session, workspace_id
            )
            if current_owner is not None:
                await self.user_repository.update_role(
                    session, current_owner.id, WorkspaceUserRole.MANAGER
                )

            # Change to new Owner
            result = await self.user_repository.update_role(
                session, new_owner_workspace_user_id, WorkspaceUserRole.OWNER
            )

        match result:
            case Success(value):
                return Success(WorkspaceUserOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def transfer_ownership_by_handle(
        self,
        handle: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceUserOutput, WorkspaceNotFound | NotFound | NotMemberOfWorkspace
    ]:
        """Fetch workspace by handle, then change Owner.

        :param handle: Workspace handle
        :param new_owner_workspace_user_id: WorkspaceUser ID of new Owner
        :return: New Owner WorkspaceUser or error
        """
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(session, handle)
        if workspace_id is None:
            return Failure(WorkspaceNotFound(workspace_id=handle))

        result = await self.transfer_ownership(
            workspace_id, new_owner_workspace_user_id
        )
        match result:
            case Success(value):
                return Success(value)
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)
