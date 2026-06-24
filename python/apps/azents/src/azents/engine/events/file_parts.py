"""Event FilePart lowering helper."""

import base64
import dataclasses
from typing import Protocol

from azents.core.llm_catalog import ModelCapabilities, ModelModality
from azents.engine.events.types import FileOutputPart

_IMAGE_MEDIA_PREFIX = "image/"
_TEXT_MEDIA_PREFIX = "text/"
_PDF_MEDIA_TYPE = "application/pdf"
_DEFAULT_MAX_FILE_BYTES = 1_000_000


@dataclasses.dataclass(frozen=True)
class ModelFileLoweringContent:
    """request-local ModelFile lower content."""

    file_url: str | None = None
    data_url: str | None = None
    file_id: str | None = None


def make_model_file_data_url(*, media_type: str, body: bytes) -> str:
    """Convert ModelFile bytes to request-local data URL."""
    encoded = base64.b64encode(body).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


class ModelFileResolver(Protocol):
    """Request-local content resolver for ModelFile referenced by FilePart."""

    def resolve(self, part: FileOutputPart) -> ModelFileLoweringContent | None:
        """Resolve FilePart as request-local rich input content."""
        ...


class RequestLocalModelFileResolver:
    """Provide ModelFile request-local content to lowerer."""

    def __init__(self) -> None:
        """Create empty resolver."""
        self._by_model_file_id: dict[str, ModelFileLoweringContent] = {}

    def clear(self) -> None:
        """Remove previous request-local content."""
        self._by_model_file_id.clear()

    def put(
        self,
        *,
        model_file_id: str,
        content: ModelFileLoweringContent,
    ) -> None:
        """Attach request-local content to ModelFile ID."""
        self._by_model_file_id[model_file_id] = content

    def resolve(self, part: FileOutputPart) -> ModelFileLoweringContent | None:
        """Return ModelFile content for FilePart."""
        return self._by_model_file_id.get(part.model_file_id)


@dataclasses.dataclass(frozen=True)
class FilePartLoweringCapabilities:
    """FilePart native lowering capability."""

    supports_image_input: bool = False
    supports_file_input: bool = False
    supports_pdf_input: bool = False
    supports_text_file_input: bool = False
    max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES

    @classmethod
    def from_model_capabilities(
        cls,
        capabilities: ModelCapabilities | None,
    ) -> "FilePartLoweringCapabilities":
        """Extract FilePart lowering capability from ModelCapabilities."""
        if capabilities is None:
            return cls()
        input_modalities = set(capabilities.modalities.input)
        supports_image = ModelModality.IMAGE in input_modalities
        supports_pdf = ModelModality.PDF in input_modalities
        # Current TEXT modality in ModelCapabilities means general text prompt support.
        # Disable text file native input until separate capability exists.
        supports_text = False
        supports_file = supports_pdf or supports_text
        return cls(
            supports_image_input=supports_image,
            supports_file_input=supports_file,
            supports_pdf_input=supports_pdf,
            supports_text_file_input=supports_text,
        )


def lower_file_output_part(
    part: FileOutputPart,
    *,
    capabilities: FilePartLoweringCapabilities,
    resolver: ModelFileResolver | None,
) -> dict[str, object]:
    """Lower FileOutputPart to Responses content part."""
    if not _within_size_budget(part, capabilities):
        return _placeholder(part, reason="file exceeds model file input budget")
    if not _supported_by_capability(part, capabilities):
        return _placeholder(part, reason="model does not support this file input")
    if resolver is None:
        return _placeholder(
            part, reason="file content is not available in this request"
        )
    content = resolver.resolve(part)
    if content is None:
        return _placeholder(
            part, reason="file content is not available in this request"
        )
    if _is_image_part(part):
        image_url = content.data_url or content.file_url
        if image_url is None:
            return _placeholder(
                part, reason="image content is not available in this request"
            )
        return {
            "type": "input_image",
            "detail": part.detail or "auto",
            "image_url": image_url,
        }
    return _lower_input_file(part, content)


def file_output_part_placeholder_text(part: FileOutputPart, *, reason: str) -> str:
    """Create bounded text placeholder describing unsupported FilePart."""
    label = part.name or part.model_file_id
    size = "unknown size" if part.size is None else f"{part.size} bytes"
    return (
        f"[file unavailable for rich input] {label} "
        f"({part.media_type}, {size}). Reason: {reason}."
    )


def _lower_input_file(
    part: FileOutputPart,
    content: ModelFileLoweringContent,
) -> dict[str, object]:
    """Lower FilePart to Responses input_file part."""
    output: dict[str, object] = {"type": "input_file"}
    if content.file_id is not None:
        output["file_id"] = content.file_id
    elif content.file_url is not None:
        output["file_url"] = content.file_url
    elif content.data_url is not None:
        output["file_data"] = content.data_url
    else:
        return _placeholder(
            part, reason="file content is not available in this request"
        )
    if part.name is not None:
        output["filename"] = part.name
    return output


def _within_size_budget(
    part: FileOutputPart,
    capabilities: FilePartLoweringCapabilities,
) -> bool:
    """Return whether FilePart is within model file budget.

    Image FilePart lowers to Responses API ``input_image``, so generic
    ``input_file`` byte budget does not apply. Image blobs are separately
    normalized/degraded by ModelFile creation/retention policy; only non-image
    rich file inputs are limited by ``max_file_bytes``.
    """
    if _is_image_part(part):
        return True
    if part.size is None:
        return True
    return part.size <= capabilities.max_file_bytes


def _supported_by_capability(
    part: FileOutputPart,
    capabilities: FilePartLoweringCapabilities,
) -> bool:
    """Return whether FilePart media type is supported by capability."""
    if _is_image_part(part):
        return capabilities.supports_image_input
    if part.media_type == _PDF_MEDIA_TYPE:
        return capabilities.supports_file_input and capabilities.supports_pdf_input
    if part.media_type.startswith(_TEXT_MEDIA_PREFIX):
        return (
            capabilities.supports_file_input and capabilities.supports_text_file_input
        )
    return False


def _is_image_part(part: FileOutputPart) -> bool:
    """Return whether FilePart is image family."""
    return part.kind == "image" or part.media_type.startswith(_IMAGE_MEDIA_PREFIX)


def _placeholder(part: FileOutputPart, *, reason: str) -> dict[str, object]:
    """Convert unsupported FilePart to bounded text placeholder."""
    return {
        "type": "input_text",
        "text": file_output_part_placeholder_text(part, reason=reason),
    }
