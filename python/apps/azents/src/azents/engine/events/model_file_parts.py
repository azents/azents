"""Helper for converting ModelFile objects to event FileParts."""

from typing import Literal

from azents.engine.events.types import FileOutputPart
from azents.repos.model_file.data import ModelFile


def file_output_part_from_model_file(
    model_file: ModelFile,
    *,
    metadata: dict[str, str] | None = None,
    caption: str | None = None,
    alt_text: str | None = None,
) -> FileOutputPart:
    """Convert a ModelFile domain model into a durable FilePart."""
    return FileOutputPart(
        model_file_id=model_file.id,
        media_type=model_file.media_type,
        name=model_file.name,
        size=model_file.size_bytes,
        kind=_file_kind(model_file.kind),
        caption=caption,
        alt_text=alt_text,
        metadata=metadata if metadata is not None else {},
    )


def _file_kind(kind: str) -> Literal["image", "document", "text", "binary"]:
    """Narrow a ModelFile kind string to a FilePart kind."""
    match kind:
        case "image":
            return "image"
        case "document":
            return "document"
        case "text":
            return "text"
        case _:
            return "binary"
