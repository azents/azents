"""Broker message encoding tests."""

from .redis import decode_broker_message, encode_broker_message
from .types import SessionStopSignal


def test_broker_message_roundtrip_with_session_stop_signal() -> None:
    """Preserves the stop signal broker message type."""
    message = SessionStopSignal(session_id="sess-1")

    decoded = decode_broker_message(encode_broker_message(message))

    assert decoded == message
    assert isinstance(decoded, SessionStopSignal)
