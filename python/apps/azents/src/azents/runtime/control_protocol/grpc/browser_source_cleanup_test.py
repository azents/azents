"""Terminal Browser cleanup cannot poison a shared Runner session."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from azents_runtime_control.proto import runtime_stream_session_pb2 as pb
from azents_runtime_control.runtime_stream_authority_codec import (
    decode_stream_authority,
)
from azents_runtime_control.runtime_stream_session import (
    APPROVED_SESSION_PROFILE,
    RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
    BrowserStreamAuthority,
)

from azents.core.runtime_browser_source_credential_test import source_request
from azents.runtime.control_protocol.grpc.runtime_stream_session_server import (
    RuntimeStreamControlDataPlane,
    _read_runner,
    _RunnerConnection,
    _SourceSession,
)
from azents.runtime.control_protocol.grpc.runtime_stream_session_server_test import (
    _local_data_plane,
    _owner,
)
from azents.runtime.stream_session_broker import BrokerStreamKey
from azents.runtime.stream_session_owner import RuntimeStreamAcceptedRunnerSession


class _AuthorityGate:
    def __init__(self) -> None:
        self.paused = False
        self.entered = asyncio.Event()
        self.resume = asyncio.Event()

    async def __call__(self, authority: BrowserStreamAuthority) -> bool:
        del authority
        if self.paused:
            self.entered.set()
            await self.resume.wait()
        return True


@dataclass(frozen=True)
class _Fixture:
    plane: RuntimeStreamControlDataPlane
    runner: _RunnerConnection
    accepted: RuntimeStreamAcceptedRunnerSession
    gate: _AuthorityGate

    def response(self, stream_id: int) -> pb.RuntimeStreamSessionEnvelope:
        owner = self.accepted.owner
        return pb.RuntimeStreamSessionEnvelope(
            protocol_fingerprint=RUNTIME_STREAM_PROTOCOL_FINGERPRINT,
            session_id=owner.session_lease_id,
            peer_boot_id=self.accepted.runner_boot_id,
            owner_boot_id=owner.owner_boot_id,
            session_lease_id=owner.session_lease_id,
            lease_generation=owner.lease_generation,
            stream_id=stream_id,
        )

    async def open_source(self, session_id: str) -> _SourceSession:
        request = source_request(datetime.now(UTC))
        opened = request.open_envelope
        opened.session_id = session_id
        opened.open.authority.runner_generation = self.accepted.owner.runner_generation
        authority = decode_stream_authority(opened.open.authority)
        assert isinstance(authority, BrowserStreamAuthority)
        source = await self.plane.register_source(
            session_id=session_id,
            peer_boot_id=opened.peer_boot_id,
            owner=None,
            browser_authority=authority,
        )
        await self.plane.handle(source, opened)
        return source

    async def accept(self, stream_id: int, source: _SourceSession) -> None:
        response = self.response(stream_id)
        response.open_accepted.CopyFrom(
            pb.RuntimeStreamSessionOpenAccepted(
                data_frame_bytes=APPROVED_SESSION_PROFILE.data_frame_bytes,
                request_credit_bytes=APPROVED_SESSION_PROFILE.request_stream_window_bytes,
                response_credit_bytes=APPROVED_SESSION_PROFILE.response_stream_window_bytes,
                route_path=pb.RUNTIME_STREAM_SESSION_ROUTE_PATH_LOCAL,
            )
        )
        await self.plane.runner_response(response)
        delivered = await anext(source.queue.__aiter__())
        assert delivered.WhichOneof("payload") == "open_accepted"


@asynccontextmanager
async def _fixture() -> AsyncIterator[_Fixture]:
    plane, _ = _local_data_plane()
    accepted = RuntimeStreamAcceptedRunnerSession(
        _owner(), "runner-boot", APPROVED_SESSION_PROFILE, datetime.now(UTC)
    )
    runner = await plane.register_runner(accepted)
    gate = _AuthorityGate()
    plane.browser_scope_validator = gate
    try:
        yield _Fixture(plane, runner, accepted, gate)
    finally:
        gate.resume.set()
        await plane.close()


@pytest.mark.parametrize("kind", ["window_update", "websocket", "reset"])
async def test_disconnect_publishes_terminal_before_guard_cleanup_and_new_source(
    kind: str,
) -> None:
    async with _fixture() as f:
        first = await f.open_source("first-source")
        runner_messages = f.runner.queue.__aiter__()
        first_open = await anext(runner_messages)
        key = BrokerStreamKey(first.source_key, 1)
        original_guard = f.plane.browser_guards.pop(key)
        original_guard.cancel()
        await asyncio.gather(original_guard, return_exceptions=True)
        started = asyncio.Event()
        cancelling = asyncio.Event()
        finish_guard = asyncio.Event()

        async def guard() -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelling.set()
                await finish_guard.wait()
                raise

        guarded = asyncio.create_task(guard())
        f.plane.browser_guards[key] = guarded
        await started.wait()
        closing = asyncio.create_task(f.plane.unregister_source(first))
        await asyncio.wait_for(cancelling.wait(), 2)
        processed = asyncio.Event()
        finish_reader = asyncio.Event()
        late = f.response(first_open.stream_id)
        if kind == "window_update":
            late.window_update.direction = pb.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
        elif kind == "websocket":
            late.websocket.CopyFrom(
                pb.RuntimeStreamSessionWebSocketFrame(
                    direction=pb.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE,
                    opcode=pb.RUNTIME_STREAM_SESSION_WEBSOCKET_OPCODE_BINARY,
                    final=True,
                    data=b"retired-frame",
                )
            )
        else:
            late.reset.reason = pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER

        async def messages() -> AsyncIterator[pb.RuntimeStreamSessionEnvelope]:
            yield late
            processed.set()
            await finish_reader.wait()

        reader = asyncio.create_task(_read_runner(f.plane, f.runner, messages()))
        try:
            assert key not in f.plane.bindings
            assert key in f.plane.source_tombstone_set
            assert await f.runner.terminal(first_open.stream_id)
            await asyncio.wait_for(processed.wait(), 2)
            assert not f.runner.queue.closed
            second = await f.open_source("second-source")
            reset = await anext(runner_messages)
            assert reset.WhichOneof("payload") == "reset"
            second_open = await anext(runner_messages)
            assert second_open.WhichOneof("payload") == "open"
            assert second_open.stream_id > first_open.stream_id
            await f.accept(second_open.stream_id, second)
            finish_guard.set()
            await asyncio.wait_for(closing, 2)
            assert not f.runner.queue.closed
            assert f.accepted.owner in f.plane.runners
            assert await f.runner.receive(late) is None
            unknown = f.response(second_open.stream_id + 1000)
            unknown.reset.reason = pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_CALLER
            with pytest.raises(ValueError, match="stream is unknown"):
                await f.plane.runner_response(unknown)
            with pytest.raises(ValueError, match="stream is unknown"):
                await f.runner.receive(unknown)
        finally:
            finish_guard.set()
            finish_reader.set()
            await closing
            await reader


async def test_disconnect_during_current_authority_check_keeps_new_source_alive() -> (
    None
):
    async with _fixture() as f:
        first = await f.open_source("first-source")
        runner_messages = f.runner.queue.__aiter__()
        first_open = await anext(runner_messages)
        late = f.response(first_open.stream_id)
        late.window_update.direction = pb.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
        processed = asyncio.Event()
        finish_reader = asyncio.Event()

        async def messages() -> AsyncIterator[pb.RuntimeStreamSessionEnvelope]:
            yield late
            processed.set()
            await finish_reader.wait()

        f.gate.paused = True
        reader = asyncio.create_task(_read_runner(f.plane, f.runner, messages()))
        try:
            await asyncio.wait_for(processed.wait(), 1)
            await asyncio.wait_for(f.gate.entered.wait(), 3)
            await f.plane.unregister_source(first)
            f.gate.paused = False
            second = await f.open_source("second-source")
            reset = await anext(runner_messages)
            assert reset.WhichOneof("payload") == "reset"
            second_open = await anext(runner_messages)
            assert second_open.stream_id > first_open.stream_id
            f.gate.resume.set()
            await asyncio.wait_for(processed.wait(), 2)
            assert not f.runner.queue.closed
            await f.accept(second_open.stream_id, second)
            assert not f.runner.queue.closed
            assert f.accepted.owner in f.plane.runners
        finally:
            f.gate.resume.set()
            finish_reader.set()
            await reader


async def test_stalled_browser_guard_does_not_block_independent_runner_responses() -> (
    None
):
    async with _fixture() as f:
        first = await f.open_source("first-source")
        second = await f.open_source("second-source")
        runner_messages = f.runner.queue.__aiter__()
        first_open = await anext(runner_messages)
        second_open = await anext(runner_messages)
        await f.accept(first_open.stream_id, first)
        await f.accept(second_open.stream_id, second)
        f.gate.paused = True
        await asyncio.wait_for(f.gate.entered.wait(), 3)
        completed = asyncio.Event()
        finish = asyncio.Event()

        async def messages() -> AsyncIterator[pb.RuntimeStreamSessionEnvelope]:
            for opened in (first_open, second_open):
                response = f.response(opened.stream_id)
                response.window_update.direction = (
                    pb.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
                )
                yield response
            completed.set()
            await finish.wait()

        reader = asyncio.create_task(_read_runner(f.plane, f.runner, messages()))
        try:
            await asyncio.wait_for(completed.wait(), 1)
            for source in (first, second):
                response = await anext(source.queue.__aiter__())
                assert response.WhichOneof("payload") == "window_update"
            assert not f.runner.queue.closed
            # The validator is still stalled: its bounded monitoring deadline
            # must revoke instead of waiting for the test to release it.
            for source in (first, second):
                async with asyncio.timeout(3):
                    response = await anext(source.queue.__aiter__())
                assert response.WhichOneof("payload") == "reset"
                assert response.reset.reason == (
                    pb.RUNTIME_STREAM_SESSION_CLOSE_REASON_AUTHORITY_REVOKED
                )
        finally:
            finish.set()
            await reader
