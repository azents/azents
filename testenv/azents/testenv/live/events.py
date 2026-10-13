"""Typed observations of the public Chat action transport.

The public transport owns envelope/payload extensions. Only fields interpreted
by these helpers are projected; provider artifacts and unrelated payloads stay
opaque. Canonical event kinds come from the generated public contract.
"""

from typing import Literal, Self

from azentspublicclient.models.chat_event_response import ChatEventResponse
from azentspublicclient.models.event_kind import EventKind
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class WireObservation(BaseModel):
    """Strict interpreted fields with public transport extension compatibility."""

    model_config = ConfigDict(strict=True, extra="allow", frozen=True, hide_input_in_errors=True)


class TextPart(WireObservation):
    """Public text output part."""

    type: Literal["text", "output_text"]
    text: str


class RichPart(WireObservation):
    """Rich output whose fields this helper does not interpret."""

    type: Literal["attachment", "artifact", "file"]


ContentPart = TextPart | RichPart


class AssistantPayload(WireObservation):
    """Assistant output, including structured text and rich content."""

    content: str | list[ContentPart]


class ToolCallPayload(WireObservation):
    """Canonical client-tool identity; arguments remain opaque."""

    call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ToolResultPayload(WireObservation):
    """Canonical client-tool terminal result."""

    call_id: str = Field(min_length=1)
    name: str | None = None
    status: Literal["completed", "failed", "cancelled", "interrupted"]
    output: str | list[ContentPart] = Field(default_factory=list)


class RunMarkerPayload(WireObservation):
    """Durable run completion, distinct from successful tool completion."""

    run_id: str = Field(min_length=1)
    status: Literal["completed", "stopped", "failed", "interrupted"]


class OpaquePayload(WireObservation):
    """Uninterpreted canonical payload retained solely as relay evidence."""

    value: JsonValue


Payload = AssistantPayload | ToolCallPayload | ToolResultPayload | RunMarkerPayload | OpaquePayload


class ChatEvent(WireObservation):
    """Canonical event identity and its explicitly decoded observation payload."""

    id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    kind: EventKind
    payload: Payload

    @model_validator(mode="before")
    @classmethod
    def decode_payload(cls, value: object) -> object:
        """Decode the kind-specific payload once, at the wire boundary."""
        if not isinstance(value, dict):
            return value
        decoded = dict(value)
        canonical = ChatEventResponse.model_validate(value)
        kind = canonical.kind
        raw = canonical.payload
        match kind:
            case EventKind.ASSISTANT_MESSAGE:
                payload = AssistantPayload.model_validate(raw)
            case EventKind.CLIENT_TOOL_CALL:
                payload = ToolCallPayload.model_validate(raw)
            case EventKind.CLIENT_TOOL_RESULT:
                payload = ToolResultPayload.model_validate(raw)
            case EventKind.RUN_MARKER:
                payload = RunMarkerPayload.model_validate(raw)
            case _:
                payload = OpaquePayload(value=raw)
        decoded["kind"] = kind
        decoded["payload"] = payload
        return decoded


ActionType = Literal[
    "action_execution_removed",
    "action_execution_updated",
    "mailbox_item_removed",
    "mailbox_item_upserted",
    "history_event_appended",
    "input_actions_updated",
    "live_event_removed",
    "live_event_upserted",
    "live_projection_reset",
    "live_run_cleared",
    "live_run_updated",
    "subagent_tree_changed",
    "subscribed",
    "subscription_health_check_ack",
    "todo_state_changed",
]


class ChatAction(WireObservation):
    """Public Chat action; event-bearing variants require a typed event."""

    type: ActionType
    session_id: str | None = None
    event: ChatEvent | None = None

    @model_validator(mode="after")
    def require_variant_fields(self) -> Self:
        """Validate the fields this helper uses for each action variant."""
        if self.type not in {"subagent_tree_changed", "todo_state_changed"}:
            if self.session_id is None:
                raise ValueError("Chat action requires session_id")
        if self.type in {"history_event_appended", "live_event_upserted"}:
            if self.event is None:
                raise ValueError("Event action requires event")
        return self


def event_name(action: ChatAction) -> str:
    """Return canonical event kind for event actions, otherwise action type."""
    return action.event.kind.value if action.event is not None else action.type


def terminal_run(action: ChatAction) -> bool:
    """Recognize a durable terminal run marker on the public transport."""
    return (
        action.type == "history_event_appended"
        and action.event is not None
        and isinstance(action.event.payload, RunMarkerPayload)
    )


def content_text(content: str | list[ContentPart]) -> str:
    """Extract canonical text parts without interpreting rich output payloads."""
    if isinstance(content, str):
        return content
    return "\n".join(part.text for part in content if isinstance(part, TextPart))
