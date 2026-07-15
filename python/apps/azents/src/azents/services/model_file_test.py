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

from azents.core.enums import ModelFileStatus
from azents.repos.model_file import model_file_storage_key
from azents.repos.model_file.data import ModelFile, ModelFileCreate
from azents.services.model_file import (
    ModelFileInvalidImage,
    ModelFileOversized,
    ModelFileService,
    model_file_size_limit_message,
    normalize_model_file_body,
)


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

    async def create(
        self,
        session: AsyncSession,
        create: ModelFileCreate,
    ) -> ModelFile:
        """Persist metadata only while the DB scope is active."""
        del session
        assert self.boundary.active == 1
        return ModelFile(
            id=create.id,
            workspace_id=create.workspace_id,
            session_id=create.session_id,
            agent_id=create.agent_id,
            name=create.name,
            media_type=create.media_type,
            kind=create.kind,
            size_bytes=create.size_bytes,
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
    )
    workspace_user_repository = AsyncMock()
    workspace_user_repository.get_by_workspace_and_user.return_value = object()
    service = ModelFileService(
        model_file_repository=cast(Any, _ModelFileRepository(boundary)),
        agent_session_repository=agent_session_repository,
        agent_run_repository=AsyncMock(),
        workspace_user_repository=workspace_user_repository,
        session_manager=boundary.session_manager,
        s3_service=cast(Any, s3),
        config=cast(
            Any,
            SimpleNamespace(workspace_s3=SimpleNamespace(bucket="test-bucket")),
        ),
    )

    result = await service.create(
        session_id="session-1",
        user_id="user-1",
        created_run_index=1,
        filename="notes.txt",
        media_type="text/plain",
        body=b"hello",
    )

    assert isinstance(result, Success)
    assert s3.objects[result.value.storage_key] == b"hello"
    assert boundary.active == 0
