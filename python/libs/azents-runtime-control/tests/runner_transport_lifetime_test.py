"""Transport termination fences effects before asynchronous request cleanup."""

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest

from azents_runtime_control.grpc_runner_client import GrpcRunnerControlClient
from azents_runtime_control.proto import runtime_runner_control_pb2 as pb


def unused_stream(
    request_iterator: AsyncIterator[pb.RunnerMessage],
    metadata: Sequence[tuple[str, str]] | None = None,
) -> AsyncIterator[pb.RunnerControlMessage]:
    raise AssertionError("This test drives the receive boundary directly")


@pytest.mark.parametrize("failed", [False, True])
async def test_stream_loss_synchronously_fences_admitted_effect(failed: bool) -> None:
    client = GrpcRunnerControlClient(unused_stream, runner_auth_token="test")
    client.connected = True
    admitted = asyncio.Event()
    release = asyncio.Event()
    effect = False
    fenced: list[bool] = []

    async def pending_effect() -> None:
        nonlocal effect
        admitted.set()
        await release.wait()
        effect = True

    operation = asyncio.create_task(pending_effect())
    await admitted.wait()

    def fence() -> None:
        fenced.append(not client.connected)
        operation.cancel()
        release.set()

    client.set_disconnect_handler(fence)

    async def ended() -> AsyncIterator[pb.RunnerControlMessage]:
        if failed:
            raise ValueError("synthetic transport loss")
        if False:
            yield pb.RunnerControlMessage()

    try:
        if failed:
            with pytest.raises(ValueError, match="synthetic"):
                await client._receive(ended())
        else:
            await client._receive(ended())
        with pytest.raises(asyncio.CancelledError):
            await operation
        assert fenced == [True] and not effect and not client.connected
    finally:
        await client.close()
