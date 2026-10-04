"""Execution-neutral canonical messages without fabricated durable event identity."""

from typing import Protocol

from pydantic import BaseModel, ConfigDict, model_validator

from azents.core.enums import EventKind
from azents.engine.events.types import EventPayload, validate_message_payload

_INTERNAL_MESSAGE_KINDS = frozenset(
    {
        EventKind.USER_MESSAGE,
        EventKind.ASSISTANT_MESSAGE,
        EventKind.REASONING,
        EventKind.CLIENT_TOOL_CALL,
        EventKind.CLIENT_TOOL_RESULT,
        EventKind.PROVIDER_TOOL_CALL,
        EventKind.UNKNOWN_ADAPTER_OUTPUT,
    }
)


class ModelTranscriptMessage(Protocol):
    """The semantic surface provider lowerers actually consume for any host."""

    @property
    def kind(self) -> EventKind: ...

    @property
    def payload(self) -> EventPayload: ...


class TransientModelMessage(BaseModel):
    """A RAM-only internal message, distinct from the public Event envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: EventKind
    payload: EventPayload

    @model_validator(mode="after")
    def validate_semantics(self) -> "TransientModelMessage":
        if self.kind not in _INTERNAL_MESSAGE_KINDS:
            raise ValueError("Message kind is unavailable to the internal host.")
        validate_message_payload(self.kind, self.payload)
        return self


class ModelMessageFactory[MessageT: ModelTranscriptMessage](Protocol):
    """Purpose-owned envelope construction after shared semantic normalization."""

    def __call__(self, kind: EventKind, payload: EventPayload) -> MessageT: ...


def transient_model_message(
    kind: EventKind, payload: EventPayload
) -> TransientModelMessage:
    return TransientModelMessage(kind=kind, payload=payload)
