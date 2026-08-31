"""FileLifecycleCleanupService tests."""

import datetime
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ArtifactStatus,
    EventKind,
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.engine.events.types import (
    ClientToolResultPayload,
    Event,
    FileOutputPart,
)
from azents.repos.agent_avatar_cleanup.data import AgentAvatarCleanupJob
from azents.repos.agent_session import ModelFileGCLaggingSession
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile
from azents.services.file_lifecycle_cleanup import FileLifecycleCleanupService
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)

_NOW = datetime.datetime.now(datetime.UTC)


class _ArtifactRepo:
    """Artifact repository test double."""

    def __init__(self, artifacts: list[Artifact]) -> None:
        self.artifacts = artifacts
        self.marked_blob_deleted: list[str] = []

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[Artifact]:
        """Mark due Artifacts expired."""
        del session, limit
        expired: list[Artifact] = []
        for artifact in self.artifacts:
            if (
                artifact.status == ArtifactStatus.AVAILABLE
                and artifact.expires_at <= now
            ):
                updated = artifact.model_copy(
                    update={"status": ArtifactStatus.EXPIRED, "expired_at": now}
                )
                self.artifacts = [
                    updated if item.id == artifact.id else item
                    for item in self.artifacts
                ]
                expired.append(updated)
        return expired

    async def list_expired_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[Artifact]:
        """Return terminal Artifacts whose blob delete marker is absent."""
        del session
        return [
            artifact
            for artifact in self.artifacts
            if artifact.status == ArtifactStatus.EXPIRED
            and artifact.blob_deleted_at is None
        ][:limit]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        artifact_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record blob deletion success."""
        del session
        self.marked_blob_deleted.append(artifact_id)
        self.artifacts = [
            artifact.model_copy(update={"blob_deleted_at": blob_deleted_at})
            if artifact.id == artifact_id
            else artifact
            for artifact in self.artifacts
        ]


class _ExchangeRepo:
    """ExchangeFile repository test double."""

    def __init__(self, files: list[ExchangeFile]) -> None:
        self.files = files
        self.marked_blob_deleted: list[str] = []

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExchangeFile]:
        """Mark due ExchangeFiles expired."""
        del session, limit
        expired: list[ExchangeFile] = []
        for file in self.files:
            if file.status == ExchangeFileStatus.AVAILABLE and file.expires_at <= now:
                updated = file.model_copy(
                    update={"status": ExchangeFileStatus.EXPIRED, "expired_at": now}
                )
                self.files = [
                    updated if item.id == file.id else item for item in self.files
                ]
                expired.append(updated)
        return expired

    async def list_expired_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ExchangeFile]:
        """Return terminal ExchangeFiles whose blob delete marker is absent."""
        del session
        return [
            file
            for file in self.files
            if file.status == ExchangeFileStatus.EXPIRED
            and file.blob_deleted_at is None
        ][:limit]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record blob deletion success."""
        del session
        self.marked_blob_deleted.append(file_id)
        self.files = [
            file.model_copy(update={"blob_deleted_at": blob_deleted_at})
            if file.id == file_id
            else file
            for file in self.files
        ]


class _ModelFileRepo:
    """ModelFile repository test double."""

    def __init__(self, model_files: list[ModelFile]) -> None:
        self.model_files = model_files
        self.marked_blob_deleted: list[str] = []
        self.deleted_requests: list[list[str]] = []

    async def mark_deleted_if_unpinned(
        self,
        session: AsyncSession,
        *,
        model_file_ids: list[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        """Delete available unpinned rows."""
        del session
        self.deleted_requests.append(list(model_file_ids))
        deleted: list[ModelFile] = []
        updated_files: list[ModelFile] = []
        for model_file in self.model_files:
            if (
                model_file.id in model_file_ids
                and model_file.status == ModelFileStatus.AVAILABLE
            ):
                updated = model_file.model_copy(
                    update={"status": ModelFileStatus.DELETED, "deleted_at": deleted_at}
                )
                deleted.append(updated)
                updated_files.append(updated)
            else:
                updated_files.append(model_file)
        self.model_files = updated_files
        return deleted

    async def list_statuses_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        model_file_ids: list[str],
    ) -> dict[str, ModelFileStatus]:
        """Return current ModelFile status by ID."""
        del session, session_id
        return {
            model_file.id: model_file.status
            for model_file in self.model_files
            if model_file.id in model_file_ids
        }

    async def list_deleted_pending_blob_deletion(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ModelFile]:
        """Return deleted ModelFiles whose blob delete marker is absent."""
        del session
        return [
            model_file
            for model_file in self.model_files
            if model_file.status == ModelFileStatus.DELETED
            and model_file.blob_deleted_at is None
        ][:limit]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        blob_deleted_at: datetime.datetime,
    ) -> None:
        """Record blob deletion success."""
        del session
        self.marked_blob_deleted.append(model_file_id)
        self.model_files = [
            model_file.model_copy(update={"blob_deleted_at": blob_deleted_at})
            if model_file.id == model_file_id
            else model_file
            for model_file in self.model_files
        ]


