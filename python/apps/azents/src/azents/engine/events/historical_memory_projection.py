"""Bounded source-event projection for Historical Memory extraction."""

from __future__ import annotations

import dataclasses
import enum
import json
from collections.abc import Sequence

from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.events.conversational_tool_projection import (
    project_conversational_tool_call,
)
from azents.engine.events.output_parts import lower_output_to_text
from azents.engine.events.provider_tool_rendering import render_provider_tool_semantic
from azents.engine.events.sensitive_text import (
    redact_sensitive_text,
    sanitize_json_value,
)
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    InputTextPart,
    OutputTextPart,
    ProviderToolCallPayload,
    SystemErrorPayload,
    UserMessagePayload,
)

_BYTES_PER_TOKEN = 4
_ROW_MAX_BYTES = 10_000
_TOOL_OUTPUT_MAX_BYTES = 8_000
_OMITTED = "[... source events omitted ...]"
_TRUNCATED = "\n... [truncated]"


class HistoricalMemoryEvidenceTier(enum.IntEnum):
    """Priority order for source evidence admission."""

    HUMAN = 1
    ASSISTANT = 2
    OTHER_AGENT = 3
    CONTEXT = 4
    TOOL = 5


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryEvidence:
    """One rendered event candidate for source-summary input."""

    event_id: str
    source_index: int
    tier: HistoricalMemoryEvidenceTier
    text: str


@dataclasses.dataclass(frozen=True)
class HistoricalMemoryInputProjection:
    """Bounded chronological source text and selection diagnostics."""

    text: str
    candidate_event_count: int
    selected_event_ids: tuple[str, ...]
    omitted_event_count: int
    selected_tier_counts: tuple[tuple[HistoricalMemoryEvidenceTier, int], ...]


def project_historical_memory_input(
    events: Sequence[Event],
    *,
    token_limit: int,
) -> HistoricalMemoryInputProjection:
    """Select and render Historical Memory source evidence under one token budget."""
    if token_limit < 1:
        raise ValueError("Historical Memory token limit must be positive")
    client_results = {
        payload.call_id: payload
        for event in events
        if isinstance((payload := event.payload), ClientToolResultPayload)
    }
    registered_result_call_ids: set[str] = set()
    candidates: list[HistoricalMemoryEvidence] = []
    for index, event in enumerate(events):
        projected = _project_event(
            event,
            source_index=index,
            client_results=client_results,
            registered_result_call_ids=registered_result_call_ids,
        )
        if projected is not None:
            candidates.append(projected)

    budget = token_limit * _BYTES_PER_TOKEN
    selected = _select_evidence(candidates, budget=budget)
    text = _render_selected(candidates, selected)
    selected_ids = tuple(candidate.event_id for candidate in selected)
    tier_counts = tuple(
        (tier, sum(candidate.tier is tier for candidate in selected))
        for tier in HistoricalMemoryEvidenceTier
        if any(candidate.tier is tier for candidate in selected)
    )
    return HistoricalMemoryInputProjection(
        text=text,
        candidate_event_count=len(candidates),
        selected_event_ids=selected_ids,
        omitted_event_count=len(candidates) - len(selected),
        selected_tier_counts=tier_counts,
    )


def _project_event(
    event: Event,
    *,
    source_index: int,
    client_results: dict[str, ClientToolResultPayload],
    registered_result_call_ids: set[str],
) -> HistoricalMemoryEvidence | None:
    payload = event.payload
    tier: HistoricalMemoryEvidenceTier
    text: str
    if isinstance(payload, UserMessagePayload):
        text = _content_text(payload.content)
        tier = HistoricalMemoryEvidenceTier.HUMAN
        label = "User"
    elif isinstance(payload, ActionMessagePayload):
        text = payload.message
        tier = HistoricalMemoryEvidenceTier.HUMAN
        label = "User action"
    elif isinstance(payload, ExternalChannelMessagePayload):
        if payload.prompt_role != "invocation":
            return None
        sender = payload.sender_display_name or payload.provider_user_id or "unknown"
        timestamp = payload.provider_updated_at or payload.provider_created_at
        metadata = [
            f"Provider: {payload.provider.value}",
            f"Resource: {payload.resource_label}",
            f"Sender: {sender} ({payload.author_type.value})",
        ]
        if timestamp is not None:
            metadata.append(f"Timestamp: {timestamp.isoformat()}")
        text = "\n".join([*metadata, "Body:", payload.body or "[No text content]"])
        tier = HistoricalMemoryEvidenceTier.HUMAN
        label = "External Channel invocation"
    elif isinstance(payload, AssistantMessagePayload):
        text = _content_text(payload.content)
        tier = HistoricalMemoryEvidenceTier.ASSISTANT
        label = "Assistant"
    elif isinstance(payload, AgentMessagePayload):
        text = payload.content
        tier = HistoricalMemoryEvidenceTier.OTHER_AGENT
        label = f"Other agent {payload.message_kind}"
    elif isinstance(payload, ClientToolCallPayload):
        result = client_results.get(payload.call_id)
        conversation = project_conversational_tool_call(payload, result)
        if conversation is not None:
            if result is not None:
                registered_result_call_ids.add(result.call_id)
            text = conversation.render()
            tier = HistoricalMemoryEvidenceTier.ASSISTANT
            label = "Agent conversation"
        else:
            text = _render_client_call(payload)
            tier = HistoricalMemoryEvidenceTier.TOOL
            label = "Client tool"
    elif isinstance(payload, ClientToolResultPayload):
        if payload.call_id in registered_result_call_ids:
            return None
        text = _render_client_result(payload)
        tier = HistoricalMemoryEvidenceTier.TOOL
        label = "Client tool result"
    elif isinstance(payload, ProviderToolCallPayload):
        text = _render_provider_tool(payload)
        tier = HistoricalMemoryEvidenceTier.TOOL
        label = "Provider tool"
    elif isinstance(payload, SystemErrorPayload):
        text = payload.content
        tier = HistoricalMemoryEvidenceTier.CONTEXT
        label = "System error"
    else:
        return None
    if not text.strip():
        return None
    rendered = _truncate_utf8(
        f"[{label}]\n{redact_sensitive_text(text.strip())}",
        max_bytes=_ROW_MAX_BYTES,
    )
    return HistoricalMemoryEvidence(
        event_id=event.id,
        source_index=source_index,
        tier=tier,
        text=rendered,
    )


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        part.text
        for part in content
        if isinstance(part, InputTextPart | OutputTextPart)
    )


