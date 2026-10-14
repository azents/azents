"""Domain-specific stream wire identity and strict ingress validation tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Literal

import pytest

from azents_runtime_control.proto import runtime_stream_session_pb2
from azents_runtime_control.runtime_stream_authority_codec import (
    decode_stream_authority,
    encode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    BrowserStreamAuthority,
    LogicalStreamState,
    OwnerSessionEpoch,
    PeerSessionState,
    RequestHead,
    SessionIdentity,
    SessionPeerRole,
    StreamAuthority,
    StreamProtocol,
    WebStreamAuthority,
)

NOW = datetime(2026, 10, 15, tzinfo=UTC)


def _web() -> WebStreamAuthority:
    return WebStreamAuthority(
        correlation_id="correlation",
        authentication_session_id="authentication",
        user_id="user",
        agent_id="agent",
        runtime_id="runtime",
        desired_generation=1,
        runner_generation=2,
        open_deadline_at=NOW + timedelta(seconds=10),
        transport_deadline_at=NOW + timedelta(minutes=1),
        service_id="service",
        service_revision=3,
        identity_id="identity",
        port=8765,
        exposure_deadline_at=NOW + timedelta(hours=1),
    )


def _browser() -> BrowserStreamAuthority:
    web = _web()
    return BrowserStreamAuthority(
        correlation_id=web.correlation_id,
        authentication_session_id=web.authentication_session_id,
        user_id=web.user_id,
        agent_id=web.agent_id,
        runtime_id=web.runtime_id,
        desired_generation=web.desired_generation,
        runner_generation=web.runner_generation,
        open_deadline_at=web.open_deadline_at,
        transport_deadline_at=web.transport_deadline_at,
        session_id="session",
        task_id="task",
        page_id="page",
        resource_incarnation="incarnation",
        allow_input=False,
    )


@pytest.mark.parametrize(
    "authority", [_web(), _browser(), replace(_browser(), allow_input=True)]
)
def test_authority_roundtrip_is_exact(authority: StreamAuthority) -> None:
    encoded = encode_stream_authority(authority)
    serialized = encoded.SerializeToString()
    decoded = decode_stream_authority(
        runtime_stream_session_pb2.RuntimeStreamSessionAuthority.FromString(serialized)
    )
    assert type(decoded) is type(authority)
    assert decoded == authority


def test_browser_authority_has_no_web_forwarding_or_exposure_fields() -> None:
    encoded = encode_stream_authority(_browser())
    assert encoded.WhichOneof("domain") == "browser"
    assert not encoded.HasField("web")
    assert set(encoded.browser.DESCRIPTOR.fields_by_name) == {
        "session_id",
        "task_id",
        "page_id",
        "resource_incarnation",
        "allow_input",
    }
    state = LogicalStreamState(
        stream_id=1,
        authority=_browser(),
        request_head=RequestHead(
            protocol=StreamProtocol.WEBSOCKET,
            method=b"GET",
            target=b"/",
            headers=(),
        ),
        profile=APPROVED_SESSION_PROFILE,
    )
    state.accept()
    assert state.snapshot().accepted


def test_domain_oneof_cannot_preserve_web_and_browser_together() -> None:
    encoded = encode_stream_authority(_web())
    encoded.browser.CopyFrom(encode_stream_authority(_browser()).browser)
    assert encoded.WhichOneof("domain") == "browser"
    assert not encoded.HasField("web")
    assert decode_stream_authority(encoded) == _browser()


@pytest.mark.parametrize("unknown_domain", [b"", b"\x8a\x01\x00", b"\x12\x07service"])
def test_unset_legacy_or_unknown_domain_is_rejected(unknown_domain: bytes) -> None:
    encoded = encode_stream_authority(_web())
    encoded.ClearField("web")
    # Neither a future domain nor an old flat service field can become Web authority.
    encoded.MergeFromString(unknown_domain)
    with pytest.raises(ValueError, match="domain is required"):
        decode_stream_authority(encoded)


@pytest.mark.parametrize(
    "field", ["session_id", "task_id", "page_id", "resource_incarnation"]
)
def test_browser_requires_complete_current_resource_scope(
    field: Literal["session_id", "task_id", "page_id", "resource_incarnation"],
) -> None:
    encoded = encode_stream_authority(_browser())
    encoded.browser.ClearField(field)
    with pytest.raises(ValueError):
        decode_stream_authority(encoded)


@pytest.mark.parametrize("field", ["open_deadline_at", "transport_deadline_at"])
def test_missing_common_deadline_is_rejected(
    field: Literal["open_deadline_at", "transport_deadline_at"],
) -> None:
    encoded = encode_stream_authority(_browser())
    encoded.ClearField(field)
    with pytest.raises(ValueError, match="deadlines are required"):
        decode_stream_authority(encoded)


def test_web_requires_exposure_deadline_and_preserves_ordering() -> None:
    encoded = encode_stream_authority(_web())
    encoded.web.ClearField("exposure_deadline_at")
    with pytest.raises(ValueError, match="exposure deadline is required"):
        decode_stream_authority(encoded)
    with pytest.raises(ValueError, match="Transport deadline"):
        replace(_web(), exposure_deadline_at=NOW)
    with pytest.raises(ValueError, match="Open deadline"):
        replace(_browser(), open_deadline_at=NOW + timedelta(hours=2))


def _peer() -> PeerSessionState:
    peer = PeerSessionState(
        identity=SessionIdentity(
            session_id="transport-session",
            peer_boot_id="runner-boot",
            role=SessionPeerRole.RUNNER,
            owner=OwnerSessionEpoch(
                owner_boot_id="owner-boot",
                session_lease_id="lease",
                lease_generation=4,
                runtime_id="runtime",
                desired_generation=1,
                runner_generation=2,
            ),
            session_nonce="nonce",
            deadline_at=NOW + timedelta(hours=1),
        )
    )
    peer.hello_sent()
    peer.accept(APPROVED_SESSION_PROFILE)
    return peer


def test_browser_wire_authority_roundtrips_through_common_peer_state() -> None:
    peer = _peer()
    authority = decode_stream_authority(encode_stream_authority(_browser()))
    stream = peer.open_stream(
        stream_id=1,
        authority=authority,
        request_head=RequestHead(
            protocol=StreamProtocol.WEBSOCKET, method=b"GET", target=b"/", headers=()
        ),
    )
    assert stream.authority == _browser()
    stream.accept()
    stream.receive_response_head(101, ())
    assert stream.snapshot().response_head_received
    peer.close()
    assert peer.streams == {}


@pytest.mark.parametrize(
    "authority",
    [
        replace(_browser(), runtime_id="another-runtime"),
        replace(_browser(), desired_generation=2),
        replace(_browser(), runner_generation=3),
    ],
)
def test_browser_peer_rejects_mismatched_current_owner(
    authority: BrowserStreamAuthority,
) -> None:
    peer = _peer()
    with pytest.raises(ValueError, match="does not match Owner epoch"):
        peer.open_stream(
            stream_id=1,
            authority=decode_stream_authority(encode_stream_authority(authority)),
            request_head=RequestHead(
                protocol=StreamProtocol.WEBSOCKET,
                method=b"GET",
                target=b"/",
                headers=(),
            ),
        )
    assert peer.last_stream_id == 0
    assert peer.streams == {}
