"""Internal messages preserve payload invariants without a durable Session fiction."""

import pytest
from pydantic import ValidationError

from azents.core.enums import EventKind
from azents.engine.events.model_messages import (
    TransientModelMessage,
    transient_model_message,
)
from azents.engine.events.types import UserMessagePayload


def test_transient_message_has_only_canonical_semantics() -> None:
    payload = UserMessagePayload(sender_user_id=None, content="Internal scoped data")
    message = transient_model_message(EventKind.USER_MESSAGE, payload)
    assert message.kind is EventKind.USER_MESSAGE and message.payload == payload
    assert set(message.model_dump()) == {"kind", "payload"}
    assert "session_id" not in TransientModelMessage.model_fields
    assert (
        "id" not in TransientModelMessage.model_fields
        and "created_at" not in TransientModelMessage.model_fields
    )


def test_transient_message_rejects_public_event_identity_and_kind() -> None:
    payload = UserMessagePayload(sender_user_id=None, content="Internal data")
    with pytest.raises(ValidationError):
        TransientModelMessage.model_validate(
            {
                "kind": "user_message",
                "payload": payload,
                "session_id": "invented",
                "id": "a" * 32,
            }
        )
    with pytest.raises(ValidationError, match="unavailable"):
        transient_model_message(EventKind.GOAL_CONTINUATION, payload)


def test_transient_payload_uses_the_foreground_canonical_shape_validation() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        transient_model_message(
            EventKind.ASSISTANT_MESSAGE,
            UserMessagePayload(sender_user_id=None, content="Wrong payload"),
        )