def _render_client_call(payload: ClientToolCallPayload) -> str:
    if payload.wire_dialect == "plaintext_custom":
        return f"{payload.name} (plaintext custom input omitted)"
    try:
        decoded = json.loads(payload.arguments)
    except json.JSONDecodeError:
        return f"{payload.name} (invalid JSON input omitted)"
    sanitized = sanitize_json_value(decoded)
    rendered = json.dumps(
        sanitized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{payload.name}({rendered})"


def _render_client_result(payload: ClientToolResultPayload) -> str:
    output = _truncate_utf8(
        redact_sensitive_text(lower_output_to_text(payload.output)),
        max_bytes=_TOOL_OUTPUT_MAX_BYTES,
    )
    header = f"{payload.name or 'unknown'} {payload.status}"
    return f"{header}\n{output}" if output else header


def _render_provider_tool(payload: ProviderToolCallPayload) -> str:
    return _truncate_utf8(
        redact_sensitive_text(render_provider_tool_semantic(payload)),
        max_bytes=_TOOL_OUTPUT_MAX_BYTES,
    )


def _select_evidence(
    candidates: Sequence[HistoricalMemoryEvidence],
    *,
    budget: int,
) -> list[HistoricalMemoryEvidence]:
    selected_indexes: set[int] = set()
    selected_overrides: dict[int, str] = {}
    minimum_truncated_size = len(_TRUNCATED.encode()) + 8
    for tier in HistoricalMemoryEvidenceTier:
        for index in range(len(candidates) - 1, -1, -1):
            candidate = candidates[index]
            if candidate.tier is not tier:
                continue
            trial_indexes = selected_indexes | {index}
            full_size = _rendered_size(
                candidates,
                selected_indexes=trial_indexes,
                selected_overrides=selected_overrides,
            )
            if full_size <= budget:
                selected_indexes.add(index)
                continue
            current_size = _rendered_size(
                candidates,
                selected_indexes=selected_indexes,
                selected_overrides=selected_overrides,
            )
            if budget - current_size < minimum_truncated_size:
                continue
            fixed_size = _rendered_size(
                candidates,
                selected_indexes=trial_indexes,
                selected_overrides={**selected_overrides, index: ""},
            )
            available = budget - fixed_size
            if available < minimum_truncated_size:
                continue
            truncated = _truncate_utf8(candidate.text, max_bytes=available)
            if not truncated:
                continue
            selected_indexes.add(index)
            selected_overrides[index] = truncated
            return _materialize_selected(
                candidates,
                selected_indexes=selected_indexes,
                selected_overrides=selected_overrides,
            )
    return _materialize_selected(
        candidates,
        selected_indexes=selected_indexes,
        selected_overrides=selected_overrides,
    )


def _rendered_size(
    candidates: Sequence[HistoricalMemoryEvidence],
    *,
    selected_indexes: set[int],
    selected_overrides: dict[int, str],
) -> int:
    selected = _materialize_selected(
        candidates,
        selected_indexes=selected_indexes,
        selected_overrides=selected_overrides,
    )
    return len(_render_selected(candidates, selected).encode())


def _materialize_selected(
    candidates: Sequence[HistoricalMemoryEvidence],
    *,
    selected_indexes: set[int],
    selected_overrides: dict[int, str],
) -> list[HistoricalMemoryEvidence]:
    selected: list[HistoricalMemoryEvidence] = []
    for index in sorted(selected_indexes):
        candidate = candidates[index]
        override = selected_overrides.get(index)
        selected.append(
            candidate
            if override is None
            else dataclasses.replace(candidate, text=override)
        )
    return selected


def _render_selected(
    candidates: Sequence[HistoricalMemoryEvidence],
    selected: Sequence[HistoricalMemoryEvidence],
) -> str:
    if not selected:
        return ""
    selected_by_index = {candidate.source_index: candidate for candidate in selected}
    lines: list[str] = []
    omitted = False
    for candidate in candidates:
        selected_candidate = selected_by_index.get(candidate.source_index)
        if selected_candidate is None:
            if not omitted:
                lines.append(_OMITTED)
                omitted = True
            continue
        lines.append(selected_candidate.text)
        omitted = False
    return "\n".join(lines)


def _truncate_utf8(value: str, *, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = value.encode()
    if len(encoded) <= max_bytes:
        return value
    note = _TRUNCATED.encode()
    if max_bytes <= len(note):
        return encoded[:max_bytes].decode(errors="ignore")
    prefix = encoded[: max_bytes - len(note)].decode(errors="ignore").rstrip()
    return f"{prefix}{_TRUNCATED}"
