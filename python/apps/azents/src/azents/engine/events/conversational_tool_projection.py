"""Declarative projection of client tools that publish conversation."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from azents.engine.events.output_parts import lower_output_to_text
from azents.engine.events.sensitive_text import (
    redact_sensitive_text,
    sanitize_json_value,
)
from azents.engine.events.types import ClientToolCallPayload, ClientToolResultPayload

ConversationSpeaker = Literal["assistant"]
ConversationDeliveryStatus = Literal["delivered", "failed", "unknown"]
JsonPath = tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class JsonValueExclusion:
    """Exclude a projection when one JSON path has a listed scalar value."""

    path: JsonPath
    values: frozenset[str]


@dataclasses.dataclass(frozen=True)
class JsonArrayStatusSelector:
    """Select a delivery status from one array of JSON objects."""

    array_path: JsonPath
    match_field: str
    match_value: str
    status_field: str


@dataclasses.dataclass(frozen=True)
class ConversationToolProjectionSpec:
    """Declarative participant-visible projection for one durable tool name."""

    durable_tool_name: str
    speaker: ConversationSpeaker
    text_paths: tuple[JsonPath, ...]
    context_paths: tuple[JsonPath, ...]
    exclusions: tuple[JsonValueExclusion, ...]
    result_status: JsonArrayStatusSelector | None


@dataclasses.dataclass(frozen=True)
class ConversationalToolProjection:
    """One semantic conversation item reconstructed from a client-tool call."""

    tool_name: str
    speaker: ConversationSpeaker
    text: str | None
    context: tuple[tuple[str, str], ...]
    delivery_status: ConversationDeliveryStatus | None

    def render(self) -> str:
        """Render the projection as bounded readable historical evidence."""
        qualifiers = [f"tool={self.tool_name}"]
        if self.delivery_status is not None:
            qualifiers.append(f"delivery={self.delivery_status}")
        lines = [f"[Assistant via conversational tool; {'; '.join(qualifiers)}]"]
        if self.text is not None:
            lines.append(self.text)
        if self.context:
            lines.append("Scoped work state:")
            lines.extend(f"- {label}: {value}" for label, value in self.context)
        return "\n".join(lines)


_CHANNEL_ACTION_SPEC = ConversationToolProjectionSpec(
    durable_tool_name="channel_action",
    speaker="assistant",
    text_paths=(("message",),),
    context_paths=(("title",), ("todo_update",)),
    exclusions=(JsonValueExclusion(path=("mode",), values=frozenset({"ignore"})),),
    result_status=JsonArrayStatusSelector(
        array_path=("outcomes",),
        match_field="operation",
        match_value="reply",
        status_field="status",
    ),
)

CONVERSATIONAL_TOOL_PROJECTIONS: Mapping[str, ConversationToolProjectionSpec] = (
    MappingProxyType(
        {
            _CHANNEL_ACTION_SPEC.durable_tool_name: _CHANNEL_ACTION_SPEC,
        }
    )
)


def project_conversational_tool_call(
    call: ClientToolCallPayload,
    result: ClientToolResultPayload | None,
) -> ConversationalToolProjection | None:
    """Project one registered client call into participant-visible conversation."""
    spec = CONVERSATIONAL_TOOL_PROJECTIONS.get(call.name)
    if spec is None or call.wire_dialect != "json_function":
        return None
    arguments = _decode_object(call.arguments)
    if arguments is None or _is_excluded(arguments, spec.exclusions):
        return None

    text = _first_text(arguments, spec.text_paths)
    context = tuple(
        rendered
        for path in spec.context_paths
        if (rendered := _render_context(arguments, path)) is not None
    )
    if text is None and not context:
        return None
    delivery_status = _delivery_status(result, spec.result_status)
    return ConversationalToolProjection(
        tool_name=call.name,
        speaker=spec.speaker,
        text=text,
        context=context,
        delivery_status=delivery_status if text is not None else None,
    )


def _decode_object(source: str) -> dict[str, object] | None:
    try:
        value = json.loads(source)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    return {str(key): item for key, item in value.items()}


def _value_at(value: object, path: JsonPath) -> object | None:
    current = value
    for segment in path:
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _is_excluded(
    arguments: dict[str, object],
    exclusions: tuple[JsonValueExclusion, ...],
) -> bool:
    for exclusion in exclusions:
        value = _value_at(arguments, exclusion.path)
        if isinstance(value, str) and value in exclusion.values:
            return True
    return False


def _first_text(
    arguments: dict[str, object],
    paths: tuple[JsonPath, ...],
) -> str | None:
    for path in paths:
        value = _value_at(arguments, path)
        if isinstance(value, str) and value.strip():
            return redact_sensitive_text(value.strip())
    return None


def _render_context(
    arguments: dict[str, object],
    path: JsonPath,
) -> tuple[str, str] | None:
    value = _value_at(arguments, path)
    if value is None or value == [] or value == {}:
        return None
    label = ".".join(path)
    if isinstance(value, str):
        rendered = redact_sensitive_text(value.strip())
        if not rendered:
            return None
    else:
        rendered = json.dumps(
            sanitize_json_value(value),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    return label, rendered


def _delivery_status(
    result: ClientToolResultPayload | None,
    selector: JsonArrayStatusSelector | None,
) -> ConversationDeliveryStatus | None:
    if selector is None:
        return None
    if result is None:
        return "unknown"
    if result.status == "failed":
        return "failed"
    if result.status != "completed":
        return "unknown"
    payload = _decode_object(lower_output_to_text(result.output))
    if payload is None:
        return "unknown"
    values = _value_at(payload, selector.array_path)
    if not isinstance(values, list):
        return "unknown"
    for value in values:
        if not isinstance(value, dict):
            continue
        if value.get(selector.match_field) != selector.match_value:
            continue
        status = value.get(selector.status_field)
        if status == "delivered":
            return "delivered"
        if status in {"failed", "not_attempted"}:
            return "failed"
        return "unknown"
    return "unknown"
