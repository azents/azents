"""Completed Workspace database operations and atomic initial ownership."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import WorkspaceUserRole
from azents.core.workspace import (
    CreateWithOwnerInput,
    HandleConflict,
    NotFound,
    WorkspaceCreate,
    WorkspaceUpdate,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import Workspace, WorkspaceList
from azents.repos.workspace.operation_data import WorkspaceOwnerCreation
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate


@dataclasses.dataclass
class WorkspaceOperationRepository:
    """Own complete Workspace CRUD and membership projection transactions."""

    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    workspace_repository: Annotated[WorkspaceRepository, Depends(WorkspaceRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]

    async def create(
        self, create: WorkspaceCreate
    ) -> Result[Workspace, HandleConflict]:
        """Create only a Workspace, preserving the Admin creation contract."""
        async with self.session_manager() as session:
            return await self.workspace_repository.create(session, create)

    async def get_by_handle(self, handle: str) -> Workspace | None:
        """Return existing public metadata without changing membership policy."""
        async with self.session_manager() as session:
            return await self.workspace_repository.get_by_handle(session, handle)

    async def list_all(self) -> WorkspaceList:
        """Return Workspaces in their existing repository order."""
        async with self.session_manager() as session:
            return await self.workspace_repository.list_all(session)

    async def update_by_handle(
        self, handle: str, update: WorkspaceUpdate
    ) -> Result[Workspace, NotFound | HandleConflict]:
        """Preserve omitted fields and typed conflicts in one completed update."""
        async with self.session_manager() as session:
            return await self.workspace_repository.update_by_handle(
                session, handle, update
            )

    async def create_with_owner(
        self, input: CreateWithOwnerInput
    ) -> Result[WorkspaceOwnerCreation, HandleConflict]:
        """Create a Workspace, resolve its ID and insert its Owner atomically."""
        async with self.session_manager() as session:
            result = await self.workspace_repository.create(
                session,
                WorkspaceCreate(
                    name=input.workspace_name, handle=input.workspace_handle
                ),
            )
            match result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(result)
            workspace_id = await self.workspace_repository.resolve_id(
                session, input.workspace_handle
            )
            assert workspace_id is not None
            await self.workspace_user_repository.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=input.user_id,
                    name=input.owner_name,
                    role=WorkspaceUserRole.OWNER,
                ),
            )
        return Success(WorkspaceOwnerCreation(workspace_handle=input.workspace_handle))

    async def list_by_user(self, user_id: str) -> WorkspaceList:
        """Keep membership order and omit missing Workspace projections."""
        async with self.session_manager() as session:
            memberships = await self.workspace_user_repository.list_by_user(
                session, user_id
            )
            items: list[Workspace] = []
            for membership in memberships.items:
                workspace = await self.workspace_repository.get_by_id(
                    session, membership.workspace_id
                )
                if workspace is not None:
                    items.append(workspace)
            return WorkspaceList(items=items)
