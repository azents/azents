"""Runner Control metadata-only Runtime Web intent tests."""

import datetime

import pytest
from azents_runtime_control.runner_web import RunnerWebCancelReason

from azents.runtime.control_protocol.grpc.runner_server import (
    _runner_web_cancel_intent,
    _runner_web_open_intent,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeCoordinationTarget,
    RuntimeRequestEnvelope,
)


def _envelope(
    *,
    operation_type: str,
    reason: str | None = None,
) -> RuntimeRequestEnvelope:
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    payload: dict[str, JsonValue] = {
        "tunnel_id": "tunnel-1",
        "endpoint_id": "endpoint-1",
        "cycle_id": "cycle-1",
        "endpoint_authority_revision": 4,
        "close_barrier": 2,
        "runtime_id": "runtime-1",
        "desired_generation": 3,
        "runner_generation": 5,
        "port": 3000,
        "join_nonce": "join-1",
        "registration_deadline_at": (now + datetime.timedelta(seconds=30)).isoformat(),
        "approval_deadline_at": (now + datetime.timedelta(minutes=5)).isoformat(),
        "transport_deadline_at": (now + datetime.timedelta(minutes=5)).isoformat(),
    }
    if reason is not None:
        payload["reason"] = reason
    return RuntimeRequestEnvelope(
        request_id="request-1",
        runtime_id="runtime-1",
        target=RuntimeCoordinationTarget.RUNNER,
        generation=5,
        operation_type=operation_type,
        payload={
            "operation_type": operation_type,
            "owner_session_id": None,
            "payload": payload,
        },
        reply_stream_id="reply-1",
        deadline_at=now + datetime.timedelta(seconds=30),
        body_stream_id=None,
    )


def test_runner_control_decodes_exact_web_open_and_cancel_intents() -> None:
    """Control stream carries only exact bounded Runtime Web metadata."""
    opened = _runner_web_open_intent(_envelope(operation_type="runtime.web.open.v1"))
    cancelled = _runner_web_cancel_intent(
        _envelope(
            operation_type="runtime.web.cancel.v1",
            reason="authority_revoked",
        )
    )

    assert opened.identity.tunnel_id == "tunnel-1"
    assert opened.identity.runner_generation == 5
    assert cancelled.identity == opened.identity
    assert cancelled.reason is RunnerWebCancelReason.AUTHORITY_REVOKED


def test_runner_control_rejects_changed_web_intent_shape() -> None:
    """Extra or missing metadata cannot bypass the exact tunnel contract."""
    envelope = _envelope(operation_type="runtime.web.open.v1")
    inner = envelope.payload["payload"]
    assert isinstance(inner, dict)
    inner["unexpected"] = "value"

    with pytest.raises(ValueError, match="fields are invalid"):
        _runner_web_open_intent(envelope)
