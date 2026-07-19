"""Provider-neutral semantic extraction for Responses hosted-tool items."""

import dataclasses
import json
from collections.abc import Callable
from typing import Literal

from azents.core.enums import EventKind
from azents.engine.events.output_parts import enforce_tool_output_text_hard_cap
from azents.engine.events.types import (
    OutputTextPart,
    ProviderToolReference,
    ProviderToolSemanticContent,
    ToolOutput,
    ToolOutputPart,
)

_PROVIDER_INPUT_MAX_CHARS = 30_000
_REFERENCE_MAX_COUNT = 100
_REFERENCE_URI_MAX_CHARS = 4096
_REFERENCE_TITLE_MAX_CHARS = 1000
_REFERENCE_EXCERPT_MAX_CHARS = 4000
_REFERENCE_METADATA_MAX_ENTRIES = 20
_REFERENCE_METADATA_KEY_MAX_CHARS = 100
_REFERENCE_METADATA_VALUE_MAX_CHARS = 1000
_TRUNCATION_SUFFIX = "... [truncated]"

ProviderToolStatus = (
    Literal[
        "running",
        "completed",
        "failed",
        "cancelled",
        "interrupted",
    ]
    | None
)
SemanticExtractor = Callable[[dict[str, object]], ProviderToolSemanticContent]
NameExtractor = Callable[[dict[str, object]], str]


@dataclasses.dataclass(frozen=True)
class ResponsesProviderToolSpec:
    """One recognized Responses hosted-tool output item contract."""

    event_kind: Literal[EventKind.PROVIDER_TOOL_CALL]
    name: str | NameExtractor
    extract: SemanticExtractor

    def resolve_name(self, item: dict[str, object]) -> str:
        """Return the canonical semantic tool name."""
        if isinstance(self.name, str):
            return self.name
        return self.name(item)


@dataclasses.dataclass(frozen=True)
class NormalizedProviderToolItem:
    """Provider-neutral durable hosted-tool item fields."""

    event_kind: Literal[EventKind.PROVIDER_TOOL_CALL]
    name: str
    semantic: ProviderToolSemanticContent


def normalize_responses_provider_tool_item(
    item: dict[str, object],
) -> NormalizedProviderToolItem | None:
    """Normalize one recognized Responses provider-tool output item."""
    item_type = item.get("type")
    if not isinstance(item_type, str):
        return None
    spec = RESPONSES_PROVIDER_TOOL_SPECS.get(item_type)
    if spec is None:
        return None
    return NormalizedProviderToolItem(
        event_kind=spec.event_kind,
        name=spec.resolve_name(item),
        semantic=spec.extract(item),
    )


def provider_tool_semantic_input_content(
    input_value: str | None,
) -> ProviderToolSemanticContent:
    """Return bounded semantic input for provider lifecycle projections."""
    return ProviderToolSemanticContent(
        input=_bounded_text(input_value, _PROVIDER_INPUT_MAX_CHARS),
        output=[],
        references=[],
    )


def _extract_web_search(item: dict[str, object]) -> ProviderToolSemanticContent:
    action = _dict(item.get("action"))
    input_value = _compact_json(
        _allowlisted_values(
            action,
            ("type", "query", "queries", "url", "pattern"),
        )
    )
    sources = action.get("sources")
    references: list[ProviderToolReference] = []
    action_url = _string(action.get("url"))
    if action_url is not None:
        references.append(_reference(kind="url", uri=action_url))
    if isinstance(sources, list):
        for source in sources:
            source_value = _dict(source)
            url = _string(source_value.get("url"))
            if url is None:
                continue
            references.append(_reference(kind="url", uri=url))
    return ProviderToolSemanticContent(
        input=input_value,
        output=[],
        references=_bounded_references(references),
    )


def _extract_file_search(item: dict[str, object]) -> ProviderToolSemanticContent:
    queries = item.get("queries")
    input_value = _compact_json(
        {"queries": [value for value in queries if isinstance(value, str)]}
        if isinstance(queries, list)
        else {}
    )
    output_parts: list[ToolOutputPart] = []
    references: list[ProviderToolReference] = []
    results = item.get("results")
    if isinstance(results, list):
        for result in results:
            value = _dict(result)
            text = _string(value.get("text"))
            filename = _string(value.get("filename"))
            file_id = _string(value.get("file_id"))
            score = _number(value.get("score"))
            if text:
                label = filename or file_id or "File search result"
                output_parts.append(OutputTextPart(text=f"{label}:\n{text}"))
            metadata: dict[str, str] = {}
            if file_id:
                metadata["file_id"] = file_id
            if score is not None:
                metadata["score"] = str(score)
            if filename or file_id or metadata:
                references.append(
                    _reference(
                        kind="file",
                        title=filename,
                        excerpt=text,
                        metadata=metadata,
                    )
                )
    output: ToolOutput = enforce_tool_output_text_hard_cap(output_parts)
    return ProviderToolSemanticContent(
        input=input_value,
        output=output,
        references=_bounded_references(references),
    )


