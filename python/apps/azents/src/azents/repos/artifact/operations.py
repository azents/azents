"""Completed database operations for Artifact metadata."""

import dataclasses
from enum import StrEnum
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.artifact import ArtifactRepository
from azents.repos.artifact.data import Artifact, ArtifactCreate
from azents.repos.file_metadata_authority import (
    FileMetadataAuthorityRepository,
    FileResourceAuthority,
)
from azents.repos.workspace_user import WorkspaceUserRepository


class ArtifactMetadataFailure(StrEnum):
    """Artifact metadata operation failure."""

    SESSION_NOT_FOUND = "session_not_found"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"


@dataclasses.dataclass(frozen=True)
class ArtifactCreateScope:
    """Authorized pre-upload Artifact identity."""

    workspace_id: str
    agent_id: str


@dataclasses.dataclass
class ArtifactOperationRepository:
    """Own complete Artifact metadata transaction lifetimes."""

    artifact_repository: Annotated[ArtifactRepository, Depends(ArtifactRepository)]
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

    async def authorize_user_create(
        self,
        *,
        session_id: str,
        user_id: str,
    ) -> Result[ArtifactCreateScope, ArtifactMetadataFailure]:
        """Authorize an Artifact upload and return detached scope."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None:
                return Failure(ArtifactMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session,
                workspace_id=agent_session.workspace_id,
                user_id=user_id,
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            return Success(
                ArtifactCreateScope(
                    workspace_id=agent_session.workspace_id,
                    agent_id=agent_session.agent_id,
                )
            )

    async def create_for_user(
        self,
        *,
        session_id: str,
        user_id: str,
        expected_scope: ArtifactCreateScope,
        create: ArtifactCreate,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Revalidate user authority and atomically create Artifact metadata."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.workspace_id != expected_scope.workspace_id
                or agent_session.agent_id != expected_scope.agent_id
            ):
                return Failure(ArtifactMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session,
                workspace_id=expected_scope.workspace_id,
                user_id=user_id,
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            return Success(await self.artifact_repository.create(session, create))

    async def validate_authority(self, authority: FileResourceAuthority) -> bool:
        """Validate authority in one completed read operation."""
        async with self.session_manager() as session:
            return await self.authority_repository.validate(
                session, authority, lock=False
            )

    async def create_for_authority(
        self,
        *,
        authority: FileResourceAuthority,
        create: ArtifactCreate,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Revalidate locked authority and atomically create Artifact metadata."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=True
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            return Success(await self.artifact_repository.create(session, create))

    async def load_verified_publication(
        self,
        *,
        authority: FileResourceAuthority,
        artifact_id: str,
    ) -> Result[Artifact | None, ArtifactMetadataFailure]:
        """Validate authority and load a stable publication identity."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=False
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            return Success(
                await self.artifact_repository.get_by_id(session, artifact_id)
            )

    async def finalize_verified_publication(
        self,
        *,
        authority: FileResourceAuthority,
        create: ArtifactCreate,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Revalidate locked authority and create or return publication metadata."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=True
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            existing = await self.artifact_repository.get_by_id(session, create.id)
            if existing is not None:
                return Success(existing)
            return Success(await self.artifact_repository.create(session, create))

    async def load_for_authority(
        self,
        *,
        authority: FileResourceAuthority,
        storage_key: str,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Authorize and load Artifact metadata with exact creator lineage."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=False
            ):
                return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
            artifact = await self.artifact_repository.get_by_storage_key(
                session, storage_key
            )
            if (
                artifact is None
                or artifact.workspace_id != authority.workspace_id
                or artifact.agent_id != authority.agent_id
                or artifact.session_id != authority.session_id
            ):
                return Failure(ArtifactMetadataFailure.NOT_FOUND)
            created_run = await self.agent_run_repository.get_by_id(
                session, artifact.created_run_id
            )
            if (
                created_run is None
                or created_run.session_id != artifact.session_id
                or created_run.run_index != artifact.created_run_index
            ):
                return Failure(ArtifactMetadataFailure.NOT_FOUND)
            return Success(artifact)

    async def load_for_user_by_id(
        self,
        *,
        artifact_id: str,
        user_id: str,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Authorize a user and load Artifact metadata by ID."""
        async with self.session_manager() as session:
            artifact = await self.artifact_repository.get_by_id(session, artifact_id)
            return await self._authorize_user_artifact(
                session, artifact=artifact, user_id=user_id
            )

    async def load_for_user_by_storage_key(
        self,
        *,
        storage_key: str,
        user_id: str,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Authorize a user and load Artifact metadata by storage key."""
        async with self.session_manager() as session:
            artifact = await self.artifact_repository.get_by_storage_key(
                session, storage_key
            )
            return await self._authorize_user_artifact(
                session, artifact=artifact, user_id=user_id
            )

    async def _authorize_user_artifact(
        self,
        session: AsyncSession,
        *,
        artifact: Artifact | None,
        user_id: str,
    ) -> Result[Artifact, ArtifactMetadataFailure]:
        """Apply current Workspace membership to one Artifact."""
        if artifact is None:
            return Failure(ArtifactMetadataFailure.NOT_FOUND)
        if not await self._has_workspace_access(
            session,
            workspace_id=artifact.workspace_id,
            user_id=user_id,
        ):
            return Failure(ArtifactMetadataFailure.ACCESS_DENIED)
        return Success(artifact)

    async def _has_workspace_access(
        self,
        session: AsyncSession,
        *,
        workspace_id: str,
        user_id: str,
    ) -> bool:
        """Return whether the user remains a Workspace member."""
        workspace_user = await self.workspace_user_repository.get_by_workspace_and_user(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return workspace_user is not None
