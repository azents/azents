"""FileLifecycleCleanupService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Any, cast
from unittest.mock import Mock

import pytest
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.file_lifecycle as file_lifecycle_module
from azents.core.enums import (
    ArtifactStatus,
    ExchangeFileOrigin,
    ExchangeFileStatus,
    ModelFileStatus,
)
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile
from azents.services.file_lifecycle import FileLifecycleCleanupService

_NOW = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class _FakeExchangeFileRepository:
    """ExchangeFile repository for lifecycle tests."""

    def __init__(self) -> None:
        self.files: dict[str, ExchangeFile] = {}
        self.blob_deleted_ids: list[str] = []

    async def expire_due(
        self,
        session: AsyncSession,
        *,
        now: datetime.datetime,
        limit: int,
    ) -> list[ExchangeFile]:
        """Mark due ExchangeFiles as expired."""
        del session
        expired: list[ExchangeFile] = []
        for file in self.files.values():
            if len(expired) >= limit:
                break
            if file.status == ExchangeFileStatus.AVAILABLE and file.expires_at <= now:
                updated = file.model_copy(
                    update={"status": ExchangeFileStatus.EXPIRED, "expired_at": now}
                )
                self.files[file.id] = updated
                expired.append(updated)
        return expired

    async def list_expired_with_blob(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ExchangeFile]:
        """Return expired ExchangeFiles still missing blob deletion marker."""
        del session
        return [
            file
            for file in self.files.values()
            if file.status == ExchangeFileStatus.EXPIRED
            and file.blob_deleted_at is None
        ][:limit]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        file_id: str,
    ) -> None:
        """Record ExchangeFile blob deletion."""
        del session
        self.blob_deleted_ids.append(file_id)
        self.files[file_id] = self.files[file_id].model_copy(
            update={"blob_deleted_at": _NOW}
        )


class _FakeArtifactRepository:
    """Artifact repository for lifecycle tests."""

    def __init__(self) -> None:
        self.artifacts: dict[str, Artifact] = {}
        self.blob_deleted_ids: list[str] = []

    async def list_candidate_session_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        """Return sessions with Artifact candidates."""
        del session, limit
        return list({artifact.session_id for artifact in self.artifacts.values()})

    async def expire_due_by_latest_run_index(
        self,
        session: AsyncSession,
        *,
        latest_run_indexes: dict[str, int],
        expired_at: datetime.datetime,
        limit: int,
    ) -> list[Artifact]:
        """Expire Artifacts by latest run index."""
        del session
        expired: list[Artifact] = []
        for artifact in self.artifacts.values():
            if len(expired) >= limit:
                break
            latest = latest_run_indexes.get(artifact.session_id)
            if (
                latest is not None
                and artifact.status == ArtifactStatus.AVAILABLE
                and artifact.expires_after_run_index < latest
            ):
                updated = artifact.model_copy(
                    update={"status": ArtifactStatus.EXPIRED, "expired_at": expired_at}
                )
                self.artifacts[artifact.id] = updated
                expired.append(updated)
        return expired

    async def list_expired_with_blob(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[Artifact]:
        """Return expired Artifacts still missing blob deletion marker."""
        del session
        return [
            artifact
            for artifact in self.artifacts.values()
            if artifact.status == ArtifactStatus.EXPIRED
            and artifact.blob_deleted_at is None
        ][:limit]

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        artifact_id: str,
    ) -> None:
        """Record Artifact blob deletion."""
        del session
        self.blob_deleted_ids.append(artifact_id)
        self.artifacts[artifact_id] = self.artifacts[artifact_id].model_copy(
            update={"blob_deleted_at": _NOW}
        )


class _FakeModelFileRepository:
    """ModelFile repository for lifecycle tests."""

    def __init__(self) -> None:
        self.model_files: dict[str, ModelFile] = {}
        self.blob_deleted_ids: list[str] = []

    async def list_candidate_session_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        """Return sessions with ModelFile candidates."""
        del session, limit
        return list({file.session_id for file in self.model_files.values()})

    async def list_due_by_latest_run_index(
        self,
        session: AsyncSession,
        *,
        latest_run_indexes: dict[str, int],
        limit: int,
    ) -> list[ModelFile]:
        """Return model files in sessions with known latest run index."""
        del session
        return [
            file
            for file in self.model_files.values()
            if file.session_id in latest_run_indexes
        ][:limit]

    async def list_deleted_with_blob(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[ModelFile]:
        """Return deleted ModelFiles still missing blob deletion marker."""
        del session
        return [
            file
            for file in self.model_files.values()
            if file.status == ModelFileStatus.DELETED and file.blob_deleted_at is None
        ][:limit]

    async def mark_degraded(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        size_bytes: int,
        normalized_format: str,
        sha256: str,
        degraded_at: datetime.datetime,
    ) -> ModelFile:
        """Record degraded ModelFile."""
        del session
        updated = self.model_files[model_file_id].model_copy(
            update={
                "status": ModelFileStatus.DEGRADED,
                "size_bytes": size_bytes,
                "normalized_format": normalized_format,
                "sha256": sha256,
                "degraded_at": degraded_at,
            }
        )
        self.model_files[model_file_id] = updated
        return updated

    async def mark_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        deleted_at: datetime.datetime,
    ) -> ModelFile:
        """Record deleted ModelFile."""
        del session
        updated = self.model_files[model_file_id].model_copy(
            update={"status": ModelFileStatus.DELETED, "deleted_at": deleted_at}
        )
        self.model_files[model_file_id] = updated
        return updated

    async def mark_unreachable(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
        unreachable_run_index: int,
        unreachable_at: datetime.datetime,
    ) -> ModelFile:
        """Record unreachable ModelFile."""
        del session
        updated = self.model_files[model_file_id].model_copy(
            update={
                "status": ModelFileStatus.UNREACHABLE,
                "unreachable_run_index": unreachable_run_index,
                "unreachable_at": unreachable_at,
            }
        )
        self.model_files[model_file_id] = updated
        return updated

    async def mark_blob_deleted(
        self,
        session: AsyncSession,
        *,
        model_file_id: str,
    ) -> None:
        """Record ModelFile blob deletion."""
        del session
        self.blob_deleted_ids.append(model_file_id)
        self.model_files[model_file_id] = self.model_files[model_file_id].model_copy(
            update={"blob_deleted_at": _NOW}
        )


class _FakeRunRepository:
    """Run repository for lifecycle tests."""

    def __init__(self, latest: dict[str, int]) -> None:
        self.latest = latest

    async def latest_run_indexes(
        self,
        session: AsyncSession,
        *,
        session_ids: list[str] | None,
    ) -> dict[str, int]:
        """Return configured latest run indexes."""
        del session
        if session_ids is None:
            return dict(self.latest)
        return {session_id: self.latest[session_id] for session_id in session_ids}


class _FakeS3Service:
    """S3 service for lifecycle tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []
        self.fail_delete_keys: set[str] = set()

    async def upload(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Store object bytes."""
        del bucket, content_type
        self.objects[key] = body

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """Download object bytes."""
        del bucket
        return self.objects.get(key)

    async def delete(self, bucket: str, key: str) -> None:
        """Delete object bytes."""
        del bucket
        if key in self.fail_delete_keys:
            msg = "delete failed"
            raise RuntimeError(msg)
        self.deleted_keys.append(key)
        self.objects.pop(key, None)


class _WorkspaceS3Config:
    """Workspace S3 config for tests."""

    bucket = "test-bucket"


class _Config:
    """Config for tests."""

    workspace_s3 = _WorkspaceS3Config()


@asynccontextmanager
async def _session_manager() -> AsyncGenerator[AsyncSession, None]:
    """Session manager for tests."""
    yield cast(AsyncSession, object())


def _make_service(
    *,
    latest_run_indexes: dict[str, int] | None = None,
) -> tuple[
    FileLifecycleCleanupService,
    _FakeExchangeFileRepository,
    _FakeArtifactRepository,
    _FakeModelFileRepository,
    _FakeS3Service,
]:
    """Create FileLifecycleCleanupService with fakes."""
    exchange_repo = _FakeExchangeFileRepository()
    artifact_repo = _FakeArtifactRepository()
    model_file_repo = _FakeModelFileRepository()
    s3 = _FakeS3Service()
    service = FileLifecycleCleanupService(
        exchange_file_repository=cast(Any, exchange_repo),
        artifact_repository=cast(Any, artifact_repo),
        model_file_repository=cast(Any, model_file_repo),
        agent_run_repository=cast(Any, _FakeRunRepository(latest_run_indexes or {})),
        session_manager=_session_manager,
        s3_service=cast(Any, s3),
        config=cast(Any, _Config()),
    )
    return service, exchange_repo, artifact_repo, model_file_repo, s3


def _exchange_file(*, file_id: str, expires_at: datetime.datetime) -> ExchangeFile:
    """Create ExchangeFile test model."""
    return ExchangeFile(
        id=file_id,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.UPLOAD,
        status=ExchangeFileStatus.AVAILABLE,
        object_key=f"exchange/workspace-1/files/{file_id}/original",
        filename="file.txt",
        media_type="text/plain",
        size_bytes=5,
        sha256="0" * 64,
        created_by_user_id="user-1",
        expires_at=expires_at,
        blob_deleted_at=None,
        created_at=_NOW,
    )


def _artifact(*, artifact_id: str, expires_after_run_index: int) -> Artifact:
    """Create Artifact test model."""
    return Artifact(
        id=artifact_id,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        created_run_id="run-1",
        created_run_index=1,
        expires_after_run_index=expires_after_run_index,
        name="artifact.txt",
        media_type="text/plain",
        size_bytes=5,
        storage_key=f"artifacts/workspace-1/session-1/1/{artifact_id}",
        status=ArtifactStatus.AVAILABLE,
        sha256="0" * 64,
        created_at=_NOW,
        blob_deleted_at=None,
    )


def _model_file(
    *,
    model_file_id: str,
    created_run_index: int,
    kind: str,
    status: ModelFileStatus = ModelFileStatus.AVAILABLE,
    normalized_format: str = "original",
    unreachable_run_index: int | None = None,
) -> ModelFile:
    """Create ModelFile test model."""
    return ModelFile(
        id=model_file_id,
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        name="model-file",
        media_type="text/plain" if kind != "image" else "image/jpeg",
        kind=kind,
        size_bytes=5,
        created_run_index=created_run_index,
        expires_after_run_index=created_run_index + 1,
        storage_key=f"model-files/workspace-1/session-1/{model_file_id}",
        status=status,
        normalized_format=normalized_format,
        sha256="0" * 64,
        created_at=_NOW,
        unreachable_run_index=unreachable_run_index,
        blob_deleted_at=None,
    )


def _jpeg_bytes(size: tuple[int, int]) -> bytes:
    """Create JPEG bytes for tests."""
    image = Image.new("RGB", size, (255, 0, 0))
    output = BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_expire_due_exchange_files_marks_and_deletes_blob() -> None:
    """Due ExchangeFiles are expired and their blobs are deleted."""
    service, exchange_repo, _artifact_repo, _model_file_repo, s3 = _make_service()
    file = _exchange_file(
        file_id="1" * 32,
        expires_at=_NOW - datetime.timedelta(seconds=1),
    )
    exchange_repo.files[file.id] = file
    s3.objects[file.object_key] = b"hello"

    expired = await service.expire_due_exchange_files()

    assert [item.id for item in expired] == [file.id]
    assert exchange_repo.files[file.id].status == ExchangeFileStatus.EXPIRED
    assert exchange_repo.files[file.id].blob_deleted_at == _NOW
    assert file.object_key not in s3.objects


@pytest.mark.asyncio
async def test_expire_due_artifacts_uses_latest_run_index() -> None:
    """Artifact cleanup uses explicit latest run index query output."""
    service, _exchange_repo, artifact_repo, _model_file_repo, s3 = _make_service(
        latest_run_indexes={"session-1": 4}
    )
    artifact = _artifact(artifact_id="a" * 32, expires_after_run_index=3)
    artifact_repo.artifacts[artifact.id] = artifact
    s3.objects[artifact.storage_key] = b"hello"

    expired = await service.expire_due_artifacts()

    assert [item.id for item in expired] == [artifact.id]
    assert artifact_repo.artifacts[artifact.id].status == ArtifactStatus.EXPIRED
    assert artifact_repo.artifacts[artifact.id].blob_deleted_at == _NOW
    assert artifact.storage_key not in s3.objects


@pytest.mark.asyncio
async def test_model_file_unreachable_grace_transitions_to_deleted() -> None:
    """Unreachable ModelFile is deleted after one run-boundary grace."""
    service, _exchange_repo, _artifact_repo, model_file_repo, s3 = _make_service(
        latest_run_indexes={"session-1": 5}
    )
    model_file = _model_file(
        model_file_id="b" * 32,
        created_run_index=1,
        kind="text",
        status=ModelFileStatus.UNREACHABLE,
        unreachable_run_index=4,
    )
    model_file_repo.model_files[model_file.id] = model_file
    s3.objects[model_file.storage_key] = b"hello"

    changed = await service.process_due_model_files()

    assert [item.id for item in changed] == [model_file.id]
    assert model_file_repo.model_files[model_file.id].status == ModelFileStatus.DELETED
    assert model_file_repo.model_files[model_file.id].blob_deleted_at == _NOW
    assert model_file.storage_key not in s3.objects


@pytest.mark.asyncio
async def test_model_file_non_image_reaches_unreachable_at_retention_age() -> None:
    """Non-image ModelFile becomes unreachable at ADR-0046 retention age."""
    service, _exchange_repo, _artifact_repo, model_file_repo, _s3 = _make_service(
        latest_run_indexes={"session-1": 4}
    )
    model_file = _model_file(
        model_file_id="c" * 32,
        created_run_index=1,
        kind="text",
    )
    model_file_repo.model_files[model_file.id] = model_file

    changed = await service.process_due_model_files()

    assert [item.id for item in changed] == [model_file.id]
    updated = model_file_repo.model_files[model_file.id]
    assert updated.status == ModelFileStatus.UNREACHABLE
    assert updated.unreachable_run_index == 4


@pytest.mark.asyncio
async def test_retry_idempotency_skips_blob_deleted_rows() -> None:
    """Blob-deleted rows are not retried by pending deletion pass."""
    service, exchange_repo, artifact_repo, model_file_repo, s3 = _make_service()
    file = _exchange_file(file_id="d" * 32, expires_at=_NOW)
    exchange_repo.files[file.id] = file.model_copy(
        update={"status": ExchangeFileStatus.EXPIRED, "blob_deleted_at": _NOW}
    )
    artifact = _artifact(artifact_id="e" * 32, expires_after_run_index=1)
    artifact_repo.artifacts[artifact.id] = artifact.model_copy(
        update={"status": ArtifactStatus.EXPIRED, "blob_deleted_at": _NOW}
    )
    model_file = _model_file(
        model_file_id="f" * 32,
        created_run_index=1,
        kind="text",
        status=ModelFileStatus.DELETED,
    )
    model_file_repo.model_files[model_file.id] = model_file.model_copy(
        update={"blob_deleted_at": _NOW}
    )

    await service.retry_pending_blob_deletions()

    assert s3.deleted_keys == []
    assert exchange_repo.blob_deleted_ids == []
    assert artifact_repo.blob_deleted_ids == []
    assert model_file_repo.blob_deleted_ids == []


@pytest.mark.asyncio
async def test_blob_delete_failure_logs_and_leaves_retry_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blob deletion failures are logged and remain retryable."""
    exception_logger = Mock()
    monkeypatch.setattr(file_lifecycle_module.logger, "exception", exception_logger)
    service, exchange_repo, _artifact_repo, _model_file_repo, s3 = _make_service()
    file = _exchange_file(
        file_id="9" * 32,
        expires_at=_NOW - datetime.timedelta(seconds=1),
    )
    exchange_repo.files[file.id] = file
    s3.objects[file.object_key] = b"hello"
    s3.fail_delete_keys.add(file.object_key)

    expired = await service.expire_due_exchange_files()

    assert [item.id for item in expired] == [file.id]
    assert exchange_repo.files[file.id].status == ExchangeFileStatus.EXPIRED
    assert exchange_repo.files[file.id].blob_deleted_at is None
    assert file.object_key in s3.objects
    exception_logger.assert_called_once_with(
        "Failed to delete expired exchange file blob",
        extra={"file_id": file.id, "object_key": file.object_key},
    )


@pytest.mark.asyncio
async def test_model_file_image_degrades_in_scheduler_pass() -> None:
    """Image ModelFile degradation is handled by scheduler lifecycle cleanup."""
    service, _exchange_repo, _artifact_repo, model_file_repo, s3 = _make_service(
        latest_run_indexes={"session-1": 2}
    )
    model_file = _model_file(
        model_file_id="7" * 32,
        created_run_index=1,
        kind="image",
        normalized_format="jpeg",
    )
    model_file_repo.model_files[model_file.id] = model_file
    s3.objects[model_file.storage_key] = _jpeg_bytes((1200, 800))

    changed = await service.process_due_model_files()

    assert [item.id for item in changed] == [model_file.id]
    updated = model_file_repo.model_files[model_file.id]
    assert updated.status == ModelFileStatus.DEGRADED
    assert updated.normalized_format == "jpeg:1024"
    assert max(Image.open(BytesIO(s3.objects[model_file.storage_key])).size) == 1024
