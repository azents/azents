"""Trusted Runtime Web Gateway proxy stream tests."""

import asyncio
import datetime
from collections.abc import AsyncIterator

import grpc
from azents_runtime_control.grpc_runner_client import runner_web_identity_to_message
from azents_runtime_control.proto import (
    runtime_web_transport_pb2,
    runtime_web_transport_pb2_grpc,
)
from azents_runtime_control.runner_web import (
    RunnerWebBodyChunk,
    RunnerWebCancelReason,
    RunnerWebIdentity,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebStreamEnd,
)

from azents.repos.runtime_web.data import (
    RuntimeWebTunnelAuthority,
    RuntimeWebTunnelRoute,
)
from azents.runtime.control_protocol.grpc.runner_web_registry import (
    RuntimeWebOwnerRegistry,
    _runner_identity,
)
from azents.runtime.control_protocol.grpc.runner_web_server import (
    AllowInsecureRuntimeWebTrustedPeerAuthenticator,
)
from azents.runtime.control_protocol.grpc.runtime_web_proxy_server import (
    _owner_events,
    add_runtime_web_proxy_servicer,
)
from azents.runtime.web_transport_coordinator import RuntimeWebOwnedTunnel


class _Coordinator:
    lease_seconds = 30.0

    def __init__(self, route: RuntimeWebTunnelRoute, *, now: datetime.datetime) -> None:
        self.route = route
        self.registry = RuntimeWebOwnerRegistry(clock=lambda: now)
        self.closed_reason: RunnerWebCancelReason | None = None
        self.runner_task: asyncio.Task[None] | None = None

    async def open_owner(self, identity: RunnerWebIdentity) -> RuntimeWebOwnedTunnel:
        assert identity == _runner_identity(self.route)
        tunnel = await self.registry.create_owner(self.route)
        self.runner_task = asyncio.create_task(self._run_runner())
        return RuntimeWebOwnedTunnel(route=self.route, tunnel=tunnel)

    async def renew_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        allow_replaced_cycle: bool,
    ) -> RuntimeWebOwnedTunnel:
        del allow_replaced_cycle
        return owned

    async def close_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        reason: RunnerWebCancelReason,
    ) -> None:
        self.closed_reason = reason
        await self.registry.release(owned.tunnel)
        if self.runner_task is not None:
            await self.runner_task

    async def _run_runner(self) -> None:
        stream = await self.registry.join_runner(_runner_identity(self.route))
        controls = stream.control_frames().__aiter__()
        head = await anext(controls)
        assert isinstance(head, RunnerWebRequestHead)
        assert head.identity == _runner_identity(self.route)
        assert await anext(controls) == RunnerWebStreamEnd(final_sequence=0)
        await stream.receive(RunnerWebResponseHead(status=200, headers=()))
        await stream.receive(RunnerWebBodyChunk(sequence=1, data=b"hello"))
        await stream.receive(RunnerWebStreamEnd(final_sequence=1))


def _route(now: datetime.datetime) -> RuntimeWebTunnelRoute:
    return RuntimeWebTunnelRoute(
        authority=RuntimeWebTunnelAuthority(
            tunnel_id="tunnel-1",
            endpoint_id="endpoint-1",
            cycle_id="cycle-1",
            endpoint_authority_revision=3,
            close_barrier=1,
            runtime_id="runtime-1",
            desired_generation=2,
            runner_generation=4,
            port=3000,
            join_nonce="join-1",
            registration_deadline_at=now + datetime.timedelta(seconds=30),
            approval_deadline_at=now + datetime.timedelta(minutes=5),
            transport_deadline_at=now + datetime.timedelta(minutes=5),
        ),
        owner_replica_id="control-a",
        owner_boot_id="boot-a",
        owner_address="control-a.internal:8032",
        route_lease_id="lease-1",
        lease_generation=1,
        lease_expires_at=now + datetime.timedelta(seconds=30),
        admission_lease_id="admission-1",
    )


async def test_owner_events_survive_gateway_input_half_close() -> None:
    """HTTP response events remain readable after the request side half-closes."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    tunnel = await registry.create_owner(route)
    owned = RuntimeWebOwnedTunnel(route=route, tunnel=tunnel)

    async def input_completed() -> None:
        return None

    async def send_response() -> None:
        await asyncio.sleep(0.01)
        runner = await registry.join_runner(_runner_identity(route))
        await runner.receive(RunnerWebResponseHead(status=200, headers=()))
        await runner.receive(RunnerWebStreamEnd(final_sequence=0))

    inbound = asyncio.create_task(input_completed())
    renewal = asyncio.create_task(asyncio.sleep(60))
    producer = asyncio.create_task(send_response())
    try:
        frames = [frame async for frame in _owner_events(owned, inbound, renewal)]
    finally:
        renewal.cancel()
        await asyncio.gather(renewal, producer, return_exceptions=True)
        await registry.release(tunnel)

    assert frames == [
        RunnerWebResponseHead(status=200, headers=()),
        RunnerWebStreamEnd(final_sequence=0),
    ]


async def test_proxy_streams_http_frames_and_releases_owner() -> None:
    """Gateway frames cross the owner and release the exact tunnel at completion."""
    now = datetime.datetime(2026, 9, 12, 12, tzinfo=datetime.UTC)
    route = _route(now)
    coordinator = _Coordinator(route, now=now)
    server = grpc.aio.server()
    add_runtime_web_proxy_servicer(
        server,
        coordinator=coordinator,
        trusted_authenticator=AllowInsecureRuntimeWebTrustedPeerAuthenticator(),
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")

    async def requests() -> AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage]:
        yield runtime_web_transport_pb2.GatewayWebMessage(
            request_head=runtime_web_transport_pb2.RuntimeWebRequestHead(
                identity=runner_web_identity_to_message(_runner_identity(route)),
                protocol=runtime_web_transport_pb2.RUNTIME_WEB_PROTOCOL_HTTP,
                method=b"GET",
                target=b"/",
            )
        )
        yield runtime_web_transport_pb2.GatewayWebMessage(
            end=runtime_web_transport_pb2.RuntimeWebStreamEnd(final_sequence=0)
        )

    try:
        responses = [
            message
            async for message in runtime_web_transport_pb2_grpc.RuntimeWebProxyStub(
                channel
            ).Proxy(requests())
        ]
    finally:
        await channel.close()
        await server.stop(grace=None)

    assert [message.WhichOneof("payload") for message in responses] == [
        "accepted",
        "response_head",
        "body",
        "end",
    ]
    assert responses[1].response_head.status == 200
    assert responses[2].body.data == b"hello"
    assert coordinator.closed_reason is RunnerWebCancelReason.CALLER
