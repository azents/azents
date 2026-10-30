"""Browser source admission traverses the actual shared Owner and current fence."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import grpc
import pytest
from azents_runtime_control.browser_source_contract import (
    BrowserScopeState,
    BrowserSourceCredentialRequest,
)
from azents_runtime_control.grpc_browser_source_client import (
    BrowserSourceScopeRevoked,
    BrowserSourceUnavailable,
    GrpcBrowserSourceClient,
)
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    decode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
    WebSocketOpcode,
)

from azents.core.runtime_browser_source_credential import (
    RuntimeBrowserSourceCredentialVerifier,
)
from azents.core.runtime_browser_source_credential_test import KEY, source_request
from azents.repos.runtime_web.data import RuntimeWebSessionRoute
from azents.runtime.control_protocol.grpc.browser_source_server import (
    add_runtime_browser_source_servicer,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server import (
    _read_source,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server_test import (
    _local_data_plane,
    _owner,
)
from azents.runtime.stream_session_owner import RuntimeStreamAcceptedRunnerSession


@pytest.mark.parametrize("route_available", [False, True])
@pytest.mark.parametrize("outcome", ["join", "revoke", "expire", "drain"])
async def test_browser_open_waits_for_current_owner_join(
    monkeypatch: pytest.MonkeyPatch, outcome: str, route_available: bool
) -> None:
    plane, _ = _local_data_plane()
    owner = _owner()
    request = source_request(datetime.now(UTC))
    request.open_envelope.open.authority.runner_generation = owner.runner_generation
    authority = decode_stream_authority(request.open_envelope.open.authority)
    assert isinstance(authority, BrowserStreamAuthority)
    current = BrowserScopeState.CURRENT
    now = datetime.now(UTC)
    plane.clock = lambda: now

    async def validate(authority: BrowserStreamAuthority) -> BrowserScopeState:
        del authority
        return current

    plane.browser_scope_validator = validate
    waiting = asyncio.Event()
    original_resolve = plane._resolve_route
    resolutions = 0

    async def resolve(
        *, runtime_id: str, desired_generation: int, runner_generation: int
    ) -> RuntimeWebSessionRoute | None:
        nonlocal resolutions
        route = await original_resolve(
            runtime_id=runtime_id,
            desired_generation=desired_generation,
            runner_generation=runner_generation,
        )
        resolutions += 1
        if resolutions > 1:
            waiting.set()
        return route if route_available else None

    monkeypatch.setattr(plane, "_resolve_route", resolve)
    source = await plane.register_source(
        session_id=request.hello.session_id,
        peer_boot_id=request.hello.peer_boot_id,
        owner=None,
        browser_authority=authority,
    )
    opening = asyncio.create_task(plane.handle(source, request.open_envelope))
    ready = asyncio.create_task(waiting.wait())
    accepted = RuntimeStreamAcceptedRunnerSession(
        owner, "runner-boot", APPROVED_SESSION_PROFILE, now
    )
    try:
        async with asyncio.timeout(5):
            done, _ = await asyncio.wait(
                (opening, ready), return_when=asyncio.FIRST_COMPLETED
            )
            assert ready in done, "Browser OPEN rejected before its Owner joined"
            assert not opening.done()
            assert not plane.bindings
            if outcome == "join":
                route_available = True
                runner = await plane.register_runner(accepted)
                await opening
                queued = await runner.queue.__aiter__().__anext__()
                assert queued.WhichOneof("payload") == "open"
                assert (
                    queued.open.authority.runner_generation == owner.runner_generation
                )
                assert len(plane.bindings) == 1
            else:
                if outcome == "revoke":
                    current = BrowserScopeState.REVOKED
                elif outcome == "drain":
                    plane.draining = True
                else:
                    now = authority.open_deadline_at
                await opening
                queued = await source.queue.__aiter__().__anext__()
                assert queued.WhichOneof("payload") == "open_rejected"
                assert queued.open_rejected.reason == (
                    pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_AUTHORITY_REVOKED
                    if outcome == "revoke"
                    else pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_SERVICE_DRAIN
                    if outcome == "drain"
                    else pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_DEADLINE
                )
                assert not plane.bindings
    finally:
        opening.cancel()
        ready.cancel()
        await asyncio.gather(opening, ready, return_exceptions=True)
        await plane.unregister_source(source)
        await plane.unregister_runner(accepted)
        await plane.close()


async def test_relay_reader_does_not_wait_for_browser_owner_join() -> None:
    plane, _ = _local_data_plane()
    owner = _owner()
    request = source_request(datetime.now(UTC))
    request.open_envelope.open.authority.runner_generation = owner.runner_generation

    async def validate(authority: BrowserStreamAuthority) -> BrowserScopeState:
        del authority
        return BrowserScopeState.CURRENT

    plane.browser_scope_validator = validate
    source = await plane.register_source(
        session_id=request.hello.session_id,
        peer_boot_id=request.hello.peer_boot_id,
        owner=owner,
    )
    continued = asyncio.Event()
    finish = asyncio.Event()

    async def messages() -> AsyncIterator[pb.RuntimeStreamSessionEnvelope]:
        yield request.open_envelope
        # The shared reader must consume cancellation and drain after the OPEN,
        # rather than dispatching a delayed OPEN before queued cancellation.
        cancelled = pb.RuntimeStreamSessionEnvelope()
        cancelled.CopyFrom(request.open_envelope)
        cancelled.cancel.SetInParent()
        yield cancelled
        drained = pb.RuntimeStreamSessionEnvelope()
        drained.CopyFrom(request.open_envelope)
        drained.stream_id = 0
        drained.go_away.SetInParent()
        yield drained
        continued.set()
        await finish.wait()

    reading = asyncio.create_task(_read_source(plane, source, messages()))
    try:
        async with asyncio.timeout(5):
            await continued.wait()
            rejected = await source.queue.__aiter__().__anext__()
            finish.set()
            await reading
        assert rejected.WhichOneof("payload") == "open_rejected"
        assert rejected.open_rejected.reason == (
            pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_OWNER_LOST
        )
        assert plane.resets == 1
        assert source.source_key in plane.draining_sources
        assert not plane.bindings and not plane.runners
    finally:
        reading.cancel()
        await asyncio.gather(reading, return_exceptions=True)
        await plane.unregister_source(source)
        await plane.close()


async def test_api_source_actual_owner_current_fence_and_fresh_connection_proof() -> (
    None
):
    plane, _ = _local_data_plane()
    owner = _owner()
    accepted = RuntimeStreamAcceptedRunnerSession(
        owner, "runner-boot", APPROVED_SESSION_PROFILE, datetime.now(UTC)
    )
    runner = await plane.register_runner(accepted)
    current = True

    async def validate(authority: BrowserStreamAuthority) -> BrowserScopeState:
        del authority
        return BrowserScopeState.CURRENT if current else BrowserScopeState.REVOKED

    plane.browser_scope_validator = validate
    server = grpc.aio.server()
    verifier = RuntimeBrowserSourceCredentialVerifier(
        KEY, clock=lambda: datetime.now(UTC)
    )
    add_runtime_browser_source_servicer(
        server,
        data_plane=plane,
        verifier=verifier,
        validate_scope=validate,
        clock=lambda: datetime.now(UTC),
    )
    port = server.add_insecure_port("localhost:0")
    await server.start()
    proofs: list[str] = []

    async def supplier(request: BrowserSourceCredentialRequest) -> str:
        proof = verifier.issue(request)
        proofs.append(proof)
        return proof

    client = GrpcBrowserSourceClient.from_endpoint(
        f"localhost:{port}", credential_supplier=supplier, tls=None, allow_insecure=True
    )
    reset = asyncio.Event()
    effects: list[bytes] = []

    async def native_peer() -> None:
        async for envelope in runner.queue:
            kind = envelope.WhichOneof("payload")
            if kind == "open":

                def response(stream_id: int) -> pb.RuntimeStreamSessionEnvelope:
                    return pb.RuntimeStreamSessionEnvelope(
                        protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
                        session_id=owner.session_lease_id,
                        peer_boot_id="runner-boot",
                        owner_boot_id=owner.owner_boot_id,
                        session_lease_id=owner.session_lease_id,
                        lease_generation=owner.lease_generation,
                        stream_id=stream_id,
                    )

                opened = response(envelope.stream_id)
                opened.open_accepted.CopyFrom(
                    pb.RuntimeStreamSessionOpenAccepted(
                        data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
                        request_credit_bytes=APPROVED_SESSION_PROFILE.request_stream_window_bytes,
                        response_credit_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                        route_path=pb.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL,
                    )
                )
                await plane.runner_response(opened)
                head = response(envelope.stream_id)
                head.response_head.status = 101
                await plane.runner_response(head)
                frame = response(envelope.stream_id)
                frame.frame_sequence = 1
                frame.websocket.CopyFrom(
                    pb.RuntimeStreamSessionWebSocketFrame(
                        direction=pb.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
                        opcode=pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY,
                        final=True,
                        data=b"volatile-browser-frame",
                    )
                )
                await plane.runner_response(frame)
            elif kind == "websocket":
                effects.append(envelope.websocket.data)
            elif kind == "reset":
                reset.set()

    task = asyncio.create_task(native_peer())
    request = source_request(datetime.now(UTC))
    request.open_envelope.open.authority.runner_generation = owner.runner_generation
    authority = decode_stream_authority(request.open_envelope.open.authority)
    assert isinstance(authority, BrowserStreamAuthority)
    connection = None
    replay_client = None
    try:
        connection = await client.connect(authority=authority)
        received = await asyncio.wait_for(connection.receive_websocket(), 5)
        assert received.payload == b"volatile-browser-frame"
        current = False
        await connection.send_websocket(
            opcode=WebSocketOpcode.TEXT, payload=b"must-not-reach-native-input"
        )
        try:
            await asyncio.wait_for(connection.receive_websocket(), 5)
        except BrowserSourceScopeRevoked as error:
            assert error.reason == "access_revoked"
        else:
            raise AssertionError("Current access revocation must purge Browser content")
        await asyncio.wait_for(reset.wait(), 5)
        assert effects == []
        assert not plane.bindings
        current = True

        async def reused(request: BrowserSourceCredentialRequest) -> str:
            return proofs[0]

        replay_client = GrpcBrowserSourceClient.from_endpoint(
            f"localhost:{port}",
            credential_supplier=reused,
            tls=None,
            allow_insecure=True,
        )
        try:
            await replay_client.connect(authority=authority)
        except BrowserSourceScopeRevoked as error:
            assert error.reason == "unauthenticated"
        else:
            raise AssertionError(
                "A proof cannot authenticate a fresh connection challenge"
            )
        fresh = await client.connect(authority=authority)
        try:
            await asyncio.wait_for(fresh.receive_websocket(), 5)
            reset.clear()
            second_open = fresh.envelope()
            second_open.open.CopyFrom(request.open_envelope.open)
            await fresh.call.write(second_open)
            try:
                await asyncio.wait_for(fresh.receive_websocket(), 5)
            except BrowserSourceUnavailable:
                pass
            else:
                raise AssertionError("A source must never accept a second OPEN")
            await asyncio.wait_for(reset.wait(), 5)
            assert effects == []
        finally:
            await fresh.close()
    finally:
        if connection is not None:
            await connection.close()
        if replay_client is not None:
            await replay_client.close()
        await client.close()
        await server.stop(None)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await plane.unregister_runner(accepted)
        await plane.close()
    assert not plane.sources and not plane.browser_guards
