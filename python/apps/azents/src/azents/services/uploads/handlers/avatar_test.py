"""AvatarUploadHandler unit tests (uses real Pillow)."""

from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from azents.services.uploads import UploadValidationError
from azents.services.uploads.handlers.avatar import AvatarUploadHandler
from azents.services.uploads.schema import StoredImage


def _make_png(width: int, height: int) -> bytes:
    """Create PNG bytes for tests."""
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def handler() -> AvatarUploadHandler:
    return AvatarUploadHandler()


@pytest.fixture
def s3_mock() -> AsyncMock:
    s3 = AsyncMock()
    s3.upload.return_value = None
    s3.delete.return_value = None
    return s3


class TestValidate:
    @pytest.mark.asyncio
    async def test_valid_square_png(self, handler: AvatarUploadHandler) -> None:
        await handler.validate(_make_png(256, 256))

    @pytest.mark.asyncio
    async def test_rejects_non_square(self, handler: AvatarUploadHandler) -> None:
        with pytest.raises(UploadValidationError, match="square"):
            await handler.validate(_make_png(300, 200))

    @pytest.mark.asyncio
    async def test_rejects_oversized_dimension(
        self, handler: AvatarUploadHandler
    ) -> None:
        with pytest.raises(UploadValidationError, match="4096x4096"):
            await handler.validate(_make_png(5000, 5000))

    @pytest.mark.asyncio
    async def test_rejects_oversized_bytes(self, handler: AvatarUploadHandler) -> None:
        body = b"\x00" * (6 * 1024 * 1024)
        with pytest.raises(UploadValidationError, match="5MB"):
            await handler.validate(body)

    @pytest.mark.asyncio
    async def test_rejects_invalid_bytes(self, handler: AvatarUploadHandler) -> None:
        with pytest.raises(UploadValidationError, match="invalid image"):
            await handler.validate(b"\x00\x01\x02 not an image")


class TestProcessAndPublish:
    @pytest.mark.asyncio
    async def test_generates_three_thumbnails(
        self, handler: AvatarUploadHandler, s3_mock: AsyncMock
    ) -> None:
        body = _make_png(512, 512)
        result = await handler.process_and_publish(
            body=body,
            owner_id="agent-1",
            filename="avatar.png",
            s3=s3_mock,
            bucket="test-bucket",
        )

        assert isinstance(result, StoredImage)
        assert result.filename == "avatar.png"
        assert result.original is None  # P5

        # small / medium / large are all populated
        assert result.thumbnails.small is not None
        assert result.thumbnails.medium is not None
        assert result.thumbnails.large is not None
        assert result.thumbnails.small.width == 128
        assert result.thumbnails.medium.width == 256
        assert result.thumbnails.large.width == 512

        # default has same key as large (shared)
        assert result.default.key == result.thumbnails.large.key

        # S3 upload called 3 times (small, medium, large)
        assert s3_mock.upload.await_count == 3
        for call in s3_mock.upload.await_args_list:
            kwargs = call.kwargs
            assert kwargs["bucket"] == "test-bucket"
            assert kwargs["key"].startswith("public/avatar/agent-1/")
            assert kwargs["content_type"] == "image/webp"

    @pytest.mark.asyncio
    async def test_key_uses_hex_unique_per_upload(
        self, handler: AvatarUploadHandler, s3_mock: AsyncMock
    ) -> None:
        body = _make_png(256, 256)
        first = await handler.process_and_publish(
            body=body,
            owner_id="agent-1",
            filename="a.png",
            s3=s3_mock,
            bucket="b",
        )
        second = await handler.process_and_publish(
            body=body,
            owner_id="agent-1",
            filename="a.png",
            s3=s3_mock,
            bucket="b",
        )
        assert first.default.key != second.default.key


class TestDeleteFiles:
    @pytest.mark.asyncio
    async def test_deletes_unique_keys(
        self, handler: AvatarUploadHandler, s3_mock: AsyncMock
    ) -> None:
        body = _make_png(256, 256)
        result = await handler.process_and_publish(
            body=body,
            owner_id="agent-1",
            filename="a.png",
            s3=s3_mock,
            bucket="bucket",
        )
        s3_mock.reset_mock()

        await handler.delete_files(result, s3_mock, "bucket")

        # default and large share key — dedup and delete only unique keys
        # (small, medium, large = 3 unique; default duplicates large)
        assert s3_mock.delete.await_count == 3
