"""Workspace service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.workspace import CreateWithOwnerInput, HandleConflict, NotFound
from azents.repos.workspace.operations import WorkspaceOperationRepository

from .data import (
    CreateWithOwnerOutput,
    WorkspaceCreateInput,
    WorkspaceListOutput,
    WorkspaceOutput,
    WorkspaceUpdateInput,
)


@dataclasses.dataclass
class WorkspaceService:
    """Workspace CRUD service."""

    repository: Annotated[
        WorkspaceOperationRepository, Depends(WorkspaceOperationRepository)
    ]

    async def create(
        self, create: WorkspaceCreateInput
    ) -> Result[WorkspaceOutput, HandleConflict]:
        """Create Workspace.

        :param create: Create data
        :return: Created Workspace or duplicate handle error
        """
        result = await self.repository.create(create)

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
        workspace = await self.repository.get_by_handle(handle)
        if workspace is None:
            return None
        return WorkspaceOutput.convert_from(workspace)

    async def list_all(self) -> WorkspaceListOutput:
        """Fetch all Workspaces.

        :return: Workspace list
        """
        workspaces = await self.repository.list_all()
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
        result = await self.repository.update_by_handle(handle, update)

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
        result = await self.repository.create_with_owner(input)
        match result:
            case Success(value):
                return Success(
                    CreateWithOwnerOutput(workspace_handle=value.workspace_handle)
                )
            case Failure(error):
                return Failure(error)
            case _:
                assert_never(result)

    async def list_by_user(self, user_id: str) -> WorkspaceListOutput:
        """Fetch Workspace list user belongs to.

        :param user_id: User ID
        :return: Workspace list
        """
        workspaces = await self.repository.list_by_user(user_id)
        return WorkspaceListOutput(
            items=[WorkspaceOutput.convert_from(w) for w in workspaces.items]
        )
