"""Completed database operations for ModelFile metadata."""

import dataclasses
import datetime
from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.file_metadata_authority import (
    FileMetadataAuthorityRepository,
    FileResourceAuthority,
)
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.repos.workspace_user import WorkspaceUserRepository


class ModelFileMetadataFailure(StrEnum):
    """ModelFile metadata operation failure."""

    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"


@dataclasses.dataclass
class ModelFileOperationRepository:
    """Own complete ModelFile metadata transaction lifetimes."""

    model_file_repository: Annotated[ModelFileRepository, Depends(ModelFileRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    @property
    def authority_repository(self) -> FileMetadataAuthorityRepository:
        """Build the shared database-only authority validator."""
        return FileMetadataAuthorityRepository(
            agent_session_repository=self.agent_session_repository,
            agent_run_repository=self.agent_run_repository,
        )

    async def validate_authority(self, authority: FileResourceAuthority) -> bool:
        """Validate authority in one completed read operation."""
        async with self.session_manager() as session:
            return await self.authority_repository.validate(
                session, authority, lock=False
            )

    async def validate_authority_in_session(
        self,
        session: AsyncSession,
        authority: FileResourceAuthority,
        *,
        lock: bool,
    ) -> bool:
        """Validate authority inside an explicitly caller-owned transaction."""
        return await self.authority_repository.validate(session, authority, lock=lock)

    async def create_for_authority(
        self,
        *,
        authority: FileResourceAuthority,
        create: ModelFileCreate,
    ) -> Result[ModelFile, ModelFileMetadataFailure]:
        """Revalidate locked authority and atomically create ModelFile metadata."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=True
            ):
                return Failure(ModelFileMetadataFailure.ACCESS_DENIED)
            return Success(await self.model_file_repository.create(session, create))

    async def mark_deleted_if_unpinned(
        self,
        *,
        model_file_ids: Sequence[str],
        deleted_at: datetime.datetime,
    ) -> int:
        """Mark unpinned ModelFiles deleted in one completed operation."""
        async with self.session_manager() as session:
            deleted = await self.model_file_repository.mark_deleted_if_unpinned(
                session,
                model_file_ids=model_file_ids,
                deleted_at=deleted_at,
            )
            return len(deleted)

    async def load_for_authority(
        self,
        *,
        authority: FileResourceAuthority,
        model_file_id: str,
    ) -> Result[ModelFile, ModelFileMetadataFailure]:
        """Authorize and load same-session ModelFile metadata."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=False
            ):
                return Failure(ModelFileMetadataFailure.ACCESS_DENIED)
            model_file = await self.model_file_repository.get_by_id_for_agent(
                session,
                model_file_id=model_file_id,
                agent_id=authority.agent_id,
            )
            if (
                model_file is None
                or model_file.workspace_id != authority.workspace_id
                or model_file.session_id != authority.session_id
            ):
                return Failure(ModelFileMetadataFailure.NOT_FOUND)
            if model_file.created_run_id is not None:
                created_run = await self.agent_run_repository.get_by_id(
                    session, model_file.created_run_id
                )
                if (
                    created_run is None
                    or created_run.session_id != model_file.session_id
                    or created_run.run_index != model_file.created_run_index
                ):
                    return Failure(ModelFileMetadataFailure.NOT_FOUND)
            return Success(model_file)

    async def load_for_user(
        self,
        *,
        model_file_id: str,
        user_id: str,
    ) -> Result[ModelFile, ModelFileMetadataFailure]:
        """Authorize current Workspace membership and load ModelFile metadata."""
        async with self.session_manager() as session:
            model_file = await self.model_file_repository.get_by_id(
                session, model_file_id
            )
            return await self._authorize_user(
                session, model_file=model_file, user_id=user_id
            )

    async def load_for_agent_user(
        self,
        *,
        model_file_id: str,
        agent_id: str,
        user_id: str,
    ) -> Result[ModelFile, ModelFileMetadataFailure]:
        """Authorize current membership in one Agent namespace."""
        async with self.session_manager() as session:
            model_file = await self.model_file_repository.get_by_id_for_agent(
                session,
                model_file_id=model_file_id,
                agent_id=agent_id,
            )
            return await self._authorize_user(
                session, model_file=model_file, user_id=user_id
            )

    async def _authorize_user(
        self,
        session: AsyncSession,
        *,
        model_file: ModelFile | None,
        user_id: str,
    ) -> Result[ModelFile, ModelFileMetadataFailure]:
        """Apply current Workspace membership to one ModelFile."""
        if model_file is None:
            return Failure(ModelFileMetadataFailure.NOT_FOUND)
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=model_file.workspace_id,
            user_id=user_id,
        )
        if workspace_user is None:
            return Failure(ModelFileMetadataFailure.ACCESS_DENIED)
        return Success(model_file)
