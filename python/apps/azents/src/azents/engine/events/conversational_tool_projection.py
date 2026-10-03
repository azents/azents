"""Typed historical projection of client tools that publish conversation."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from azents.engine.events.output_parts import lower_output_to_text
from azents.engine.events.sensitive_text import (
    redact_sensitive_text,
    sanitize_json_value,
)
from azents.engine.events.types import ClientToolCallPayload, ClientToolResultPayload

ConversationSpeaker = Literal["assistant"]
ConversationDeliveryStatus = Literal["delivered", "failed", "unknown"]


class RenderedConversationContext(NamedTuple):
    """One named context value ready for historical text rendering."""

    label: str
    value: str


@dataclasses.dataclass(frozen=True)
class ConversationToolProjectionSpec:
    """Participant attribution for one registered durable tool name."""

    durable_tool_name: str
    speaker: ConversationSpeaker


@dataclasses.dataclass(frozen=True)
class ConversationalToolProjection:
    """One semantic conversation item reconstructed from a client-tool call."""

    tool_name: str
    speaker: ConversationSpeaker
    text: str | None
    context: tuple[RenderedConversationContext, ...]
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
            lines.extend(f"- {item.label}: {item.value}" for item in self.context)
        return "\n".join(lines)


def _render_context(value: object, *, label: str) -> RenderedConversationContext | None:
    """Normalize one historical context value at the decoding boundary."""
    if value is None or value == [] or value == {}:
        return None
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
    return RenderedConversationContext(label=label, value=rendered)


class _ChannelActionConversationInput(BaseModel):
    """Decode the historical conversation view, not today's executable input.

    Historical calls may omit current execution fields or contain unrelated
    fields. Invalid optional text is ignored and arbitrary context is rendered
    at ingress, preserving the existing historical projection contract.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)
    ignored: bool = Field(default=False, validation_alias="mode")
    text: str | None = Field(default=None, validation_alias="message")
    title: RenderedConversationContext | None = None
    todo_update: RenderedConversationContext | None = None

    @field_validator("ignored", mode="before")
    @classmethod
    def decode_mode(cls, value: object) -> bool:
        return isinstance(value, str) and value == "ignore"

    @field_validator("text", mode="before")
    @classmethod
    def decode_text(cls, value: object) -> str | None:
        if isinstance(value, str) and value.strip():
            return redact_sensitive_text(value.strip())
        return None

    @field_validator("title", mode="before")
    @classmethod
    def decode_title(cls, value: object) -> RenderedConversationContext | None:
        return _render_context(value, label="title")

    @field_validator("todo_update", mode="before")
    @classmethod
    def decode_todo_update(cls, value: object) -> RenderedConversationContext | None:
        return _render_context(value, label="todo_update")


class _ChannelActionReplyOutcome(BaseModel):
    """Typed reply evidence with tolerant historical field decoding."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    operation: str | None = None
    status: str | None = None

    @field_validator("operation", "status", mode="before")
    @classmethod
    def decode_text(cls, value: object) -> str | None:
        return value if isinstance(value, str) else None


class _ChannelActionConversationResult(BaseModel):
    """Decode only ordered historical outcomes; ignore unrelated output fields."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    outcomes: tuple[_ChannelActionReplyOutcome, ...] = ()

    @field_validator("outcomes", mode="before")
    @classmethod
    def decode_outcomes(cls, value: object) -> tuple[_ChannelActionReplyOutcome, ...]:
        if not isinstance(value, list):
            return ()
        return tuple(
            _ChannelActionReplyOutcome.model_validate(item)
            for item in value
            if isinstance(item, dict)
        )


_CHANNEL_ACTION_SPEC = ConversationToolProjectionSpec(
    durable_tool_name="channel_action",
    speaker="assistant",
)
CONVERSATIONAL_TOOL_PROJECTIONS: Mapping[str, ConversationToolProjectionSpec] = (
    MappingProxyType({_CHANNEL_ACTION_SPEC.durable_tool_name: _CHANNEL_ACTION_SPEC})
)


def project_conversational_tool_call(
    call: ClientToolCallPayload,
    result: ClientToolResultPayload | None,
) -> ConversationalToolProjection | None:
    """Project one registered client call into participant-visible conversation."""
    spec = CONVERSATIONAL_TOOL_PROJECTIONS.get(call.name)
    if spec is None or call.wire_dialect != "json_function":
        return None
    try:
        arguments = _ChannelActionConversationInput.model_validate_json(call.arguments)
    except ValidationError:
        return None
    if arguments.ignored:
        return None
    context = tuple(
        item for item in (arguments.title, arguments.todo_update) if item is not None
    )
    if arguments.text is None and not context:
        return None
    return ConversationalToolProjection(
        tool_name=call.name,
        speaker=spec.speaker,
        text=arguments.text,
        context=context,
        delivery_status=_delivery_status(result)
        if arguments.text is not None
        else None,
    )


def _delivery_status(
    result: ClientToolResultPayload | None,
) -> ConversationDeliveryStatus:
    if result is None:
        return "unknown"
    if result.status == "failed":
        return "failed"
    if result.status != "completed":
        return "unknown"
    try:
        payload = _ChannelActionConversationResult.model_validate_json(
            lower_output_to_text(result.output)
        )
    except ValidationError:
        return "unknown"
    for outcome in payload.outcomes:
        if outcome.operation != "reply":
            continue
        if outcome.status == "delivered":
            return "delivered"
        if outcome.status in {"failed", "not_attempted"}:
            return "failed"
        return "unknown"
    return "unknown"
