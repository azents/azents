"""Completed database operations for ExchangeFile metadata."""

import dataclasses
import datetime
import logging
from enum import StrEnum
from typing import Annotated

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.core.exchange_upload import ExchangeUploadError, ExchangeUploadState
from azents.rdb.deps import get_session_manager
from azents.rdb.models.exchange_upload_operation import RDBExchangeUploadOperation
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.exchange_file import ExchangeFileRepository
from azents.repos.exchange_file.data import ExchangeFile, ExchangeFileCreate
from azents.repos.exchange_file.upload_data import ExchangeUploadOperation
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

    async def prepare_agent_upload_operation(
        self,
        *,
        agent_id: str,
        user_id: str,
        filename: str,
        media_type: str,
        expected_size: int,
        expected_sha256: str,
        now: datetime.datetime,
        expires_at: datetime.datetime,
        cleanup_after: datetime.datetime,
    ) -> Result[ExchangeUploadOperation, ExchangeUploadError]:
        """Authorize and reserve the exact manifest before a PUT is signed."""
        async with self.session_manager() as session:
            authorized = await self._authorize_agent_upload(
                session, agent_id=agent_id, user_id=user_id, workspace_id=None
            )
            if isinstance(authorized, Failure):
                return authorized
            try:
                operation = ExchangeUploadOperation(
                    upload_id=uuid7().hex,
                    publication_id=uuid7().hex,
                    preview_file_id=uuid7().hex,
                    workspace_id=authorized.value,
                    agent_id=agent_id,
                    uploader_user_id=user_id,
                    filename=filename,
                    media_type=media_type,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    created_at=now,
                    expires_at=expires_at,
                    cleanup_after=cleanup_after,
                    state=ExchangeUploadState.PENDING,
                    finalize_claim_id=None,
                    finalize_lease_until=None,
                    finalized_at=None,
                    cleanup_claim_id=None,
                    cleanup_lease_until=None,
                    cleanup_completed_at=None,
                )
            except ValueError:
                return Failure(ExchangeUploadError.INVALID_REQUEST)
            session.add(
                RDBExchangeUploadOperation(
                    id=operation.upload_id,
                    publication_id=operation.publication_id,
                    preview_file_id=operation.preview_file_id,
                    workspace_id=operation.workspace_id,
                    agent_id=operation.agent_id,
                    uploader_user_id=operation.uploader_user_id,
                    filename=operation.filename,
                    media_type=operation.media_type,
                    expected_size=operation.expected_size,
                    expected_sha256=operation.expected_sha256,
                    created_at=operation.created_at,
                    expires_at=operation.expires_at,
                    cleanup_after=operation.cleanup_after,
                    state=operation.state,
                    finalize_claim_id=None,
                    finalize_lease_until=None,
                    finalized_at=None,
                    cleanup_claim_id=None,
                    cleanup_lease_until=None,
                    cleanup_completed_at=None,
                )
            )
            await session.flush()
            return Success(operation)

    async def claim_agent_upload_operation(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        claim_id: str,
        now: datetime.datetime,
        lease_until: datetime.datetime,
    ) -> Result[ExchangeUploadOperation, ExchangeUploadError]:
        """Claim an authorized live attempt or recover its finalized identity."""
        if not _valid_upload_claim(claim_id, now, lease_until):
            return Failure(ExchangeUploadError.INVALID_REQUEST)
        async with self.session_manager() as session:
            row = await self._lock_upload(session, upload_id)
            authorized = await self._authorize_upload_row(
                session, row=row, agent_id=agent_id, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return authorized
            assert row is not None
            if row.state is ExchangeUploadState.FINALIZED:
                publication = await self._load_upload_publication(session, row, now)
                if isinstance(publication, Failure):
                    return publication
                return Success(_upload_operation(row))
            if row.expires_at <= now:
                return Failure(ExchangeUploadError.EXPIRED)
            if row.cleanup_completed_at is not None or row.cleanup_claim_id is not None:
                return Failure(ExchangeUploadError.FENCED)
            if (
                row.finalize_claim_id is not None
                and row.finalize_claim_id != claim_id
                and row.finalize_lease_until is not None
                and row.finalize_lease_until > now
            ):
                return Failure(ExchangeUploadError.BUSY)
            row.finalize_claim_id = claim_id
            row.finalize_lease_until = min(lease_until, row.expires_at)
            await session.flush()
            return Success(_upload_operation(row))

    async def load_agent_upload_publication(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        now: datetime.datetime,
    ) -> Result[ExchangeFile, ExchangeUploadError]:
        """Reauthorize a finalized retry without reading or rewriting S3 bytes."""
        if now.tzinfo is None or now.utcoffset() is None:
            return Failure(ExchangeUploadError.INVALID_REQUEST)
        async with self.session_manager() as session:
            row = await self._lock_upload(session, upload_id)
            authorized = await self._authorize_upload_row(
                session, row=row, agent_id=agent_id, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return authorized
            assert row is not None
            if row.state is not ExchangeUploadState.FINALIZED:
                return Failure(ExchangeUploadError.NOT_FOUND)
            return await self._load_upload_publication(session, row, now)

    async def release_agent_upload_claim(
        self, *, upload_id: str, claim_id: str
    ) -> bool:
        """Release only the exact live claim after trusted preparation failure."""
        if not 1 <= len(claim_id) <= 128:
            return False
        async with self.session_manager() as session:
            row = await self._lock_upload(session, upload_id)
            now = datetime.datetime.now(datetime.UTC)
            if (
                row is None
                or row.state is not ExchangeUploadState.PENDING
                or row.finalize_claim_id != claim_id
                or row.finalize_lease_until is None
                or row.finalize_lease_until <= now
                or row.expires_at <= now
                or row.cleanup_claim_id is not None
                or row.cleanup_completed_at is not None
            ):
                return False
            row.finalize_claim_id = None
            row.finalize_lease_until = None
            await session.flush()
            return True

    async def finalize_agent_upload_operation(
        self,
        *,
        agent_id: str,
        user_id: str,
        upload_id: str,
        claim_id: str,
        now: datetime.datetime,
        batch: ExchangeFileCreateBatch,
    ) -> Result[ExchangeFile, ExchangeUploadError]:
        """Reauthorize and atomically publish the exact verified metadata family."""
        if not _valid_upload_claim(claim_id, now, now + datetime.timedelta(seconds=1)):
            return Failure(ExchangeUploadError.INVALID_REQUEST)
        async with self.session_manager() as session:
            row = await self._lock_upload(session, upload_id)
            authorized = await self._authorize_upload_row(
                session, row=row, agent_id=agent_id, user_id=user_id
            )
            if isinstance(authorized, Failure):
                return authorized
            assert row is not None
            if not _upload_batch_matches(row, batch) or batch.source.expires_at <= now:
                return Failure(ExchangeUploadError.MANIFEST_MISMATCH)
            if row.state is ExchangeUploadState.FINALIZED:
                return await self._load_upload_publication(session, row, now)
            if row.expires_at <= now:
                return Failure(ExchangeUploadError.EXPIRED)
            if (
                row.finalize_claim_id != claim_id
                or row.finalize_lease_until is None
                or row.finalize_lease_until <= now
                or row.cleanup_claim_id is not None
                or row.cleanup_completed_at is not None
            ):
                return Failure(ExchangeUploadError.FENCED)
            published = await self._persist_batch(session, batch)
            row.state = ExchangeUploadState.FINALIZED
            row.finalized_at = now
            row.finalize_claim_id = None
            row.finalize_lease_until = None
            await session.flush()
            return Success(published)

    async def claim_due_agent_upload_cleanup(
        self,
        *,
        now: datetime.datetime,
        claim_id: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> tuple[ExchangeUploadOperation, ...]:
        """Claim bounded initial or recurring cleanup after capability expiry."""
        if (
            not _valid_upload_claim(claim_id, now, lease_until)
            or not 1 <= limit <= 1000
        ):
            raise ValueError("Upload cleanup lease or page bound is invalid")
        async with self.session_manager() as session:
            rows = await session.scalars(
                sa.select(RDBExchangeUploadOperation)
                .where(
                    RDBExchangeUploadOperation.cleanup_after <= now,
                    sa.or_(
                        RDBExchangeUploadOperation.cleanup_lease_until.is_(None),
                        RDBExchangeUploadOperation.cleanup_lease_until <= now,
                    ),
                )
                .order_by(
                    RDBExchangeUploadOperation.cleanup_after,
                    RDBExchangeUploadOperation.id,
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
            operations: list[ExchangeUploadOperation] = []
            for row in rows:
                row.cleanup_claim_id = claim_id
                row.cleanup_lease_until = lease_until
                operations.append(_upload_operation(row))
            await session.flush()
            return tuple(operations)

    async def finish_agent_upload_cleanup(
        self, *, upload_id: str, claim_id: str
    ) -> bool:
        """Record exact claim completion and schedule a bounded late-PUT sweep."""
        async with self.session_manager() as session:
            row = await self._lock_upload(session, upload_id)
            if row is None or row.cleanup_claim_id != claim_id:
                return False
            completed_at = datetime.datetime.now(datetime.UTC)
            row.cleanup_completed_at = completed_at
            row.cleanup_after = completed_at + datetime.timedelta(hours=1)
            row.cleanup_claim_id = None
            row.cleanup_lease_until = None
            await session.flush()
            return True

    async def _lock_upload(
        self, session: AsyncSession, upload_id: str
    ) -> RDBExchangeUploadOperation | None:
        """Lock one exact operation without following a caller object key."""
        return await session.scalar(
            sa.select(RDBExchangeUploadOperation)
            .where(RDBExchangeUploadOperation.id == upload_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def _authorize_agent_upload(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        user_id: str,
        workspace_id: str | None,
    ) -> Result[str, ExchangeUploadError]:
        """Lock current Agent scope and the requester's current membership."""
        agent = await self.agent_repository.lock_by_id(session, agent_id)
        if agent is None:
            return Failure(ExchangeUploadError.NOT_FOUND)
        if workspace_id is not None and agent.workspace_id != workspace_id:
            return Failure(ExchangeUploadError.ACCESS_DENIED)
        membership = await self.workspace_user_repository.lock_by_workspace_and_user(
            session, workspace_id=agent.workspace_id, user_id=user_id
        )
        if membership is None:
            return Failure(ExchangeUploadError.ACCESS_DENIED)
        return Success(agent.workspace_id)

    async def _authorize_upload_row(
        self,
        session: AsyncSession,
        *,
        row: RDBExchangeUploadOperation | None,
        agent_id: str,
        user_id: str,
    ) -> Result[str, ExchangeUploadError]:
        """An operation never grants access after ownership or membership changes."""
        if row is None:
            return Failure(ExchangeUploadError.NOT_FOUND)
        if row.agent_id != agent_id or row.uploader_user_id != user_id:
            return Failure(ExchangeUploadError.ACCESS_DENIED)
        return await self._authorize_agent_upload(
            session,
            agent_id=agent_id,
            user_id=user_id,
            workspace_id=row.workspace_id,
        )

    async def _load_upload_publication(
        self,
        session: AsyncSession,
        row: RDBExchangeUploadOperation,
        now: datetime.datetime,
    ) -> Result[ExchangeFile, ExchangeUploadError]:
        """Return the exact existing verified publication, never recreate one."""
        file = await self.exchange_file_repository.get_by_id(
            session, row.publication_id
        )
        if file is None:
            return Failure(ExchangeUploadError.NOT_FOUND)
        if file.status is not ExchangeFileStatus.AVAILABLE or file.expires_at <= now:
            return Failure(ExchangeUploadError.EXPIRED)
        if (
            file.id != row.publication_id
            or file.workspace_id != row.workspace_id
            or file.agent_id != row.agent_id
            or file.filename != row.filename
            or file.media_type != row.media_type
            or file.size_bytes != row.expected_size
            or file.sha256 != row.expected_sha256
            or file.created_by_user_id != row.uploader_user_id
            or file.source_user_id != row.uploader_user_id
            or file.origin_type is not ExchangeFileOrigin.UPLOAD
            or file.provenance_kind is not ExchangeFileProvenanceKind.HUMAN
            or file.blob_deleted_at is not None
        ):
            return Failure(ExchangeUploadError.MANIFEST_MISMATCH)
        return Success(file)

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


def _valid_upload_claim(
    claim_id: str,
    now: datetime.datetime,
    lease_until: datetime.datetime,
) -> bool:
    """Validate claim shape without trusting a naive caller clock."""
    return (
        1 <= len(claim_id) <= 128
        and now.tzinfo is not None
        and now.utcoffset() is not None
        and lease_until.tzinfo is not None
        and lease_until.utcoffset() is not None
        and lease_until > now
    )


def _upload_operation(row: RDBExchangeUploadOperation) -> ExchangeUploadOperation:
    """Detach a complete manifest before closing its database transaction."""
    return ExchangeUploadOperation(
        upload_id=row.id,
        publication_id=row.publication_id,
        preview_file_id=row.preview_file_id,
        workspace_id=row.workspace_id,
        agent_id=row.agent_id,
        uploader_user_id=row.uploader_user_id,
        filename=row.filename,
        media_type=row.media_type,
        expected_size=row.expected_size,
        expected_sha256=row.expected_sha256,
        created_at=row.created_at,
        expires_at=row.expires_at,
        cleanup_after=row.cleanup_after,
        state=row.state,
        finalize_claim_id=row.finalize_claim_id,
        finalize_lease_until=row.finalize_lease_until,
        finalized_at=row.finalized_at,
        cleanup_claim_id=row.cleanup_claim_id,
        cleanup_lease_until=row.cleanup_lease_until,
        cleanup_completed_at=row.cleanup_completed_at,
    )


def _upload_batch_matches(
    row: RDBExchangeUploadOperation, batch: ExchangeFileCreateBatch
) -> bool:
    """Bind publication IDs, verified manifest, provenance, and preview scope."""
    source = batch.source
    if (
        source.id != row.publication_id
        or source.workspace_id != row.workspace_id
        or source.agent_id != row.agent_id
        or source.filename != row.filename
        or source.media_type != row.media_type
        or source.size_bytes != row.expected_size
        or source.sha256 != row.expected_sha256
        or source.created_by_user_id != row.uploader_user_id
        or source.source_user_id != row.uploader_user_id
        or source.origin_type is not ExchangeFileOrigin.UPLOAD
        or source.provenance_kind is not ExchangeFileProvenanceKind.HUMAN
        or source.source_agent_id is not None
        or source.source_run_id is not None
        or source.source_tool_name is not None
        or source.source_provider is not None
        or source.source_exchange_file_id is not None
        or source.retention_root_session_id is not None
        or source.retention_bound_at is not None
    ):
        return False
    if batch.preview is None:
        return True
    preview = batch.preview.create
    return (
        preview.id == row.preview_file_id
        and preview.workspace_id == row.workspace_id
        and preview.agent_id == row.agent_id
        and preview.created_by_user_id == row.uploader_user_id
        and preview.origin_type is ExchangeFileOrigin.UPLOAD
        and preview.provenance_kind is ExchangeFileProvenanceKind.PREVIEW
        and preview.source_exchange_file_id == row.publication_id
        and preview.source_user_id is None
        and preview.source_agent_id is None
        and preview.source_run_id is None
        and preview.source_tool_name is None
        and preview.source_provider is None
        and preview.retention_root_session_id is None
        and preview.retention_bound_at is None
        and preview.expires_at == source.expires_at
    )
