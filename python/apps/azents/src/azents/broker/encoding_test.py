"""Broker message encoding tests."""

from .redis import decode_broker_message, encode_broker_message
from .types import SessionStopSignal


def test_broker_message_roundtrip_with_session_stop_signal() -> None:
    """Preserves the stop signal broker message type."""
    message = SessionStopSignal(
        session_id="sess-1",
        user_id="user-1",
        stop_request_id="stop-1",
    )

    decoded = decode_broker_message(encode_broker_message(message))

    assert decoded == message
    assert isinstance(decoded, SessionStopSignal)


def test_legacy_stop_signal_without_request_id_remains_decodable() -> None:
    """Rolling deploys accept already-queued stop wake hints from older workers."""
    decoded = decode_broker_message(
        b'{"session_id":"sess-1","user_id":"user-1","type":"session_stop_signal"}'
    )

    assert decoded == SessionStopSignal(
        session_id="sess-1",
        user_id="user-1",
        stop_request_id=None,
    )
