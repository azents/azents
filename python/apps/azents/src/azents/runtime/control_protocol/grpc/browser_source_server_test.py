"""Real RPC proof, TLS composition, bounded stream and cleanup regressions."""

import asyncio
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

import grpc
import pytest
from azents_runtime_control.browser_source_contract import BrowserScopeState
from azents_runtime_control.grpc_browser_source_client import (
    BrowserSourceProtocolError,
    BrowserSourceScopeRevoked,
    BrowserSourceUnavailable,
    GrpcBrowserSourceClient,
)
from azents_runtime_control.grpc_tls import GrpcClientTlsConfig
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    decode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    BrowserStreamAuthority,
    WebSocketOpcode,
)
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from azents.core.runtime_browser_source_credential import (
    RuntimeBrowserSourceCredentialSupplier,
    RuntimeBrowserSourceCredentialVerifier,
)
from azents.core.runtime_browser_source_credential_test import KEY, source_request
from azents.runtime.control_protocol.grpc.browser_source_server import (
    add_runtime_browser_source_servicer,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server import (
    _acceptance,
    _SourceSession,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server_test import (
    _local_data_plane,
)


class _Certificate(NamedTuple):
    private_key: bytes
    certificate: bytes


def _certificate() -> _Certificate:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return _Certificate(
        private_key=key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        certificate=certificate.public_bytes(serialization.Encoding.PEM),
    )


@pytest.mark.parametrize("tls_enabled", [False, True])
async def test_real_browser_source_rpc_tls_proof_frame_and_scoped_cleanup(
    monkeypatch: pytest.MonkeyPatch, tls_enabled: bool
) -> None:
    plane, _ = _local_data_plane()
    admitted: list[BrowserStreamAuthority] = []

    async def current(authority: BrowserStreamAuthority) -> BrowserScopeState:
        admitted.append(authority)
        return BrowserScopeState.CURRENT

    async def handle(
        source: _SourceSession, envelope: pb.RuntimeStreamSessionEnvelope
    ) -> None:
        if envelope.WhichOneof("payload") == "open":
            assert source.browser_authority is not None
            accepted = _acceptance(
                envelope, plane.control_boot_id, lambda: datetime.now(UTC)
            )
            accepted.stream_id = 1
            accepted.open_accepted.SetInParent()
            await source.queue.put(accepted)
            frame = pb.RuntimeStreamSessionEnvelope(
                protocol_fingerprint=envelope.protocol_fingerprint,
                session_id=source.session_id,
                peer_boot_id=plane.control_boot_id,
                stream_id=1,
                frame_sequence=1,
                websocket=pb.RuntimeStreamSessionWebSocketFrame(
                    direction=pb.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
                    opcode=pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY,
                    final=True,
                    data=b"synthetic-frame",
                ),
            )
            await source.queue.put(frame)
        else:
            assert envelope.WhichOneof("payload") in {"window_update", "websocket"}

    monkeypatch.setattr(plane, "handle", handle)
    server = grpc.aio.server()
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )
    add_runtime_browser_source_servicer(
        server,
        data_plane=plane,
        verifier=verifier,
        validate_scope=current,
        clock=lambda: datetime.now(UTC),
    )
    tls = None
    if tls_enabled:
        key, certificate = _certificate()
        port = server.add_secure_port(
            "localhost:0", grpc.ssl_server_credentials(((key, certificate),))
        )
        tls = GrpcClientTlsConfig(certificate)
    else:
        port = server.add_insecure_port("localhost:0")
    await server.start()
    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}",
        credential_supplier=RuntimeBrowserSourceCredentialSupplier(verifier),
        tls=tls,
        allow_insecure=not tls_enabled,
    )
    authority = decode_stream_authority(
        source_request(datetime.now(UTC)).open_envelope.open.authority
    )
    assert isinstance(authority, BrowserStreamAuthority)
    connection = None
    try:
        connection = await client.connect(authority=authority)
        message = await asyncio.wait_for(connection.receive_websocket(), timeout=5)
        assert message.opcode is WebSocketOpcode.BINARY
        assert message.payload == b"synthetic-frame"
        await connection.send_websocket(
            opcode=WebSocketOpcode.TEXT, payload=b'{"type":"frame_ack"}'
        )
        with pytest.raises(BrowserSourceProtocolError):
            await connection.send(source_request(datetime.now(UTC)).open_envelope)
        assert len(admitted) == 1
        assert admitted[0] == authority
        await connection.close()
    finally:
        if connection is not None:
            await connection.close()
        await client.close()
        await server.stop(None)
        await plane.close()
    assert not plane.sources


