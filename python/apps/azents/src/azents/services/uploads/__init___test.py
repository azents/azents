"""UploadService unit tests."""

import datetime
from typing import ClassVar
from unittest.mock import AsyncMock

import pytest
from azcommon.infra.s3.service import S3Service

from azents.services.uploads import (
    UploadService,
    UploadTicket,
    UploadValidationError,
)
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
)


class _StubHandler:
    """Stub handler for tests — satisfies Protocol."""

    category: ClassVar[str] = "stub"
    allowed_mime_types: ClassVar[frozenset[str]] = frozenset({"image/png"})
    max_bytes: ClassVar[int] = 1024

    def __init__(self) -> None:
        self.validate_mock = AsyncMock()
        self.process_mock = AsyncMock()

    async def validate(self, body: bytes) -> None:
        await self.validate_mock(body)

    async def process_and_publish(
        self,
        body: bytes,
        owner_id: str,
        filename: str,
        s3: S3Service,
        bucket: str,
    ) -> StoredImage:
        await self.process_mock(
            body=body, owner_id=owner_id, filename=filename, bucket=bucket
        )
        return StoredImage(
            filename=filename,
            default=StoredImageFile(
                key=f"public/stub/{owner_id}/default.png",
                content_type="image/png",
                size_bytes=len(body),
                width=128,
                height=128,
            ),
            thumbnails=StoredImageThumbnails(),
            uploaded_at=datetime.datetime.now(datetime.timezone.utc),
        )


@pytest.fixture
def s3_mock() -> AsyncMock:
    """S3Service mock."""
    s3 = AsyncMock()
    s3.get_upload_url.return_value = "https://s3.example/upload-url"
    s3.download_bytes.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    s3.delete.return_value = None
    s3.upload.return_value = None
    return s3


@pytest.fixture
def handler() -> _StubHandler:
    return _StubHandler()


@pytest.fixture
def service(s3_mock: AsyncMock, handler: _StubHandler) -> UploadService:
    return UploadService(
        s3=s3_mock,
        bucket="test-bucket",
        handlers={handler.category: handler},
    )


class TestIssueUploadTicket:
    """presigned PUT URL issuance behavior."""

    @pytest.mark.asyncio
    async def test_success_returns_ticket(
        self, service: UploadService, s3_mock: AsyncMock
    ) -> None:
        ticket = await service.issue_upload_ticket(
            category="stub",
            owner_id="owner-1",
            content_type="image/png",
            content_length=500,
        )

        assert isinstance(ticket, UploadTicket)
        assert ticket.upload_key.startswith("uploads/stub/owner-1/")
        assert ticket.upload_url == "https://s3.example/upload-url"
        # expires_at is approximately 10 minutes later
        assert ticket.expires_at.tzinfo is not None
        delta = ticket.expires_at - datetime.datetime.now(datetime.timezone.utc)
        assert 590 <= delta.total_seconds() <= 610

        s3_mock.get_upload_url.assert_awaited_once()
        kwargs = s3_mock.get_upload_url.await_args.kwargs
        assert kwargs["bucket"] == "test-bucket"
        assert kwargs["content_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_unsupported_mime_raises(self, service: UploadService) -> None:
        with pytest.raises(UploadValidationError, match="unsupported mime"):
            await service.issue_upload_ticket(
                category="stub",
                owner_id="owner-1",
                content_type="image/gif",
                content_length=500,
            )

    @pytest.mark.asyncio
    async def test_oversized_content_length_raises(
        self, service: UploadService
    ) -> None:
        with pytest.raises(UploadValidationError, match="content_length"):
            await service.issue_upload_ticket(
                category="stub",
                owner_id="owner-1",
                content_type="image/png",
                content_length=10 * 1024,
            )

    @pytest.mark.asyncio
    async def test_zero_content_length_raises(self, service: UploadService) -> None:
        with pytest.raises(UploadValidationError, match="content_length"):
            await service.issue_upload_ticket(
                category="stub",
                owner_id="owner-1",
                content_type="image/png",
                content_length=0,
            )

    @pytest.mark.asyncio
    async def test_unknown_category_raises(self, service: UploadService) -> None:
        with pytest.raises(UploadValidationError, match="unknown upload category"):
            await service.issue_upload_ticket(
                category="unknown",
                owner_id="owner-1",
                content_type="image/png",
                content_length=500,
            )


class TestFinalize:
    """finalize pipeline."""

    @pytest.mark.asyncio
    async def test_success_runs_pipeline(
        self,
        service: UploadService,
        s3_mock: AsyncMock,
        handler: _StubHandler,
    ) -> None:
        upload_key = "uploads/stub/owner-1/abc-def"
        result = await service.finalize(
            category="stub",
            owner_id="owner-1",
            upload_key=upload_key,
            filename="test.png",
        )

        assert isinstance(result, StoredImage)
        assert result.filename == "test.png"
        handler.validate_mock.assert_awaited_once()
        handler.process_mock.assert_awaited_once()
        # uploads/ file deletion should be called
        s3_mock.delete.assert_awaited_once_with(bucket="test-bucket", key=upload_key)

    @pytest.mark.asyncio
    async def test_scope_mismatch_raises(self, service: UploadService) -> None:
        """400 on upload_key prefix mismatch prevents finalize injection."""
        with pytest.raises(UploadValidationError, match="scope mismatch"):
            await service.finalize(
                category="stub",
                owner_id="owner-1",
                upload_key="uploads/stub/other-owner/abc",
                filename="test.png",
            )

    @pytest.mark.asyncio
    async def test_missing_object_raises(
        self, service: UploadService, s3_mock: AsyncMock
    ) -> None:
        s3_mock.download_bytes.return_value = None
        with pytest.raises(UploadValidationError, match="not found or expired"):
            await service.finalize(
                category="stub",
                owner_id="owner-1",
                upload_key="uploads/stub/owner-1/abc",
                filename="test.png",
            )

    @pytest.mark.asyncio
    async def test_validation_failure_still_deletes_upload(
        self,
        service: UploadService,
        s3_mock: AsyncMock,
        handler: _StubHandler,
    ) -> None:
        """Try uploads/ deletion even on validation failure (try/finally)."""
        handler.validate_mock.side_effect = UploadValidationError("bad image")
        with pytest.raises(UploadValidationError, match="bad image"):
            await service.finalize(
                category="stub",
                owner_id="owner-1",
                upload_key="uploads/stub/owner-1/abc",
                filename="test.png",
            )
        s3_mock.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_failure_is_swallowed(
        self,
        service: UploadService,
        s3_mock: AsyncMock,
    ) -> None:
        """Swallow uploads/ deletion failure (Lifecycle performs backup cleanup)."""
        s3_mock.delete.side_effect = RuntimeError("s3 down")
        result = await service.finalize(
            category="stub",
            owner_id="owner-1",
            upload_key="uploads/stub/owner-1/abc",
            filename="test.png",
        )
        # Result is returned normally
        assert isinstance(result, StoredImage)
