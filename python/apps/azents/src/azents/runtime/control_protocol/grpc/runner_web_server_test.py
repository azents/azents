"""Runtime Web Runner and one-hop relay tests."""

import asyncio
import datetime
from collections.abc import Iterable, Mapping
from typing import NoReturn

import grpc
import pytest
from azents_runtime_control.grpc_runner_web_client import GrpcRunnerWebClient
from azents_runtime_control.runner_web import (
    RunnerWebBodyChunk,
    RunnerWebHeader,
    RunnerWebIdentity,
    RunnerWebProtocol,
    RunnerWebRequestHead,
    RunnerWebResponseHead,
    RunnerWebStreamEnd,
)

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
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
    GrpcRuntimeWebRelayConnector,
    MtlsRuntimeWebTrustedPeerAuthenticator,
    RuntimeRunnerWebBroker,
    add_runtime_runner_web_servicer,
    add_runtime_web_relay_servicer,
)


class _RouteCoordinator:
    def __init__(self, *, owner_boot_id: str, route: RuntimeWebTunnelRoute) -> None:
        self.owner_boot_id = owner_boot_id
        self.route = route

    async def resolve_route(
        self,
        identity: object,
    ) -> RuntimeWebTunnelRoute | None:
        return self.route if identity == _runner_identity(self.route) else None


class _TrustedContext:
    def __init__(self, identity: str) -> None:
        self.identity = identity

    def auth_context(self) -> Mapping[str, Iterable[bytes]]:
        return {"x509_subject_alternative_name": (self.identity.encode(),)}

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str,
    ) -> NoReturn:
        raise RuntimeError(f"{code.name}: {details}")


class _RunnerAuthenticator:
    async def authenticate_runner(self, secret: str) -> RuntimeRunnerCredential:
        assert secret == "runner-token"
        return RuntimeRunnerCredential(
            credential_id="credential-1",
            runtime_id="runtime-1",
            desired_generation=2,
        )

    async def authorize_runner(self, credential: RuntimeRunnerCredential) -> bool:
        return credential.runtime_id == "runtime-1"


class _UnexpectedRelayConnector:
    async def connect(
        self,
        route: RuntimeWebTunnelRoute,
        identity: RunnerWebIdentity,
    ) -> NoReturn:
        del route, identity
        raise AssertionError("Local owner must not use a relay")


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
        owner_address="owner.invalid:8032",
        route_lease_id="lease-1",
        lease_generation=1,
        lease_expires_at=now + datetime.timedelta(seconds=30),
        admission_lease_id="admission-1",
    )


async def test_runner_on_second_control_relays_once_to_owner() -> None:
    """A receiving Control bridges frames to the advertised owner Control."""
    now = datetime.datetime.now(datetime.UTC)
    route = _route(now)
    owner_registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    owner_tunnel = await owner_registry.create_owner(route)
    owner_coordinator = _RouteCoordinator(owner_boot_id="boot-a", route=route)

    server = grpc.aio.server()
    add_runtime_web_relay_servicer(
        server,
        coordinator=owner_coordinator,
        registry=owner_registry,
        trusted_authenticator=AllowInsecureRuntimeWebTrustedPeerAuthenticator(),
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        receiving_coordinator = _RouteCoordinator(owner_boot_id="boot-b", route=route)
        connector = GrpcRuntimeWebRelayConnector(
            channel_factory=lambda _address: grpc.aio.insecure_channel(
                f"127.0.0.1:{port}"
            )
        )
        broker = RuntimeRunnerWebBroker(
            coordinator=receiving_coordinator,
            registry=RuntimeWebOwnerRegistry(clock=lambda: now),
            relay_connector=connector,
        )
        runner_stream = await broker.connect(
            _runner_identity(route),
            credential=RuntimeRunnerCredential(
                credential_id="credential-1",
                runtime_id="runtime-1",
                desired_generation=2,
            ),
        )
        await owner_tunnel.send(
            RunnerWebRequestHead(
                identity=_runner_identity(route),
                protocol=RunnerWebProtocol.HTTP,
                method=b"GET",
                target=b"/events",
                headers=(RunnerWebHeader(b"accept", b"text/event-stream"),),
            )
        )
        await owner_tunnel.send(RunnerWebStreamEnd(final_sequence=0))
        controls = runner_stream.control_frames().__aiter__()

        assert isinstance(await anext(controls), RunnerWebRequestHead)
        assert await anext(controls) == RunnerWebStreamEnd(final_sequence=0)

        await runner_stream.receive(RunnerWebResponseHead(status=200, headers=()))
        await runner_stream.receive(RunnerWebBodyChunk(sequence=1, data=b"data"))
        await runner_stream.receive(RunnerWebStreamEnd(final_sequence=1))
        events = owner_tunnel.events().__aiter__()

        assert await anext(events) == RunnerWebResponseHead(status=200, headers=())
        assert await anext(events) == RunnerWebBodyChunk(sequence=1, data=b"data")
        assert await anext(events) == RunnerWebStreamEnd(final_sequence=1)
        await runner_stream.close()
    finally:
        await server.stop(grace=None)


async def test_trusted_peer_role_uses_certificate_identity() -> None:
    """Gateway and Control roles admit only configured mTLS identities."""
    authenticator = MtlsRuntimeWebTrustedPeerAuthenticator(
        gateway_identities=frozenset({"gateway.internal"}),
        control_identities=frozenset({"control.internal"}),
    )

    await authenticator.authorize(
        _TrustedContext("gateway.internal"),
        role="gateway",
    )
    with pytest.raises(RuntimeError, match="not authorized"):
        await authenticator.authorize(
            _TrustedContext("gateway.internal"),
            role="control",
        )


async def test_authenticated_runner_web_rpc_joins_local_owner() -> None:
    """The dedicated Runner RPC authenticates and bridges exact local frames."""
    now = datetime.datetime.now(datetime.UTC)
    route = _route(now)
    registry = RuntimeWebOwnerRegistry(clock=lambda: now)
    owner = await registry.create_owner(route)
    broker = RuntimeRunnerWebBroker(
        coordinator=_RouteCoordinator(owner_boot_id="boot-a", route=route),
        registry=registry,
        relay_connector=_UnexpectedRelayConnector(),
    )
    server = grpc.aio.server()
    add_runtime_runner_web_servicer(
        server,
        broker=broker,
        runner_authenticator=_RunnerAuthenticator(),
    )
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    client = GrpcRunnerWebClient.from_endpoint(
        f"127.0.0.1:{port}",
        runner_auth_token="runner-token",
        tls=None,
        allow_insecure=True,
    )
    received: asyncio.Queue[object] = asyncio.Queue()
    client.set_control_handler(received.put)
    try:
        accepted = await client.start(_runner_identity(route))
        assert accepted.tunnel_id == route.authority.tunnel_id
        await owner.send(
            RunnerWebRequestHead(
                identity=_runner_identity(route),
                protocol=RunnerWebProtocol.HTTP,
                method=b"GET",
                target=b"/",
                headers=(),
            )
        )
        await owner.send(RunnerWebStreamEnd(final_sequence=0))

        assert isinstance(await received.get(), RunnerWebRequestHead)
        assert await received.get() == RunnerWebStreamEnd(final_sequence=0)

        await client.send(RunnerWebResponseHead(status=204, headers=()))
        await client.finish(RunnerWebStreamEnd(final_sequence=0))
        events = owner.events().__aiter__()
        assert await anext(events) == RunnerWebResponseHead(status=204, headers=())
        assert await anext(events) == RunnerWebStreamEnd(final_sequence=0)
    finally:
        await client.close()
        await server.stop(grace=None)