class _PinnedModelFileRepo(_ModelFileRepo):
    """ModelFile repository that simulates active pins."""

    async def mark_deleted_if_unpinned(
        self,
        session: AsyncSession,
        *,
        model_file_ids: list[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        """Do not delete because all requested IDs are pinned."""
        del session, deleted_at
        self.deleted_requests.append(list(model_file_ids))
        return []


class _PinRepo:
    """ModelFile pin repository test double."""

    def __init__(self, released: int = 0) -> None:
        self.released = released

    async def release_terminal_run_pins(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> int:
        """Return configured stale pin release count."""
        del session, limit
        return self.released


class _AvatarCleanupRepo:
    """Durable superseded-avatar cleanup repository test double."""

    def __init__(self, jobs: list[AgentAvatarCleanupJob]) -> None:
        self.jobs = jobs
        self.claimed: list[tuple[datetime.datetime, str, datetime.datetime, int]] = []
        self.deleted: list[tuple[str, str]] = []
        self.retries: list[tuple[str, str, datetime.datetime, str]] = []

    async def claim_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        lease_token: str,
        lease_until: datetime.datetime,
        limit: int,
    ) -> list[AgentAvatarCleanupJob]:
        """Return the configured bounded due page."""
        del session
        self.claimed.append((now, lease_token, lease_until, limit))
        return self.jobs[:limit]

    async def delete_completed(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_token: str,
    ) -> bool:
        """Record successful cleanup row deletion."""
        del session
        self.deleted.append((job_id, lease_token))
        return True

    async def mark_retry(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        lease_token: str,
        next_attempt_at: datetime.datetime,
        failure_kind: str,
        now: datetime.datetime,
    ) -> bool:
        """Record failed cleanup retry state."""
        del session, now
        self.retries.append((job_id, lease_token, next_attempt_at, failure_kind))
        return True


class _AgentSessionRepo:
    """AgentSession repository test double."""

    def __init__(self, lagging: list[ModelFileGCLaggingSession]) -> None:
        self.lagging = lagging
        self.advanced: list[tuple[str, str]] = []

    async def list_model_file_gc_lagging(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ModelFileGCLaggingSession]:
        """Return configured lagging sessions."""
        del session, limit
        return self.lagging

    async def advance_model_file_gc_cursor(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        cursor_event_id: str,
        updated_at: datetime.datetime,
    ) -> None:
        """Record cursor advancement."""
        del session, updated_at
        self.advanced.append((session_id, cursor_event_id))


class _TranscriptRepo:
    """Transcript repository test double."""

    def __init__(self, events: list[Event]) -> None:
        self.events = events

    async def list_model_file_gc_range(
        self,
        session: AsyncSession,
        session_id: str,
        *,
        after_event_id: str | None,
        to_event_id: str,
        limit: int,
    ) -> list[Event]:
        """Return configured events inside the requested range."""
        del session, session_id, limit
        return [
            event
            for event in self.events
            if (after_event_id is None or event.id > after_event_id)
            and event.id <= to_event_id
        ]


class _S3Service:
    """S3 service test double."""

    def __init__(self) -> None:
        self.deleted_keys: list[str] = []

    async def delete(self, bucket: str, key: str) -> None:
        """Record delete call."""
        del bucket
        self.deleted_keys.append(key)


class _FailingS3Service(_S3Service):
    """S3 test double that fails every deletion."""

    async def delete(self, bucket: str, key: str) -> None:
        """Raise a deterministic storage deletion error."""
        del bucket, key
        msg = "storage deletion failed"
        raise RuntimeError(msg)


class _AvatarHandler:
    """Avatar deletion handler test double."""

    def __init__(
        self,
        *,
        failing_keys: frozenset[str] | None = None,
        failure_message: str = "avatar deletion failed",
    ) -> None:
        self.failing_keys = frozenset() if failing_keys is None else failing_keys
        self.failure_message = failure_message
        self.deleted_keys: list[str] = []

    async def delete_files(
        self,
        avatar: StoredImage,
        s3: _S3Service,
        bucket: str,
    ) -> None:
        """Record one durable-avatar deletion attempt."""
        del s3, bucket
        if avatar.default.key in self.failing_keys:
            raise RuntimeError(self.failure_message)
        self.deleted_keys.append(avatar.default.key)


class _WorkspaceS3Config:
    """Workspace S3 config for tests."""

    bucket = "test-bucket"


class _Config:
    """Config for tests."""

    workspace_s3 = _WorkspaceS3Config()


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Return fake session context."""
    yield cast(AsyncSession, object())


def _artifact() -> Artifact:
    """Create due Artifact."""
    return Artifact(
        id="a" * 32,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        created_run_id="run-1",
        created_run_index=1,
        expires_at=_NOW - datetime.timedelta(seconds=1),
        name="artifact.txt",
        media_type="text/plain",
        size_bytes=1,
        storage_key="artifacts/workspace-1/session-1/1/a",
        status=ArtifactStatus.AVAILABLE,
        sha256="1" * 64,
        created_at=_NOW,
        expired_at=None,
        blob_deleted_at=None,
    )


def _exchange_file() -> ExchangeFile:
    """Create due ExchangeFile."""
    return ExchangeFile(
        id="e" * 32,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/files/e/original",
        filename="file.txt",
        media_type="text/plain",
        size_bytes=1,
        sha256="2" * 64,
        provenance_kind=ExchangeFileProvenanceKind.HUMAN,
        source_user_id="user-1",
        source_agent_id=None,
        source_run_id=None,
        source_tool_name=None,
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id=None,
        retention_bound_at=None,
        expires_at=_NOW - datetime.timedelta(seconds=1),
        expired_at=None,
        blob_deleted_at=None,
        created_at=_NOW,
    )


def _model_file(status: ModelFileStatus = ModelFileStatus.AVAILABLE) -> ModelFile:
    """Create ModelFile."""
    return ModelFile(
        id="m" * 32,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        name="image.jpg",
        media_type="image/jpeg",
        kind="image",
        size_bytes=1,
        created_run_id="run-1",
        created_run_index=1,
        storage_key="model-files/workspace-1/session-1/m",
        status=status,
        normalized_format="jpeg",
        sha256="3" * 64,
        metadata={},
        created_at=_NOW,
        deleted_at=None,
        blob_deleted_at=None,
    )


def _file_event(model_file_id: str = "m" * 32) -> Event:
    """Create event containing one FileOutputPart."""
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.CLIENT_TOOL_RESULT,
        payload=ClientToolResultPayload(
            call_id="call-1",
            name="read_image",
            status="completed",
            output=[
                FileOutputPart(
                    model_file_id=model_file_id,
                    media_type="image/jpeg",
                    name="image.jpg",
                    size=1,
                    kind="image",
                )
            ],
            wire_dialect="json_function",
        ),
        created_at=_NOW,
    )


def _lagging_session() -> ModelFileGCLaggingSession:
    """Create lagging session state."""
    return ModelFileGCLaggingSession(
        session_id="session-1",
        head_event_id="1" * 32,
        cursor_event_id=None,
    )


def _avatar(
    key: str = "public/avatar/agent-1/large/old.webp",
) -> StoredImage:
    """Create one immutable superseded-avatar snapshot."""
    default = StoredImageFile(
        key=key,
        content_type="image/webp",
        size_bytes=1,
        width=512,
        height=512,
    )
    return StoredImage(
        filename="old.webp",
        default=default,
        thumbnails=StoredImageThumbnails(large=default),
        original=None,
        uploaded_at=_NOW,
    )


def _avatar_cleanup_job() -> AgentAvatarCleanupJob:
    """Create one due durable cleanup job."""
    return AgentAvatarCleanupJob(
        id="j" * 32,
        agent_id="agent-1",
        avatar=_avatar(),
        attempt_count=1,
        next_attempt_at=_NOW,
        lease_token=None,
        lease_until=None,
        last_failure_kind=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _avatar_cleanup_job_for(
    *,
    job_id: str,
    avatar: StoredImage,
) -> AgentAvatarCleanupJob:
    """Create one due cleanup job for an exact immutable snapshot."""
    return _avatar_cleanup_job().model_copy(
        update={
            "id": job_id,
            "avatar": avatar,
        }
    )


def _service(
    *,
    artifacts: list[Artifact] | None = None,
    exchange_files: list[ExchangeFile] | None = None,
    model_file_repo: _ModelFileRepo | None = None,
    agent_session_repo: _AgentSessionRepo | None = None,
    transcript_repo: _TranscriptRepo | None = None,
    s3_service: _S3Service | None = None,
    avatar_cleanup_repo: _AvatarCleanupRepo | None = None,
    avatar_handler: _AvatarHandler | None = None,
) -> FileLifecycleCleanupService:
    """Build service with fake dependencies."""
    return FileLifecycleCleanupService(
        session_manager=_session_manager,
        artifact_repository=cast(Any, _ArtifactRepo(artifacts or [])),
        exchange_file_repository=cast(Any, _ExchangeRepo(exchange_files or [])),
        model_file_repository=cast(Any, model_file_repo or _ModelFileRepo([])),
        model_file_pin_repository=cast(Any, _PinRepo()),
        agent_session_repository=cast(
            Any,
            agent_session_repo or _AgentSessionRepo([]),
        ),
        transcript_repository=cast(Any, transcript_repo or _TranscriptRepo([])),
        avatar_cleanup_repository=cast(
            Any,
            avatar_cleanup_repo or _AvatarCleanupRepo([]),
        ),
        avatar_handler=cast(Any, avatar_handler or _AvatarHandler()),
        s3_service=cast(Any, s3_service or _S3Service()),
        config=cast(Any, _Config()),
    )


@pytest.mark.asyncio
async def test_cleanup_once_expires_ttl_resources_and_retries_blob_deletion() -> None:
    """Cleanup expires TTL rows and records blob deletion markers separately."""
    artifact_repo = _ArtifactRepo([_artifact()])
    exchange_repo = _ExchangeRepo([_exchange_file()])
    s3 = _S3Service()
    service = FileLifecycleCleanupService(
        session_manager=_session_manager,
        artifact_repository=cast(Any, artifact_repo),
        exchange_file_repository=cast(Any, exchange_repo),
        model_file_repository=cast(Any, _ModelFileRepo([])),
        model_file_pin_repository=cast(Any, _PinRepo()),
        agent_session_repository=cast(Any, _AgentSessionRepo([])),
        transcript_repository=cast(Any, _TranscriptRepo([])),
        avatar_cleanup_repository=cast(Any, _AvatarCleanupRepo([])),
        avatar_handler=cast(Any, _AvatarHandler()),
        s3_service=cast(Any, s3),
        config=cast(Any, _Config()),
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.artifacts_expired == 1
    assert summary.exchange_files_expired == 1
    assert summary.artifact_blobs_deleted == 1
    assert summary.exchange_file_blobs_deleted == 1
    assert summary.model_file_blobs_deleted == 0
    assert summary.pending_blob_deletion_attempts == 0
    assert summary.blob_delete_failed == 0
    assert artifact_repo.marked_blob_deleted == ["a" * 32]
    assert exchange_repo.marked_blob_deleted == ["e" * 32]
    assert s3.deleted_keys == [
        "artifacts/workspace-1/session-1/1/a",
        "exchange/workspace-1/files/e/original",
    ]


@pytest.mark.asyncio
async def test_model_file_gc_deletes_unpinned_model_file_and_advances_cursor() -> None:
    """ModelFile GC deletes unpinned refs and advances through processed range."""
    model_repo = _ModelFileRepo([_model_file()])
    session_repo = _AgentSessionRepo([_lagging_session()])
    service = _service(
        model_file_repo=model_repo,
        agent_session_repo=session_repo,
        transcript_repo=_TranscriptRepo([_file_event()]),
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.model_files_deleted == 1
    assert summary.model_file_blobs_deleted == 1
    assert summary.sessions_advanced == 1
    assert model_repo.deleted_requests == [["m" * 32]]
    assert session_repo.advanced == [("session-1", "1" * 32)]


@pytest.mark.asyncio
async def test_model_file_gc_does_not_advance_cursor_when_file_is_pinned() -> None:
    """Pinned ModelFile keeps the GC cursor behind for a later retry."""
    model_repo = _PinnedModelFileRepo([_model_file()])
    session_repo = _AgentSessionRepo([_lagging_session()])
    service = _service(
        model_file_repo=model_repo,
        agent_session_repo=session_repo,
        transcript_repo=_TranscriptRepo([_file_event()]),
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.model_files_deleted == 0
    assert summary.sessions_advanced == 0
    assert model_repo.deleted_requests == [["m" * 32]]
    assert session_repo.advanced == []


@pytest.mark.asyncio
async def test_cleanup_once_counts_pending_blob_deletion_attempts() -> None:
    """Cleanup distinguishes prior pending blobs from newly expired resources."""
    expired_exchange_file = _exchange_file().model_copy(
        update={
            "status": ExchangeFileStatus.EXPIRED,
            "expired_at": _NOW,
        }
    )
    exchange_repo = _ExchangeRepo([expired_exchange_file])
    service = FileLifecycleCleanupService(
        session_manager=_session_manager,
        artifact_repository=cast(Any, _ArtifactRepo([])),
        exchange_file_repository=cast(Any, exchange_repo),
        model_file_repository=cast(Any, _ModelFileRepo([])),
        model_file_pin_repository=cast(Any, _PinRepo()),
        agent_session_repository=cast(Any, _AgentSessionRepo([])),
        transcript_repository=cast(Any, _TranscriptRepo([])),
        avatar_cleanup_repository=cast(Any, _AvatarCleanupRepo([])),
        avatar_handler=cast(Any, _AvatarHandler()),
        s3_service=cast(Any, _S3Service()),
        config=cast(Any, _Config()),
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.exchange_files_expired == 0
    assert summary.exchange_file_blobs_deleted == 1
    assert summary.pending_blob_deletion_attempts == 1
    assert summary.blob_delete_failed == 0
    assert exchange_repo.marked_blob_deleted == ["e" * 32]


@pytest.mark.asyncio
async def test_cleanup_once_counts_blob_deletion_failures() -> None:
    """Cleanup reports failed deletes while preserving later retry eligibility."""
    artifact_repo = _ArtifactRepo([_artifact()])
    service = FileLifecycleCleanupService(
        session_manager=_session_manager,
        artifact_repository=cast(Any, artifact_repo),
        exchange_file_repository=cast(Any, _ExchangeRepo([])),
        model_file_repository=cast(Any, _ModelFileRepo([])),
        model_file_pin_repository=cast(Any, _PinRepo()),
        agent_session_repository=cast(Any, _AgentSessionRepo([])),
        transcript_repository=cast(Any, _TranscriptRepo([])),
        avatar_cleanup_repository=cast(Any, _AvatarCleanupRepo([])),
        avatar_handler=cast(Any, _AvatarHandler()),
        s3_service=cast(Any, _FailingS3Service()),
        config=cast(Any, _Config()),
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.artifacts_expired == 1
    assert summary.artifact_blobs_deleted == 0
    assert summary.pending_blob_deletion_attempts == 0
    assert summary.blob_delete_failed == 1
    assert artifact_repo.marked_blob_deleted == []


@pytest.mark.asyncio
async def test_cleanup_once_keeps_model_blob_deletion_batch_bounded() -> None:
    """Pre-existing pending blobs consume the ModelFile deletion batch first."""
    pending_model_files = [
        _model_file(ModelFileStatus.DELETED).model_copy(
            update={
                "id": f"{index:032x}",
                "storage_key": f"model-files/workspace-1/session-1/{index}",
                "deleted_at": _NOW,
            }
        )
        for index in range(200)
    ]
    model_repo = _ModelFileRepo([*pending_model_files, _model_file()])
    s3 = _S3Service()
    service = _service(
        model_file_repo=model_repo,
        agent_session_repo=_AgentSessionRepo([_lagging_session()]),
        transcript_repo=_TranscriptRepo([_file_event()]),
        s3_service=s3,
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.model_files_deleted == 1
    assert summary.model_file_blobs_deleted == 200
    assert summary.pending_blob_deletion_attempts == 200
    assert len(s3.deleted_keys) == 200
    assert "model-files/workspace-1/session-1/m" not in s3.deleted_keys
    assert "m" * 32 not in model_repo.marked_blob_deleted


@pytest.mark.asyncio
async def test_cleanup_once_completes_claimed_superseded_avatar() -> None:
    """Avatar cleanup succeeds independently of current Agent metadata."""
    avatar_cleanup_repo = _AvatarCleanupRepo([_avatar_cleanup_job()])
    avatar_handler = _AvatarHandler()
    service = _service(
        avatar_cleanup_repo=avatar_cleanup_repo,
        avatar_handler=avatar_handler,
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.avatar_cleanup_attempted == 1
    assert summary.avatar_cleanup_completed == 1
    assert summary.avatar_cleanup_failed == 0
    lease_token = avatar_cleanup_repo.claimed[0][1]
    assert lease_token.startswith("scheduler-1:")
    assert avatar_cleanup_repo.claimed[0][3] == 100
    assert avatar_cleanup_repo.deleted == [("j" * 32, lease_token)]
    assert avatar_handler.deleted_keys == ["public/avatar/agent-1/large/old.webp"]


@pytest.mark.asyncio
async def test_cleanup_once_retries_failed_superseded_avatar_with_safe_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Avatar cleanup failure logs only static text and safe diagnostic fields."""
    sentinel_endpoint = "https://storage.internal.example.test"
    sentinel_key = "public/avatar/agent-1/large/sentinel-private-key.webp"
    avatar_cleanup_repo = _AvatarCleanupRepo([_avatar_cleanup_job()])
    service = _service(
        avatar_cleanup_repo=avatar_cleanup_repo,
        avatar_handler=_AvatarHandler(
            failing_keys=frozenset({"public/avatar/agent-1/large/old.webp"}),
            failure_message=(
                f"Avatar delete failed at {sentinel_endpoint} for {sentinel_key}"
            ),
        ),
    )
    caplog.set_level(
        logging.ERROR,
        logger="azents.services.file_lifecycle_cleanup",
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.avatar_cleanup_attempted == 1
    assert summary.avatar_cleanup_completed == 0
    assert summary.avatar_cleanup_failed == 1
    assert len(avatar_cleanup_repo.retries) == 1
    job_id, lease_token, next_attempt_at, failure_kind = avatar_cleanup_repo.retries[0]
    assert job_id == "j" * 32
    assert lease_token.startswith("scheduler-1:")
    assert next_attempt_at > _NOW
    assert failure_kind == "RuntimeError"
    record = next(
        record
        for record in caplog.records
        if record.getMessage() == "Failed to delete superseded Agent avatar"
    )
    formatted = logging.Formatter().format(record)
    assert "Failed to delete superseded Agent avatar" in formatted
    assert "Superseded Agent avatar cleanup failed" in formatted
    assert "in delete_files" in formatted
    assert sentinel_endpoint not in formatted
    assert sentinel_key not in formatted
    assert record.__dict__["agent_avatar_cleanup_job_id"] == "j" * 32
    assert record.__dict__["agent_id"] == "agent-1"
    assert record.__dict__["attempt_count"] == 1
    assert record.__dict__["failure_kind"] == "RuntimeError"
    assert "lease_token" not in record.__dict__


@pytest.mark.asyncio
async def test_cleanup_once_continues_after_one_superseded_avatar_failure() -> None:
    """One failed avatar schedules retry without blocking later claimed jobs."""
    failed = _avatar_cleanup_job()
    succeeding = _avatar_cleanup_job_for(
        job_id="k" * 32,
        avatar=_avatar("public/avatar/agent-1/large/new.webp"),
    )
    avatar_cleanup_repo = _AvatarCleanupRepo([failed, succeeding])
    avatar_handler = _AvatarHandler(
        failing_keys=frozenset({"public/avatar/agent-1/large/old.webp"})
    )
    service = _service(
        avatar_cleanup_repo=avatar_cleanup_repo,
        avatar_handler=avatar_handler,
    )

    summary = await service.cleanup_once(lease_owner="scheduler-1")

    assert summary.avatar_cleanup_attempted == 2
    assert summary.avatar_cleanup_failed == 1
    assert summary.avatar_cleanup_completed == 1
    assert avatar_cleanup_repo.deleted[0][0] == "k" * 32
    assert avatar_cleanup_repo.deleted[0][1].startswith("scheduler-1:")
    assert avatar_handler.deleted_keys == ["public/avatar/agent-1/large/new.webp"]


@pytest.mark.asyncio
async def test_cleanup_once_uses_fresh_avatar_cleanup_token_per_pass() -> None:
    """Each cleanup pass creates an independent opaque avatar cleanup token."""
    avatar_cleanup_repo = _AvatarCleanupRepo([])
    service = _service(avatar_cleanup_repo=avatar_cleanup_repo)

    await service.cleanup_once(lease_owner="scheduler-1")
    await service.cleanup_once(lease_owner="scheduler-1")

    first_token = avatar_cleanup_repo.claimed[0][1]
    second_token = avatar_cleanup_repo.claimed[1][1]
    assert first_token.startswith("scheduler-1:")
    assert second_token.startswith("scheduler-1:")
    assert first_token != second_token