def _extract_code_interpreter(item: dict[str, object]) -> ProviderToolSemanticContent:
    code = _bounded_text(_string(item.get("code")), _PROVIDER_INPUT_MAX_CHARS)
    output_parts: list[ToolOutputPart] = []
    references: list[ProviderToolReference] = []
    outputs = item.get("outputs")
    if isinstance(outputs, list):
        for output in outputs:
            value = _dict(output)
            output_type = value.get("type")
            if output_type == "logs":
                logs = _string(value.get("logs"))
                if logs:
                    output_parts.append(OutputTextPart(text=logs))
                continue
            if output_type == "image":
                url = _string(value.get("url"))
                if url:
                    references.append(
                        _reference(kind="url", uri=url, title="Output image")
                    )
    output_value: ToolOutput = enforce_tool_output_text_hard_cap(output_parts)
    return ProviderToolSemanticContent(
        input=code,
        output=output_value,
        references=_bounded_references(references),
    )


def _extract_image_generation(item: dict[str, object]) -> ProviderToolSemanticContent:
    input_value = _compact_json(
        _allowlisted_values(item, ("action", "prompt", "quality", "size"))
    )
    return ProviderToolSemanticContent(
        input=input_value,
        output=[],
        references=[],
    )


def _extract_mcp(item: dict[str, object]) -> ProviderToolSemanticContent:
    input_value = _compact_json(
        _allowlisted_values(item, ("name", "server_label", "arguments"))
    )
    output_parts: list[ToolOutputPart] = []
    output = _string(item.get("output"))
    error = _string(item.get("error"))
    if output:
        output_parts.append(OutputTextPart(text=output))
    if error:
        output_parts.append(OutputTextPart(text=f"Error: {error}"))
    output_value: ToolOutput = enforce_tool_output_text_hard_cap(output_parts)
    return ProviderToolSemanticContent(
        input=input_value,
        output=output_value,
        references=[],
    )


def _mcp_name(item: dict[str, object]) -> str:
    name = _string(item.get("name"))
    return f"mcp:{name}" if name else "mcp"


def _allowlisted_values(
    value: dict[str, object],
    keys: tuple[str, ...],
) -> dict[str, object]:
    return {key: value[key] for key in keys if _json_safe(value.get(key))}


def _json_safe(value: object) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return value is not None
    if isinstance(value, list):
        return all(_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _json_safe(item) for key, item in value.items()
        )
    return False


def _compact_json(value: dict[str, object]) -> str | None:
    if not value:
        return None
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return _bounded_text(rendered, _PROVIDER_INPUT_MAX_CHARS)


def _bounded_references(
    references: list[ProviderToolReference],
) -> list[ProviderToolReference]:
    return references[:_REFERENCE_MAX_COUNT]


def _reference(
    *,
    kind: Literal["url", "file", "other"],
    uri: str | None = None,
    title: str | None = None,
    excerpt: str | None = None,
    metadata: dict[str, str] | None = None,
) -> ProviderToolReference:
    bounded_metadata = {
        _bounded_text(key, _REFERENCE_METADATA_KEY_MAX_CHARS) or "": (
            _bounded_text(value, _REFERENCE_METADATA_VALUE_MAX_CHARS) or ""
        )
        for key, value in list((metadata or {}).items())[
            :_REFERENCE_METADATA_MAX_ENTRIES
        ]
        if key
    }
    return ProviderToolReference(
        kind=kind,
        uri=_bounded_text(uri, _REFERENCE_URI_MAX_CHARS),
        title=_bounded_text(title, _REFERENCE_TITLE_MAX_CHARS),
        excerpt=_bounded_text(excerpt, _REFERENCE_EXCERPT_MAX_CHARS),
        metadata=bounded_metadata,
    )


def _bounded_text(value: str | None, max_chars: int) -> str | None:
    if value is None or not value:
        return None
    if len(value) <= max_chars:
        return value
    keep_chars = max(0, max_chars - len(_TRUNCATION_SUFFIX))
    return value[:keep_chars].rstrip() + _TRUNCATION_SUFFIX


def _dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int | float) else None


RESPONSES_PROVIDER_TOOL_SPECS: dict[str, ResponsesProviderToolSpec] = {
    "web_search_call": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name="web_search",
        extract=_extract_web_search,
    ),
    "web_search": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name="web_search",
        extract=_extract_web_search,
    ),
    "file_search_call": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name="file_search",
        extract=_extract_file_search,
    ),
    "code_interpreter_call": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name="code_interpreter",
        extract=_extract_code_interpreter,
    ),
    "image_generation_call": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name="image_generation",
        extract=_extract_image_generation,
    ),
    "mcp_call": ResponsesProviderToolSpec(
        event_kind=EventKind.PROVIDER_TOOL_CALL,
        name=_mcp_name,
        extract=_extract_mcp,
    ),
}