@pytest.mark.parametrize("phase", ["scope", "open"])
async def test_browser_source_setup_deadline_bounds_authority_and_initial_open(
    monkeypatch: pytest.MonkeyPatch, phase: str
) -> None:
    plane, _ = _local_data_plane()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def stall() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def current(authority: BrowserStreamAuthority) -> BrowserScopeState:
        del authority
        if phase == "scope":
            await stall()
        return BrowserScopeState.CURRENT

    async def handle(
        source: _SourceSession, envelope: pb.RuntimeStreamSessionEnvelope
    ) -> None:
        del source, envelope
        await stall()

    monkeypatch.setattr(plane, "handle", handle)
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )
    server = grpc.aio.server()
    add_runtime_browser_source_servicer(
        server,
        data_plane=plane,
        verifier=verifier,
        validate_scope=current,
        clock=lambda: datetime.now(UTC),
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}",
        credential_supplier=RuntimeBrowserSourceCredentialSupplier(verifier),
        tls=None,
        allow_insecure=True,
    )
    authority = decode_stream_authority(
        source_request(datetime.now(UTC)).open_envelope.open.authority
    )
    assert isinstance(authority, BrowserStreamAuthority)
    authority = dataclasses.replace(
        authority, open_deadline_at=datetime.now(UTC) + timedelta(seconds=0.5)
    )
    try:
        async with asyncio.timeout(2):
            with pytest.raises(BrowserSourceScopeRevoked):
                await client.connect(authority=authority)
        assert entered.is_set() and cancelled.is_set()
        assert not plane.sources
    finally:
        await client.close()
        await server.stop(None)
        await plane.close()


async def test_browser_source_wrong_ca_and_missing_tls_fail_closed() -> None:
    key, certificate = _certificate()
    _, other_ca = _certificate()
    server = grpc.aio.server()
    port = server.add_secure_port(
        "localhost:0", grpc.ssl_server_credentials(((key, certificate),))
    )
    await server.start()
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )
    supplier = RuntimeBrowserSourceCredentialSupplier(verifier)
    authority = decode_stream_authority(
        source_request(datetime.now(UTC)).open_envelope.open.authority
    )
    assert isinstance(authority, BrowserStreamAuthority)
    with pytest.raises(ValueError, match="TLS configuration is required"):
        GrpcBrowserSourceClient.from_endpoint(
            f"localhost:{port}",
            credential_supplier=supplier,
            tls=None,
            allow_insecure=False,
        )
    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}",
        credential_supplier=supplier,
        tls=GrpcClientTlsConfig(other_ca),
        allow_insecure=False,
    )
    try:
        with pytest.raises(BrowserSourceUnavailable):
            await client.connect(authority=authority)
    finally:
        await client.close()
        await server.stop(None)


async def test_disabled_plane_rejects_without_source_admission() -> None:
    server = grpc.aio.server()
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )

    async def never(authority: BrowserStreamAuthority) -> BrowserScopeState:
        raise AssertionError("Disabled common transport must not validate or allocate")

    add_runtime_browser_source_servicer(
        server,
        data_plane=None,
        verifier=verifier,
        validate_scope=never,
        clock=lambda: datetime.now(UTC),
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}",
        credential_supplier=RuntimeBrowserSourceCredentialSupplier(verifier),
        tls=None,
        allow_insecure=True,
    )
    authority = decode_stream_authority(
        source_request(datetime.now(UTC)).open_envelope.open.authority
    )
    assert isinstance(authority, BrowserStreamAuthority)
    try:
        with pytest.raises(BrowserSourceUnavailable):
            await client.connect(authority=authority)
    finally:
        await client.close()
        await server.stop(None)


@pytest.mark.parametrize("change", ["readonly", "wrong-root", "account-revoked"])
async def test_current_scope_rejection_precedes_capacity(change: str) -> None:
    plane, _ = _local_data_plane()
    server = grpc.aio.server()
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )

    async def denied(authority: BrowserStreamAuthority) -> BrowserScopeState:
        assert isinstance(authority, BrowserStreamAuthority)
        return BrowserScopeState.REVOKED

    add_runtime_browser_source_servicer(
        server,
        data_plane=plane,
        verifier=verifier,
        validate_scope=denied,
        clock=lambda: datetime.now(UTC),
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}",
        credential_supplier=RuntimeBrowserSourceCredentialSupplier(verifier),
        tls=None,
        allow_insecure=True,
    )
    authority = decode_stream_authority(
        source_request(datetime.now(UTC)).open_envelope.open.authority
    )
    assert isinstance(authority, BrowserStreamAuthority)
    if change == "readonly":
        authority = dataclasses.replace(authority, allow_input=True)
    elif change == "wrong-root":
        authority = dataclasses.replace(authority, session_id="wrong-root")
    try:
        with pytest.raises(BrowserSourceScopeRevoked):
            await client.connect(authority=authority)
        assert not plane.sources and not plane.bindings
    finally:
        await client.close()
        await server.stop(None)
        await plane.close()
