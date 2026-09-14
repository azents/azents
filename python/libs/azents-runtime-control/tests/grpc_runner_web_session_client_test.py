"""Inactive persistent Runner Web gRPC client tests."""

import asyncio
import inspect
from collections.abc import AsyncIterator

import pytest

from azents_runtime_control.grpc_runner_web_session_client import (
    GrpcRunnerWebSessionClient,
    RunnerWebResourceExhausted,
)
from azents_runtime_control.proto import runtime_web_session_pb2


def _envelope(payload: str) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
    envelope = runtime_web_session_pb2.RuntimeWebSessionEnvelope(
        protocol_fingerprint="f" * 64,
        session_id="session-a",
        peer_boot_id="owner-a",
    )
    if payload == "accepted":
        envelope.session_accepted.data_frame_bytes = 256 * 1024
    else:
        envelope.heartbeat.monotonic_sequence = 1
    return envelope


async def _failure_handler() -> None:
    pass


class _Resources:
    def __init__(self, *, accepting: bool = True) -> None:
        self.accepting = accepting
        self.reserved: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []

    def try_reserve_envelope(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> bool:
        if not self.accepting:
            return False
        self.reserved.append(envelope)
        return True

    def release_envelope(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        self.reserved.remove(envelope)


def test_activation_gate_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(GrpcRunnerWebSessionClient.activate)


async def test_client_outbound_queue_enforces_and_releases_process_resources() -> None:
    release = asyncio.Event()
    resources = _Resources()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _envelope("accepted")
        await release.wait()

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=resources,
    )
    await client.start(
        _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
    )
    client.activate()
    queued = _envelope("heartbeat")
    await client.send(queued)

    assert resources.reserved == [queued]
    await client.close()
    assert resources.reserved == []

    rejecting = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=_Resources(accepting=False),
    )
    await rejecting.start(
        _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
    )
    rejecting.activate()
    with pytest.raises(RunnerWebResourceExhausted):
        await rejecting.send(_envelope("heartbeat"))
    await rejecting.close()


async def test_client_requires_acceptance_first_and_dispatches_later_frames() -> None:
    observed_requests: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
    observed_metadata: object = None
    handled: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
    failed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        nonlocal observed_metadata
        observed_metadata = metadata
        observed_requests.append(await anext(requests))
        yield _envelope("accepted")
        yield _envelope("heartbeat")

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        handled.append(envelope)

    async def failure_handler() -> None:
        failed.set()

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )
    hello = _envelope("heartbeat")

    accepted = await client.start(hello, handler, failure_handler, timeout_seconds=1)
    assert accepted.WhichOneof("payload") == "session_accepted"
    assert client.receiver_task is not None
    client.activate()
    await client.receiver_task
    assert observed_requests == [hello]
    assert observed_metadata == (("authorization", "Bearer token-a"),)
    assert [item.WhichOneof("payload") for item in handled] == ["heartbeat"]
    assert failed.is_set()


async def test_client_rejects_non_acceptance_first_frame() -> None:
    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _envelope("heartbeat")

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )

    with pytest.raises(RuntimeError, match="session-scoped"):
        await client.start(
            _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
        )


async def test_client_rejects_stream_scoped_session_acceptance() -> None:
    accepted = _envelope("accepted")
    accepted.stream_id = 7

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield accepted

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )

    with pytest.raises(RuntimeError, match="session-scoped"):
        await client.start(
            _envelope("heartbeat"),
            handler,
            _failure_handler,
            timeout_seconds=1,
        )


async def test_close_fails_sender_blocked_on_full_queue() -> None:
    release = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _envelope("accepted")
        await release.wait()

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )
    await client.start(
        _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
    )
    client.activate()
    for _ in range(8):
        await client.send(_envelope("heartbeat"))
    blocked = asyncio.create_task(client.send(_envelope("heartbeat")))
    async with client.condition:
        assert len(client.outbound) == 8
        assert not blocked.done()

    await client.close()

    with pytest.raises(RuntimeError, match="not active"):
        await blocked
    assert not client.outbound
    release.set()


async def test_close_cleans_up_before_propagating_handler_failure() -> None:
    handled = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        yield _envelope("accepted")
        yield _envelope("heartbeat")

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope
        handled.set()
        raise ValueError("handler failed")

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )
    await client.start(
        _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
    )
    client.activate()
    await handled.wait()

    with pytest.raises(ValueError, match="handler failed"):
        await client.close()

    assert client.receiver_task is None
    assert not client.outbound


async def test_start_failure_cleans_up_without_receiver_task() -> None:
    def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del requests, metadata
        raise RuntimeError("stream failed")

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )

    with pytest.raises(RuntimeError, match="stream failed"):
        await client.start(
            _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=1
        )
    assert client.receiver_task is None
    assert not client.outbound


async def test_start_timeout_cancels_and_retrieves_receiver_task() -> None:
    async def stream(
        requests: AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        *,
        metadata: object = None,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        del metadata
        await anext(requests)
        await asyncio.Event().wait()
        if False:
            yield _envelope("accepted")

    async def handler(
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        del envelope

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
        outbound_resources=None,
    )

    with pytest.raises(TimeoutError):
        await client.start(
            _envelope("heartbeat"), handler, _failure_handler, timeout_seconds=0.01
        )
    assert client.receiver_task is None
    assert not client.outbound
