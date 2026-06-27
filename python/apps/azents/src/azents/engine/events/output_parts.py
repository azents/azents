"""Event tool output part helper."""

from collections.abc import Iterable

from azents.engine.events.types import (
    ArtifactOutputPart,
    AttachmentOutputPart,
    FileOutputPart,
    OutputTextPart,
    ToolOutput,
    ToolOutputPart,
)

TOOL_OUTPUT_TEXT_HARD_CAP_CHARS = 30_000
_TOOL_OUTPUT_TRUNCATION_PREFIX = "... (truncated)\n"


def iter_output_parts(output: ToolOutput) -> Iterable[ToolOutputPart]:
    """Iterate Tool output as part stream."""
    if isinstance(output, str):
        yield OutputTextPart(text=output)
        return
    yield from output


def append_output_part(output: ToolOutput, part: ToolOutputPart) -> ToolOutput:
    """Add part to Tool output."""
    if isinstance(output, str):
        return [OutputTextPart(text=output), part]
    return [*output, part]


def enforce_tool_output_text_hard_cap(
    output: ToolOutput,
    *,
    max_chars: int = TOOL_OUTPUT_TEXT_HARD_CAP_CHARS,
) -> ToolOutput:
    """Apply global hard cap to Tool output text."""
    if isinstance(output, str):
        return _truncate_text_tail(output, max_chars=max_chars)

    remaining = max_chars
    truncated = False
    kept_reversed: list[ToolOutputPart] = []
    for part in reversed(output):
        if not isinstance(part, OutputTextPart):
            kept_reversed.append(part)
            continue
        if remaining <= 0:
            truncated = True
            continue
        if len(part.text) <= remaining:
            kept_reversed.append(part)
            remaining -= len(part.text)
            continue
        kept_reversed.append(OutputTextPart(text=part.text[-remaining:]))
        remaining = 0
        truncated = True

    kept = list(reversed(kept_reversed))
    if not truncated:
        return kept
    return _prepend_truncation_marker(kept)


def output_text_preview(output: ToolOutput, max_chars: int) -> str:
    """Return bounded text preview of Tool output."""
    text = lower_output_to_text(output)
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}... [truncated]"


def lower_output_to_text(output: ToolOutput) -> str:
    """Lower Tool output to model-visible text."""
    texts: list[str] = []
    for part in iter_output_parts(output):
        if isinstance(part, OutputTextPart):
            texts.append(part.text)
        elif isinstance(part, AttachmentOutputPart):
            texts.append(_attachment_text(part))
        elif isinstance(part, ArtifactOutputPart):
            texts.append(_artifact_text(part))
        elif isinstance(part, FileOutputPart):
            texts.append(_file_text(part))
    return "\n".join(text for text in texts if text)


def _truncate_text_tail(text: str, *, max_chars: int) -> str:
    """Preserve tail when text exceeds maximum length."""
    if len(text) <= max_chars:
        return text
    return _TOOL_OUTPUT_TRUNCATION_PREFIX + text[-max_chars:]


def _prepend_truncation_marker(parts: list[ToolOutputPart]) -> list[ToolOutputPart]:
    """Add truncation marker to first text part."""
    for index, part in enumerate(parts):
        if isinstance(part, OutputTextPart):
            return [
                *parts[:index],
                OutputTextPart(text=_TOOL_OUTPUT_TRUNCATION_PREFIX + part.text),
                *parts[index + 1 :],
            ]
    return [OutputTextPart(text=_TOOL_OUTPUT_TRUNCATION_PREFIX), *parts]


def _attachment_text(part: AttachmentOutputPart) -> str:
    """Convert attachment output part to text metadata."""
    status = (
        ""
        if part.availability == "available"
        else f"\nStatus: {part.availability}; no longer accessible"
    )
    preview = ""
    if part.preview_title or part.preview_summary:
        preview_values = [v for v in [part.preview_title, part.preview_summary] if v]
        preview = "\nPreview: " + " — ".join(preview_values)
    return (
        f"Attachment: {part.name} ({part.media_type}, {part.size} bytes)\n"
        f"URI: {part.uri}{preview}{status}"
    )


def _artifact_text(part: ArtifactOutputPart) -> str:
    """Convert artifact output part to text metadata."""
    if part.status == "expired":
        return (
            f"Artifact: {part.name} ({part.media_type}, {part.size} bytes)\n"
            f"URI: {part.uri}\nStatus: expired; no longer accessible"
        )
    suffix = ""
    if part.expires_at is not None:
        suffix = f"\nExpires at: {part.expires_at.isoformat()}"
    return (
        f"Artifact: {part.name} ({part.media_type}, {part.size} bytes)\n"
        f"URI: {part.uri}{suffix}"
    )


def _file_text(part: FileOutputPart) -> str:
    """Convert FilePart to rich input fallback text."""
    first_line = f"File: {part.name or part.model_file_id} ({part.media_type}"
    if part.size is not None:
        first_line += f", {part.size} bytes"
    first_line += ")"
    values = [first_line]
    if part.caption:
        values.append(f"Caption: {part.caption}")
    if part.alt_text:
        values.append(f"Alt text: {part.alt_text}")
    values.append(
        "Status: file content is not available to this model in rich input form"
    )
    return "\n".join(values)
