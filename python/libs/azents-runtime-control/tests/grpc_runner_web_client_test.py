"""Runtime Runner Web gRPC client tests."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta

from azents_runtime_control.grpc_runner_client import runner_web_identity_to_message
from azents_runtime_control.grpc_runner_web_client import (
    GrpcRunnerWebClient,
    runner_web_control_from_message,
    runner_web_event_to_message,
)
from azents_runtime_control.proto import runtime_web_transport_pb2
from azents_runtime_control.runner_web import (
    RunnerWebCancel,
    RunnerWebCancelReason,
    RunnerWebControlFrame,
    RunnerWebHeader,
    RunnerWebIdentity,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebStreamEnd,
)


async def test_client_registers_and_delivers_ordered_control_frames() -> None:
    """One dedicated stream registers exact authority before request frames."""
    identity = _identity()
    frames: list[RunnerWebControlFrame] = []
    received = asyncio.Event()
    release = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_web_transport_pb2.RunnerWebControlMessage]:
        assert metadata == (("authorization", "Bearer runner-token"),)
        registration = await anext(requests)
        assert registration.WhichOneof("payload") == "register"
        assert registration.register.identity.tunnel_id == identity.tunnel_id
        yield runtime_web_transport_pb2.RunnerWebControlMessage(
            accepted=runtime_web_transport_pb2.RuntimeWebStreamAccepted(
                tunnel_id=identity.tunnel_id
            )
        )
        yield runtime_web_transport_pb2.RunnerWebControlMessage(
            request_head=runtime_web_transport_pb2.RuntimeWebRequestHead(
                identity=runner_web_identity_to_message(identity),
                protocol=runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_HTTP,
                method=b"POST",
                target=b"/events",
                headers=[
                    runtime_web_transport_pb2.RuntimeWebHeader(
                        name=b"content-type", value=b"application/json"
                    )
                ],
            )
        )
        yield runtime_web_transport_pb2.RunnerWebControlMessage(
            cancel=runtime_web_transport_pb2.RuntimeWebCancel(
                reason=runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_CALLER
            )
        )
        received.set()
        await release.wait()

    client = GrpcRunnerWebClient(stream, runner_auth_token="runner-token")

    async def handle(frame: RunnerWebControlFrame) -> None:
        frames.append(frame)

    client.set_control_handler(handle)
    accepted = await client.start(identity)
    await asyncio.wait_for(received.wait(), timeout=1)

    assert accepted.tunnel_id == identity.tunnel_id
    assert frames == [
        RunnerWebRequestHead(
            identity=identity,
            protocol=RunnerWebProtocol.HTTP,
            method=b"POST",
            target=b"/events",
            headers=(RunnerWebHeader(b"content-type", b"application/json"),),
        ),
        RunnerWebCancel(RunnerWebCancelReason.CALLER),
    ]

    release.set()
    await client.close()


def test_event_and_control_conversion_preserve_raw_headers_and_end_sequence() -> None:
    """Typed conversion preserves response metadata and exact end evidence."""
    response = RunnerWebResponseHead(
        status=201,
        headers=(RunnerWebHeader(b"set-cookie", b"app=value"),),
    )
    response_message = runner_web_event_to_message(response)
    end_message = runner_web_event_to_message(RunnerWebStreamEnd(final_sequence=4))
    cancel = runner_web_control_from_message(
        runtime_web_transport_pb2.RunnerWebControlMessage(
            cancel=runtime_web_transport_pb2.RuntimeWebCancel(
                reason=(
                    runtime_web_transport_pb2.RUNTIME_WEB_CANCEL_REASON_APPROVAL_EXPIRED
                )
            )
        )
    )

    assert response_message.response_head.status == 201
    assert bytes(response_message.response_head.headers[0].name) == b"set-cookie"
    assert end_message.end.final_sequence == 4
    assert cancel == RunnerWebCancel(RunnerWebCancelReason.APPROVAL_EXPIRED)


def _identity() -> RunnerWebIdentity:
    now = datetime(2026, 9, 12, tzinfo=UTC)
    return RunnerWebIdentity(
        tunnel_id="tunnel-1",
        endpoint_id="endpoint-1",
        cycle_id="cycle-1",
        endpoint_authority_revision=4,
        close_barrier=1,
        runtime_id="runtime-1",
        desired_generation=5,
        runner_generation=7,
        port=3000,
        join_nonce="nonce-1",
        registration_deadline_at=now + timedelta(seconds=15),
        approval_deadline_at=now + timedelta(minutes=30),
        transport_deadline_at=now + timedelta(minutes=30),
    )
