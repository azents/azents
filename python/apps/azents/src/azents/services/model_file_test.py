"""ModelFileService tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Failure, Success
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentRunStatus, AgentSessionStatus, ModelFileStatus
from azents.repos.model_file import model_file_storage_key
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.services.model_file import (
    ModelFileAccessDenied,
    ModelFileInvalidImage,
    ModelFileOversized,
    ModelFileService,
    model_file_size_limit_message,
    normalize_model_file_body,
)
from azents.services.session_resource_authority import SessionResourceAuthority


class _SessionBoundary:
    """Track DB scope lifetime around object-storage calls."""

    def __init__(self) -> None:
        self.active = 0

    @asynccontextmanager
    async def session_manager(self) -> AsyncGenerator[AsyncSession, None]:
        """Yield one tracked fake DB session."""
        self.active += 1
        try:
            yield cast(AsyncSession, object())
        finally:
            self.active -= 1


class _ModelFileRepository:
    """ModelFile repository honoring the service-preallocated ID."""

    def __init__(self, boundary: _SessionBoundary) -> None:
        self.boundary = boundary
        self.create_calls = 0
        self.discarded_ids: list[str] = []

    async def create(
        self,
        session: AsyncSession,
        create: ModelFileCreate,
    ) -> ModelFile:
        """Persist metadata only while the DB scope is active."""
        del session
        assert self.boundary.active == 1
        self.create_calls += 1
        return ModelFile(
            id=create.id,
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            name=create.name,
            media_type=create.media_type,
            kind=create.kind,
            size_bytes=create.size_bytes,
            created_run_id=create.created_run_id,
            created_run_index=create.created_run_index,
            storage_key=model_file_storage_key(
                workspace_id=create.workspace_id,
                session_id=create.session_id,
                model_file_id=create.id,
            ),
            status=ModelFileStatus.AVAILABLE,
            normalized_format=create.normalized_format,
            sha256=create.sha256,
            metadata=create.metadata,
            created_at=datetime.datetime.now(datetime.UTC),
        )

    async def mark_deleted_if_unpinned(
        self,
        session: AsyncSession,
        *,
        model_file_ids: list[str],
        deleted_at: datetime.datetime,
    ) -> list[ModelFile]:
        """Record pending ModelFiles marked for scheduled blob cleanup."""
        del session, deleted_at
        assert self.boundary.active == 1
        self.discarded_ids.extend(model_file_ids)
        return [cast(ModelFile, object()) for _ in model_file_ids]


class _S3Service:
    """Object storage asserting that no DB session is open."""

    def __init__(self, boundary: _SessionBoundary) -> None:
        self.boundary = boundary
        self.objects: dict[str, bytes] = {}

    async def upload(
        self,
        bucket: str,
        key: str,
        body: bytes,
        *,
        content_type: str | None = None,
    ) -> None:
        """Store bytes only outside a DB scope."""
        del bucket, content_type
        assert self.boundary.active == 0
        self.objects[key] = body

    async def delete(self, bucket: str, key: str) -> None:
        """Delete bytes only outside a DB scope."""
        del bucket
        assert self.boundary.active == 0
        self.objects.pop(key, None)


def _png_bytes() -> bytes:
    """Create PNG bytes for tests."""
    image = Image.new("RGBA", (2, 2), (255, 0, 0, 128))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_image_model_file_normalizes_to_jpeg() -> None:
    """Image ModelFile is converted to JPEG normalized blob."""
    result = normalize_model_file_body(media_type="image/png", body=_png_bytes())

    assert isinstance(result, Success)
    assert result.value.media_type == "image/jpeg"
    assert result.value.kind == "image"
    assert result.value.normalized_format == "jpeg"
    assert result.value.body.startswith(b"\xff\xd8")


def test_invalid_image_fails_without_storing_random_bytes_as_image() -> None:
    """Does not create image ModelFile when declared image payload is broken."""
    result = normalize_model_file_body(media_type="image/png", body=b"not an image")

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileInvalidImage)


def test_non_image_model_file_keeps_original_bytes_under_cap() -> None:
    """Non-image ModelFile is not normalized and only applies size cap."""
    body = b"\x00\x01\x02"
    result = normalize_model_file_body(
        media_type="application/octet-stream",
        body=body,
    )

    assert isinstance(result, Success)
    assert result.value.body == body
    assert result.value.kind == "binary"
    assert result.value.normalized_format == "original"


def test_non_image_model_file_rejects_oversized_input() -> None:
    """Non-image input exceeding size cap is not made into ModelFile."""
    body = b"x" * 1_000_001
    result = normalize_model_file_body(media_type="application/pdf", body=body)

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileOversized)
    assert "File size exceeds the allowed limit" in model_file_size_limit_message(
        result.error
    )


@pytest.mark.asyncio
async def test_model_file_upload_closes_db_session_before_s3_io() -> None:
    """ModelFile creation uploads outside DB and persists its stable key afterward."""
    boundary = _SessionBoundary()
    s3 = _S3Service(boundary)
    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        agent_id="agent-1",
        owner_generation=1,
        status=AgentSessionStatus.ACTIVE,
    )
    agent_session_repository.lock_by_id.return_value = (
        agent_session_repository.get_by_id.return_value
    )
    agent_session_repository.get_root_session_agent_by_session_id.return_value = (
        SimpleNamespace(agent_session_id="root-session-1")
    )
    agent_run_repository = AsyncMock()
    agent_run_repository.get_by_id.return_value = SimpleNamespace(
        session_id="session-1",
        run_index=1,
        status=AgentRunStatus.RUNNING,
    )
    agent_run_repository.lock_by_id.return_value = (
        agent_run_repository.get_by_id.return_value
    )
    service = ModelFileService(
        model_file_repository=cast(Any, _ModelFileRepository(boundary)),
        agent_session_repository=agent_session_repository,
        agent_run_repository=agent_run_repository,
        workspace_user_repository=AsyncMock(),
        session_manager=boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
    )

    result = await service.create(
        authority=_authority(),
        filename="notes.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert s3.objects[result.value.storage_key] == b"hello"
    assert boundary.active == 0


@pytest.mark.asyncio
async def test_admitted_model_file_creation_ignores_workspace_membership() -> None:
    """Accepted attachment promotion is authorized by root lineage, not a User."""
    boundary = _SessionBoundary()
    s3 = _S3Service(boundary)
    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        agent_id="agent-1",
        owner_generation=1,
        status=AgentSessionStatus.ACTIVE,
    )
    agent_session_repository.lock_by_id.return_value = (
        agent_session_repository.get_by_id.return_value
    )
    agent_session_repository.get_root_session_agent_by_session_id.return_value = (
        SimpleNamespace(agent_session_id="root-session-1")
    )
    agent_run_repository = AsyncMock()
    agent_run_repository.get_by_id.return_value = SimpleNamespace(
        session_id="session-1",
        run_index=1,
        status=AgentRunStatus.RUNNING,
    )
    agent_run_repository.lock_by_id.return_value = (
        agent_run_repository.get_by_id.return_value
    )
    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = None
    service = ModelFileService(
        model_file_repository=cast(Any, _ModelFileRepository(boundary)),
        agent_session_repository=agent_session_repository,
        agent_run_repository=agent_run_repository,
        workspace_user_repository=workspace_user_repository,
        session_manager=boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
    )

    result = await service.create(
        authority=_authority(),
        filename="accepted.txt",
        media_type="text/plain",
        body=b"accepted",
    )

    assert isinstance(result, Success)
    assert s3.objects[result.value.storage_key] == b"accepted"
    workspace_user_repository.get_by_workspace_and_user.assert_not_awaited()
    assert boundary.active == 0


@pytest.mark.asyncio
async def test_admitted_model_file_cleans_object_when_root_lineage_changes() -> None:
    """A lineage change after S3 upload aborts metadata creation and compensates."""
    boundary = _SessionBoundary()
    s3 = _S3Service(boundary)
    agent_session_repository = AsyncMock()
    agent_session_repository.get_by_id.side_effect = [
        SimpleNamespace(
            workspace_id="workspace-1",
            agent_id="agent-1",
            owner_generation=1,
            status=AgentSessionStatus.ACTIVE,
        ),
        SimpleNamespace(
            workspace_id="workspace-1",
            agent_id="agent-1",
            owner_generation=1,
            status=AgentSessionStatus.ACTIVE,
        ),
    ]
    agent_session_repository.lock_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1",
        agent_id="agent-1",
        owner_generation=1,
        status=AgentSessionStatus.ACTIVE,
    )
    agent_session_repository.get_root_session_agent_by_session_id.side_effect = [
        SimpleNamespace(agent_session_id="root-session-1"),
        SimpleNamespace(agent_session_id="new-root-session"),
    ]
    model_file_repository = _ModelFileRepository(boundary)
    workspace_user_repository = AsyncMock()
    service = ModelFileService(
        model_file_repository=cast(Any, model_file_repository),
        agent_session_repository=agent_session_repository,
        agent_run_repository=AsyncMock(
            get_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="session-1",
                    run_index=1,
                    status=AgentRunStatus.RUNNING,
                )
            ),
            lock_by_id=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="session-1",
                    run_index=1,
                    status=AgentRunStatus.RUNNING,
                )
            ),
        ),
        workspace_user_repository=workspace_user_repository,
        session_manager=boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
    )

    result = await service.create(
        authority=_authority(),
        filename="accepted.txt",
        media_type="text/plain",
        body=b"accepted",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, ModelFileAccessDenied)
    assert s3.objects == {}
    workspace_user_repository.get_by_workspace_and_user.assert_not_awaited()
    assert model_file_repository.create_calls == 0
    assert boundary.active == 0


@pytest.mark.asyncio
async def test_discard_pending_input_marks_files_for_lifecycle_cleanup() -> None:
    """Failed input promotion marks created ModelFiles deleted in one DB scope."""
    boundary = _SessionBoundary()
    repository = _ModelFileRepository(boundary)
    service = ModelFileService(
        model_file_repository=cast(Any, repository),
        agent_session_repository=AsyncMock(),
        agent_run_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        session_manager=boundary.session_manager,
        s3_service=cast(Any, _S3Service(boundary)),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
    )

    discarded = await service.discard_pending_input(
        model_file_ids=["model-file-1", "model-file-2"],
    )

    assert discarded == 2
    assert repository.discarded_ids == ["model-file-1", "model-file-2"]
    assert boundary.active == 0


def _authority() -> SessionResourceAuthority:
    """Create canonical ModelFile authority for tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="root-session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )
