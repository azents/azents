"""Completed database operations for WorkspaceUser management."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.owner_lifecycle import OwnerLifecycleRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import (
    NotFound,
    UserNotFound,
    WorkspaceNotFound,
    WorkspaceUser,
    WorkspaceUserAlreadyExists,
    WorkspaceUserCreate,
    WorkspaceUserList,
    WorkspaceUserUpdate,
)


@dataclasses.dataclass(frozen=True)
class WorkspaceUserOwnerAlreadyExists:
    """Workspace already has an Owner."""

    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceUserOwnerLocked:
    """Workspace Owner cannot be modified by a membership operation."""


@dataclasses.dataclass(frozen=True)
class WorkspaceUserOutsideWorkspace:
    """Target membership does not belong to the selected Workspace."""

    workspace_user_id: str


@dataclasses.dataclass(frozen=True)
class DeletedWorkspaceUser:
    """Committed membership deletion that requires authority invalidation."""

    user_id: str


@dataclasses.dataclass(frozen=True)
class WorkspaceOwnershipTransfer:
    """Committed ownership transfer and affected User identities."""

    owner: WorkspaceUser
    previous_owner_user_id: str | None
    changed: bool


@dataclasses.dataclass
class WorkspaceUserOperationRepository:
    """Own complete WorkspaceUser management transaction lifetimes."""

    user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    owner_lifecycle_repository: Annotated[
        OwnerLifecycleRepository, Depends(OwnerLifecycleRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create_by_handle(
        self,
        *,
        workspace_handle: str,
        user_id: str,
        name: str,
        role: WorkspaceUserRole,
    ) -> Result[
        WorkspaceUser,
        (
            WorkspaceNotFound
            | UserNotFound
            | WorkspaceUserAlreadyExists
            | WorkspaceUserOwnerAlreadyExists
        ),
    ]:
        """Create one membership in a completed transaction."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(workspace_id=workspace_handle))
            if role == WorkspaceUserRole.OWNER:
                locked_workspace = await self.workspace_repository.get_by_id_for_update(
                    session, workspace_id
                )
                if locked_workspace is None:
                    return Failure(WorkspaceNotFound(workspace_id=workspace_id))
                current_owner = await self.user_repository.get_owner_by_workspace(
                    session, workspace_id
                )
                if current_owner is not None:
                    return Failure(
                        WorkspaceUserOwnerAlreadyExists(
                            workspace_user_id=current_owner.id
                        )
                    )
            result = await self.user_repository.create_with_conflict(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    name=name,
                    role=role,
                ),
            )
            match result:
                case Success(value):
                    return Success(value)
                case Failure(error):
                    match error:
                        case WorkspaceNotFound():
                            return Failure(error)
                        case UserNotFound():
                            return Failure(error)
                        case WorkspaceUserAlreadyExists():
                            return Failure(error)
                        case _:
                            assert_never(error)
                case _:
                    assert_never(result)

    async def get(self, *, workspace_user_id: str) -> WorkspaceUser | None:
        """Fetch one membership in a completed read operation."""
        async with self.session_manager() as session:
            return await self.user_repository.get(session, workspace_user_id)

    async def list_by_workspace_handle(
        self, *, workspace_handle: str
    ) -> WorkspaceUserList:
        """List memberships by Workspace handle in a completed read operation."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return WorkspaceUserList(items=[])
            return await self.user_repository.list_by_workspace(session, workspace_id)

    async def update(
        self,
        *,
        workspace_user_id: str,
        update: WorkspaceUserUpdate,
    ) -> Result[WorkspaceUser, NotFound]:
        """Update one membership in a completed transaction."""
        async with self.session_manager() as session:
            return await self.user_repository.update(session, workspace_user_id, update)

    async def update_non_owner_role(
        self,
        *,
        workspace_user_id: str,
        role: WorkspaceUserRole,
    ) -> Result[WorkspaceUser, NotFound | WorkspaceUserOwnerLocked]:
        """Update a non-Owner membership while holding the Workspace lock."""
        async with self.session_manager() as session:
            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))

            locked_workspace = await self.workspace_repository.get_by_id_for_update(
                session, target.workspace_id
            )
            if locked_workspace is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))

            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            if target.role == WorkspaceUserRole.OWNER:
                return Failure(WorkspaceUserOwnerLocked())

            result = await self.user_repository.update_role(
                session, workspace_user_id, role
            )
            match result:
                case Success(value):
                    return Success(value)
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(result)

    async def delete_non_owner(
        self, *, workspace_user_id: str
    ) -> Result[DeletedWorkspaceUser, NotFound | WorkspaceUserOwnerLocked]:
        """Delete a non-Owner membership and archive its lifecycle atomically."""
        async with self.session_manager() as session:
            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))

            locked_workspace = await self.workspace_repository.get_by_id_for_update(
                session, target.workspace_id
            )
            if locked_workspace is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))

            target = await self.user_repository.get(session, workspace_user_id)
            if target is None:
                return Failure(NotFound(workspace_user_id=workspace_user_id))
            if target.role == WorkspaceUserRole.OWNER:
                return Failure(WorkspaceUserOwnerLocked())

            await self.user_repository.delete(session, workspace_user_id)
            await self.owner_lifecycle_repository.create_or_get_membership_archive(
                session,
                workspace_id=target.workspace_id,
                user_id=target.user_id,
            )
            return Success(DeletedWorkspaceUser(user_id=target.user_id))

    async def transfer_ownership(
        self,
        *,
        workspace_id: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceOwnershipTransfer,
        WorkspaceNotFound | NotFound | WorkspaceUserOutsideWorkspace,
    ]:
        """Transfer Workspace ownership in one completed transaction."""
        async with self.session_manager() as session:
            return await self._transfer_ownership(
                session,
                workspace_id=workspace_id,
                new_owner_workspace_user_id=new_owner_workspace_user_id,
            )

    async def transfer_ownership_by_handle(
        self,
        *,
        workspace_handle: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceOwnershipTransfer,
        WorkspaceNotFound | NotFound | WorkspaceUserOutsideWorkspace,
    ]:
        """Resolve a Workspace handle and transfer ownership atomically."""
        async with self.session_manager() as session:
            workspace_id = await self.workspace_repository.resolve_id(
                session, workspace_handle
            )
            if workspace_id is None:
                return Failure(WorkspaceNotFound(workspace_id=workspace_handle))
            return await self._transfer_ownership(
                session,
                workspace_id=workspace_id,
                new_owner_workspace_user_id=new_owner_workspace_user_id,
            )

    async def _transfer_ownership(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        new_owner_workspace_user_id: str,
    ) -> Result[
        WorkspaceOwnershipTransfer,
        WorkspaceNotFound | NotFound | WorkspaceUserOutsideWorkspace,
    ]:
        """Transfer ownership inside the caller-owned repository transaction."""
        locked_workspace = await self.workspace_repository.get_by_id_for_update(
            session, workspace_id
        )
        if locked_workspace is None:
            return Failure(WorkspaceNotFound(workspace_id=workspace_id))

        new_owner = await self.user_repository.get_for_update(
            session, new_owner_workspace_user_id
        )
        if new_owner is None:
            return Failure(NotFound(workspace_user_id=new_owner_workspace_user_id))
        if new_owner.workspace_id != workspace_id:
            return Failure(
                WorkspaceUserOutsideWorkspace(
                    workspace_user_id=new_owner_workspace_user_id
                )
            )

        current_owner = await self.user_repository.get_owner_by_workspace_for_update(
            session, workspace_id
        )
        if (
            current_owner is not None
            and current_owner.id == new_owner_workspace_user_id
        ):
            return Success(
                WorkspaceOwnershipTransfer(
                    owner=current_owner,
                    previous_owner_user_id=None,
                    changed=False,
                )
            )

        if current_owner is not None:
            demotion_result = await self.user_repository.update_role(
                session, current_owner.id, WorkspaceUserRole.MANAGER
            )
            match demotion_result:
                case Success():
                    pass
                case Failure(error):
                    await session.rollback()
                    return Failure(error)
                case _:
                    assert_never(demotion_result)

        promotion_result = await self.user_repository.update_role(
            session, new_owner_workspace_user_id, WorkspaceUserRole.OWNER
        )
        match promotion_result:
            case Success(owner):
                return Success(
                    WorkspaceOwnershipTransfer(
                        owner=owner,
                        previous_owner_user_id=(
                            None if current_owner is None else current_owner.user_id
                        ),
                        changed=True,
                    )
                )
            case Failure(error):
                await session.rollback()
                return Failure(error)
            case _:
                assert_never(promotion_result)
