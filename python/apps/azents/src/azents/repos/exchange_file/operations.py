"""Completed database operations for ExchangeFile metadata."""

import dataclasses
import datetime
import logging
from enum import StrEnum
from typing import Annotated

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExchangeFileStatus
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.file_metadata_authority import (
    FileMetadataAuthorityRepository,
    FileResourceAuthority,
)
from azents.repos.workspace_user import WorkspaceUserRepository

logger = logging.getLogger(__name__)


class ExchangeFileMetadataFailure(StrEnum):
    """ExchangeFile metadata operation failure."""

    SESSION_NOT_FOUND = "session_not_found"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"


@dataclasses.dataclass(frozen=True)
class ExchangeFileCreateScope:
    """Authorized pre-upload ExchangeFile identity."""

    workspace_id: str
    agent_id: str
    retention_root_session_id: str | None


@dataclasses.dataclass(frozen=True)
class ExchangeFilePreviewCreate:
    """Preview metadata atomically persisted with its source."""

    create: ExchangeFileCreate
    width: int
    height: int
    generated_at: datetime.datetime


@dataclasses.dataclass(frozen=True)
class ExchangeFileCreateBatch:
    """Source and optional preview metadata for one atomic publication."""

    source: ExchangeFileCreate
    preview: ExchangeFilePreviewCreate | None


@dataclasses.dataclass(frozen=True)
class ExchangeFileFamily:
    """Authorized source and linked preview metadata."""

    file: ExchangeFile
    preview: ExchangeFile | None


