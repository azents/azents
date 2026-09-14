"""Inactive persistent Runner Web gRPC client tests."""

import asyncio
import inspect
from collections.abc import AsyncIterator

import pytest

from azents_runtime_control.grpc_runner_web_session_client import (
    GrpcRunnerWebSessionClient,
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


def test_activation_gate_is_synchronous() -> None:
    assert not inspect.iscoroutinefunction(GrpcRunnerWebSessionClient.activate)


async def test_client_requires_acceptance_first_and_dispatches_later_frames() -> None:
    observed_requests: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []
    observed_metadata: object = None
    handled: list[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = []

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

    client = GrpcRunnerWebSessionClient(
        stream,
        runner_auth_token="token-a",
        channel=None,
    )
    hello = _envelope("heartbeat")

    accepted = await client.start(hello, handler, timeout_seconds=1)
    assert accepted.WhichOneof("payload") == "session_accepted"
    assert client.receiver_task is not None
    client.activate()
    await client.receiver_task
    assert observed_requests == [hello]
    assert observed_metadata == (("authorization", "Bearer token-a"),)
    assert [item.WhichOneof("payload") for item in handled] == ["heartbeat"]


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
    )

    with pytest.raises(RuntimeError, match="accepted frame must be first"):
        await client.start(_envelope("heartbeat"), handler, timeout_seconds=1)


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
    )
    await client.start(_envelope("heartbeat"), handler, timeout_seconds=1)
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
    )
    await client.start(_envelope("heartbeat"), handler, timeout_seconds=1)
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
    )

    with pytest.raises(RuntimeError, match="stream failed"):
        await client.start(_envelope("heartbeat"), handler, timeout_seconds=1)
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
    )

    with pytest.raises(TimeoutError):
        await client.start(_envelope("heartbeat"), handler, timeout_seconds=0.01)
    assert client.receiver_task is None
    assert not client.outbound
