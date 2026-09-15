"""Replacement Runtime Web session protocol foundation tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import azents_runtime_control.runtime_web_session as runtime_web_session_module
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    APPROVED_SESSION_PROFILE,
    MANDATORY_DATA_FRAME_BYTES,
    MAX_STREAM_TOMBSTONES,
    MAX_WEBSOCKET_MESSAGE_BYTES,
    OPTIONAL_DATA_FRAME_BYTES,
    RUNTIME_WEB_CAPABILITY,
    RUNTIME_WEB_PROTOCOL_FINGERPRINT,
    CloseReason,
    Header,
    LogicalStreamState,
    OwnerSessionEpoch,
    PeerSessionState,
    RequestHead,
    RunnerSessionOffer,
    SessionIdentity,
    SessionPeerRole,
    SessionProfile,
    SessionState,
    StreamAuthority,
    StreamDirection,
    StreamProtocol,
    WebSocketOpcode,
    protocol_fingerprint,
)

NOW = datetime(2026, 9, 14, tzinfo=UTC)


def _identity(role: SessionPeerRole = SessionPeerRole.RUNNER) -> SessionIdentity:
    owner = None
    if role is not SessionPeerRole.GATEWAY:
        owner = OwnerSessionEpoch(
            owner_boot_id="boot-1",
            session_lease_id="lease-1",
            lease_generation=1,
            runtime_id="runtime-1",
            desired_generation=2,
            runner_generation=3,
        )
    return SessionIdentity(
        session_id="session-1",
        peer_boot_id="peer-boot-1",
        role=role,
        owner=owner,
        session_nonce="nonce-1",
        deadline_at=NOW + timedelta(seconds=10),
    )


def _authority() -> StreamAuthority:
    return StreamAuthority(
        correlation_id="correlation-1",
        service_id="endpoint-1",
        service_revision=4,
        identity_id="identity-1",
        authentication_session_id="auth-session-1",
        user_id="user-1",
        agent_id="agent-session-1",
        runtime_id="runtime-1",
        desired_generation=2,
        runner_generation=3,
        port=6006,
        open_deadline_at=NOW + timedelta(seconds=10),
        exposure_deadline_at=NOW + timedelta(hours=1),
        transport_deadline_at=NOW + timedelta(minutes=30),
    )


def _head(protocol: StreamProtocol = StreamProtocol.HTTP) -> RequestHead:
    return RequestHead(
        protocol=protocol,
        method=b"GET",
        target=b"/index.html",
        headers=(Header(name=b"accept", value=b"*/*"),),
    )


def _stream(protocol: StreamProtocol = StreamProtocol.HTTP) -> LogicalStreamState:
    return LogicalStreamState(
        stream_id=1,
        authority=_authority(),
        request_head=_head(protocol),
        profile=APPROVED_SESSION_PROFILE,
    )


def test_schema_and_fingerprint_are_exact() -> None:
    assert set(runtime_web_session_pb2.DESCRIPTOR.services_by_name) == {
        "RuntimeRunnerWebSession",
        "RuntimeWebControlSession",
        "RuntimeWebGatewaySession",
    }
    assert RUNTIME_WEB_CAPABILITY == "runtime-web-http"
    assert (
        RUNTIME_WEB_PROTOCOL_FINGERPRINT
        == "3e0dcc00e011b6e7ad0fa3d2ce445eee0c1f8822e9f0c9d792d6f2c6d7586089"
    )
    assert (
        protocol_fingerprint(descriptor=b"different")
        != RUNTIME_WEB_PROTOCOL_FINGERPRINT
    )
    assert (
        protocol_fingerprint(material={"changed": True})
        != RUNTIME_WEB_PROTOCOL_FINGERPRINT
    )
    assert (
        protocol_fingerprint(runner_offer_descriptor=b"different")
        != RUNTIME_WEB_PROTOCOL_FINGERPRINT
    )
    assert (
        protocol_fingerprint(runner_offer_field_descriptor=b"different")
        != RUNTIME_WEB_PROTOCOL_FINGERPRINT
    )


def test_runner_offer_accepts_authority_without_destination() -> None:
    RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id="boot-1",
            session_lease_id="lease-1",
            lease_generation=1,
            runtime_id="runtime-1",
            desired_generation=2,
            runner_generation=3,
        ),
        session_nonce="nonce",
        protocol_fingerprint=RUNTIME_WEB_PROTOCOL_FINGERPRINT,
        deadline_at=NOW + timedelta(seconds=10),
    )


def test_profile_accepts_only_approved_frame_sizes() -> None:
    assert APPROVED_SESSION_PROFILE.data_frame_bytes == MANDATORY_DATA_FRAME_BYTES
    SessionProfile(
        data_frame_bytes=OPTIONAL_DATA_FRAME_BYTES,
        request_stream_window_bytes=APPROVED_SESSION_PROFILE.request_stream_window_bytes,
        response_stream_window_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
        request_session_window_bytes=APPROVED_SESSION_PROFILE.request_session_window_bytes,
        response_session_window_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
    )
    with pytest.raises(ValueError, match="unsupported"):
        SessionProfile(
            data_frame_bytes=64 * 1024,
            request_stream_window_bytes=APPROVED_SESSION_PROFILE.request_stream_window_bytes,
            response_stream_window_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
            request_session_window_bytes=APPROVED_SESSION_PROFILE.request_session_window_bytes,
            response_session_window_bytes=APPROVED_SESSION_PROFILE.response_session_window_bytes,
        )


def test_session_and_http_lifecycle_releases_terminal_stream() -> None:
    session = PeerSessionState(identity=_identity())
    session.hello_sent()
    session.accept(APPROVED_SESSION_PROFILE)
    stream = session.open_stream(
        stream_id=1, authority=_authority(), request_head=_head()
    )
    stream.accept()
    stream.receive_data(StreamDirection.REQUEST, 1, b"request")
    stream.end_direction(StreamDirection.REQUEST, 1)
    stream.receive_response_head(200, (Header(b"content-type", b"text/plain"),))
    stream.receive_data(StreamDirection.RESPONSE, 1, b"response")
    stream.end_direction(StreamDirection.RESPONSE, 1)
    stream.finish()
    assert stream.snapshot().completed
    session.release_stream(1)
    assert not session.streams
    assert 1 in session.tombstone_set
    session.start_draining(1)
    assert session.state is SessionState.DRAINING
    session.close()
    assert not session.tombstones


def test_http_and_websocket_frame_kinds_and_effective_size_are_separate() -> None:
    http = _stream()
    http.accept()
    with pytest.raises(ValueError, match="invalid size"):
        http.receive_data(StreamDirection.REQUEST, 1, b"x" * OPTIONAL_DATA_FRAME_BYTES)

    websocket = _stream(StreamProtocol.WEBSOCKET)
    websocket.accept()
    websocket.receive_response_head(101, ())
    with pytest.raises(ValueError, match="typed frames"):
        websocket.receive_data(StreamDirection.REQUEST, 1, b"bypass")


def test_http_request_body_limit_is_enforced_across_data_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runtime_web_session_module, "MAX_REQUEST_BODY_BYTES", 4)
    stream = _stream()
    stream.accept()

    stream.receive_data(StreamDirection.REQUEST, 1, b"abc")
    with pytest.raises(ValueError, match="request body exceeds"):
        stream.receive_data(StreamDirection.REQUEST, 2, b"de")

    assert stream.request_body_bytes == 3
    assert stream.request_sequence == 1


def test_websocket_control_interleaves_and_close_fences_each_direction() -> None:
    stream = _stream(StreamProtocol.WEBSOCKET)
    stream.accept()
    stream.receive_response_head(101, ())
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=1,
        opcode=WebSocketOpcode.TEXT,
        final=False,
        data=b"hel",
    )
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=2,
        opcode=WebSocketOpcode.PING,
        final=True,
        data=b"",
    )
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=3,
        opcode=WebSocketOpcode.CONTINUATION,
        final=True,
        data=b"lo",
    )
    stream.receive_websocket(
        direction=StreamDirection.RESPONSE,
        sequence=1,
        opcode=WebSocketOpcode.CLOSE,
        final=True,
        data=(1000).to_bytes(2, "big"),
    )
    with pytest.raises(ValueError, match="already closed"):
        stream.receive_websocket(
            direction=StreamDirection.RESPONSE,
            sequence=2,
            opcode=WebSocketOpcode.BINARY,
            final=True,
            data=b"late",
        )
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=4,
        opcode=WebSocketOpcode.BINARY,
        final=True,
        data=b"still-open",
    )


def test_websocket_close_rejects_reserved_codes_and_releases_direction_payload() -> (
    None
):
    stream = _stream(StreamProtocol.WEBSOCKET)
    stream.accept()
    stream.receive_response_head(101, ())
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=1,
        opcode=WebSocketOpcode.BINARY,
        final=False,
        data=b"partial",
    )
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=2,
        opcode=WebSocketOpcode.CLOSE,
        final=True,
        data=(1000).to_bytes(2, "big"),
    )
    assert stream.websocket_opcode[StreamDirection.REQUEST] is None
    assert not stream.websocket_message_data[StreamDirection.REQUEST]

    reserved = _stream(StreamProtocol.WEBSOCKET)
    reserved.accept()
    reserved.receive_response_head(101, ())
    with pytest.raises(ValueError, match="close code"):
        reserved.receive_websocket(
            direction=StreamDirection.REQUEST,
            sequence=1,
            opcode=WebSocketOpcode.CLOSE,
            final=True,
            data=(2000).to_bytes(2, "big"),
        )


def test_websocket_message_limit_and_utf8_are_directional() -> None:
    stream = _stream(StreamProtocol.WEBSOCKET)
    stream.accept()
    stream.receive_response_head(101, ())
    stream.receive_websocket(
        direction=StreamDirection.REQUEST,
        sequence=1,
        opcode=WebSocketOpcode.BINARY,
        final=False,
        data=b"a" * MANDATORY_DATA_FRAME_BYTES,
    )
    for sequence in range(
        2, MAX_WEBSOCKET_MESSAGE_BYTES // MANDATORY_DATA_FRAME_BYTES + 1
    ):
        stream.receive_websocket(
            direction=StreamDirection.REQUEST,
            sequence=sequence,
            opcode=WebSocketOpcode.CONTINUATION,
            final=False,
            data=b"b" * MANDATORY_DATA_FRAME_BYTES,
        )
    with pytest.raises(ValueError, match="maximum size"):
        stream.receive_websocket(
            direction=StreamDirection.REQUEST,
            sequence=5,
            opcode=WebSocketOpcode.CONTINUATION,
            final=False,
            data=b"c",
        )


def test_session_tombstones_are_bounded() -> None:
    session = PeerSessionState(identity=_identity())
    session.hello_sent()
    session.accept(APPROVED_SESSION_PROFILE)
    for stream_id in range(1, MAX_STREAM_TOMBSTONES + 3):
        stream = session.open_stream(
            stream_id=stream_id, authority=_authority(), request_head=_head()
        )
        stream.reject(CloseReason.RESOURCE_EXHAUSTED)
        session.release_stream(stream_id)
    assert len(session.tombstones) == MAX_STREAM_TOMBSTONES
    assert 1 not in session.tombstone_set


def test_gateway_session_cannot_carry_owner_epoch() -> None:
    gateway = _identity(SessionPeerRole.GATEWAY)
    assert gateway.owner is None
    with pytest.raises(ValueError, match="must not carry"):
        SessionIdentity(
            session_id="gateway",
            peer_boot_id="gateway-boot",
            role=SessionPeerRole.GATEWAY,
            owner=_identity().owner,
            session_nonce="nonce",
            deadline_at=NOW + timedelta(seconds=10),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("runtime_id", "runtime-2"),
        ("desired_generation", 7),
        ("runner_generation", 8),
    ),
)
def test_owner_session_rejects_mismatched_stream_authority(
    field: str,
    value: str | int,
) -> None:
    session = PeerSessionState(identity=_identity())
    session.hello_sent()
    session.accept(APPROVED_SESSION_PROFILE)
    with pytest.raises(ValueError, match="Owner epoch"):
        session.open_stream(
            stream_id=1,
            authority=replace(_authority(), **{field: value}),
            request_head=_head(),
        )


def test_goaway_terminates_registered_streams_above_boundary() -> None:
    session = PeerSessionState(identity=_identity())
    session.hello_sent()
    session.accept(APPROVED_SESSION_PROFILE)
    retained = session.open_stream(
        stream_id=1,
        authority=_authority(),
        request_head=_head(),
    )
    retained.accept()
    pending = session.open_stream(
        stream_id=2,
        authority=_authority(),
        request_head=_head(),
    )
    assert session.start_draining(1) == (2,)
    assert retained.snapshot().accepted
    assert pending.snapshot().rejected
    assert pending.snapshot().terminal_reason is CloseReason.SERVICE_DRAIN


def test_open_deadline_is_independent_and_bounded() -> None:
    with pytest.raises(ValueError, match="Open deadline"):
        replace(
            _authority(),
            open_deadline_at=NOW + timedelta(minutes=31),
        )