@dataclasses.dataclass
class ExchangeFileOperationRepository:
    """Own complete ExchangeFile metadata transaction lifetimes."""

    exchange_file_repository: Annotated[
        ExchangeFileRepository, Depends(ExchangeFileRepository)
    ]
    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
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

    async def load_verified_publication(
        self,
        *,
        authority: FileResourceAuthority,
        file_id: str,
    ) -> Result[ExchangeFile | None, ExchangeFileMetadataFailure]:
        """Validate authority and load a stable publication identity."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=False
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return Success(
                await self.exchange_file_repository.get_by_id(session, file_id)
            )

    async def load_publication_for_recovery(
        self,
        *,
        file_id: str,
    ) -> ExchangeFile | None:
        """Read publication identity for post-failure object compensation."""
        async with self.session_manager() as session:
            return await self.exchange_file_repository.get_by_id(session, file_id)

    async def finalize_authority_create(
        self,
        *,
        authority: FileResourceAuthority,
        batch: ExchangeFileCreateBatch,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Revalidate locked authority and atomically persist a file family."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=True
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            existing = await self.exchange_file_repository.get_by_id(
                session, batch.source.id
            )
            if existing is not None:
                return Success(existing)
            return Success(await self._persist_batch(session, batch))

    async def load_for_authority(
        self,
        *,
        authority: FileResourceAuthority,
        object_key: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Authorize and load one ExchangeFile under a retention root."""
        async with self.session_manager() as session:
            if not await self.authority_repository.validate(
                session, authority, lock=False
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            file = await self.exchange_file_repository.get_by_object_key_for_agent(
                session,
                object_key=object_key,
                agent_id=authority.agent_id,
            )
            if file is None:
                return Failure(ExchangeFileMetadataFailure.NOT_FOUND)
            if file.retention_root_session_id != authority.root_session_id:
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return Success(file)

    async def authorize_agent_create(
        self,
        *,
        agent_id: str,
        user_id: str,
    ) -> Result[ExchangeFileCreateScope, ExchangeFileMetadataFailure]:
        """Authorize an Agent-scoped upload and return detached scope."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session, workspace_id=agent.workspace_id, user_id=user_id
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return Success(
                ExchangeFileCreateScope(
                    workspace_id=agent.workspace_id,
                    agent_id=agent_id,
                    retention_root_session_id=None,
                )
            )

    async def finalize_agent_create(
        self,
        *,
        agent_id: str,
        user_id: str,
        expected_scope: ExchangeFileCreateScope,
        batch: ExchangeFileCreateBatch,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Revalidate Agent upload authority and atomically persist metadata."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None or agent.workspace_id != expected_scope.workspace_id:
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session,
                workspace_id=expected_scope.workspace_id,
                user_id=user_id,
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return Success(await self._persist_batch(session, batch))

    async def authorize_session_create(
        self,
        *,
        session_id: str,
        user_id: str,
        expected_agent_id: str | None,
    ) -> Result[ExchangeFileCreateScope, ExchangeFileMetadataFailure]:
        """Authorize a Session-scoped upload and return detached scope."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None or (
                expected_agent_id is not None
                and agent_session.agent_id != expected_agent_id
            ):
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session,
                workspace_id=agent_session.workspace_id,
                user_id=user_id,
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            root = await (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )(session, session_id)
            if root is None:
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            return Success(
                ExchangeFileCreateScope(
                    workspace_id=agent_session.workspace_id,
                    agent_id=agent_session.agent_id,
                    retention_root_session_id=root.agent_session_id,
                )
            )

    async def finalize_session_create(
        self,
        *,
        session_id: str,
        user_id: str,
        expected_scope: ExchangeFileCreateScope,
        batch: ExchangeFileCreateBatch,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Revalidate Session/root authority and atomically persist metadata."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if (
                agent_session is None
                or agent_session.agent_id != expected_scope.agent_id
                or agent_session.workspace_id != expected_scope.workspace_id
            ):
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            if not await self._has_workspace_access(
                session,
                workspace_id=expected_scope.workspace_id,
                user_id=user_id,
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            root = await (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )(session, session_id)
            if (
                root is None
                or root.agent_session_id != expected_scope.retention_root_session_id
            ):
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            return Success(await self._persist_batch(session, batch))

    async def load_for_user_by_id(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Authorize a user and load current file metadata by ID."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            return await self._authorize_and_expire(session, file=file, user_id=user_id)

    async def load_for_user_by_object_key(
        self,
        *,
        object_key: str,
        user_id: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Authorize a user and load current file metadata by object key."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_object_key(
                session, object_key
            )
            return await self._authorize_and_expire(session, file=file, user_id=user_id)

    async def load_for_agent_user(
        self,
        *,
        object_key: str,
        agent_id: str,
        session_id: str,
        user_id: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Authorize a user inside the current Session retention root."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            root = await (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )(session, session_id)
            if root is None:
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            file = await self.exchange_file_repository.get_by_object_key_for_agent(
                session,
                object_key=object_key,
                agent_id=agent_id,
            )
            if (
                file is not None
                and file.retention_root_session_id != root.agent_session_id
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return await self._authorize_and_expire(session, file=file, user_id=user_id)

    async def load_admitted_input(
        self,
        *,
        object_key: str,
        agent_id: str,
        session_id: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Resolve metadata only when the durable root claim matches."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session, session_id
            )
            if agent_session is None:
                return Failure(ExchangeFileMetadataFailure.SESSION_NOT_FOUND)
            if agent_session.agent_id != agent_id:
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            root = await (
                self.agent_session_repository.get_root_session_agent_by_session_id
            )(session, session_id)
            if root is None:
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            file = await self.exchange_file_repository.get_by_object_key_for_agent(
                session,
                object_key=object_key,
                agent_id=agent_id,
            )
            if file is None:
                return Failure(ExchangeFileMetadataFailure.NOT_FOUND)
            if (
                file.workspace_id != agent_session.workspace_id
                or file.retention_root_session_id != root.agent_session_id
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            return Success(await self._expire_if_due(session, file))

    async def load_family_for_user(
        self,
        *,
        file_id: str,
        user_id: str,
    ) -> Result[ExchangeFileFamily, ExchangeFileMetadataFailure]:
        """Authorize and load source plus linked preview metadata."""
        async with self.session_manager() as session:
            file = await self.exchange_file_repository.get_by_id(session, file_id)
            authorized = await self._authorize_and_expire(
                session, file=file, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return Failure(authorized.error)
            file = authorized.value
            preview: ExchangeFile | None = None
            if file.preview_thumbnail_file_id is not None:
                preview = await self.exchange_file_repository.get_by_id(
                    session, file.preview_thumbnail_file_id
                )
                if preview is None:
                    logger.warning(
                        "Exchange file preview thumbnail metadata is missing",
                        extra={
                            "file_id": file.id,
                            "preview_thumbnail_file_id": (
                                file.preview_thumbnail_file_id
                            ),
                        },
                    )
            return Success(ExchangeFileFamily(file=file, preview=preview))

    async def delete_family_for_user(
        self,
        *,
        file_ids: list[str],
        workspace_id: str,
        user_id: str,
    ) -> Result[None, ExchangeFileMetadataFailure]:
        """Revalidate user authority and atomically delete exact metadata rows."""
        async with self.session_manager() as session:
            if not await self._has_workspace_access(
                session, workspace_id=workspace_id, user_id=user_id
            ):
                return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            for file_id in file_ids:
                file = await self.exchange_file_repository.get_by_id(session, file_id)
                if file is None:
                    return Failure(ExchangeFileMetadataFailure.NOT_FOUND)
                if file.workspace_id != workspace_id:
                    return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
            for file_id in file_ids:
                await self.exchange_file_repository.delete_by_id(session, file_id)
            return Success(None)

    async def _persist_batch(
        self,
        session: AsyncSession,
        batch: ExchangeFileCreateBatch,
    ) -> ExchangeFile:
        """Persist uploaded source and optional preview metadata atomically."""
        source = await self.exchange_file_repository.create(session, batch.source)
        if batch.preview is None:
            return source
        preview = await self.exchange_file_repository.create(
            session, batch.preview.create
        )
        return await self.exchange_file_repository.set_preview_thumbnail_file_id(
            session,
            file_id=source.id,
            preview_thumbnail_file_id=preview.id,
            preview_thumbnail_media_type=preview.media_type,
            preview_thumbnail_width=batch.preview.width,
            preview_thumbnail_height=batch.preview.height,
            preview_generated_at=batch.preview.generated_at,
        )

    async def _authorize_and_expire(
        self,
        session: AsyncSession,
        *,
        file: ExchangeFile | None,
        user_id: str,
    ) -> Result[ExchangeFile, ExchangeFileMetadataFailure]:
        """Apply Workspace membership and current expiration state."""
        if file is None:
            return Failure(ExchangeFileMetadataFailure.NOT_FOUND)
        if not await self._has_workspace_access(
            session, workspace_id=file.workspace_id, user_id=user_id
        ):
            return Failure(ExchangeFileMetadataFailure.ACCESS_DENIED)
        return Success(await self._expire_if_due(session, file))

    async def _expire_if_due(
        self,
        session: AsyncSession,
        file: ExchangeFile,
    ) -> ExchangeFile:
        """Transition a due file family and return current source metadata."""
        if file.status is ExchangeFileStatus.EXPIRED:
            return file
        now = datetime.datetime.now(datetime.UTC)
        if file.expires_at > now:
            return file
        expired = await self.exchange_file_repository.expire_file_family(
            session,
            file_id=file.id,
            expired_at=now,
        )
        for item in expired:
            if item.id == file.id:
                return item
        return file.model_copy(
            update={"status": ExchangeFileStatus.EXPIRED, "expired_at": now}
        )

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
