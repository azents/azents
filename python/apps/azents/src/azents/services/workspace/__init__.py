"""Workspace service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import HandleConflict, NotFound, WorkspaceCreate
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.repos.workspace_user.data import WorkspaceUserCreate, WorkspaceUserRole

from .data import (
    CreateWithOwnerInput,
    CreateWithOwnerOutput,
    WorkspaceCreateInput,
    WorkspaceListOutput,
    WorkspaceOutput,
    WorkspaceUpdateInput,
)


@dataclasses.dataclass
class WorkspaceService:
    """Workspace CRUD service."""

    workspace_repository: Annotated[WorkspaceRepository, Depends()]
    workspace_user_repository: Annotated[WorkspaceUserRepository, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def create(
        self, create: WorkspaceCreateInput
    ) -> Result[WorkspaceOutput, HandleConflict]:
        """Create Workspace.

        :param create: Create data
        :return: Created Workspace or duplicate handle error
        """
        async with self.session_manager() as session:
            result = await self.workspace_repository.create(session, create)

        match result:
            case Success(value):
                return Success(WorkspaceOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def get_by_handle(self, handle: str) -> WorkspaceOutput | None:
        """Fetch Workspace by handle.

        :param handle: Workspace handle
        :return: Workspace or None
        """
        async with self.session_manager() as session:
            workspace = await self.workspace_repository.get_by_handle(session, handle)
        if workspace is None:
            return None
        return WorkspaceOutput.convert_from(workspace)

    async def list_all(self) -> WorkspaceListOutput:
        """Fetch all Workspaces.

        :return: Workspace list
        """
        async with self.session_manager() as session:
            workspaces = await self.workspace_repository.list_all(session)
        return WorkspaceListOutput(
            items=[WorkspaceOutput.convert_from(w) for w in workspaces.items]
        )

    async def update_by_handle(
        self, handle: str, update: WorkspaceUpdateInput
    ) -> Result[WorkspaceOutput, NotFound | HandleConflict]:
        """Update Workspace by handle.

        :param handle: Workspace handle
        :param update: Update data
        :return: Updated Workspace or error
        """
        async with self.session_manager() as session:
            result = await self.workspace_repository.update_by_handle(
                session, handle, update
            )

        match result:
            case Success(value):
                return Success(WorkspaceOutput.convert_from(value))
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def create_with_owner(
        self, input: CreateWithOwnerInput
    ) -> Result[CreateWithOwnerOutput, HandleConflict]:
        """Create Workspace + Owner WorkspaceUser in single transaction.

        :param input: Create input data
        :return: Created Workspace information or duplicate handle error
        """
        async with self.session_manager() as session:
            # Create Workspace
            ws_result = await self.workspace_repository.create(
                session,
                WorkspaceCreate(
                    name=input.workspace_name,
                    handle=input.workspace_handle,
                ),
            )
            match ws_result:
                case Success():
                    pass
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(ws_result)

            # Convert handle → internal ID, then create Owner WorkspaceUser
            workspace_id = await self.workspace_repository.resolve_id(
                session, input.workspace_handle
            )
            assert workspace_id is not None  # Must exist because it was just created

            await self.workspace_user_repository.create(
                session,
                WorkspaceUserCreate(
                    workspace_id=workspace_id,
                    user_id=input.user_id,
                    name=input.owner_name,
                    role=WorkspaceUserRole.OWNER,
                ),
            )

        return Success(
            CreateWithOwnerOutput(
                workspace_handle=input.workspace_handle,
            )
        )

    async def list_by_user(self, user_id: str) -> WorkspaceListOutput:
        """Fetch Workspace list user belongs to.

        :param user_id: User ID
        :return: Workspace list
        """
        async with self.session_manager() as session:
            workspace_users = await self.workspace_user_repository.list_by_user(
                session, user_id
            )
            items: list[WorkspaceOutput] = []
            for wu in workspace_users.items:
                workspace = await self.workspace_repository.get_by_id(
                    session, wu.workspace_id
                )
                if workspace is not None:
                    items.append(WorkspaceOutput.convert_from(workspace))
        return WorkspaceListOutput(items=items)

    async def delete_by_handle(self, handle: str) -> None:
        """Delete Workspace by handle.

        :param handle: Workspace handle
        """
        async with self.session_manager() as session:
            await self.workspace_repository.delete_by_handle(session, handle)
