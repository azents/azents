"""Deterministic model, hosted-tool, Imagine, and xAI OAuth proxy."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode, urlsafe_b64encode
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import (
    ClassVar,
    Literal,
    NamedTuple,
    Protocol,
    assert_never,
    runtime_checkable,
)
from urllib.parse import parse_qs, urlsplit

_PROMPT = "Provider image generation handoff"
_EXPLICIT_IMAGE_PROMPT = "Provider image generation explicit pin handoff"
_FOLLOW_UP_PROMPT = "Provider image generation follow-up"
_OPENAI_IMAGE_PROMPT = "A deterministic OpenAI image"
_OPENAI_IMAGE_CALL_ID = "call_openai_image_generation"
_BRAVE_PROMPT_PREFIX = "Brave Search E2E "
_BRAVE_KINDS = ("web", "context", "news", "images", "videos")
_SEMANTIC_PROMPT = "Provider semantic web search handoff"
_SEMANTIC_SAME_NATIVE_PROMPT = "Provider semantic same-native follow-up"
_SEMANTIC_CROSS_NATIVE_PROMPT = "Provider semantic cross-native follow-up"
_SEMANTIC_POST_COMPACTION_PROMPT = "Provider semantic post-compaction follow-up"
_SEMANTIC_QUERY = "Azents provider semantic transcript"
_SEMANTIC_SOURCE_URL = "https://example.com/provider-semantic-transcript"
_SEMANTIC_RESPONSE = "PROVIDER_SEMANTIC_WEB_SEARCH_COMPLETED"
_SEMANTIC_SAME_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_SAME_NATIVE_COMPLETED"
_SEMANTIC_CROSS_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_CROSS_NATIVE_COMPLETED"
_SEMANTIC_POST_COMPACTION_RESPONSE = "PROVIDER_SEMANTIC_POST_COMPACTION_COMPLETED"
_SEMANTIC_ITEM_ID = "search_provider_semantic"
_PROVIDER_TOOL_LIVE_PROMPT = "Provider tool live activity handoff"
_PROVIDER_TOOL_LIVE_QUERY = "provider-neutral live activity"
_PROVIDER_TOOL_LIVE_RESPONSE = "PROVIDER_TOOL_LIVE_ACTIVITY_COMPLETED"
_PROVIDER_TOOL_LIVE_ITEM_ID = "search_provider_tool_live"
_PROVIDER_TOOL_LIVE_BARRIER_PATH = "/v1/_provider_tool_live_barrier"
_PROVIDER_TOOL_LIVE_BARRIER_RELEASE_PATH = f"{_PROVIDER_TOOL_LIVE_BARRIER_PATH}/release"
_PROVIDER_TOOL_LIVE_BARRIER_TIMEOUT_SECONDS = 60.0
_INFERENCE_PROFILE_PREFIX = "Ultrafast E2E "
_INFERENCE_PROFILE_BARRIER_PATH = "/v1/_inference_profile_barrier"
_INFERENCE_PROFILE_TIERS: dict[str, str | None] = {
    "served-ultrafast": "ultrafast",
    "missing-tier": None,
    "served-default": "default",
    "served-priority": "priority",
    "retry": "ultrafast",
    "rejected": None,
    "prepared": "ultrafast",
    "queued": "default",
}
_COMPACTION_SYSTEM_PREFIX = (
    "You are a context compaction engine for a long-running agent."
)
_COMPACTION_SUMMARY = f"""## Active Objective
Preserve provider-hosted tool semantics across compaction.

## Current Execution State
- Web search query: {_SEMANTIC_QUERY}
- Source: {_SEMANTIC_SOURCE_URL}
- Assistant answer: {_SEMANTIC_RESPONSE}

## Next Actions
- Continue the deterministic provider semantic transcript verification.
"""

_HISTORICAL_MEMORY_PREFIX = "Historical Memory E2E "
_HISTORICAL_MEMORY_INSPECT_PREFIX = f"{_HISTORICAL_MEMORY_PREFIX}inspect "
_HISTORICAL_MEMORY_SUMMARY = (
    "User correction: retain the approved blue rollout, not the Agent's red proposal.\n"
    "Evidence: the source reports a passed local check, not a production deployment.\n"
    "Unfinished work: verify the pending rollout before release.\n"
    "Delivery uncertainty: no external completion is verified."
)


_CONSOLIDATION_TASK_MARKER = (
    "You are an internal historical-context consolidation Agent."
)
_CONSOLIDATION_SENTINEL = re.compile(r"AGENTIC_(?:TEAM|PERSONAL)_[a-zA-Z0-9]+_V[0-9]+")
_CONSOLIDATION_WORK = re.compile(
    r"- Work ([0-9a-f]{32}); (?:prepared|removed|restored); "
    r"(azents://memory/historical/(team|user)/[0-9a-f]{32}/summary\.md)"
)


class ConsolidationFixtureWork(NamedTuple):
    """An exact presented identity parsed only from this execution's result."""

    work_id: str
    uri: str
    scope: str


class ConsolidationFixtureCall(NamedTuple):
    call_id: str
    name: str
    arguments: dict[str, object]


class ConsolidationFixturePlan(NamedTuple):
    call: ConsolidationFixtureCall | None
    final_text: str | None


class ConsolidationFixtureContinuation(NamedTuple):
    chain_id: str
    input_items: list[dict[str, object]]


class ConsolidationFixtureRequest(NamedTuple):
    chain_id: str
    request: dict[str, object]


def is_consolidation_fixture_request(request: dict[str, object]) -> bool:
    """Match the closed internal host rather than foreground Memory tools."""
    instructions = request.get("instructions")
    names = {
        name
        for tool in _list(request.get("tools", []))
        if isinstance(tool, dict) and isinstance(name := tool.get("name"), str)
    }
    return (
        isinstance(instructions, str)
        and _CONSOLIDATION_TASK_MARKER in instructions
        and {"read", "write", "edit"} <= names
        and names <= {"read", "write", "edit", "delete", "glob", "grep", "apply_patch"}
    )


def consolidation_fixture_request(
    request: dict[str, object],
    continuations: Mapping[str, ConsolidationFixtureContinuation],
    *,
    new_chain_id: str,
) -> ConsolidationFixtureRequest:
    """Emulate provider stored context without mixing logical executions."""
    inputs = [_object(item) for item in _list(request.get("input", []))]
    previous = request.get("previous_response_id")
    if isinstance(previous, str) and previous.startswith("resp_consolidation_"):
        stored = continuations.get(previous)
        if stored is None:
            raise ValueError("Consolidation fixture context is unavailable.")
        return ConsolidationFixtureRequest(
            stored.chain_id, {**request, "input": [*stored.input_items, *inputs]}
        )
    identifiers = {
        call_id.rsplit("_", 1)[-1]
        for item in inputs
        if isinstance(call_id := item.get("call_id"), str)
        and call_id.startswith("call_consolidation_")
    }
    if len(identifiers) > 1:
        raise ValueError("Consolidation fixture mixes execution identities.")
    chain_id = next(iter(identifiers), new_chain_id)
    return ConsolidationFixtureRequest(chain_id, {**request, "input": inputs})


def consolidation_fixture_plan(
    request: dict[str, object], *, chain_id: str
) -> ConsolidationFixturePlan:
    """Choose real file-tool rounds from returned own-scope evidence."""
    outputs: dict[str, str] = {}
    for raw in _list(request.get("input", [])):
        item = _object(raw)
        if item.get("type") != "function_call_output":
            continue
        call_id, output = item.get("call_id"), item.get("output")
        if not isinstance(call_id, str) or not call_id.startswith(
            "call_consolidation_"
        ):
            continue
        if not call_id.endswith(f"_{chain_id}") or not isinstance(output, str):
            raise ValueError("Consolidation fixture result is invalid.")
        stage = call_id.removeprefix("call_consolidation_").removesuffix(f"_{chain_id}")
        outputs[stage] = output

    def call(
        stage: str, name: str, arguments: dict[str, object]
    ) -> ConsolidationFixturePlan:
        return ConsolidationFixturePlan(
            ConsolidationFixtureCall(
                f"call_consolidation_{stage}_{chain_id}", name, arguments
            ),
            None,
        )

    def read(stage: str, path: str) -> ConsolidationFixturePlan:
        return call(
            stage,
            "read",
            {"path": path, "offset": 0, "limit": 10000, "encoding": "utf-8"},
        )

    if "work" not in outputs:
        return read("work", "azents://memory/inventory/work/README.md")
    work = [
        ConsolidationFixtureWork(match.group(1), match.group(2), match.group(3))
        for match in _CONSOLIDATION_WORK.finditer(outputs["work"])
    ]
    if len({entry.scope for entry in work}) > 1:
        raise ValueError("Consolidation inventory crosses a scope boundary.")
    if "draft" not in outputs:
        return read("draft", "azents://memory-draft/summary.md")
    if "coverage" not in outputs:
        return read("coverage", "azents://memory-draft/coverage.json")
    for index, entry in enumerate(work):
        if f"source{index}" not in outputs:
            return read(f"source{index}", entry.uri)
    useful = [
        (entry, outputs[f"source{index}"])
        for index, entry in enumerate(work)
        if _CONSOLIDATION_SENTINEL.search(outputs[f"source{index}"])
    ]
    if not useful:
        return ConsolidationFixturePlan(None, "UNSUPPORTED_CONSOLIDATION_FIXTURE")
    context = "\n".join(
        re.sub(r"azents://[^\s\"'`]+", "[source route below]", text)[:1200]
        for _entry, text in useful
    )
    routes = "\n".join(
        f"- {entry.uri} — Correction and unfinished-work evidence"
        for entry, _text in useful
    )
    markdown = (
        "## Historical Context\nConsolidation working draft\n"
        f"{context}\n\n## Source Routes\n{routes}\n"
    )
    if "write_summary" not in outputs:
        return call(
            "write_summary",
            "write",
            {
                "path": "azents://memory-draft/summary.md",
                "content": markdown,
                "overwrite": "## Historical Context" in outputs["draft"],
            },
        )
    if "observe_summary" not in outputs:
        if not outputs["write_summary"].startswith("VFS write committed:"):
            if "refresh_draft" not in outputs:
                return read("refresh_draft", "azents://memory-draft/summary.md")
            if "retry_write_summary" not in outputs:
                return call(
                    "retry_write_summary",
                    "write",
                    {
                        "path": "azents://memory-draft/summary.md",
                        "content": markdown,
                        "overwrite": "## Historical Context"
                        in outputs["refresh_draft"],
                    },
                )
            if not outputs["retry_write_summary"].startswith("VFS write committed:"):
                raise ValueError("Consolidation fixture could not author its draft.")
        return read("observe_summary", "azents://memory-draft/summary.md")
    if "bad_edit" not in outputs:
        return call(
            "bad_edit",
            "edit",
            {
                "path": "azents://memory-draft/summary.md",
                "old_string": "ABSENT_CONSOLIDATION_FIXTURE_MATCH",
                "new_string": "Unreachable replacement",
                "replace_all": False,
            },
        )
    if "repair_edit" not in outputs:
        return call(
            "repair_edit",
            "edit",
            {
                "path": "azents://memory-draft/summary.md",
                "old_string": "Consolidation working draft",
                "new_string": "Source-dependent integrated context",
                "replace_all": False,
            },
        )
    if "observe_coverage" not in outputs:
        return read("observe_coverage", "azents://memory-draft/coverage.json")
    if "write_coverage" not in outputs:
        useful_ids = {entry.work_id for entry, _text in useful}
        coverage = {
            "dispositions": [
                {
                    "work_id": entry.work_id,
                    "action": "considered"
                    if entry.work_id in useful_ids
                    else "omitted",
                    "reason": "Integrated source-dependent evidence"
                    if entry.work_id in useful_ids
                    else "Empty or unavailable synthetic summary",
                }
                for entry in work
            ]
        }
        return call(
            "write_coverage",
            "write",
            {
                "path": "azents://memory-draft/coverage.json",
                "content": json.dumps(coverage, ensure_ascii=False),
                "overwrite": '"dispositions"' in outputs["observe_coverage"],
            },
        )
    if "verify" not in outputs:
        return read("verify", "azents://memory-draft/summary.md")
    return ConsolidationFixturePlan(
        None, "CONSOLIDATION_FIXTURE_FINISHED_NOT_THE_PUBLICATION_BODY"
    )


def historical_memory_summary_response(request: _ModelRequestInput) -> str | None:
    """Match isolated Historical fixtures and enforce the real strict schema."""
    request = _decode_model_request(request)
    format_value = request.historical_format
    if format_value is None or format_value.name != "historical_memory":
        return None
    source = request.input_json
    if _HISTORICAL_MEMORY_PREFIX not in source:
        return None
    if (
        format_value.kind != "json_schema"
        or not format_value.strict
        or not format_value.summary_schema
    ):
        raise ValueError("Historical fixture requires the strict one-field schema.")
    if f"{_HISTORICAL_MEMORY_PREFIX}empty" in source:
        return '{"summary":""}'
    if f"{_HISTORICAL_MEMORY_PREFIX}malformed" in source:
        return '{"summary":42,"unexpected":true}'
    if f"{_HISTORICAL_MEMORY_PREFIX}oversized" in source:
        return json.dumps({"summary": "Bounded evidence " * 1_000})
    sentinels = tuple(dict.fromkeys(_CONSOLIDATION_SENTINEL.findall(source)))
    suffix = "\nSynthetic scope evidence: " + " ".join(sentinels) if sentinels else ""
    return json.dumps({"summary": _HISTORICAL_MEMORY_SUMMARY + suffix})


class HistoricalMemoryInspection(NamedTuple):
    """One deterministic generic-read call with explicit field identity."""

    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class _HistoricalInspectionControl:
    """The local read/glob/grep fixture protocol, including its optional nonce."""

    operation: Literal["read", "glob", "grep"]
    path: str
    nonce: str | None


def _decode_historical_inspection_control(text: str) -> _HistoricalInspectionControl:
    payload = _object(json.loads(text))
    required = {"operation", "path"}
    if not required <= payload.keys() or payload.keys() - required - {"nonce"}:
        raise ValueError("Historical inspection requires one read/glob/grep location.")
    path = payload["path"]
    nonce = payload.get("nonce")
    if not isinstance(path, str) or (nonce is not None and not isinstance(nonce, str)):
        raise ValueError("Historical inspection requires one read/glob/grep location.")
    match payload["operation"]:
        case "read":
            return _HistoricalInspectionControl("read", path, nonce)
        case "glob":
            return _HistoricalInspectionControl("glob", path, nonce)
        case "grep":
            return _HistoricalInspectionControl("grep", path, nonce)
        case _:
            raise ValueError(
                "Historical inspection requires one read/glob/grep location."
            )


