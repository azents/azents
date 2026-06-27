"""ModelFileService tests."""

from io import BytesIO

from azcommon.result import Failure, Success
from PIL import Image

from azents.services.model_file import (
    ModelFileInvalidImage,
    ModelFileOversized,
    model_file_size_limit_message,
    normalize_model_file_body,
)


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