def historical_memory_inspection(
    request: _ModelRequestInput,
) -> HistoricalMemoryInspection | None:
    """Match one current read/glob/grep fixture without historical-call bleed."""
    user_text = _last_user_text(request)
    if not isinstance(user_text, str) or not user_text.startswith(
        _HISTORICAL_MEMORY_INSPECT_PREFIX
    ):
        return None
    control = _decode_historical_inspection_control(
        user_text[len(_HISTORICAL_MEMORY_INSPECT_PREFIX) :]
    )
    name, path = control.operation, control.path
    call_id = f"call_historical_memory_{sha256(user_text.encode()).hexdigest()[:16]}"
    arguments: dict[str, object]
    if name == "glob":
        arguments = {"pattern": path}
    elif name == "grep":
        arguments = {"path": path, "pattern": "blue"}
    else:
        arguments = {"path": path}
    return HistoricalMemoryInspection(
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


class _DynamicWorktreeScenario(NamedTuple):
    """Dynamic worktree operation, exact path, and force flag."""

    operation: str
    path: str
    force: bool


@runtime_checkable
class _ChunkReadable(Protocol):
    """Response stream that exposes a non-blocking buffered chunk read."""

    def read1(self, size: int = -1) -> bytes:
        """Read at most one buffered chunk."""
        ...


def _object(value: object) -> dict[str, object]:
    """Validate one request or provider object with string keys."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("Expected an object with string keys.")
    return value


def _list(value: object) -> list[object]:
    """Validate one request or provider list."""
    if not isinstance(value, list):
        raise ValueError("Expected a list.")
    return value


@dataclass(frozen=True)
class _ToolOutputObservation:
    """A tool result identity and its consumed diagnostic text."""

    call_id: str
    kind: str | None
    output_text: str | None


@dataclass(frozen=True)
class _ModelInputItem:
    """The fields used for matching one extensible provider input item."""

    object_item: bool
    role: str | None
    kind: str | None
    call_id_present: bool
    call_id: str | None
    tool_call_id: str | None
    text: str | None
    tool_outputs: tuple[_ToolOutputObservation, ...]
    wire_json: str

    @property
    def effective_call_id(self) -> str | None:
        return self.call_id if self.call_id_present else self.tool_call_id


@dataclass(frozen=True)
class _NamedTool:
    name: str | None
    kind: str | None


@dataclass(frozen=True)
class _HistoricalSummaryFormat:
    name: str | None
    kind: str | None
    strict: bool
    summary_schema: bool


@dataclass(frozen=True)
class _PreparedMatcherContext:
    """Local matcher fields are explicit and independent of provider wire data."""

    generation_present: bool
    generation: int | None
    turn: str | None
    flow: str | None
    reference_tokens: tuple[str, ...]
    reference_tokens_are_tuple: bool
    observed_stages: tuple[str, ...]
    request_key: str | None


@dataclass(frozen=True)
class _ModelRequest:
    """Validated matching fields alongside opaque provider snapshots for egress."""

    model: str | None
    stream: bool
    instructions: str | None
    previous_response_id: str | None
    input_text: str | None
    responses_input_present: bool
    input_items: tuple[_ModelInputItem, ...] | None
    input_strings: tuple[str, ...]
    input_json: str
    named_tools: tuple[_NamedTool, ...]
    tools_json: str
    tool_outputs: tuple[_ToolOutputObservation, ...]
    historical_format: _HistoricalSummaryFormat | None
    context: _PreparedMatcherContext | None
    matching_text: str
    matching_ascii_text: str
    matching_sorted_text: str
    request_fingerprint: str
    wire_json: str


type _ModelRequestInput = _ModelRequest | dict[str, object]


def _optional_string(value: object) -> str | None:
    """Unsupported optional provider fields do not participate in local matching."""
    return value if isinstance(value, str) else None


def _decode_string_leaves(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        return tuple(
            text
            for child in _object(value).values()
            for text in _decode_string_leaves(child)
        )
    if isinstance(value, list):
        return tuple(
            text for child in _list(value) for text in _decode_string_leaves(child)
        )
    return ()


def _decode_tool_outputs(value: object) -> tuple[_ToolOutputObservation, ...]:
    """Validate the consumed identities while allowing provider-owned extra fields."""
    outputs: list[_ToolOutputObservation] = []
    if isinstance(value, dict):
        payload = _object(value)
        kind = _optional_string(payload.get("type"))
        call_id = _optional_string(payload.get("call_id"))
        text = _optional_string(payload.get("output"))
        if (
            kind in {"function_call_output", "custom_tool_call_output"}
            and call_id is not None
        ):
            outputs.append(_ToolOutputObservation(call_id, kind, text))
        tool_call_id = _optional_string(payload.get("tool_call_id"))
        if payload.get("role") == "tool" and tool_call_id is not None:
            outputs.append(_ToolOutputObservation(tool_call_id, None, text))
        for child in payload.values():
            outputs.extend(_decode_tool_outputs(child))
    elif isinstance(value, list):
        for child in _list(value):
            outputs.extend(_decode_tool_outputs(child))
    return tuple(outputs)


def _decode_model_input_item(value: object) -> _ModelInputItem:
    payload = _object(value) if isinstance(value, dict) else {}
    content = payload.get("content")
    text: str | None = None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts: list[str] = []
        for raw in _list(content):
            if not isinstance(raw, dict):
                continue
            part = _object(raw)
            part_text = part.get("text")
            if part.get("type") in {"input_text", "text"} and isinstance(
                part_text, str
            ):
                parts.append(part_text)
        text = "".join(parts)
    return _ModelInputItem(
        object_item=isinstance(value, dict),
        role=_optional_string(payload.get("role")),
        kind=_optional_string(payload.get("type")),
        call_id_present="call_id" in payload,
        call_id=_optional_string(payload.get("call_id")),
        tool_call_id=_optional_string(payload.get("tool_call_id")),
        text=text,
        tool_outputs=_decode_tool_outputs(value),
        wire_json=json.dumps(value),
    )


def _decode_historical_format(value: object) -> _HistoricalSummaryFormat | None:
    if not isinstance(value, dict):
        return None
    text = _object(value)
    raw_format = text.get("format")
    if not isinstance(raw_format, dict):
        return None
    format_value = _object(raw_format)
    raw_schema = format_value.get("schema")
    schema = _object(raw_schema) if isinstance(raw_schema, dict) else {}
    return _HistoricalSummaryFormat(
        name=_optional_string(format_value.get("name")),
        kind=_optional_string(format_value.get("type")),
        strict=format_value.get("strict") is True,
        summary_schema=(
            schema.get("additionalProperties") is False
            and schema.get("required") == ["summary"]
            and isinstance(schema.get("properties"), dict)
            and set(_object(schema["properties"])) == {"summary"}
        ),
    )


def _decode_matcher_context(
    payload: dict[str, object],
) -> _PreparedMatcherContext | None:
    fields = {
        "_external_channel_fixture_generation",
        "_external_channel_fixture_turn",
        "_external_channel_fixture_flow",
        "_external_channel_fixture_reference_tokens",
        "_external_channel_fixture_observed_stages",
        "_external_channel_fixture_request_key",
    }
    if fields.isdisjoint(payload):
        return None
    generation = payload.get("_external_channel_fixture_generation")
    references = payload.get("_external_channel_fixture_reference_tokens")
    stages = payload.get("_external_channel_fixture_observed_stages")
    return _PreparedMatcherContext(
        generation_present="_external_channel_fixture_generation" in payload,
        generation=(
            generation
            if isinstance(generation, int) and not isinstance(generation, bool)
            else None
        ),
        turn=_optional_string(payload.get("_external_channel_fixture_turn")),
        flow=_optional_string(payload.get("_external_channel_fixture_flow")),
        reference_tokens=(
            tuple(item for item in references if isinstance(item, str))
            if isinstance(references, list | tuple)
            else ()
        ),
        reference_tokens_are_tuple=isinstance(references, tuple),
        observed_stages=(
            tuple(item for item in stages if isinstance(item, str))
            if isinstance(stages, list)
            else ()
        ),
        request_key=_optional_string(
            payload.get("_external_channel_fixture_request_key")
        ),
    )


def _decode_model_request(value: object) -> _ModelRequest:
    """Project matching fields while retaining provider compatibility at egress."""
    if isinstance(value, _ModelRequest):
        return value
    payload = _object(value)
    input_value = payload.get("input", payload.get("messages"))
    tools = payload.get("tools")
    named_tools: list[_NamedTool] = []
    if isinstance(tools, list):
        for raw in _list(tools):
            if isinstance(raw, dict):
                tool = _object(raw)
                named_tools.append(
                    _NamedTool(
                        _optional_string(tool.get("name")),
                        _optional_string(tool.get("type")),
                    )
                )
    return _ModelRequest(
        model=_optional_string(payload.get("model")),
        stream=payload.get("stream") is True,
        instructions=_optional_string(payload.get("instructions")),
        previous_response_id=_optional_string(payload.get("previous_response_id")),
        input_text=input_value if isinstance(input_value, str) else None,
        responses_input_present=isinstance(payload.get("input"), list),
        input_items=(
            tuple(_decode_model_input_item(item) for item in _list(input_value))
            if isinstance(input_value, list)
            else None
        ),
        input_strings=_decode_string_leaves(input_value),
        input_json=json.dumps(payload.get("input"), ensure_ascii=False),
        named_tools=tuple(named_tools),
        tools_json=json.dumps(payload.get("tools", [])),
        tool_outputs=_decode_tool_outputs(payload),
        historical_format=_decode_historical_format(payload.get("text")),
        context=_decode_matcher_context(payload),
        # Existing inert selectors match the full serialized provider request.
        # Decode those textual selector projections once, independently of the
        # opaque journal/relay snapshot retained solely for egress.
        matching_text=json.dumps(payload, ensure_ascii=False),
        matching_ascii_text=json.dumps(payload),
        matching_sorted_text=json.dumps(payload, sort_keys=True),
        request_fingerprint=sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest(),
        wire_json=json.dumps(payload),
    )


def _model_request_egress(request: _ModelRequestInput) -> dict[str, object]:
    """Restore only the opaque snapshot and explicitly declared matcher tuple."""
    decoded = _decode_model_request(request)
    payload = _object(json.loads(decoded.wire_json))
    context = decoded.context
    if context is not None and context.reference_tokens_are_tuple:
        payload["_external_channel_fixture_reference_tokens"] = context.reference_tokens
    return payload


def _model_tools_egress(request: _ModelRequestInput) -> object:
    """Relay provider-owned tool declarations without inspecting their JSON."""
    return json.loads(_decode_model_request(request).tools_json)


def _model_input_item_egress(item: _ModelInputItem) -> object:
    return json.loads(item.wire_json)


def _with_input_alias(item: _ModelInputItem, call_id: str) -> _ModelInputItem:
    """Encode a declared alias change while relaying the opaque item extras."""
    payload = _object(_model_input_item_egress(item))
    payload["tool_call_id" if item.role == "tool" else "call_id"] = call_id
    return _decode_model_input_item(payload)


def _prepared_matcher_view(
    request: _ModelRequest,
    items: tuple[_ModelInputItem, ...],
    context: _PreparedMatcherContext,
) -> _ModelRequest:
    """Encode typed local view fields without inspecting opaque provider extras."""
    payload = _model_request_egress(request)
    payload["input"] = [_model_input_item_egress(item) for item in items]
    payload["_external_channel_fixture_turn"] = context.turn
    payload["_external_channel_fixture_flow"] = context.flow
    payload["_external_channel_fixture_reference_tokens"] = context.reference_tokens
    payload["_external_channel_fixture_generation"] = context.generation
    payload["_external_channel_fixture_observed_stages"] = list(context.observed_stages)
    payload["_external_channel_fixture_request_key"] = context.request_key
    return _decode_model_request(payload)


_SEMANTIC_FOLLOW_UP_RESPONSES = {
    _SEMANTIC_SAME_NATIVE_PROMPT: _SEMANTIC_SAME_NATIVE_RESPONSE,
    _SEMANTIC_CROSS_NATIVE_PROMPT: _SEMANTIC_CROSS_NATIVE_RESPONSE,
    _SEMANTIC_POST_COMPACTION_PROMPT: _SEMANTIC_POST_COMPACTION_RESPONSE,
}
_UPSTREAM = os.environ.get("AIMOCK_UPSTREAM", "http://mock-openai:8080")
_IMAGE_PATH = Path(
    os.environ.get(
        "IMAGE_GENERATION_FIXTURE",
        "/fixtures/provider-image-generation.png",
    )
)
_OPENAI_MODEL_LIST_PATH = "/v1/models"
_JOURNAL_PATH = "/v1/_image_generation_requests"
_OPENAI_IMAGE_JOURNAL_PATH = "/v1/_openai_images_requests"
_DYNAMIC_WORKTREE_JOURNAL_PATH = "/v1/_dynamic_worktree_requests"
_EXTERNAL_CHANNEL_PROGRESS_JOURNAL_PATH = "/v1/_external_channel_progress_requests"
_EXTERNAL_CHANNEL_FILE_JOURNAL_PATH = "/v1/_external_channel_file_requests"
_XAI_IMAGINE_JOURNAL_PATH = "/v1/_xai_imagine_requests"
_XAI_OAUTH_JOURNAL_PATH = "/v1/_xai_oauth_requests"
_SUBSCRIPTION_USAGE_JOURNAL_PATH = "/v1/_subscription_usage_requests"
_OAUTH_CONNECTION_SCENARIO_PATH = "/v1/_oauth_connection_scenarios"
_CHATGPT_DEVICE_USER_CODE_PATH = "/chatgpt/device/usercode"
_CHATGPT_DEVICE_TOKEN_PATH = "/chatgpt/device/token"
_CHATGPT_USAGE_PATH = "/backend-api/wham/usage"
_CHATGPT_TOKEN_PATH = "/chatgpt/oauth/token"
_XAI_DEVICE_CODE_PATH = "/oauth2/device/code"
_XAI_SETTINGS_PATH = "/v1/settings"
_XAI_BILLING_PATH = "/v1/billing"
_XAI_AUTO_TOP_UP_PATH = "/v1/auto-topup-rule"
_CHATGPT_SCENARIOS = {
    "test-chatgpt-normal": "chatgpt_normal",
    "test-chatgpt-exhausted": "chatgpt_exhausted",
    "test-chatgpt-refresh": "chatgpt_refresh",
    "test-chatgpt-transport": "chatgpt_transport",
    "test-chatgpt-rate-limited": "chatgpt_rate_limited",
    "test-chatgpt-unavailable": "chatgpt_unavailable",
    "test-chatgpt-malformed": "chatgpt_malformed",
    "test-chatgpt-stale": "chatgpt_stale",
}
_XAI_USAGE_SCENARIOS = {
    "test-xai-normal": "xai_normal",
    "test-xai-external": "xai_external",
    "test-xai-invalid-redirect": "xai_invalid_redirect",
    "test-xai-billing-denied": "xai_billing_denied",
    "test-xai-settings-failure": "xai_settings_failure",
    "test-xai-transport": "xai_transport",
    "test-xai-unavailable": "xai_unavailable",
    "test-xai-malformed": "xai_malformed",
}
_XAI_API_KEY_IMAGE_PROMPT = "A deterministic xAI API-key aurora"
_XAI_OAUTH_IMAGE_PROMPT = "A deterministic xAI OAuth aurora"
_XAI_OAUTH_REFRESH_IMAGE_PROMPT = "A deterministic xAI OAuth refresh aurora"
_XAI_OAUTH_REJECTED_IMAGE_PROMPT = "A deterministic rejected xAI OAuth aurora"
_CAPTURED_MODEL_PROMPTS = {
    _PROMPT,
    _EXPLICIT_IMAGE_PROMPT,
    _FOLLOW_UP_PROMPT,
    "Per prompt Fast retry preserves prepared option",
    "Per prompt fast profile",
    "Per prompt quality profile",
    "Per prompt quality standard profile",
    "xAI API-key image generation",
    "xAI OAuth image generation",
    "xAI OAuth image generation after 401",
    "xAI OAuth image generation repeated 401",
    "xAI image generation disabled",
}


def image_generation_model_list_payload() -> dict[str, object]:
    """Return credential-visible models for deterministic image catalog sync."""
    return {
        "object": "list",
        "data": [
            {
                "id": "gpt-image-2.5-flare",
                "object": "model",
                "created": 0,
                "owned_by": "openai",
            },
            {
                "id": "gpt-image-2.5-sunburst",
                "object": "model",
                "created": 0,
                "owned_by": "openai",
            },
            {
                "id": "provider-visible-unregistered-image-model",
                "object": "model",
                "created": 0,
                "owned_by": "openai",
            },
        ],
        "has_more": False,
    }


_EXTERNAL_CHANNEL_PROGRESS_MARKER = "Provider-native Channel Work progress E2E"
_EXTERNAL_CHANNEL_QUIET_WORK_MARKER = "Discord quiet work presence E2E"
_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_MARKER = "Discord quiet work setup E2E"
_EXTERNAL_CHANNEL_SEARCH_CALL_ID = "call_external_channel_tool_search"
_EXTERNAL_CHANNEL_PROGRESS_CALL_ID = "call_external_channel_progress"
_EXTERNAL_CHANNEL_PROGRESS_REFERENCE_TOKENS = ("@User UREVIEWER", "#e2e")
_EXTERNAL_CHANNEL_FINISH_CALL_ID = "call_external_channel_finish"
_EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID = "call_external_channel_outcome_progress"
_EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID = "call_external_channel_failure_progress"
_EXTERNAL_CHANNEL_REQUEST_INPUT_CALL_ID = "call_external_channel_request_input"
_EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID = "call_external_channel_held_progress"
_EXTERNAL_CHANNEL_PROGRESS_CALL_IDS = frozenset(
    {
        _EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
        _EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID,
        _EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID,
        _EXTERNAL_CHANNEL_REQUEST_INPUT_CALL_ID,
        _EXTERNAL_CHANNEL_FINISH_CALL_ID,
    }
)
_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID = (
    "call_external_channel_quiet_work_setup_search"
)
_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID = (
    "call_external_channel_quiet_work_setup_finish"
)
_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_PATH = "/v1/_external_channel_quiet_work_barrier"
_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_RELEASE_PATH = (
    f"{_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_PATH}/release"
)
_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_BINDING = re.compile(r"[A-Za-z0-9_-]{1,256}")
_EXTERNAL_CHANNEL_TURN_BINDING = re.compile(r"Binding: ([A-Za-z0-9_-]+)")
_EXTERNAL_CHANNEL_COMPACTION_BINDING = re.compile(r"### Binding `([^`]+)`")
_EXTERNAL_CHANNEL_DISCORD_TITLE_MARKER = "Private Discord Gateway invocation"
_EXTERNAL_CHANNEL_DISCORD_TITLE_RESPONSE = '{"title":"Upload session initialized."}'
_EXTERNAL_CHANNEL_SLACK_RESPONSE_MODE_TITLE_INPUT = (
    "Create a title from this request:\nInitial response-mode invocation"
)
_SESSION_TITLE_SYSTEM_MARKER = "Create a brief title from the request"
_EXTERNAL_CHANNEL_FILE_MARKER = "External Channel file transfer E2E"
_EXTERNAL_CHANNEL_FILE_LOCATOR = re.compile(r"File: (external-file:v1:[^\\\s\"']+)")
_EXTERNAL_CHANNEL_FILE_DECLARED_SIZE = re.compile(r"Declared size: (\d+) bytes")
_EXTERNAL_CHANNEL_FILE_SEARCH_CALL_ID = "call_external_channel_file_tool_search"
_EXTERNAL_CHANNEL_FILE_DOWNLOAD_CALL_ID = "call_external_channel_file_download"
_EXTERNAL_CHANNEL_FILE_PROCESS_CALL_ID = "call_external_channel_file_process"
_EXTERNAL_CHANNEL_FILE_FINISH_CALL_ID = "call_external_channel_file_finish"
_EXTERNAL_CHANNEL_FILE_INPUT_PATH = "/workspace/agent/external-input.txt"
_EXTERNAL_CHANNEL_FILE_INPUT_BYTES = 6 * 1024 * 1024
_EXTERNAL_CHANNEL_FILE_OUTPUT_PATHS = (
    "/workspace/agent/external-summary.txt",
    "/workspace/agent/external-details.txt",
)
_APPLY_PATCH_SUCCESS_MESSAGE = "Apply patch E2E success"
_APPLY_PATCH_SUCCESS_CALL_ID = "call_apply_patch_success"
_APPLY_PATCH_SUCCESS_INSPECT_CALL_ID = "call_apply_patch_success_inspect"
_APPLY_PATCH_SUCCESS_INPUT = """*** Base Path: /workspace/agent/apply-patch-e2e
*** Begin Patch
*** Update File: source.txt
@@
-alpha
+ALPHA
 keep-one
@@
 keep-two
-omega
+OMEGA
*** Add File: added.txt
+first
+second
*** Delete File: legacy.txt
*** End Patch"""
_APPLY_PATCH_SUCCESS_INSPECT_ARGUMENTS: dict[str, object] = {
    "command": (
        "base=/workspace/agent/apply-patch-e2e; echo 'source<<'; "
        "cat \"$base/source.txt\"; echo '>>'; echo 'added<<'; "
        "cat \"$base/added.txt\"; echo '>>'; "
        "test ! -e \"$base/legacy.txt\" && echo 'legacy=missing'"
    ),
    "yield_time_ms": 10000,
    "max_output_bytes": 2000,
}
_APPLY_PATCH_TRAVERSAL_MESSAGE = "Apply patch E2E reject traversal"
_APPLY_PATCH_TRAVERSAL_CALL_ID = "call_apply_patch_traversal"
_APPLY_PATCH_TRAVERSAL_INSPECT_CALL_ID = "call_apply_patch_traversal_inspect"
_APPLY_PATCH_TRAVERSAL_INPUT = """*** Base Path: /workspace/agent/apply-patch-e2e
*** Begin Patch
*** Add File: ../apply-patch-escaped.txt
+TRAVERSAL_SECRET
*** End Patch"""
_APPLY_PATCH_TRAVERSAL_INSPECT_ARGUMENTS: dict[str, object] = {
    "command": (
        "base=/workspace/agent/apply-patch-e2e; "
        "test ! -e /workspace/agent/apply-patch-escaped.txt && "
        "echo 'escape=missing'; "
        'source=$(paste -sd, "$base/source.txt"); echo "source=$source"'
    ),
    "yield_time_ms": 10000,
    "max_output_bytes": 1000,
}
_RUN_TOOL_TO_FILE_PROMPT = "Run tool to file E2E"
_RUN_TOOL_TO_FILE_CREATE_CALL_ID = "call_run_tool_to_file_create"
_RUN_TOOL_TO_FILE_STORE_CALL_ID = "call_run_tool_to_file_store"
_RUN_TOOL_TO_FILE_INSPECT_CALL_ID = "call_run_tool_to_file_inspect"
_RUN_TOOL_TO_FILE_SOURCE_PATH = "/workspace/agent/run-tool-to-file-source/source.txt"
_RUN_TOOL_TO_FILE_DIRECTORY = "/workspace/agent/run-tool-to-file-output"
_RUN_TOOL_TO_FILE_CREATE_ARGUMENTS: dict[str, object] = {
    "command": (
        f"mkdir -p {_RUN_TOOL_TO_FILE_SOURCE_PATH.rsplit('/', 1)[0]} && "
        f"head -c 35050 /dev/zero | tr '\\000' x > "
        f"{_RUN_TOOL_TO_FILE_SOURCE_PATH}"
    ),
    "yield_time_ms": 10_000,
    "max_output_bytes": 2_000,
}
_RUN_TOOL_TO_FILE_ARGUMENTS: dict[str, object] = {
    "tool_name": "read",
    "arguments": json.dumps(
        {
            "path": _RUN_TOOL_TO_FILE_SOURCE_PATH,
            "offset": 0,
            "limit": 40_000,
            "encoding": "utf-8",
        },
        separators=(",", ":"),
    ),
    "directory": _RUN_TOOL_TO_FILE_DIRECTORY,
    "overwrite": True,
}
_RUN_TOOL_TO_FILE_INSPECT_ARGUMENTS: dict[str, object] = {
    "command": (
        f"wc -c < {_RUN_TOOL_TO_FILE_DIRECTORY}/output.txt; "
        f"sha256sum {_RUN_TOOL_TO_FILE_DIRECTORY}/output.txt | cut -d' ' -f1; "
        f"cat {_RUN_TOOL_TO_FILE_DIRECTORY}/manifest.json"
    ),
    "yield_time_ms": 10_000,
    "max_output_bytes": 4_000,
}
_DYNAMIC_WORKTREE_CREATE_PREFIX = "Agent-managed worktree E2E create\nSource: "
_DYNAMIC_WORKTREE_REMOVE_PREFIX = "Agent-managed worktree E2E remove\nPath: "
_DYNAMIC_WORKTREE_FORCE_TRUE_SUFFIX = "\nForce: true"
_DYNAMIC_WORKTREE_FORCE_FALSE_SUFFIX = "\nForce: false"
_DYNAMIC_WORKTREE_CREATE_CALL_ID = "call_dynamic_worktree_create"
_DYNAMIC_WORKTREE_LOAD_SKILL_CALL_ID = "call_dynamic_worktree_load_skill"
_DYNAMIC_WORKTREE_REMOVE_DIRTY_CALL_ID = "call_dynamic_worktree_remove_dirty"
_DYNAMIC_WORKTREE_REMOVE_FORCE_CALL_ID = "call_dynamic_worktree_remove_force"
_DYNAMIC_WORKTREE_SKILL_PATH = re.compile(
    r"(/workspace/agent/[^\s\"']+/"
    r"\.claude/skills/worktree-e2e/SKILL\.md)"
)
_DYNAMIC_WORKTREE_EXTERNAL_MARKER = (
    "Agent-managed worktree External Channel continuity E2E"
)
_DYNAMIC_WORKTREE_EXTERNAL_SOURCE = re.compile(
    r"Source: (/workspace/agent/[^\s\\\"']+)"
)
_DYNAMIC_WORKTREE_EXTERNAL_CREATE_CALL_ID = "call_dynamic_worktree_external_create"
_DYNAMIC_WORKTREE_EXTERNAL_LOAD_SKILL_CALL_ID = (
    "call_dynamic_worktree_external_load_skill"
)
_DYNAMIC_WORKTREE_EXTERNAL_SEARCH_CALL_ID = "call_dynamic_worktree_external_tool_search"
_DYNAMIC_WORKTREE_EXTERNAL_FINISH_CALL_ID = "call_dynamic_worktree_external_finish"


def _dynamic_worktree_scenario(
    request: _ModelRequestInput,
) -> _DynamicWorktreeScenario | None:
    """Return the deterministic dynamic-worktree operation and exact path."""
    serialized = _decode_model_request(request).matching_text
    create_prefix = json.dumps(
        _DYNAMIC_WORKTREE_CREATE_PREFIX,
        ensure_ascii=False,
    )[1:-1]
    remove_prefix = json.dumps(
        _DYNAMIC_WORKTREE_REMOVE_PREFIX,
        ensure_ascii=False,
    )[1:-1]
    user_text = _last_user_text(request)
    if user_text is not None and user_text.startswith(_DYNAMIC_WORKTREE_CREATE_PREFIX):
        source_path = user_text.removeprefix(_DYNAMIC_WORKTREE_CREATE_PREFIX).strip()
        create_request_index = serialized.rfind(create_prefix)
        create_reminder_index = serialized.rfind(
            "Agent-managed Git worktree creation reached terminal status"
        )
        if source_path and create_request_index > create_reminder_index:
            return _DynamicWorktreeScenario("create", source_path, False)
    if user_text is not None and user_text.startswith(_DYNAMIC_WORKTREE_REMOVE_PREFIX):
        path_and_force = user_text.removeprefix(_DYNAMIC_WORKTREE_REMOVE_PREFIX)
        force = path_and_force.endswith(_DYNAMIC_WORKTREE_FORCE_TRUE_SUFFIX)
        worktree_path = (
            path_and_force.removesuffix(_DYNAMIC_WORKTREE_FORCE_TRUE_SUFFIX)
            .removesuffix(_DYNAMIC_WORKTREE_FORCE_FALSE_SUFFIX)
            .strip()
        )
        remove_request_index = serialized.rfind(remove_prefix)
        remove_reminder_index = serialized.rfind(
            "Agent-managed Git worktree removal reached terminal status"
        )
        if worktree_path and remove_request_index > remove_reminder_index:
            return _DynamicWorktreeScenario("remove", worktree_path, force)
    markers = (
        (
            serialized.rfind(_DYNAMIC_WORKTREE_CREATE_CALL_ID),
            _DynamicWorktreeScenario("create", "", False),
        ),
        (
            serialized.rfind(
                "Agent-managed Git worktree creation reached terminal status"
            ),
            _DynamicWorktreeScenario("create", "", False),
        ),
        (
            serialized.rfind(_DYNAMIC_WORKTREE_REMOVE_DIRTY_CALL_ID),
            _DynamicWorktreeScenario("remove", "", False),
        ),
        (
            serialized.rfind(_DYNAMIC_WORKTREE_REMOVE_FORCE_CALL_ID),
            _DynamicWorktreeScenario("remove", "", True),
        ),
        (
            serialized.rfind(
                "Agent-managed Git worktree removal reached terminal status"
            ),
            _DynamicWorktreeScenario(
                "remove",
                "",
                serialized.rfind("Force used: true.")
                > serialized.rfind("Force used: false."),
            ),
        ),
    )
    marker_index, scenario = max(markers, key=lambda item: item[0])
    if marker_index >= 0:
        return scenario
    return None


def _dynamic_worktree_external_source(
    request: _ModelRequestInput,
) -> str | None:
    """Return the current External Channel continuity source Project."""
    user_text = _last_user_text(request)
    if (
        user_text is None
        or _DYNAMIC_WORKTREE_EXTERNAL_MARKER not in user_text
        or user_text.startswith(_DYNAMIC_WORKTREE_REMOVE_PREFIX)
    ):
        return None
    match = _DYNAMIC_WORKTREE_EXTERNAL_SOURCE.search(user_text)
    return None if match is None else match.group(1)


def _dynamic_worktree_external_stage(
    request: _ModelRequestInput,
) -> str | None:
    """Return one deterministic External Channel worktree request stage."""
    serialized = _decode_model_request(request).matching_text
    user_text = _last_user_text(request)
    if (
        _DYNAMIC_WORKTREE_EXTERNAL_MARKER not in serialized
        or external_channel_binding(request) is None
        or (
            user_text is not None
            and user_text.startswith(_DYNAMIC_WORKTREE_REMOVE_PREFIX)
        )
    ):
        return None
    if request_has_tool_output(
        request,
        _DYNAMIC_WORKTREE_EXTERNAL_FINISH_CALL_ID,
    ):
        return "after_finish"
    if request_has_tool_output(
        request,
        _DYNAMIC_WORKTREE_EXTERNAL_SEARCH_CALL_ID,
    ):
        return "after_search"
    if request_has_tool_output(
        request,
        _DYNAMIC_WORKTREE_EXTERNAL_LOAD_SKILL_CALL_ID,
    ):
        return "after_skill"
    if "Agent-managed Git worktree creation reached terminal status" in serialized:
        return "continuation"
    if _dynamic_worktree_external_source(request) is not None:
        return "initial"
    return None


def _last_user_text(request: _ModelRequestInput) -> str | None:
    """Return the text from the last user input or message item."""
    request = _decode_model_request(request)
    if request.input_text is not None:
        return request.input_text
    if request.input_items is None:
        return None
    for item in reversed(request.input_items):
        if item.role == "user":
            return item.text
    return None


def _request_has_named_tool(request: _ModelRequestInput, name: str) -> bool:
    """Return whether a model request exposes one named function tool."""
    request = _decode_model_request(request)
    return any(tool.name == name for tool in request.named_tools)


def _request_has_named_tool_type(
    request: _ModelRequestInput,
    *,
    name: str,
    tool_type: str,
) -> bool:
    """Return whether a request exposes one named tool with the exact dialect."""
    request = _decode_model_request(request)
    return any(
        tool.name == name and tool.kind == tool_type for tool in request.named_tools
    )


def request_has_tool_output(value: object, call_id: str) -> bool:
    """Find one completed tool output in nested Responses or Chat input."""
    if isinstance(value, _ModelRequest | _ModelInputItem):
        outputs = value.tool_outputs
    else:
        outputs = _decode_tool_outputs(value)
    return any(output.call_id == call_id for output in outputs)


def apply_patch_scenario(request: _ModelRequestInput) -> str | None:
    """Return the current deterministic apply-patch scenario."""
    request = _decode_model_request(request)
    user_text = _last_user_text(request)
    if user_text == _APPLY_PATCH_SUCCESS_MESSAGE:
        return "success"
    if user_text == _APPLY_PATCH_TRAVERSAL_MESSAGE:
        return "traversal"

    message_scenarios: list[str] = []
    for text in request.input_strings:
        if text == _APPLY_PATCH_SUCCESS_MESSAGE:
            message_scenarios.append("success")
        elif text == _APPLY_PATCH_TRAVERSAL_MESSAGE:
            message_scenarios.append("traversal")
    if message_scenarios:
        return message_scenarios[-1]

    previous_response_id = request.previous_response_id
    response_scenarios = {
        "resp_apply_patch_success": "success",
        "resp_apply_patch_success_inspect": "success",
        "resp_apply_patch_success_verified": "success",
        "resp_apply_patch_traversal": "traversal",
        "resp_apply_patch_traversal_inspect": "traversal",
        "resp_apply_patch_traversal_verified": "traversal",
    }
    if isinstance(previous_response_id, str):
        scenario = response_scenarios.get(previous_response_id)
        if scenario is not None:
            return scenario

    call_scenarios = {
        _APPLY_PATCH_SUCCESS_CALL_ID: "success",
        _APPLY_PATCH_SUCCESS_INSPECT_CALL_ID: "success",
        _APPLY_PATCH_TRAVERSAL_CALL_ID: "traversal",
        _APPLY_PATCH_TRAVERSAL_INSPECT_CALL_ID: "traversal",
    }
    if request.input_items is None:
        return None
    for item in reversed(request.input_items):
        call_id = item.effective_call_id
        if call_id is not None:
            scenario = call_scenarios.get(call_id)
            if scenario is not None:
                return scenario
    return None


def is_run_tool_to_file_scenario(request: _ModelRequestInput) -> bool:
    """Recognize the deterministic Runtime output materialization journey."""
    request = _decode_model_request(request)
    if _last_user_text(request) == _RUN_TOOL_TO_FILE_PROMPT:
        return True
    previous_response_id = request.previous_response_id
    if previous_response_id in {
        "resp_run_tool_to_file_create",
        "resp_run_tool_to_file_store",
        "resp_run_tool_to_file_inspect",
        "resp_run_tool_to_file_completed",
    }:
        return True
    return any(
        request_has_tool_output(request, call_id)
        for call_id in (
            _RUN_TOOL_TO_FILE_CREATE_CALL_ID,
            _RUN_TOOL_TO_FILE_STORE_CALL_ID,
            _RUN_TOOL_TO_FILE_INSPECT_CALL_ID,
        )
    )


def external_channel_file_tool_output_evidence(
    value: object,
) -> dict[str, dict[str, object]]:
    """Return bounded diagnostic metadata without retaining tool output bodies."""
    call_ids = {
        _EXTERNAL_CHANNEL_FILE_SEARCH_CALL_ID,
        _EXTERNAL_CHANNEL_FILE_DOWNLOAD_CALL_ID,
        _EXTERNAL_CHANNEL_FILE_PROCESS_CALL_ID,
        _EXTERNAL_CHANNEL_FILE_FINISH_CALL_ID,
    }
    evidence: dict[str, dict[str, object]] = {}

    outputs = (
        value.tool_outputs
        if isinstance(value, _ModelRequest | _ModelInputItem)
        else _decode_tool_outputs(value)
    )
    for result in outputs:
        if result.call_id not in call_ids or result.kind not in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            continue
        output = result.output_text
        error_match = (
            re.search(r"(?i)\b(error|failed|unavailable|denied|invalid)\b", output)
            if output is not None
            else None
        )
        evidence[result.call_id] = {
            "present": True,
            "length": len(output) if output is not None else None,
            "error": output[:512]
            if output is not None and error_match is not None
            else None,
        }
    return evidence


def external_channel_binding(request: _ModelRequestInput) -> str | None:
    """Extract the binding handle from an external turn or compacted work."""
    serialized = _decode_model_request(request).matching_text
    turn_match = _EXTERNAL_CHANNEL_TURN_BINDING.search(serialized)
    if turn_match is not None:
        return turn_match.group(1)
    compaction_match = _EXTERNAL_CHANNEL_COMPACTION_BINDING.search(serialized)
    return None if compaction_match is None else compaction_match.group(1)


def latest_external_channel_human_binding(
    request: _ModelRequestInput,
) -> str | None:
    """Return the Binding from the latest canonical human External Channel turn."""
    latest_user_text = _last_user_text(request)
    if (
        latest_user_text is None
        or "Message Type: EXTERNAL_CHANNEL_TURN" not in latest_user_text
    ):
        return None
    match = _EXTERNAL_CHANNEL_TURN_BINDING.search(latest_user_text)
    return None if match is None else match.group(1)


def _latest_external_channel_progress_marker(
    request: _ModelRequestInput,
) -> bool:
    """Return whether the current logical user turn starts progress work."""
    latest_user_text = _last_user_text(request)
    return latest_user_text is not None and (
        _EXTERNAL_CHANNEL_PROGRESS_MARKER in latest_user_text
        or _EXTERNAL_CHANNEL_QUIET_WORK_MARKER in latest_user_text
    )


def has_current_external_channel_progress_result(
    request: _ModelRequestInput,
) -> bool:
    """Return whether a current tool result follows the latest user turn."""
    return any(
        has_current_tool_output(request, call_id)
        for call_id in _EXTERNAL_CHANNEL_PROGRESS_CALL_IDS
    )


def has_current_tool_output(request: _ModelRequestInput, call_id: str) -> bool:
    """Return whether one tool output follows the latest logical user turn."""
    request = _decode_model_request(request)
    if request.input_items is None:
        return False
    input_items = request.input_items
    latest_user_index = max(
        (index for index, item in enumerate(input_items) if item.role == "user"),
        default=-1,
    )
    if latest_user_index < 0:
        return False
    return any(
        request_has_tool_output(raw_item, call_id)
        for raw_item in input_items[latest_user_index + 1 :]
    )


def is_external_channel_progress_request(request: _ModelRequestInput) -> bool:
    """Recognize the deterministic progress journey by stable request markers."""
    return (
        _latest_external_channel_progress_marker(request)
        and external_channel_binding(request) is not None
        and (
            _request_has_named_tool(request, "tool_search")
            or _request_has_named_tool(request, "channel_action")
        )
    )


def is_external_channel_quiet_work_request(
    request: _ModelRequestInput,
) -> bool:
    """Recognize the Discord-only quiet-work progress journey."""
    latest_user_text = _last_user_text(request)
    return (
        latest_user_text is not None
        and _EXTERNAL_CHANNEL_QUIET_WORK_MARKER in latest_user_text
        and is_external_channel_progress_request(request)
    )


def is_external_channel_quiet_work_setup_request(
    request: _ModelRequestInput,
) -> bool:
    """Recognize the isolated setup flow that establishes quiet-work Binding."""
    latest_user_text = _last_user_text(request)
    has_setup_result = request_has_tool_output(
        request,
        _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID,
    ) or request_has_tool_output(
        request,
        _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
    )
    return (
        latest_user_text is not None
        and _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_MARKER in latest_user_text
        and (
            has_setup_result
            or _request_has_named_tool(request, "tool_search")
            or _request_has_named_tool(request, "channel_action")
        )
        and external_channel_binding(request) is not None
    )


def is_external_channel_discord_title_request(
    request: _ModelRequestInput,
) -> bool:
    """Recognize only the Discord P0 automatic-title model request."""
    serialized = _decode_model_request(request).matching_text
    return (
        _SESSION_TITLE_SYSTEM_MARKER in serialized
        and _EXTERNAL_CHANNEL_DISCORD_TITLE_MARKER in serialized
    )


def is_external_channel_slack_response_mode_title_request(
    request: _ModelRequestInput,
) -> bool:
    """Recognize only the Slack response-mode automatic-title request."""
    serialized = _decode_model_request(request).matching_sorted_text
    return (
        _SESSION_TITLE_SYSTEM_MARKER in serialized
        and _last_user_text(request)
        == _EXTERNAL_CHANNEL_SLACK_RESPONSE_MODE_TITLE_INPUT
    )


def external_channel_progress_evidence(
    request: _ModelRequestInput,
) -> dict[str, object]:
    """Return sanitized evidence about one deterministic progress request."""
    latest_user_text = _last_user_text(request)
    return {
        "binding": external_channel_binding(request),
        "marker_present": _latest_external_channel_progress_marker(request),
        "resolved_user_reference": (
            latest_user_text is not None and "@User UREVIEWER" in latest_user_text
        ),
        "resolved_channel_reference": (
            latest_user_text is not None and "#e2e" in latest_user_text
        ),
        "search_tool_available": _request_has_named_tool(
            request,
            "tool_search",
        ),
        "progress_tool_available": _request_has_named_tool(
            request,
            "channel_action",
        ),
    }


def external_channel_file_locators(request: _ModelRequestInput) -> list[str]:
    """Extract ordered opaque file locators from the rendered external message."""
    serialized = _decode_model_request(request).matching_text
    return list(dict.fromkeys(_EXTERNAL_CHANNEL_FILE_LOCATOR.findall(serialized)))


def external_channel_file_declared_sizes(
    request: _ModelRequestInput,
) -> list[int]:
    """Extract ordered declared sizes from rendered file metadata."""
    serialized = _decode_model_request(request).matching_text
    return [
        int(value) for value in _EXTERNAL_CHANNEL_FILE_DECLARED_SIZE.findall(serialized)
    ]


def is_external_channel_file_request(request: _ModelRequestInput) -> bool:
    """Recognize the file journey before or after deferred-tool activation."""
    serialized = _decode_model_request(request).matching_text
    return (
        _EXTERNAL_CHANNEL_FILE_MARKER in serialized
        and external_channel_binding(request) is not None
        and len(external_channel_file_locators(request)) >= 2
        and (
            _request_has_named_tool(request, "tool_search")
            or (
                _request_has_named_tool(request, "download_external_file")
                and _request_has_named_tool(request, "exec_command")
                and _request_has_named_tool(request, "channel_action")
            )
        )
    )


def external_channel_file_evidence(
    request: _ModelRequestInput,
) -> dict[str, object]:
    """Return sanitized request-stage evidence for the file-transfer journey."""
    serialized = _decode_model_request(request).matching_text
    return {
        "matched": is_external_channel_file_request(request),
        "binding": external_channel_binding(request),
        "marker_present": _EXTERNAL_CHANNEL_FILE_MARKER in serialized,
        "locator_count": len(external_channel_file_locators(request)),
        "search_tool_available": _request_has_named_tool(
            request,
            "tool_search",
        ),
        "download_tool_available": _request_has_named_tool(
            request,
            "download_external_file",
        ),
        "process_tool_available": _request_has_named_tool(
            request,
            "exec_command",
        ),
        "channel_action_tool_available": _request_has_named_tool(
            request,
            "channel_action",
        ),
    }


def _is_semantic_compaction_request(request: _ModelRequestInput) -> bool:
    """Return whether compaction belongs to the semantic transcript scenario."""
    request = _decode_model_request(request)
    instructions = request.instructions
    user_text = _last_user_text(request)
    return (
        isinstance(instructions, str)
        and instructions.startswith(_COMPACTION_SYSTEM_PREFIX)
        and user_text is not None
        and _SEMANTIC_QUERY in user_text
        and _SEMANTIC_SOURCE_URL in user_text
        and _SEMANTIC_RESPONSE in user_text
    )


class _ProviderToolLiveBarrier:
    """Coordinate the provider-tool live stream with its E2E assertion."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed = False
        self._reached = threading.Event()
        self._released = threading.Event()

    def arm(self) -> None:
        """Reset and arm the barrier for one provider-tool live response."""
        with self._lock:
            self._armed = True
            self._reached.clear()
            self._released.clear()

    def evidence(self) -> dict[str, bool]:
        """Return safe barrier state for test diagnostics."""
        with self._lock:
            armed = self._armed
        return {
            "armed": armed,
            "reached": self._reached.is_set(),
            "released": self._released.is_set(),
        }

    def release(self) -> None:
        """Release the current provider-tool live response."""
        self._released.set()

    def wait_until_reached(self, timeout: float) -> bool:
        """Wait until the provider stream reaches the held running boundary."""
        return self._reached.wait(timeout=timeout)

    def wait_for_release(self) -> bool:
        """Mark the running boundary reached and wait for explicit release."""
        with self._lock:
            if not self._armed:
                return False
        self._reached.set()
        return self._released.wait(timeout=_PROVIDER_TOOL_LIVE_BARRIER_TIMEOUT_SECONDS)


_PROVIDER_TOOL_LIVE_BARRIER = _ProviderToolLiveBarrier()
_INFERENCE_PROFILE_BARRIER = _ProviderToolLiveBarrier()


type _InferenceProfileSourceVariant = Literal["baseline", "refreshed", "missing-model"]


@dataclass(frozen=True)
class _InferenceProfileSourceControl:
    """Accept only the bounded source-only fixture control."""

    variant: _InferenceProfileSourceVariant


def _decode_inference_profile_source_control(
    body: bytes,
) -> _InferenceProfileSourceControl:
    """Validate the exact control object before entering fixture state logic."""
    payload: object = json.loads(body)
    if not isinstance(payload, dict) or set(payload) != {"variant"}:
        raise ValueError("A valid catalog source variant is required.")
    match payload["variant"]:
        case "baseline":
            return _InferenceProfileSourceControl(variant="baseline")
        case "refreshed":
            return _InferenceProfileSourceControl(variant="refreshed")
        case "missing-model":
            return _InferenceProfileSourceControl(variant="missing-model")
        case _:
            raise ValueError("A valid catalog source variant is required.")


def _inference_profile_source_payload(
    variant: _InferenceProfileSourceVariant,
) -> dict[str, dict[str, object]]:
    """Supply inert exact-scoped facts and per-token synthetic catalog prices."""
    full_efforts = ["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    model_efforts = {
        "gpt-5.5": full_efforts,
        "gpt-5.5-mini": [],
        "gpt-6-astra": full_efforts,
        "gpt-5.6-sol": full_efforts,
    }
    model_web_search = {
        "gpt-5.5": True,
        "gpt-5.5-mini": False,
        "gpt-6-astra": True,
        "gpt-5.6-sol": True,
    }
    payload: dict[str, dict[str, object]] = {
        model: {
            "litellm_provider": "openai",
            "display_name": model,
            "mode": "responses",
            "supported_endpoints": ["/v1/responses"],
            "max_input_tokens": 128_000,
            "supported_modalities": ["text", "image", "pdf"],
            "supported_output_modalities": ["text"],
            "supports_vision": True,
            "supports_pdf_input": True,
            "supports_function_calling": True,
            "supports_parallel_function_calling": True,
            "supports_response_schema": True,
            "supports_reasoning": bool(efforts),
            "reasoning_effort_levels": list(efforts),
            "supports_web_search": model_web_search[model],
            "input_cost_per_token": 0.000001,
            "output_cost_per_token": 0.000002,
            "cache_read_input_token_cost": 0.0000001,
            "cache_creation_input_token_cost": 0.000001,
        }
        for model, efforts in model_efforts.items()
    }
    payload["gpt-5.5-title-plain"] = {
        **payload["gpt-5.5"],
        "display_name": "Plain Title Deterministic",
        "supports_response_schema": False,
        "supports_reasoning": False,
        "reasoning_effort_levels": [],
    }
    match variant:
        case "baseline":
            pass
        case "refreshed":
            payload["gpt-5.5"].update(
                {
                    "reasoning_effort_levels": [
                        effort for effort in full_efforts if effort != "max"
                    ],
                    "input_cost_per_token": 0.000003,
                    "output_cost_per_token": 0.000004,
                }
            )
        case "missing-model":
            del payload["gpt-5.5"]
        case _:
            assert_never(variant)
    return payload


def inference_profile_scenario(user_text: str | None) -> str | None:
    """Recognize only explicitly named synthetic inference-profile requests."""
    if user_text is None or not user_text.startswith(_INFERENCE_PROFILE_PREFIX):
        return None
    scenario = user_text.removeprefix(_INFERENCE_PROFILE_PREFIX).split(" ", 1)[0]
    return scenario if scenario in _INFERENCE_PROFILE_TIERS else None


def is_inference_profile_title_request(request: _ModelRequestInput) -> bool:
    """Recognize the independent title operation for a synthetic profile input."""
    serialized = _decode_model_request(request).matching_text
    return (
        _SESSION_TITLE_SYSTEM_MARKER in serialized
        and _INFERENCE_PROFILE_PREFIX in serialized
    )


class _ExternalChannelResponseContext(NamedTuple):
    """Safe association for one locally emitted Responses tool call."""

    binding: str
    turn: str
    flow: str
    call_id: str
    stage: str
    released_outcome: bool = False
    reference_tokens: tuple[str, ...] = ()


class _ExternalChannelStaleResponseContext(ValueError):
    """A prepared matcher belongs to a retired fixture generation."""


class _ExternalChannelResponseRegistry:
    """Restore exact sparse continuations without retaining message bodies."""

    def __init__(self, *, limit: int = 2048) -> None:
        self._limit = limit
        self._lock = threading.RLock()
        self._generation = 0
        self._serial = 0
        self._responses: OrderedDict[str, _ExternalChannelResponseContext] = (
            OrderedDict()
        )
        self._identities: OrderedDict[tuple[str, str, str, str], str] = OrderedDict()
        self._aliases: OrderedDict[tuple[str, str], _ExternalChannelResponseContext] = (
            OrderedDict()
        )
        self._used_stages: set[tuple[str, str]] = set()
        self._released_outcomes: OrderedDict[str, None] = OrderedDict()

    def clear(self, *, reset_state: Callable[[], None] | None = None) -> None:
        """Invalidate all associations, including in-flight previous responses."""
        with self._lock:
            self._generation += 1
            self._responses.clear()
            self._identities.clear()
            self._aliases.clear()
            self._released_outcomes.clear()
            if reset_state is not None:
                reset_state()

    def run_if_current(
        self, request: _ModelRequestInput, dispatch: Callable[[], None]
    ) -> bool:
        """Serialize all scoped state mutations with generation retirement."""
        request = _decode_model_request(request)
        matcher = request.context
        with self._lock:
            if matcher is None or matcher.generation != self._generation:
                return False
            dispatch()
            return True

    def released_outcome_replay(self, request: _ModelRequestInput) -> bool:
        """Recognize a previously chosen rich outcome, including delayed retries."""
        request = _decode_model_request(request)
        matcher = request.context
        with self._lock:
            if matcher is None or matcher.generation != self._generation:
                return False
            key = matcher.request_key
            if key is not None and key in self._released_outcomes:
                return True
            context = self._responses.get(str(request.previous_response_id))
            return (
                context is not None
                and context.released_outcome
                and context.turn == matcher.turn
                and context.binding == external_channel_binding(request)
            )

    def remember_released_outcome(self, request: _ModelRequestInput) -> None:
        """Retain only a safe request fingerprint, never response/body contents."""
        request = _decode_model_request(request)
        matcher = request.context
        with self._lock:
            key = matcher.request_key if matcher is not None else None
            if key is not None:
                self._released_outcomes[key] = None
                while len(self._released_outcomes) > self._limit:
                    self._released_outcomes.popitem(last=False)
            previous = str(request.previous_response_id)
            context = self._responses.get(previous)
            if (
                context is not None
                and context.turn == (matcher.turn if matcher is not None else None)
                and context.binding == external_channel_binding(request)
            ):
                self._responses[previous] = context._replace(released_outcome=True)

    def prepare(self, request: _ModelRequestInput) -> dict[str, object]:
        """Keep the public helper's wire interface at an explicit fixture boundary."""
        decoded = _decode_model_request(request)
        prepared = self.prepare_model(decoded)
        if prepared is decoded and isinstance(request, dict):
            return request
        return _model_request_egress(prepared)

    def prepare_model(self, request: _ModelRequest) -> _ModelRequest:
        """Build a typed matcher view while preserving the original upstream body."""
        if not request.responses_input_present or request.input_items is None:
            return request
        items = request.input_items
        latest_text = _last_user_text(request)
        human_binding = latest_external_channel_human_binding(request)
        binding = human_binding or external_channel_binding(request)
        with self._lock:
            generation = self._generation
            context = self._responses.get(str(request.previous_response_id))
            if latest_text is None:
                if (
                    context is None
                    or len(items) != 1
                    or any(item.role == "user" for item in items)
                    or not any(
                        item.kind == "function_call_output"
                        and item.call_id == context.call_id
                        for item in items
                    )
                ):
                    return request
                binding = context.binding
                flow = context.flow
                turn = context.turn
                reference_tokens = context.reference_tokens
                references = "\n".join(reference_tokens)
                marker = {
                    "setup": _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_MARKER,
                    "progress": _EXTERNAL_CHANNEL_PROGRESS_MARKER,
                    "resume": "",
                }[flow]
                items = (
                    _decode_model_input_item(
                        {
                            "role": "user",
                            "content": (
                                "Message Type: EXTERNAL_CHANNEL_TURN\n"
                                f"Binding: {binding}\n\n{marker}\n{references}"
                            ),
                        }
                    ),
                    *items,
                )
            elif binding is not None:
                flow = (
                    "setup"
                    if is_external_channel_quiet_work_setup_request(request)
                    else (
                        "resume"
                        if _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting(binding)
                        else "progress"
                    )
                )
                turn = sha256(latest_text.encode()).hexdigest()[:24]
                reference_tokens = tuple(
                    token
                    for token in _EXTERNAL_CHANNEL_PROGRESS_REFERENCE_TOKENS
                    if human_binding == binding and token in latest_text
                )
            else:
                return request
            latest_user_index = max(
                (index for index, item in enumerate(items) if item.role == "user"),
                default=-1,
            )
            normalized: list[_ModelInputItem] = []
            observed_stages: list[str] = []
            for index, item in enumerate(items):
                if not item.object_item:
                    normalized.append(item)
                    continue
                raw_call_id = item.effective_call_id
                alias = self._aliases.get((str(binding), str(raw_call_id)))
                if (
                    alias is not None
                    and alias.binding == binding
                    and (item.kind == "function_call_output" or item.role == "tool")
                ):
                    normalized.append(_with_input_alias(item, alias.stage))
                    if index > latest_user_index and alias.turn == turn:
                        observed_stages.append(alias.stage)
                else:
                    normalized.append(item)
        return _prepared_matcher_view(
            request,
            tuple(normalized),
            _PreparedMatcherContext(
                generation_present=True,
                generation=generation,
                turn=turn,
                flow=flow,
                reference_tokens=reference_tokens,
                reference_tokens_are_tuple=True,
                observed_stages=tuple(observed_stages),
                request_key=request.request_fingerprint,
            ),
        )

    def issue(
        self,
        request: _ModelRequestInput,
        stage: str,
        *,
        arguments: dict[str, object] | None = None,
    ) -> tuple[str, str, str] | None:
        """Give new logical calls distinct identities and keep retries stable."""
        request = _decode_model_request(request)
        matcher = request.context
        known_stages = _EXTERNAL_CHANNEL_PROGRESS_CALL_IDS | {
            _EXTERNAL_CHANNEL_SEARCH_CALL_ID,
            _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID,
            _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
            _EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID,
        }
        binding = latest_external_channel_human_binding(
            request
        ) or external_channel_binding(request)
        turn = matcher.turn if matcher is not None else None
        flow = matcher.flow if matcher is not None else None
        if (
            stage not in known_stages
            or matcher is None
            or binding is None
            or not isinstance(turn, str)
            or not isinstance(flow, str)
        ):
            return None
        with self._lock:
            if matcher.generation != self._generation:
                raise _ExternalChannelStaleResponseContext(
                    "External Channel fixture generation was retired."
                )
            semantics = (
                sha256(
                    json.dumps(arguments, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest()
                if arguments is not None
                else ""
            )
            key = (binding, turn, stage, semantics)
            call_id = self._identities.get(key)
            if call_id is None or stage == _EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID:
                self._serial += 1
                call_id = (
                    stage
                    if (binding, stage) not in self._used_stages
                    and len(self._used_stages) < self._limit
                    else f"{stage}_{self._generation}_{self._serial}"
                )
                if call_id == stage:
                    self._used_stages.add((binding, stage))
                self._identities[key] = call_id
            suffix = sha256(
                f"{self._generation}:{binding}:{turn}:{call_id}".encode()
            ).hexdigest()[:24]
            response_id = f"resp_external_channel_{suffix}"
            item_id = f"fc_external_channel_{suffix}"
            canonical_stage = (
                _EXTERNAL_CHANNEL_PROGRESS_CALL_ID
                if stage == _EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID
                and flow == "progress"
                else stage
            )
            reference_tokens = tuple(
                token
                for token in _EXTERNAL_CHANNEL_PROGRESS_REFERENCE_TOKENS
                if matcher.reference_tokens_are_tuple
                and token in matcher.reference_tokens
            )
            context = _ExternalChannelResponseContext(
                binding,
                turn,
                flow,
                call_id,
                canonical_stage,
                reference_tokens=reference_tokens,
            )
            self._responses[response_id] = context
            self._aliases[(binding, call_id)] = context
            for mapping in (self._responses, self._identities, self._aliases):
                while len(mapping) > self._limit:
                    mapping.popitem(last=False)
            return call_id, response_id, item_id


_EXTERNAL_CHANNEL_RESPONSES = _ExternalChannelResponseRegistry()


class _ExternalChannelQuietWorkBarrier:
    """Coordinate Discord quiet-work progress with a deterministic E2E boundary."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._armed = False
        self._binding: str | None = None
        self._generation = 0
        self._progress_issued = False
        self._timed_out = False
        self._reached = threading.Event()
        self._released = threading.Event()

    def arm(self, binding: str) -> None:
        """Reset and arm the barrier for one quiet-work continuation."""
        with self._lock:
            self._released.set()
            self._armed = True
            self._binding = binding
            self._generation += 1
            self._progress_issued = False
            self._timed_out = False
            self._reached = threading.Event()
            self._released = threading.Event()

    def evidence(self) -> dict[str, bool]:
        """Return safe barrier state without retaining request content."""
        with self._lock:
            armed = self._armed
            timed_out = self._timed_out
        return {
            "armed": armed,
            "reached": self._reached.is_set(),
            "released": self._released.is_set(),
            "timed_out": timed_out,
        }

    def clear(self) -> None:
        """Retire a journal's Work boundary without leaving old latches active."""
        with self._lock:
            self._armed = False
            self._binding = None
            self._generation += 1
            self._progress_issued = False
            self._timed_out = False
            self._reached = threading.Event()
            self._released = threading.Event()

    def is_armed_for(self, binding: str | None) -> bool:
        """Return whether this deterministic boundary covers one Binding."""
        with self._lock:
            return self._armed and binding is not None and self._binding == binding

    def mark_progress_issued(self, binding: str) -> None:
        """Record the first quiet-work progress call emitted by this proxy."""
        with self._lock:
            if self._armed and self._binding == binding:
                self._progress_issued = True

    def has_progress_issued_for(self, binding: str | None) -> bool:
        """Return whether one scoped continuation must enter the barrier."""
        with self._lock:
            return (
                self._armed
                and binding is not None
                and self._binding == binding
                and self._progress_issued
            )

    def complete_progress_boundary(self, binding: str) -> bool:
        """Consume the pending stage only after an explicit barrier release."""
        with self._lock:
            if (
                self._binding == binding
                and self._released.is_set()
                and self._progress_issued
            ):
                self._progress_issued = False
                return True
            return False

    def release(self) -> None:
        """Release the current quiet-work continuation."""
        with self._lock:
            released = self._released
        released.set()

    def wait_until_reached(self, timeout: float) -> bool:
        """Wait until the model continuation reaches the held boundary."""
        return self._reached.wait(timeout=timeout)

    def hold(self, binding: str) -> bool:
        """Hold Work progression, never the HTTP/model inference attempt."""
        with self._lock:
            if not self._armed or self._binding != binding or self._released.is_set():
                return False
            self._reached.set()
            return True


_EXTERNAL_CHANNEL_QUIET_WORK_BARRIER = _ExternalChannelQuietWorkBarrier()


class _ExternalChannelProgressSequenceRegistry:
    """Track active deterministic progress sequences by opaque Binding."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bindings: set[str] = set()
        self._awaiting_bindings: set[str] = set()

    def clear(self, binding: str) -> None:
        """Clear one completed deterministic progress sequence."""
        with self._lock:
            self._bindings.discard(binding)
            self._awaiting_bindings.discard(binding)

    def clear_all(self) -> None:
        """Clear all sequences when their deterministic journal resets."""
        with self._lock:
            self._bindings.clear()
            self._awaiting_bindings.clear()

    def is_active(self, binding: str | None) -> bool:
        """Return whether one Binding has an active progress sequence."""
        with self._lock:
            return binding is not None and binding in self._bindings

    def start(self, binding: str) -> None:
        """Register one progress sequence started by the latest user turn."""
        with self._lock:
            self._bindings.add(binding)
            self._awaiting_bindings.discard(binding)

    def mark_awaiting(self, binding: str) -> None:
        """Record one delivered question waiting for same-binding input."""
        with self._lock:
            self._bindings.discard(binding)
            self._awaiting_bindings.add(binding)

    def is_awaiting(self, binding: str | None) -> bool:
        """Return whether one Binding awaits the next participant input."""
        with self._lock:
            return binding is not None and binding in self._awaiting_bindings


_EXTERNAL_CHANNEL_PROGRESS_SEQUENCES = _ExternalChannelProgressSequenceRegistry()


def _reset_external_channel_progress_state() -> None:
    """Reset scoped Work state while the response generation is locked."""
    _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.clear_all()
    _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.clear()


@dataclass(frozen=True)
class _QuietWorkBarrierControl:
    """One exact bounded Binding for the local Work barrier protocol."""

    binding: str


def _decode_quiet_work_barrier_control(body: bytes) -> _QuietWorkBarrierControl | None:
    """Decode an exact local control object before mutating barrier state."""
    try:
        payload: object = json.loads(body)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or set(payload) != {"binding"}:
        return None
    binding = _object(payload).get("binding")
    if (
        not isinstance(binding, str)
        or _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_BINDING.fullmatch(binding) is None
    ):
        return None
    return _QuietWorkBarrierControl(binding)


def _external_channel_quiet_work_barrier_binding(body: bytes) -> str | None:
    """Keep the scalar compatibility view at the fixture's helper boundary."""
    control = _decode_quiet_work_barrier_control(body)
    return control.binding if control is not None else None


@dataclass(frozen=True)
class _OAuthConnectionScenario:
    """Validated local account fixture state rather than a raw control dictionary."""

    provider: Literal["chatgpt", "xai"]
    scenario: str
    access_token: str
    refresh_token: str


def _decode_oauth_connection_scenario(body: bytes) -> _OAuthConnectionScenario:
    payload = _object(json.loads(body))
    if set(payload) != {"provider", "scenario", "access_token", "refresh_token"}:
        raise ValueError("Invalid OAuth fixture scenario.")
    scenario, access_token, refresh_token = (
        payload["scenario"],
        payload["access_token"],
        payload["refresh_token"],
    )
    if (
        not isinstance(scenario, str)
        or not isinstance(access_token, str)
        or not isinstance(refresh_token, str)
    ):
        raise ValueError("Invalid OAuth fixture scenario.")
    match payload["provider"]:
        case "chatgpt":
            return _OAuthConnectionScenario(
                "chatgpt", scenario, access_token, refresh_token
            )
        case "xai":
            return _OAuthConnectionScenario(
                "xai", scenario, access_token, refresh_token
            )
        case _:
            raise ValueError("Invalid OAuth fixture scenario.")


@dataclass(frozen=True)
class _DeviceAuthorizationRequest:
    """The consumed field projected from the extensible provider request."""

    device_auth_id: str | None


def _decode_device_authorization(body: bytes) -> _DeviceAuthorizationRequest:
    # Provider-owned extra fields (such as user_code) remain compatible.
    payload = _object(json.loads(body))
    device_auth_id = payload.get("device_auth_id")
    return _DeviceAuthorizationRequest(
        device_auth_id if isinstance(device_auth_id, str) else None
    )


@dataclass(frozen=True)
class _ImageGenerationRequest:
    """A matching prompt and opaque original wire snapshot for journal egress."""

    prompt: str | None
    wire_json: str


def _decode_image_generation_request(body: bytes) -> _ImageGenerationRequest:
    # OpenAI/xAI own additional generation fields; this fixture consumes prompt.
    payload = _object(json.loads(body))
    prompt = payload.get("prompt")
    return _ImageGenerationRequest(
        prompt if isinstance(prompt, str) else None,
        json.dumps(payload),
    )


def _image_request_egress(request: _ImageGenerationRequest) -> dict[str, object]:
    """Relay the opaque journal snapshot without inspecting its contents."""
    return _object(json.loads(request.wire_json))


class _State:
    catalog_source_variant: ClassVar[_InferenceProfileSourceVariant] = "baseline"
    requests: ClassVar[list[dict[str, object]]] = []
    consolidation_continuations: ClassVar[
        OrderedDict[str, ConsolidationFixtureContinuation]
    ] = OrderedDict()
    openai_image_requests: ClassVar[list[dict[str, object]]] = []
    dynamic_worktree_requests: ClassVar[list[dict[str, object]]] = []
    external_channel_progress_requests: ClassVar[list[dict[str, object]]] = []
    external_channel_file_requests: ClassVar[list[dict[str, object]]] = []
    imagine_requests: ClassVar[list[dict[str, object]]] = []
    oauth_requests: ClassVar[list[dict[str, object]]] = []
    subscription_usage_requests: ClassVar[list[dict[str, object]]] = []
    subscription_usage_sequences: ClassVar[dict[tuple[str, str], int]] = {}
    oauth_connection_queues: ClassVar[dict[str, list[_OAuthConnectionScenario]]] = {
        "chatgpt": [],
        "xai": [],
    }
    oauth_connection_sessions: ClassVar[dict[str, _OAuthConnectionScenario]] = {}
    oauth_connection_sequence: ClassVar[int] = 0
    lock: ClassVar[threading.Lock] = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        """Return a local journal, deterministic usage, or proxied response."""
        if self.path == "/inference-profile/catalog-source":
            with _State.lock:
                variant = _State.catalog_source_variant
            self._write_json(200, _inference_profile_source_payload(variant))
            return
        if self.path == _INFERENCE_PROFILE_BARRIER_PATH:
            self._write_json(200, _INFERENCE_PROFILE_BARRIER.evidence())
            return
        if urlsplit(self.path).path == _OPENAI_MODEL_LIST_PATH:
            self._write_json(200, image_generation_model_list_payload())
            return
        if self.path == _PROVIDER_TOOL_LIVE_BARRIER_PATH:
            self._write_json(200, _PROVIDER_TOOL_LIVE_BARRIER.evidence())
            return
        if self.path == _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_PATH:
            self._write_json(200, _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.evidence())
            return
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                payload = list(journal)
            self._write_json(200, payload)
            return
        if self._write_subscription_usage_get():
            return
        self._proxy()

    def do_DELETE(self) -> None:
        """Clear a local journal or proxy the request."""
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                journal.clear()
                if journal is _State.requests:
                    _State.consolidation_continuations.clear()
                if journal is _State.subscription_usage_requests:
                    _State.subscription_usage_sequences.clear()
            if journal is _State.external_channel_progress_requests:
                _EXTERNAL_CHANNEL_RESPONSES.clear(
                    reset_state=_reset_external_channel_progress_state
                )
            self._write_json(200, {"cleared": True})
            return
        self._proxy()

    def do_POST(self) -> None:
        """Handle deterministic image, hosted-tool, and OAuth boundaries."""
        if self.path == "/inference-profile/catalog-source":
            try:
                control = _decode_inference_profile_source_control(self._read_body())
            except ValueError:
                self._write_json(
                    400,
                    {
                        "error": {
                            "message": "A valid catalog source variant is required."
                        }
                    },
                )
                return
            with _State.lock:
                _State.catalog_source_variant = control.variant
            self._write_json(200, {"variant": control.variant})
            return
        if self.path == _INFERENCE_PROFILE_BARRIER_PATH:
            _INFERENCE_PROFILE_BARRIER.arm()
            self._write_json(201, _INFERENCE_PROFILE_BARRIER.evidence())
            return
        if self.path == f"{_INFERENCE_PROFILE_BARRIER_PATH}/release":
            _INFERENCE_PROFILE_BARRIER.release()
            self._write_json(200, _INFERENCE_PROFILE_BARRIER.evidence())
            return
        if self.path == _PROVIDER_TOOL_LIVE_BARRIER_PATH:
            _PROVIDER_TOOL_LIVE_BARRIER.arm()
            self._write_json(201, _PROVIDER_TOOL_LIVE_BARRIER.evidence())
            return
        if self.path == _PROVIDER_TOOL_LIVE_BARRIER_RELEASE_PATH:
            _PROVIDER_TOOL_LIVE_BARRIER.release()
            self._write_json(200, _PROVIDER_TOOL_LIVE_BARRIER.evidence())
            return
        if self.path == _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_PATH:
            control = _decode_quiet_work_barrier_control(self._read_body())
            if control is None:
                self._write_json(
                    400,
                    {"error": {"message": "A bounded nonblank Binding is required."}},
                )
                return
            _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.arm(control.binding)
            self._write_json(201, _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.evidence())
            return
        if self.path == _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER_RELEASE_PATH:
            _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.release()
            self._write_json(200, _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.evidence())
            return
        body = self._read_body()
        if self.path == _OAUTH_CONNECTION_SCENARIO_PATH:
            self._queue_oauth_connection_scenario(body)
            return
        if self.path == _CHATGPT_DEVICE_USER_CODE_PATH:
            self._write_chatgpt_device_user_code()
            return
        if self.path == _CHATGPT_DEVICE_TOKEN_PATH:
            self._write_chatgpt_device_authorization(body)
            return
        if self.path == _CHATGPT_TOKEN_PATH:
            self._write_chatgpt_oauth_token_response(body)
            return
        if self.path == _XAI_DEVICE_CODE_PATH:
            self._write_xai_device_code()
            return
        if self.path == "/v1/images/generations":
            self._write_image_api_response(body)
            return
        if self.path == "/oauth2/token":
            self._write_xai_oauth_token_response(body)
            return
        if self.path not in {"/v1/responses", "/v1/chat/completions"}:
            self._proxy(body)
            return
        try:
            request = _decode_model_request(json.loads(body))
        except ValueError:
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        if self.path == "/v1/responses":
            request = _EXTERNAL_CHANNEL_RESPONSES.prepare_model(request)
        self._dispatch_prepared_request(request, body)

    def _dispatch_prepared_request(
        self, request: _ModelRequestInput, body: bytes
    ) -> None:
        """Reject retired matchers before any Work or response state mutation."""
        request = _decode_model_request(request)
        if request.context is not None and request.context.generation_present:
            admitted = _EXTERNAL_CHANNEL_RESPONSES.run_if_current(
                request, lambda: self._dispatch_model_request(request, body)
            )
            if not admitted:
                self._write_json(
                    409,
                    {
                        "error": {
                            "message": "External Channel fixture generation retired."
                        }
                    },
                )
            return
        self._dispatch_model_request(request, body)

    def _dispatch_model_request(self, request: _ModelRequestInput, body: bytes) -> None:
        """Route one generation-fenced local model request."""
        request = _decode_model_request(request)
        user_text = _last_user_text(request)
        if self.path == "/v1/responses":
            fixture_request = _model_request_egress(request)
            if is_consolidation_fixture_request(fixture_request):
                try:
                    with _State.lock:
                        logical = consolidation_fixture_request(
                            fixture_request,
                            _State.consolidation_continuations,
                            new_chain_id=os.urandom(16).hex(),
                        )
                        plan = consolidation_fixture_plan(
                            logical.request, chain_id=logical.chain_id
                        )
                        _State.requests.append(
                            {
                                **logical.request,
                                "fixture_consolidation_chain": logical.chain_id,
                                "fixture_physical_input": fixture_request.get("input"),
                            }
                        )
                        if plan.call is not None:
                            call = plan.call
                            response_id = f"resp_{call.call_id.removeprefix('call_')}"
                            item: dict[str, object] = {
                                "id": f"fc_{call.call_id.removeprefix('call_')}",
                                "type": "function_call",
                                "status": "completed",
                                "call_id": call.call_id,
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            }
                            _State.consolidation_continuations[response_id] = (
                                ConsolidationFixtureContinuation(
                                    logical.chain_id,
                                    [
                                        *[
                                            _object(item)
                                            for item in _list(
                                                logical.request.get("input", [])
                                            )
                                        ],
                                        item,
                                    ],
                                )
                            )
                            while len(_State.consolidation_continuations) > 256:
                                _State.consolidation_continuations.popitem(last=False)
                except ValueError:
                    self._write_json(
                        409,
                        {
                            "error": {
                                "message": "Invalid consolidation fixture context."
                            }
                        },
                    )
                    return
                if plan.call is not None:
                    self._write_function_call_response(
                        request,
                        call_id=plan.call.call_id,
                        name=plan.call.name,
                        arguments=plan.call.arguments,
                    )
                else:
                    assert plan.final_text is not None
                    self._write_text_response(
                        request,
                        plan.final_text,
                        response_id=f"resp_consolidation_final_{logical.chain_id}",
                    )
                return
            try:
                historical_summary = historical_memory_summary_response(request)
                historical_inspection = historical_memory_inspection(request)
            except ValueError, json.JSONDecodeError:
                self._write_json(
                    409, {"error": {"message": "Invalid Historical fixture request."}}
                )
                return
            previous = request.previous_response_id
            historical_continuation = isinstance(previous, str) and previous.startswith(
                "resp_historical_memory_"
            )
            if historical_summary is not None:
                with _State.lock:
                    _State.requests.append(_model_request_egress(request))
                if f"{_HISTORICAL_MEMORY_PREFIX}provider-failure" in request.input_json:
                    self._write_json(
                        500,
                        {
                            "error": {
                                "message": "Deterministic Historical provider failure."
                            }
                        },
                    )
                    return
                self._write_text_response(
                    request,
                    historical_summary,
                    response_id="resp_historical_memory_summary",
                )
                return
            if (
                isinstance(user_text, str)
                and user_text.startswith(_HISTORICAL_MEMORY_PREFIX)
            ) or historical_continuation:
                with _State.lock:
                    _State.requests.append(_model_request_egress(request))
                instructions = request.instructions or ""
                if _SESSION_TITLE_SYSTEM_MARKER in instructions:
                    self._write_text_response(
                        request,
                        '{"title":"Historical Memory E2E"}',
                        response_id="resp_historical_memory_title",
                    )
                    return
                if historical_inspection is not None:
                    if not has_current_tool_output(
                        request, historical_inspection.call_id
                    ):
                        if not _request_has_named_tool(
                            request, historical_inspection.name
                        ):
                            self._write_json(
                                409,
                                {"error": {"message": "Generic read tool is missing."}},
                            )
                            return
                        self._write_function_call_response(
                            request,
                            call_id=historical_inspection.call_id,
                            name=historical_inspection.name,
                            arguments=historical_inspection.arguments,
                        )
                        return
                self._write_text_response(
                    request,
                    "HISTORICAL_MEMORY_E2E_TURN_COMPLETED",
                    response_id="resp_historical_memory_turn",
                )
                return
        compaction_request = _is_semantic_compaction_request(request)
        if self.path == "/v1/responses" and is_inference_profile_title_request(request):
            with _State.lock:
                _State.requests.append(_model_request_egress(request))
            self._write_text_response(
                request,
                '{"title":"Synthetic inference profile"}',
                response_id="resp_inference_profile_title",
            )
            return
        if is_external_channel_slack_response_mode_title_request(request):
            self._write_text_response(
                request,
                '{"title":"Initial response mode"}',
                response_id="resp_external_channel_slack_response_mode_title",
            )
            return
        if is_external_channel_discord_title_request(request):
            if self.path == "/v1/responses":
                self._write_text_response(
                    request,
                    _EXTERNAL_CHANNEL_DISCORD_TITLE_RESPONSE,
                    response_id="resp_external_channel_discord_title",
                )
                return
        captured_prompts = _CAPTURED_MODEL_PROMPTS | {
            _SEMANTIC_PROMPT,
            *_SEMANTIC_FOLLOW_UP_RESPONSES,
            *(f"{_BRAVE_PROMPT_PREFIX}{kind}" for kind in _BRAVE_KINDS),
            f"{_BRAVE_PROMPT_PREFIX}disabled",
        }
        matching_text = _decode_model_request(request).matching_text
        watchdog_title_request = _SESSION_TITLE_SYSTEM_MARKER in matching_text and any(
            prompt in matching_text
            for prompt in ("Provider title retry", "Structured title fallback")
        )
        if (
            user_text in captured_prompts
            or watchdog_title_request
            or inference_profile_scenario(user_text) is not None
            or compaction_request
            or request_has_tool_output(request, "call_brave_e2e_images")
            or (
                self.path == "/v1/responses"
                and "Brave Search E2E external_channel"
                in _decode_model_request(request).matching_ascii_text
            )
        ):
            with _State.lock:
                _State.requests.append(_model_request_egress(request))
        profile_scenario = inference_profile_scenario(user_text)
        if self.path == "/v1/responses" and profile_scenario is not None:
            if profile_scenario == "rejected":
                self._write_json(
                    403,
                    {
                        "error": {
                            "message": "Synthetic Ultrafast entitlement rejected.",
                            "type": "permission_error",
                            "code": "ultrafast_unavailable",
                        }
                    },
                )
                return
            if profile_scenario == "retry":
                with _State.lock:
                    attempts = sum(
                        _last_user_text(item) == user_text for item in _State.requests
                    )
                if attempts == 1:
                    self._write_json(
                        429,
                        {
                            "error": {
                                "message": "Synthetic Ultrafast transient rejection.",
                                "type": "rate_limit_error",
                                "code": "rate_limit",
                            }
                        },
                    )
                    return
            if (
                profile_scenario == "prepared"
                and not _INFERENCE_PROFILE_BARRIER.wait_for_release()
            ):
                self._write_json(
                    409, {"error": {"message": "Inference barrier was not released."}}
                )
                return
            self._write_text_response(
                request,
                f"INFERENCE_PROFILE_COMPLETED {profile_scenario}",
                response_id=f"resp_inference_profile_{profile_scenario}",
            )
            return
        if self.path == "/v1/responses" and user_text in {
            _PROMPT,
            _EXPLICIT_IMAGE_PROMPT,
        }:
            call_id = (
                _OPENAI_IMAGE_CALL_ID
                if user_text == _PROMPT
                else f"{_OPENAI_IMAGE_CALL_ID}_explicit"
            )
            if has_current_tool_output(request, call_id):
                self._write_text_response(
                    request,
                    "OPENAI_CLIENT_IMAGE_GENERATION_COMPLETED",
                    response_id="resp_openai_client_image_completed",
                )
                return
            if not _request_has_named_tool(request, "image_generation"):
                self._write_json(
                    409, {"error": {"message": "image_generation tool is unavailable"}}
                )
                return
            self._write_function_call_response(
                request,
                call_id=call_id,
                name="image_generation",
                arguments={"prompt": _OPENAI_IMAGE_PROMPT},
            )
            return
        if self.path == "/v1/responses" and user_text == _FOLLOW_UP_PROMPT:
            self._write_text_response(
                request,
                "PROVIDER_IMAGE_GENERATION_FOLLOW_UP_COMPLETED",
                response_id="resp_openai_client_image_follow_up",
            )
            return
        if (
            self.path == "/v1/responses"
            and "Brave Search E2E external_channel"
            in _decode_model_request(request).matching_ascii_text
            and (binding := external_channel_binding(request)) is not None
        ):
            search_id = "call_brave_e2e_channel_images"
            finish_id = "call_brave_e2e_channel_finish"
            if request_has_tool_output(request, finish_id):
                self._write_text_response(
                    request,
                    "BRAVE_SEARCH_E2E_CHANNEL_COMPLETED",
                    response_id="resp_brave_e2e_channel_completed",
                )
                return
            if request_has_tool_output(request, search_id):
                if not _request_has_named_tool(request, "channel_action"):
                    self._write_json(
                        409,
                        {"error": {"message": "Channel Action is unavailable."}},
                    )
                    return
                self._write_function_call_response(
                    request,
                    call_id=finish_id,
                    name="channel_action",
                    arguments={
                        "mode": "finish",
                        "binding": binding,
                        "message": (
                            "Brave image search found "
                            "https://example.org/brave/original-1.png "
                            "on https://example.org/brave/image-page-1."
                        ),
                    },
                )
                return
            if not _request_has_named_tool(request, "brave__search_images"):
                self._write_json(
                    409,
                    {"error": {"message": "Brave image search is unavailable."}},
                )
                return
            self._write_function_call_response(
                request,
                call_id=search_id,
                name="brave__search_images",
                arguments={"q": "Brave Search E2E external_channel", "count": 2},
            )
            return
        disabled_search_id = "call_brave_e2e_disabled_tool_search"
        if self.path == "/v1/responses" and (
            user_text == f"{_BRAVE_PROMPT_PREFIX}disabled"
            or (
                user_text is None
                and request_has_tool_output(request, disabled_search_id)
            )
        ):
            if request_has_tool_output(request, disabled_search_id):
                self._write_text_response(
                    request,
                    "BRAVE_SEARCH_E2E_DISABLED_VERIFIED",
                    response_id="resp_brave_e2e_disabled_completed",
                )
                return
            if _request_has_named_tool(request, "tool_search"):
                self._write_function_call_response(
                    request,
                    call_id=disabled_search_id,
                    name="tool_search",
                    arguments={"query": "Private Brave E2E search images", "limit": 10},
                )
                return
            self._write_json(
                409, {"error": {"message": "Brave E2E Tool Search is missing."}}
            )
            return
        if self.path == "/v1/responses":
            for kind in _BRAVE_KINDS:
                call_id = f"call_brave_e2e_{kind}"
                search_call_id = f"call_brave_e2e_tool_search_{kind}"
                if user_text != f"{_BRAVE_PROMPT_PREFIX}{kind}" and not (
                    user_text is None
                    and (
                        request_has_tool_output(request, search_call_id)
                        or request_has_tool_output(request, call_id)
                    )
                ):
                    continue
                if request_has_tool_output(request, call_id):
                    self._write_text_response(
                        request,
                        f"BRAVE_SEARCH_E2E_COMPLETED_{kind}",
                        response_id=f"resp_brave_e2e_{kind}_completed",
                    )
                    return
                name = f"brave__search_{kind}"
                if not _request_has_named_tool(request, name):
                    if _request_has_named_tool(
                        request, "tool_search"
                    ) and not request_has_tool_output(request, search_call_id):
                        self._write_function_call_response(
                            request,
                            call_id=search_call_id,
                            name="tool_search",
                            arguments={"query": f"brave search {kind}", "limit": 5},
                        )
                        return
                    self._write_json(
                        409,
                        {"error": {"message": f"Brave E2E tool {name} is missing."}},
                    )
                    return
                self._write_function_call_response(
                    request,
                    call_id=call_id,
                    name=name,
                    arguments={
                        "q": f"Brave E2E {kind}",
                        "count": 3 if kind == "images" else 1,
                    },
                )
                return
        if self.path == "/v1/responses" and is_run_tool_to_file_scenario(request):
            if request_has_tool_output(
                request,
                _RUN_TOOL_TO_FILE_INSPECT_CALL_ID,
            ):
                self._write_text_response(
                    request,
                    "RUN_TOOL_TO_FILE_E2E_COMPLETED",
                    response_id="resp_run_tool_to_file_completed",
                )
                return
            if request_has_tool_output(
                request,
                _RUN_TOOL_TO_FILE_STORE_CALL_ID,
            ):
                self._write_function_call_response(
                    request,
                    call_id=_RUN_TOOL_TO_FILE_INSPECT_CALL_ID,
                    name="exec_command",
                    arguments=_RUN_TOOL_TO_FILE_INSPECT_ARGUMENTS,
                )
                return
            if request_has_tool_output(
                request,
                _RUN_TOOL_TO_FILE_CREATE_CALL_ID,
            ):
                self._write_function_call_response(
                    request,
                    call_id=_RUN_TOOL_TO_FILE_STORE_CALL_ID,
                    name="run_tool_to_file",
                    arguments=_RUN_TOOL_TO_FILE_ARGUMENTS,
                )
                return
            if not all(
                _request_has_named_tool(request, name)
                for name in ("exec_command", "read", "run_tool_to_file")
            ):
                self._write_json(
                    409,
                    {
                        "error": {
                            "message": (
                                "run_tool_to_file E2E request did not expose the "
                                "required Runtime tools."
                            )
                        }
                    },
                )
                return
            self._write_function_call_response(
                request,
                call_id=_RUN_TOOL_TO_FILE_CREATE_CALL_ID,
                name="exec_command",
                arguments=_RUN_TOOL_TO_FILE_CREATE_ARGUMENTS,
            )
            return
        patch_scenario = apply_patch_scenario(request)
        if self.path == "/v1/responses" and patch_scenario == "success":
            if request_has_tool_output(
                request,
                _APPLY_PATCH_SUCCESS_INSPECT_CALL_ID,
            ):
                self._write_text_response(
                    request,
                    "Apply patch E2E success verified.",
                    response_id="resp_apply_patch_success_verified",
                )
                return
            if request_has_tool_output(request, _APPLY_PATCH_SUCCESS_CALL_ID):
                self._write_function_call_response(
                    request,
                    call_id=_APPLY_PATCH_SUCCESS_INSPECT_CALL_ID,
                    name="exec_command",
                    arguments=_APPLY_PATCH_SUCCESS_INSPECT_ARGUMENTS,
                )
                return
            if _request_has_named_tool_type(
                request,
                name="apply_patch",
                tool_type="custom",
            ):
                self._write_custom_tool_call_response(
                    request,
                    call_id=_APPLY_PATCH_SUCCESS_CALL_ID,
                    name="apply_patch",
                    input_value=_APPLY_PATCH_SUCCESS_INPUT,
                )
                return
        if self.path == "/v1/responses" and patch_scenario == "traversal":
            if request_has_tool_output(
                request,
                _APPLY_PATCH_TRAVERSAL_INSPECT_CALL_ID,
            ):
                self._write_text_response(
                    request,
                    "Apply patch E2E traversal rejection verified.",
                    response_id="resp_apply_patch_traversal_verified",
                )
                return
            if request_has_tool_output(request, _APPLY_PATCH_TRAVERSAL_CALL_ID):
                self._write_function_call_response(
                    request,
                    call_id=_APPLY_PATCH_TRAVERSAL_INSPECT_CALL_ID,
                    name="exec_command",
                    arguments=_APPLY_PATCH_TRAVERSAL_INSPECT_ARGUMENTS,
                )
                return
            if _request_has_named_tool_type(
                request,
                name="apply_patch",
                tool_type="custom",
            ):
                self._write_custom_tool_call_response(
                    request,
                    call_id=_APPLY_PATCH_TRAVERSAL_CALL_ID,
                    name="apply_patch",
                    input_value=_APPLY_PATCH_TRAVERSAL_INPUT,
                )
                return
        serialized = _decode_model_request(request).matching_text
        dynamic_worktree_external_stage = _dynamic_worktree_external_stage(request)
        if self.path == "/v1/responses" and dynamic_worktree_external_stage is not None:
            binding = external_channel_binding(request)
            source_path = _dynamic_worktree_external_source(request)
            skill_match = _DYNAMIC_WORKTREE_SKILL_PATH.search(serialized)
            with _State.lock:
                _State.dynamic_worktree_requests.append(
                    {
                        "operation": "external_channel_create",
                        "binding": binding,
                        "stage": dynamic_worktree_external_stage,
                        "create_tool_available": _request_has_named_tool(
                            request,
                            "create_git_worktree",
                        ),
                        "load_skill_available": _request_has_named_tool(
                            request,
                            "load_skill",
                        ),
                        "search_tool_available": _request_has_named_tool(
                            request,
                            "tool_search",
                        ),
                        "channel_action_tool_available": _request_has_named_tool(
                            request,
                            "channel_action",
                        ),
                        "target_skill_present": skill_match is not None,
                    }
                )
            if binding is None:
                self._write_json(
                    409,
                    {
                        "error": {
                            "message": (
                                "External Channel worktree continuity lost its "
                                "active binding."
                            )
                        }
                    },
                )
                return
            if dynamic_worktree_external_stage == "after_finish":
                self._write_text_response(
                    request,
                    "External Channel worktree continuity E2E completed.",
                    response_id="resp_dynamic_worktree_external_completed",
                )
                return
            if dynamic_worktree_external_stage == "after_search":
                if _request_has_named_tool(request, "channel_action"):
                    self._write_function_call_response(
                        request,
                        call_id=_DYNAMIC_WORKTREE_EXTERNAL_FINISH_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "finish",
                            "binding": binding,
                            "message": (
                                "The Agent-managed worktree continuity check "
                                "completed successfully."
                            ),
                        },
                    )
                    return
            elif dynamic_worktree_external_stage == "after_skill":
                if _request_has_named_tool(request, "channel_action"):
                    self._write_function_call_response(
                        request,
                        call_id=_DYNAMIC_WORKTREE_EXTERNAL_FINISH_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "finish",
                            "binding": binding,
                            "message": (
                                "The Agent-managed worktree continuity check "
                                "completed successfully."
                            ),
                        },
                    )
                    return
                if _request_has_named_tool(request, "tool_search"):
                    self._write_function_call_response(
                        request,
                        call_id=_DYNAMIC_WORKTREE_EXTERNAL_SEARCH_CALL_ID,
                        name="tool_search",
                        arguments={
                            "query": "publish final External Channel result",
                            "limit": 5,
                        },
                    )
                    return
            elif dynamic_worktree_external_stage == "continuation":
                if skill_match is not None and _request_has_named_tool(
                    request,
                    "load_skill",
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_DYNAMIC_WORKTREE_EXTERNAL_LOAD_SKILL_CALL_ID,
                        name="load_skill",
                        arguments={"skill_path": skill_match.group(1)},
                    )
                    return
            elif source_path is not None and _request_has_named_tool(
                request, "create_git_worktree"
            ):
                self._write_function_call_response(
                    request,
                    call_id=_DYNAMIC_WORKTREE_EXTERNAL_CREATE_CALL_ID,
                    name="create_git_worktree",
                    arguments={
                        "source_project_path": source_path,
                        "starting_ref": "worktree-e2e-target",
                        "branch_name": "e2e/external-channel-continuity",
                    },
                )
                return
            self._write_json(
                409,
                {
                    "error": {
                        "message": (
                            "External Channel worktree continuity did not "
                            "expose its required Agent tool."
                        )
                    }
                },
            )
            return
        dynamic_worktree = _dynamic_worktree_scenario(request)
        if self.path == "/v1/responses" and dynamic_worktree is not None:
            operation, exact_path, force = dynamic_worktree
            create_continuation = (
                operation == "create"
                and exact_path == ""
                and (
                    "Agent-managed Git worktree creation reached terminal status"
                    in serialized
                )
            )
            remove_continuation = (
                operation == "remove"
                and exact_path == ""
                and (
                    "Agent-managed Git worktree removal reached terminal status"
                    in serialized
                )
            )
            skill_match = _DYNAMIC_WORKTREE_SKILL_PATH.search(serialized)
            stage = "initial"
            if create_continuation:
                stage = (
                    "after_skill"
                    if request_has_tool_output(
                        request,
                        _DYNAMIC_WORKTREE_LOAD_SKILL_CALL_ID,
                    )
                    else "continuation"
                )
            elif remove_continuation:
                stage = "continuation"
            with _State.lock:
                _State.dynamic_worktree_requests.append(
                    {
                        "operation": operation,
                        "force": force,
                        "stage": stage,
                        "create_tool_available": _request_has_named_tool(
                            request,
                            "create_git_worktree",
                        ),
                        "remove_tool_available": _request_has_named_tool(
                            request,
                            "remove_git_worktree",
                        ),
                        "load_skill_available": _request_has_named_tool(
                            request,
                            "load_skill",
                        ),
                        "target_skill_present": skill_match is not None,
                    }
                )
            if operation == "create":
                if create_continuation:
                    if request_has_tool_output(
                        request,
                        _DYNAMIC_WORKTREE_LOAD_SKILL_CALL_ID,
                    ):
                        self._write_text_response(
                            request,
                            "Agent-managed worktree creation continuation completed.",
                            response_id="resp_dynamic_worktree_create_completed",
                        )
                        return
                    if skill_match is not None and _request_has_named_tool(
                        request, "load_skill"
                    ):
                        self._write_function_call_response(
                            request,
                            call_id=_DYNAMIC_WORKTREE_LOAD_SKILL_CALL_ID,
                            name="load_skill",
                            arguments={"skill_path": skill_match.group(1)},
                        )
                        return
                    self._write_json(
                        409,
                        {
                            "error": {
                                "message": (
                                    "Dynamic worktree continuation did not expose "
                                    "the target-only Skill."
                                )
                            }
                        },
                    )
                    return
                if request_has_tool_output(
                    request,
                    _DYNAMIC_WORKTREE_CREATE_CALL_ID,
                ):
                    self._write_json(
                        409,
                        {
                            "error": {
                                "message": (
                                    "Dynamic worktree creation continued without "
                                    "the fresh-Run reminder."
                                )
                            }
                        },
                    )
                    return
                if _request_has_named_tool(request, "create_git_worktree"):
                    self._write_function_call_response(
                        request,
                        call_id=_DYNAMIC_WORKTREE_CREATE_CALL_ID,
                        name="create_git_worktree",
                        arguments={
                            "source_project_path": exact_path,
                            "starting_ref": "worktree-e2e-target",
                            "branch_name": "e2e/agent-managed",
                        },
                    )
                    return
            else:
                call_id = (
                    _DYNAMIC_WORKTREE_REMOVE_FORCE_CALL_ID
                    if force
                    else _DYNAMIC_WORKTREE_REMOVE_DIRTY_CALL_ID
                )
                if remove_continuation:
                    expected_force = f"Force used: {str(force).lower()}."
                    if expected_force not in serialized:
                        self._write_json(
                            409,
                            {
                                "error": {
                                    "message": (
                                        "Dynamic worktree removal continuation "
                                        "reported the wrong force value."
                                    )
                                }
                            },
                        )
                        return
                    self._write_text_response(
                        request,
                        (
                            "Agent-managed worktree forced removal continuation "
                            "completed."
                            if force
                            else (
                                "Agent-managed worktree dirty removal refusal "
                                "continuation completed."
                            )
                        ),
                        response_id=(
                            "resp_dynamic_worktree_remove_force_completed"
                            if force
                            else "resp_dynamic_worktree_remove_dirty_completed"
                        ),
                    )
                    return
                if request_has_tool_output(request, call_id):
                    self._write_json(
                        409,
                        {
                            "error": {
                                "message": (
                                    "Dynamic worktree removal continued without "
                                    "the fresh-Run reminder."
                                )
                            }
                        },
                    )
                    return
                if _request_has_named_tool(request, "remove_git_worktree"):
                    self._write_function_call_response(
                        request,
                        call_id=call_id,
                        name="remove_git_worktree",
                        arguments={
                            "worktree_project_path": exact_path,
                            "force": force,
                        },
                    )
                    return
            self._write_json(
                409,
                {
                    "error": {
                        "message": (
                            "Dynamic worktree scenario did not expose its "
                            "required Agent tool."
                        )
                    }
                },
            )
            return
        if _EXTERNAL_CHANNEL_FILE_MARKER in serialized or bool(
            external_channel_file_locators(request)
        ):
            file_evidence = external_channel_file_evidence(request)
            file_evidence["tool_outputs"] = external_channel_file_tool_output_evidence(
                request
            )
            file_evidence["path"] = self.path
            file_evidence["stage"] = (
                "after_finish"
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FILE_FINISH_CALL_ID,
                )
                else (
                    "after_process"
                    if request_has_tool_output(
                        request,
                        _EXTERNAL_CHANNEL_FILE_PROCESS_CALL_ID,
                    )
                    else (
                        "after_download"
                        if request_has_tool_output(
                            request,
                            _EXTERNAL_CHANNEL_FILE_DOWNLOAD_CALL_ID,
                        )
                        else (
                            "after_search"
                            if request_has_tool_output(
                                request,
                                _EXTERNAL_CHANNEL_FILE_SEARCH_CALL_ID,
                            )
                            else "initial"
                        )
                    )
                )
            )
            with _State.lock:
                _State.external_channel_file_requests.append(file_evidence)
        if (
            _EXTERNAL_CHANNEL_PROGRESS_MARKER in serialized
            or external_channel_binding(request) is not None
            or _request_has_named_tool(request, "channel_action")
        ):
            evidence = external_channel_progress_evidence(request)
            evidence["path"] = self.path
            evidence["matched"] = is_external_channel_progress_request(request)
            evidence["stage"] = (
                "after_finish"
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FINISH_CALL_ID,
                )
                else (
                    "after_progress"
                    if request_has_tool_output(
                        request,
                        _EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
                    )
                    else (
                        "after_search"
                        if request_has_tool_output(
                            request,
                            _EXTERNAL_CHANNEL_SEARCH_CALL_ID,
                        )
                        else "initial"
                    )
                )
            )
            with _State.lock:
                _State.external_channel_progress_requests.append(evidence)
                del _State.external_channel_progress_requests[:-4096]
        if self.path == "/v1/responses" and is_external_channel_file_request(request):
            binding = external_channel_binding(request)
            locators = external_channel_file_locators(request)
            if binding is not None and locators:
                declared_sizes = external_channel_file_declared_sizes(request)
                if (
                    _request_has_named_tool(request, "tool_search")
                    and not request_has_tool_output(
                        request,
                        _EXTERNAL_CHANNEL_FILE_SEARCH_CALL_ID,
                    )
                    and not _request_has_named_tool(
                        request,
                        "download_external_file",
                    )
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_FILE_SEARCH_CALL_ID,
                        name="tool_search",
                        arguments={
                            "query": (
                                "download an external channel file and publish "
                                "the result"
                            ),
                            "limit": 5,
                        },
                    )
                    return
                if not (
                    _request_has_named_tool(request, "download_external_file")
                    and _request_has_named_tool(request, "exec_command")
                    and _request_has_named_tool(request, "channel_action")
                ):
                    self._proxy(body)
                    return
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FILE_FINISH_CALL_ID,
                ):
                    self._write_text_response(
                        request,
                        "External Channel file transfer E2E completed.",
                        response_id="resp_external_channel_file_completed",
                    )
                    return
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FILE_PROCESS_CALL_ID,
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_FILE_FINISH_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "finish",
                            "binding": binding,
                            "message": (
                                "Processed the selected input and attached two "
                                "deterministic results."
                            ),
                            "files": list(_EXTERNAL_CHANNEL_FILE_OUTPUT_PATHS),
                        },
                    )
                    return
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FILE_DOWNLOAD_CALL_ID,
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_FILE_PROCESS_CALL_ID,
                        name="exec_command",
                        arguments={
                            "command": (
                                'python -c "from pathlib import Path; '
                                f"data=Path('{_EXTERNAL_CHANNEL_FILE_INPUT_PATH}')"
                                ".read_text(); "
                                f"Path('{_EXTERNAL_CHANNEL_FILE_OUTPUT_PATHS[0]}')"
                                ".write_text('summary:' + data); "
                                f"Path('{_EXTERNAL_CHANNEL_FILE_OUTPUT_PATHS[1]}')"
                                ".write_text('details:' + data[:64].upper())\""
                            ),
                            "workdir": "/workspace/agent",
                        },
                    )
                    return
                self._write_function_call_response(
                    request,
                    call_id=_EXTERNAL_CHANNEL_FILE_DOWNLOAD_CALL_ID,
                    name="download_external_file",
                    arguments={
                        "file": locators[0],
                        "expected_size_bytes": (
                            declared_sizes[0]
                            if declared_sizes
                            else _EXTERNAL_CHANNEL_FILE_INPUT_BYTES
                        ),
                        "path": _EXTERNAL_CHANNEL_FILE_INPUT_PATH,
                        "overwrite": True,
                    },
                )
                return
        if (
            self.path == "/v1/responses"
            and is_external_channel_quiet_work_setup_request(request)
        ):
            binding = external_channel_binding(request)
            if binding is not None:
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
                ):
                    self._write_text_response(
                        request,
                        "Discord quiet-work setup E2E completed.",
                        response_id="resp_external_channel_quiet_work_setup_completed",
                    )
                    return
                if request_has_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID,
                ):
                    if _request_has_named_tool(request, "channel_action"):
                        self._write_function_call_response(
                            request,
                            call_id=_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
                            name="channel_action",
                            arguments={
                                "mode": "finish",
                                "binding": binding,
                                "message": (
                                    "Discord quiet-work setup binding established."
                                ),
                            },
                        )
                        return
                    self._write_json(
                        409,
                        {
                            "error": {
                                "message": (
                                    "Discord quiet-work setup did not expose "
                                    "channel_action."
                                )
                            }
                        },
                    )
                    return
                if _request_has_named_tool(request, "channel_action"):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_FINISH_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "finish",
                            "binding": binding,
                            "message": (
                                "Discord quiet-work setup binding established."
                            ),
                        },
                    )
                    return
                if _request_has_named_tool(request, "tool_search"):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_QUIET_WORK_SETUP_SEARCH_CALL_ID,
                        name="tool_search",
                        arguments={
                            "query": "establish Discord quiet-work binding",
                            "limit": 5,
                        },
                    )
                    return
            self._write_json(
                409,
                {
                    "error": {
                        "message": (
                            "Discord quiet-work setup did not expose a required tool."
                        )
                    }
                },
            )
            return
        progress_request = is_external_channel_progress_request(request)
        released_outcome_replay = _EXTERNAL_CHANNEL_RESPONSES.released_outcome_replay(
            request
        )
        binding = external_channel_binding(request)
        progress_continuation = _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_active(
            binding
        ) and has_current_external_channel_progress_result(request)
        human_binding = latest_external_channel_human_binding(request)
        awaiting_resume = _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.is_awaiting(
            human_binding
        )
        if awaiting_resume:
            binding = human_binding
        if (
            self.path == "/v1/responses"
            and binding is not None
            and (
                progress_request
                or released_outcome_replay
                or progress_continuation
                or awaiting_resume
                or _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.has_progress_issued_for(binding)
            )
        ):
            if progress_request and not released_outcome_replay:
                _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.start(binding)
            observed_stages = (
                request.context.observed_stages if request.context is not None else ()
            )
            if _EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID in observed_stages:
                _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.complete_progress_boundary(binding)
            if (
                _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.has_progress_issued_for(binding)
                and not released_outcome_replay
            ):
                if _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.hold(binding):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "continue",
                            "binding": binding,
                            "title": "Investigating error logs…",
                        },
                    )
                    return
            if (
                _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.has_progress_issued_for(binding)
                or released_outcome_replay
            ):
                _EXTERNAL_CHANNEL_RESPONSES.remember_released_outcome(request)
                self._write_function_call_response(
                    request,
                    call_id=_EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID,
                    name="channel_action",
                    arguments={
                        "mode": "continue",
                        "binding": binding,
                        "message": "I found a release that matches the incident.",
                        "title": "Investigating error logs…",
                        "todo_update": [
                            {
                                "id": "inspect",
                                "title": "Inspect recent failures",
                                "status": "completed",
                                "output": "The failing release was identified.",
                                "sources": [
                                    {
                                        "url": "https://example.com/logs",
                                        "label": "Error log dashboard",
                                    }
                                ],
                            },
                            {
                                "id": "verify",
                                "title": "Verify the affected release",
                                "status": "completed",
                                "output": "Release 2026.07.23 contains the regression.",
                            },
                            {
                                "id": "trace",
                                "title": "Trace the unavailable dependency",
                                "status": "failed",
                                "output": "The dependency trace was unavailable.",
                            },
                            {
                                "id": "summarize",
                                "title": "Summarize the incident",
                                "status": "in_progress",
                            },
                        ],
                    },
                )
                return
            if awaiting_resume:
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FINISH_CALL_ID,
                ):
                    _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.clear(binding)
                    self._write_text_response(
                        request,
                        "External Channel request-input E2E completed.",
                        response_id="resp_external_channel_request_input_completed",
                    )
                    return
                if _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.hold(binding):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_HELD_PROGRESS_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "continue",
                            "binding": binding,
                            "title": "Investigating error logs…",
                        },
                    )
                    return
                if _request_has_named_tool(
                    request, "tool_search"
                ) and not _request_has_named_tool(request, "channel_action"):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_SEARCH_CALL_ID,
                        name="tool_search",
                        arguments={
                            "query": "external channel finish resumed work",
                            "limit": 5,
                        },
                    )
                    return
                if _request_has_named_tool(request, "channel_action"):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_FINISH_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "finish",
                            "binding": binding,
                            "message": (
                                "The participant response resumed and completed "
                                "the deterministic investigation."
                            ),
                        },
                    )
                    return
                self._write_json(
                    409,
                    {
                        "error": {
                            "message": (
                                "Request-input resume did not expose channel_action."
                            )
                        }
                    },
                )
                return
            if progress_request or progress_continuation:
                if (
                    _request_has_named_tool(request, "tool_search")
                    and not has_current_tool_output(
                        request,
                        _EXTERNAL_CHANNEL_SEARCH_CALL_ID,
                    )
                    and not _request_has_named_tool(request, "channel_action")
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_SEARCH_CALL_ID,
                        name="tool_search",
                        arguments={
                            "query": "external channel publish progress",
                            "limit": 5,
                        },
                    )
                    return
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FINISH_CALL_ID,
                ):
                    _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.clear(binding)
                    self._write_text_response(
                        request,
                        "External Channel progress E2E completed.",
                        response_id="resp_external_channel_progress_completed",
                    )
                    return
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_REQUEST_INPUT_CALL_ID,
                ):
                    _EXTERNAL_CHANNEL_PROGRESS_SEQUENCES.mark_awaiting(binding)
                    self._write_text_response(
                        request,
                        "Waiting for participant input.",
                        response_id="resp_external_channel_request_input_waiting",
                    )
                    return
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID,
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_REQUEST_INPUT_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "request_input",
                            "binding": binding,
                            "message": ("Which incident response option should I use?"),
                        },
                    )
                    return
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID,
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_FAILURE_PROGRESS_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "continue",
                            "binding": binding,
                            "title": "Investigating error logs…",
                            "todo_update": [
                                {
                                    "id": "inspect",
                                    "title": "Inspect recent failures",
                                    "status": "completed",
                                    "output": "The failing release was identified.",
                                    "sources": [
                                        {
                                            "url": "https://example.com/logs",
                                            "label": "Error log dashboard",
                                        }
                                    ],
                                },
                                {
                                    "id": "verify",
                                    "title": "Verify the affected release",
                                    "status": "completed",
                                    "output": (
                                        "Release 2026.07.23 contains the regression."
                                    ),
                                },
                                {
                                    "id": "trace",
                                    "title": "Trace the unavailable dependency",
                                    "status": "failed",
                                    "output": "The dependency trace was unavailable.",
                                },
                                {
                                    "id": "summarize",
                                    "title": "Summarize the incident",
                                    "status": "pending",
                                    "details": "Preparing the incident summary.",
                                },
                            ],
                        },
                    )
                    return
                if has_current_tool_output(
                    request,
                    _EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
                ):
                    self._write_function_call_response(
                        request,
                        call_id=_EXTERNAL_CHANNEL_OUTCOME_PROGRESS_CALL_ID,
                        name="channel_action",
                        arguments={
                            "mode": "continue",
                            "binding": binding,
                            "title": "Investigating error logs…",
                        },
                    )
                    return
                _EXTERNAL_CHANNEL_QUIET_WORK_BARRIER.mark_progress_issued(binding)
                self._write_function_call_response(
                    request,
                    call_id=_EXTERNAL_CHANNEL_PROGRESS_CALL_ID,
                    name="channel_action",
                    arguments={
                        "mode": "continue",
                        "binding": binding,
                        "title": "Investigating error logs…",
                        "todo_update": [
                            {
                                "id": "inspect",
                                "title": "Inspect recent failures",
                                "status": "in_progress",
                                "details": "Comparing recent application errors.",
                                "sources": [
                                    {
                                        "url": "https://example.com/logs",
                                        "label": "Error log dashboard",
                                    }
                                ],
                            },
                            {
                                "id": "verify",
                                "title": "Verify the affected release",
                                "status": "completed",
                                "output": "Release 2026.07.23 contains the regression.",
                            },
                            {
                                "id": "trace",
                                "title": "Trace the unavailable dependency",
                                "status": "failed",
                                "output": "The dependency trace was unavailable.",
                            },
                            {
                                "id": "summarize",
                                "title": "Summarize the incident",
                                "status": "pending",
                            },
                        ],
                    },
                )
                return
        if user_text == _SEMANTIC_PROMPT:
            self._write_semantic_web_search_response(request)
            return
        if user_text == _PROVIDER_TOOL_LIVE_PROMPT:
            self._write_provider_tool_live_response(request)
            return
        if user_text in _SEMANTIC_FOLLOW_UP_RESPONSES:
            self._write_text_response(
                request,
                _SEMANTIC_FOLLOW_UP_RESPONSES[user_text],
                response_id=f"resp_{user_text.lower().replace(' ', '_')}",
            )
            return
        if compaction_request:
            self._write_text_response(
                request,
                _COMPACTION_SUMMARY,
                response_id="resp_provider_semantic_compaction",
            )
            return
        self._proxy(body)

    def _journal_for_path(self) -> list[dict[str, object]] | None:
        """Return the journal selected by the current request path."""
        if self.path == _JOURNAL_PATH:
            return _State.requests
        if self.path == _OPENAI_IMAGE_JOURNAL_PATH:
            return _State.openai_image_requests
        if self.path == _DYNAMIC_WORKTREE_JOURNAL_PATH:
            return _State.dynamic_worktree_requests
        if self.path == _EXTERNAL_CHANNEL_PROGRESS_JOURNAL_PATH:
            return _State.external_channel_progress_requests
        if self.path == _EXTERNAL_CHANNEL_FILE_JOURNAL_PATH:
            return _State.external_channel_file_requests
        if self.path == _XAI_IMAGINE_JOURNAL_PATH:
            return _State.imagine_requests
        if self.path == _XAI_OAUTH_JOURNAL_PATH:
            return _State.oauth_requests
        if self.path == _SUBSCRIPTION_USAGE_JOURNAL_PATH:
            return _State.subscription_usage_requests
        return None

    def _queue_oauth_connection_scenario(self, body: bytes) -> None:
        """Queue one fake account for the next provider device flow."""
        try:
            request = _decode_oauth_connection_scenario(body)
        except ValueError:
            self._write_json(400, {"error": "invalid request"})
            return
        with _State.lock:
            _State.oauth_connection_queues[request.provider].append(request)
        self._write_json(201, {"queued": True, "provider": request.provider})

    @staticmethod
    def _start_oauth_connection(provider: str) -> str | None:
        """Consume the next queued provider account and return its opaque ID."""
        with _State.lock:
            queue = _State.oauth_connection_queues[provider]
            if not queue:
                return None
            _State.oauth_connection_sequence += 1
            connection_id = f"{provider}-{_State.oauth_connection_sequence}"
            _State.oauth_connection_sessions[connection_id] = queue.pop(0)
            return connection_id

    @staticmethod
    def _oauth_connection(connection_id: str) -> _OAuthConnectionScenario | None:
        """Return one configured fake provider account."""
        with _State.lock:
            return _State.oauth_connection_sessions.get(connection_id)

    def _write_chatgpt_device_user_code(self) -> None:
        """Start one deterministic ChatGPT device flow."""
        connection_id = self._start_oauth_connection("chatgpt")
        if connection_id is None:
            self._write_json(409, {"error": "no queued ChatGPT scenario"})
            return
        self._write_json(
            200,
            {
                "device_auth_id": connection_id,
                "user_code": "TEST-CHATGPT",
                "interval": 0,
            },
        )

    def _write_chatgpt_device_authorization(self, body: bytes) -> None:
        """Complete one deterministic ChatGPT device authorization."""
        try:
            request = _decode_device_authorization(body)
        except ValueError:
            self._write_json(400, {"error": "invalid request"})
            return
        connection_id = request.device_auth_id
        if (
            not isinstance(connection_id, str)
            or self._oauth_connection(connection_id) is None
        ):
            self._write_json(404, {"error": "unknown device authorization"})
            return
        self._write_json(
            200,
            {
                "authorization_code": connection_id,
                "code_verifier": "deterministic-code-verifier",
            },
        )

    def _write_xai_device_code(self) -> None:
        """Start one deterministic xAI device flow."""
        connection_id = self._start_oauth_connection("xai")
        if connection_id is None:
            self._write_json(409, {"error": "no queued xAI scenario"})
            return
        self._write_json(
            200,
            {
                "device_code": connection_id,
                "user_code": "TEST-XAI",
                "verification_uri": "https://accounts.x.ai/oauth2/device",
                "verification_uri_complete": (
                    "https://accounts.x.ai/oauth2/device?user_code=TEST-XAI"
                ),
                "interval": 0,
                "expires_in": 900,
            },
        )

    @staticmethod
    def _fake_id_token(claims: dict[str, str]) -> str:
        """Encode unsigned deterministic claims for clients that inspect metadata."""

        def encoded(value: dict[str, str]) -> str:
            raw = json.dumps(value, separators=(",", ":")).encode()
            return urlsafe_b64encode(raw).decode().rstrip("=")

        return f"{encoded({'alg': 'none'})}.{encoded(claims)}.signature"

    def _write_subscription_usage_get(self) -> bool:
        """Handle deterministic subscription-usage provider reads."""
        path = urlsplit(self.path).path
        if path == _CHATGPT_USAGE_PATH:
            self._write_chatgpt_usage(path=path)
            return True
        if path in {_XAI_SETTINGS_PATH, _XAI_BILLING_PATH, _XAI_AUTO_TOP_UP_PATH}:
            self._write_xai_usage(path=path)
            return True
        return False

    def _write_chatgpt_usage(self, *, path: str) -> None:
        """Return one deterministic ChatGPT usage outcome."""
        account_id = self.headers.get("ChatGPT-Account-Id")
        scenario = _CHATGPT_SCENARIOS.get(account_id or "", "unknown")
        sequence = self._next_subscription_sequence(scenario=scenario, path=path)
        authorization = self.headers.get("Authorization")
        headers = {
            "authorization": authorization is not None,
            "account": account_id is not None,
            "originator": self.headers.get("originator") is not None,
            "user_agent": self.headers.get("user-agent") is not None,
        }

        status: int | str
        payload: object
        if scenario == "chatgpt_normal":
            status, payload = 200, self._chatgpt_usage_payload(used_percent=42)
        elif scenario == "chatgpt_exhausted":
            status, payload = 200, self._chatgpt_usage_payload(used_percent=100)
        elif scenario == "chatgpt_refresh":
            if authorization == "Bearer test-chatgpt-refresh-initial":
                status, payload = 401, {"error": "expired"}
            elif authorization == "Bearer test-chatgpt-refreshed":
                status, payload = 200, self._chatgpt_usage_payload(used_percent=35)
            else:
                status, payload = 401, {"error": "invalid"}
        elif scenario == "chatgpt_transport":
            status, payload = "transport_close", None
        elif scenario == "chatgpt_rate_limited":
            status, payload = 429, {"error": "rate_limited"}
        elif scenario == "chatgpt_unavailable":
            status, payload = 503, {"error": "unavailable"}
        elif scenario == "chatgpt_malformed":
            status, payload = 200, {"rate_limit": [None]}
        elif scenario == "chatgpt_stale":
            status, payload = (
                (200, self._chatgpt_usage_payload(used_percent=58))
                if sequence == 1
                else (503, {"error": "unavailable"})
            )
        else:
            status, payload = 400, {"error": "unknown deterministic scenario"}

        self._append_subscription_request(
            scenario=scenario,
            path=path,
            sequence=sequence,
            status=status,
            required_headers=headers,
        )
        if status == "transport_close":
            self.close_connection = True
            self.connection.close()
            return
        self._write_json(status, payload)

    def _write_xai_usage(self, *, path: str) -> None:
        """Return one deterministic xAI settings or billing outcome."""
        account_id = self.headers.get("x-userid")
        scenario = _XAI_USAGE_SCENARIOS.get(account_id or "", "unknown")
        sequence = self._next_subscription_sequence(scenario=scenario, path=path)
        headers = {
            "authorization": self.headers.get("Authorization") is not None,
            "token_auth": self.headers.get("X-XAI-Token-Auth") is not None,
            "account": account_id is not None,
            "client_version": self.headers.get("x-grok-client-version") is not None,
            "client_identifier": self.headers.get("x-grok-client-identifier")
            is not None,
            "client_mode": self.headers.get("x-grok-client-mode") is not None,
        }

        status: int | str
        payload: object
        if path == _XAI_SETTINGS_PATH:
            if scenario == "xai_external":
                status, payload = (
                    200,
                    {
                        "usage_billing_redirect_url": "https://grok.com/usage",
                    },
                )
            elif scenario == "xai_invalid_redirect":
                status, payload = (
                    200,
                    {
                        "usage_billing_redirect_url": "https://example.com/rejected",
                    },
                )
            elif scenario == "xai_settings_failure":
                status, payload = 503, {"error": "unavailable"}
            else:
                status, payload = (
                    200,
                    {
                        "subscription_tier": "supergrok",
                        "subscription_tier_display": "SuperGrok",
                    },
                )
        elif path == _XAI_BILLING_PATH:
            query = parse_qs(urlsplit(self.path).query)
            if query.get("format") != ["credits"]:
                status, payload = 400, {"error": "format is required"}
            elif scenario == "xai_billing_denied":
                status, payload = 403, {"error": "denied"}
            elif scenario == "xai_transport":
                status, payload = "transport_close", None
            elif scenario == "xai_unavailable":
                status, payload = 503, {"error": "unavailable"}
            elif scenario == "xai_malformed":
                status, payload = 200, {"config": [None]}
            elif scenario in {"xai_external", "xai_invalid_redirect"}:
                status, payload = 500, {"error": "billing must be short-circuited"}
            else:
                status, payload = 200, self._xai_billing_payload()
        else:
            status, payload = 200, self._xai_auto_top_up_payload()

        self._append_subscription_request(
            scenario=scenario,
            path=path,
            sequence=sequence,
            status=status,
            required_headers=headers,
        )
        if status == "transport_close":
            self.close_connection = True
            self.connection.close()
            return
        self._write_json(status, payload)

    def _write_chatgpt_oauth_token_response(self, body: bytes) -> None:
        """Return deterministic ChatGPT connection or refresh tokens."""
        form = parse_qs(body.decode())
        if form.get("grant_type") == ["authorization_code"]:
            connection_id = form.get("code", [None])[0]
            connection = (
                self._oauth_connection(connection_id)
                if isinstance(connection_id, str)
                else None
            )
            if connection is None:
                self._write_json(400, {"error": "invalid_grant"})
                return
            scenario = connection.scenario
            self._write_json(
                200,
                {
                    "access_token": connection.access_token,
                    "refresh_token": connection.refresh_token,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "id_token": self._fake_id_token(
                        {
                            "sub": scenario,
                            "email": f"{scenario}@example.com",
                            "plan_type": "Pro",
                        }
                    ),
                },
            )
            return

        refresh_token = form.get("refresh_token", [None])[0]
        scenario = (
            "chatgpt_refresh"
            if refresh_token == "test-chatgpt-refresh-success"
            else "unknown"
        )
        status = 200 if scenario == "chatgpt_refresh" else 400
        sequence = self._next_subscription_sequence(
            scenario=scenario,
            path=_CHATGPT_TOKEN_PATH,
        )
        self._append_subscription_request(
            scenario=scenario,
            path=_CHATGPT_TOKEN_PATH,
            sequence=sequence,
            status=status,
            required_headers={
                "content_type": self.headers.get("Content-Type")
                == "application/x-www-form-urlencoded",
            },
        )
        if status != 200:
            self._write_json(status, {"error": "invalid_grant"})
            return
        self._write_json(
            200,
            {
                "access_token": "test-chatgpt-refreshed",
                "refresh_token": "test-chatgpt-refresh-success",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    @staticmethod
    def _chatgpt_usage_payload(*, used_percent: int) -> dict[str, object]:
        """Build a valid deterministic ChatGPT usage response."""
        return {
            "plan_type": "Pro",
            "rate_limit": {
                "primary_window": {
                    "used_percent": used_percent,
                    "limit_window_seconds": 18_000,
                    "reset_at": 1_784_460_000,
                },
                "secondary_window": {
                    "used_percent": 81,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_784_894_400,
                },
            },
            "additional_rate_limits": [],
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "balance": "120 credits",
            },
            "spend_control": {
                "reached": False,
                "individual_limit": {
                    "limit": "500 credits",
                    "used": "180 credits",
                    "remaining_percent": 64,
                    "reset_at": 1_785_542_400,
                },
            },
        }

    @staticmethod
    def _xai_billing_payload() -> dict[str, object]:
        """Build a valid deterministic xAI billing response."""
        return {
            "subscriptionTier": "SuperGrok",
            "onDemandEnabled": True,
            "config": {
                "creditUsagePercent": 42,
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "start": "2026-07-13T00:00:00+00:00",
                    "end": "2026-07-20T00:00:00+00:00",
                },
                "prepaidBalance": {"val": 2540},
                "onDemandCap": {"val": 10000},
                "onDemandUsed": {"val": 1275},
                "isUnifiedBillingUser": True,
            },
        }

    @staticmethod
    def _xai_auto_top_up_payload() -> dict[str, object]:
        """Build a valid deterministic xAI auto top-up response."""
        return {
            "rule": {
                "enabled": True,
                "minBeforeHittingSl": {"val": 500},
                "topupAmount": {"val": 2000},
                "maxAmountPerMonth": {"val": 10000},
            }
        }

    @staticmethod
    def _next_subscription_sequence(*, scenario: str, path: str) -> int:
        """Return a monotonic request sequence for one safe scenario/path key."""
        key = (scenario, path)
        with _State.lock:
            sequence = _State.subscription_usage_sequences.get(key, 0) + 1
            _State.subscription_usage_sequences[key] = sequence
        return sequence

    @staticmethod
    def _append_subscription_request(
        *,
        scenario: str,
        path: str,
        sequence: int,
        status: int | str,
        required_headers: dict[str, bool],
    ) -> None:
        """Append one sanitized subscription-usage journal entry."""
        with _State.lock:
            _State.subscription_usage_requests.append(
                {
                    "scenario": scenario,
                    "path": path,
                    "sequence": sequence,
                    "status": status,
                    "required_headers": required_headers,
                }
            )

    def _write_image_api_response(self, body: bytes) -> None:
        """Handle the OpenAI client tool and xAI Imagine on their shared path."""
        try:
            request = _decode_image_generation_request(body)
        except ValueError:
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        if request.prompt == _OPENAI_IMAGE_PROMPT:
            with _State.lock:
                _State.openai_image_requests.append(_image_request_egress(request))
            self._write_json(
                200,
                {
                    "created": 1,
                    "data": [
                        {"b64_json": b64encode(_IMAGE_PATH.read_bytes()).decode()}
                    ],
                },
            )
            return
        self._write_xai_imagine_response(body)

    def _write_xai_imagine_response(self, body: bytes) -> None:
        """Return deterministic Imagine output and bounded auth failures."""
        try:
            request = _decode_image_generation_request(body)
        except ValueError:
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        prompt = request.prompt
        if not isinstance(prompt, str):
            self._write_json(400, {"error": {"message": "prompt is required"}})
            return
        credential = self._xai_credential_label()
        status = 200
        if prompt == _XAI_OAUTH_REFRESH_IMAGE_PROMPT and credential == "oauth_initial":
            status = 401
        elif prompt == _XAI_OAUTH_REJECTED_IMAGE_PROMPT:
            status = 401
        elif prompt not in {
            _XAI_API_KEY_IMAGE_PROMPT,
            _XAI_OAUTH_IMAGE_PROMPT,
            _XAI_OAUTH_REFRESH_IMAGE_PROMPT,
            _XAI_OAUTH_REJECTED_IMAGE_PROMPT,
        }:
            status = 400
        with _State.lock:
            _State.imagine_requests.append(
                {
                    "prompt": prompt,
                    "credential": credential,
                    "status": status,
                }
            )
        if status != 200:
            self._write_json(status, {"error": {"message": "deterministic failure"}})
            return
        self._write_json(
            200,
            {"data": [{"b64_json": b64encode(_IMAGE_PATH.read_bytes()).decode()}]},
        )

    def _write_xai_oauth_token_response(self, body: bytes) -> None:
        """Return deterministic xAI connection or refresh tokens."""
        form = parse_qs(body.decode())
        if form.get("grant_type") == ["urn:ietf:params:oauth:grant-type:device_code"]:
            connection_id = form.get("device_code", [None])[0]
            connection = (
                self._oauth_connection(connection_id)
                if isinstance(connection_id, str)
                else None
            )
            if connection is None:
                self._write_json(400, {"error": "invalid_grant"})
                return
            scenario = connection.scenario
            self._write_json(
                200,
                {
                    "access_token": connection.access_token,
                    "refresh_token": connection.refresh_token,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                    "id_token": self._fake_id_token(
                        {
                            "sub": scenario,
                            "email": f"{scenario}@example.com",
                        }
                    ),
                },
            )
            return

        refresh_token = form.get("refresh_token", [None])[0]
        if refresh_token == "test-xai-refresh-success":
            refresh_case = "success"
            access_token = "test-xai-oauth-refreshed"
        elif refresh_token == "test-xai-refresh-rejected":
            refresh_case = "rejected"
            access_token = "test-xai-oauth-rejected-refreshed"
        else:
            self._write_json(400, {"error": "invalid_grant"})
            return
        with _State.lock:
            _State.oauth_requests.append({"refresh_case": refresh_case})
        self._write_json(
            200,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    def _xai_credential_label(self) -> str:
        """Classify deterministic credentials without recording token values."""
        authorization = self.headers.get("Authorization")
        return {
            "Bearer test-xai-api-key": "api_key",
            "Bearer test-xai-oauth-token": "oauth",
            "Bearer test-xai-oauth-refresh-initial": "oauth_initial",
            "Bearer test-xai-oauth-refreshed": "oauth_refreshed",
            "Bearer test-xai-oauth-rejected-initial": "oauth_rejected_initial",
            "Bearer test-xai-oauth-rejected-refreshed": "oauth_rejected_refreshed",
        }.get(authorization or "", "unknown")

    def log_message(self, format: str, *args: object) -> None:
        """Suppress routine proxy access logs."""
        del format, args

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _write_text_response(
        self,
        request: _ModelRequestInput,
        text: str,
        *,
        response_id: str,
    ) -> None:
        """Write one deterministic assistant message response."""
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        item_id = f"msg_{response_id.removeprefix('resp_')}"
        message_item: dict[str, object] = {
            "id": item_id,
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                    "annotations": [],
                }
            ],
        }
        response = self._response(
            request=request,
            response_id=response_id,
            model=model,
            output=[message_item],
        )
        if not request.stream:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {
                        **message_item,
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item": message_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 3,
                    "response": response,
                },
            ]
        )

    def _write_semantic_web_search_response(
        self,
        request: _ModelRequestInput,
    ) -> None:
        """Write Web-search semantics followed by a separate assistant answer."""
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        search_item: dict[str, object] = {
            "id": _SEMANTIC_ITEM_ID,
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": _SEMANTIC_QUERY,
                "sources": [
                    {
                        "type": "url",
                        "url": _SEMANTIC_SOURCE_URL,
                    }
                ],
            },
        }
        message_item: dict[str, object] = {
            "id": "msg_provider_semantic",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": _SEMANTIC_RESPONSE,
                    "annotations": [],
                }
            ],
        }
        response = self._response(
            request=request,
            response_id="resp_provider_semantic",
            model=model,
            output=[search_item, message_item],
        )
        if not request.stream:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {**search_item, "status": "in_progress"},
                },
                {
                    "type": "response.web_search_call.in_progress",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.web_search_call.searching",
                    "sequence_number": 3,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.web_search_call.completed",
                    "sequence_number": 4,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 5,
                    "output_index": 0,
                    "item": search_item,
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 6,
                    "output_index": 1,
                    "item": {
                        **message_item,
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 7,
                    "output_index": 1,
                    "item": message_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 8,
                    "response": response,
                },
            ]
        )

    def _write_provider_tool_live_response(
        self,
        request: _ModelRequestInput,
    ) -> None:
        """Hold one running Web-search event until the E2E snapshot is verified."""
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        search_item: dict[str, object] = {
            "id": _PROVIDER_TOOL_LIVE_ITEM_ID,
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": _PROVIDER_TOOL_LIVE_QUERY,
                "sources": [],
            },
        }
        message_item: dict[str, object] = {
            "id": "msg_provider_tool_live",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": _PROVIDER_TOOL_LIVE_RESPONSE,
                    "annotations": [],
                }
            ],
        }
        response = self._response(
            request=request,
            response_id="resp_provider_tool_live",
            model=model,
            output=[search_item, message_item],
        )
        if not request.stream:
            self._write_json(200, response)
            return

        self._start_sse()
        self._write_sse_events(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {**search_item, "status": "in_progress"},
                },
                {
                    "type": "response.web_search_call.in_progress",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": _PROVIDER_TOOL_LIVE_ITEM_ID,
                },
                {
                    "type": "response.web_search_call.searching",
                    "sequence_number": 3,
                    "output_index": 0,
                    "item_id": _PROVIDER_TOOL_LIVE_ITEM_ID,
                },
            ]
        )
        if not _PROVIDER_TOOL_LIVE_BARRIER.wait_for_release():
            self.close_connection = True
            return
        self._write_sse_events(
            [
                {
                    "type": "response.web_search_call.completed",
                    "sequence_number": 4,
                    "output_index": 0,
                    "item_id": _PROVIDER_TOOL_LIVE_ITEM_ID,
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 5,
                    "output_index": 0,
                    "item": search_item,
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 6,
                    "output_index": 1,
                    "item": {
                        **message_item,
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 7,
                    "output_index": 1,
                    "item": message_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 8,
                    "response": response,
                },
            ]
        )
        self._finish_sse()

    def _write_function_call_response(
        self,
        request: _ModelRequestInput,
        *,
        call_id: str,
        name: str,
        arguments: dict[str, object],
    ) -> None:
        """Write one deterministic Responses function call."""
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        response_id = f"resp_{call_id.removeprefix('call_')}"
        item_id = f"fc_{call_id.removeprefix('call_')}"
        try:
            identity = _EXTERNAL_CHANNEL_RESPONSES.issue(
                request, call_id, arguments=arguments
            )
        except _ExternalChannelStaleResponseContext:
            self._write_json(
                409,
                {"error": {"message": "External Channel fixture generation retired."}},
            )
            return
        if identity is not None:
            call_id, response_id, item_id = identity
        encoded_arguments = json.dumps(
            arguments,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        function_item: dict[str, object] = {
            "id": item_id,
            "type": "function_call",
            "status": "completed",
            "call_id": call_id,
            "name": name,
            "arguments": encoded_arguments,
        }
        response = self._response(
            request=request,
            response_id=response_id,
            model=model,
            output=[function_item],
        )
        if not request.stream:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {
                        **function_item,
                        "status": "in_progress",
                        "arguments": "",
                    },
                },
                {
                    "type": "response.function_call_arguments.done",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": item_id,
                    "name": name,
                    "arguments": encoded_arguments,
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 3,
                    "output_index": 0,
                    "item": function_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 4,
                    "response": response,
                },
            ]
        )

    def _write_custom_tool_call_response(
        self,
        request: _ModelRequestInput,
        *,
        call_id: str,
        name: str,
        input_value: str,
    ) -> None:
        """Write one deterministic Responses plaintext custom-tool call."""
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        response_id = f"resp_{call_id.removeprefix('call_')}"
        item_id = f"ctc_{call_id.removeprefix('call_')}"
        custom_item: dict[str, object] = {
            "id": item_id,
            "type": "custom_tool_call",
            "call_id": call_id,
            "name": name,
            "input": input_value,
        }
        response = self._response(
            request=request,
            response_id=response_id,
            model=model,
            output=[custom_item],
        )
        if not request.stream:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {**custom_item, "input": ""},
                },
                {
                    "type": "response.custom_tool_call_input.delta",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": item_id,
                    "delta": input_value,
                },
                {
                    "type": "response.custom_tool_call_input.done",
                    "sequence_number": 3,
                    "output_index": 0,
                    "item_id": item_id,
                    "input": input_value,
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 4,
                    "output_index": 0,
                    "item": custom_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 5,
                    "response": response,
                },
            ]
        )

    def _response(
        self,
        *,
        request: _ModelRequestInput,
        response_id: str,
        model: str,
        output: list[dict[str, object]],
    ) -> dict[str, object]:
        """Build one completed Responses payload."""
        response: dict[str, object] = {
            "id": response_id,
            "object": "response",
            "created_at": time.time(),
            "model": model,
            "status": "completed",
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": _model_tools_egress(request),
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }

        scenario = inference_profile_scenario(_last_user_text(request))
        if scenario is not None:
            tier = _INFERENCE_PROFILE_TIERS[scenario]
            if tier is not None:
                response["service_tier"] = tier
        return response

    def _write_sse(self, events: list[dict[str, object]]) -> None:
        """Write deterministic Responses server-sent events."""
        self._start_sse()
        self._write_sse_events(events)
        self._finish_sse()

    def _start_sse(self) -> None:
        """Start one Responses server-sent event stream."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _write_sse_events(self, events: list[dict[str, object]]) -> None:
        """Write and flush one ordered batch of Responses stream events."""
        for event in events:
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("Responses event type is missing.")
            encoded = json.dumps(event, separators=(",", ":")).encode()
            self.wfile.write(b"event: " + event_type.encode() + b"\n")
            self.wfile.write(b"data: " + encoded + b"\n\n")
            self.wfile.flush()

    def _finish_sse(self) -> None:
        """Finish one Responses server-sent event stream."""
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _write_image_generation_response(self, request: _ModelRequestInput) -> None:
        image_base64 = b64encode(_IMAGE_PATH.read_bytes()).decode()
        request = _decode_model_request(request)
        model = request.model if request.model is not None else "gpt-5.5"
        response_id = "resp_provider_image_generation"
        item_id = "ig_provider_image_generation"
        created_at = time.time()
        image_item = {
            "id": item_id,
            "type": "image_generation_call",
            "status": "completed",
            "result": image_base64,
        }
        response = {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "status": "completed",
            "output": [image_item],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": _model_tools_egress(request),
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        if not request.stream:
            self._write_json(200, response)
            return

        events: list[dict[str, object]] = [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**response, "status": "in_progress", "output": []},
            },
            {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {
                    "id": item_id,
                    "type": "image_generation_call",
                    "status": "in_progress",
                    "result": None,
                },
            },
            {
                "type": "response.image_generation_call.in_progress",
                "sequence_number": 2,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.generating",
                "sequence_number": 3,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.completed",
                "sequence_number": 4,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 5,
                "output_index": 0,
                "item": image_item,
            },
            {
                "type": "response.completed",
                "sequence_number": 6,
                "response": response,
            },
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("Responses event type is missing.")
            encoded = json.dumps(event, separators=(",", ":")).encode()
            self.wfile.write(b"event: " + event_type.encode() + b"\n")
            self.wfile.write(b"data: " + encoded + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _proxy(self, body: bytes | None = None) -> None:
        target = f"{_UPSTREAM}{self.path}"
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        request = urllib.request.Request(
            target,
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError as error:
            self._write_json(502, {"error": {"message": str(error.reason)}})
            return
        try:
            status = response.getcode()
            self.send_response(status if status is not None else 502)
            for key, value in response.headers.items():
                if key.lower() not in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            read_chunk = (
                response.read1
                if isinstance(response, _ChunkReadable)
                else response.read
            )
            while chunk := read_chunk(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            response.close()
        self.close_connection = True

    def _write_json(self, status: int, value: object) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    """Run the deterministic proxy."""
    server = ThreadingHTTPServer(("0.0.0.0", 8081), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
