"""Authenticated Runner Web streams and one-hop Control relay."""

import asyncio
import contextlib
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from datetime import UTC, datetime
from typing import NoReturn, Protocol

import grpc
from azents_runtime_control.grpc_runner_client import (
    runner_web_identity_from_message,
    runner_web_identity_to_message,
)
from azents_runtime_control.grpc_runner_web_client import (
    runner_web_control_from_message,
    runner_web_control_to_message,
    runner_web_event_from_message,
    runner_web_event_to_message,
)
from azents_runtime_control.proto import (
    runtime_web_transport_pb2,
    runtime_web_transport_pb2_grpc,
)
from azents_runtime_control.runner_web import (
    MAX_RUNTIME_WEB_FRAME_BYTES,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebIdentity,
    RunnerWebStreamAccepted,
    RunnerWebStreamErrorCode,
)

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.repos.runtime_web.data import RuntimeWebTunnelRoute
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeRunnerCredentialAuthenticator,
    RuntimeRunnerCredentialGrpcAuth,
)
from azents.runtime.control_protocol.grpc.runner_web_registry import (
    RuntimeWebOwnerRegistry,
    RuntimeWebRunnerTunnel,
    RuntimeWebTunnelAdmissionError,
)

_DEFAULT_PENDING_BYTES = 256 * 1024
_MAX_RELAY_FRAMES = _DEFAULT_PENDING_BYTES // MAX_RUNTIME_WEB_FRAME_BYTES


class RuntimeWebJoinedStream(Protocol):
    """One accepted local or relayed Runner-side tunnel."""

    @property
    def accepted(self) -> RunnerWebStreamAccepted: ...

    async def receive(self, frame: RunnerWebEventFrame) -> None: ...

    def control_frames(self) -> AsyncIterator[RunnerWebControlFrame]: ...

    async def close(self) -> None: ...


class RuntimeWebRouteCoordinator(Protocol):
    """Resolve live durable routes for Runner and relay admission."""

    owner_boot_id: str

    async def resolve_route(
        self,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebTunnelRoute | None: ...


class RuntimeWebRelayConnector(Protocol):
    """Open one authenticated Control-to-owner relay."""

    async def connect(
        self,
        route: RuntimeWebTunnelRoute,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebJoinedStream: ...


class RuntimeWebGrpcContext(Protocol):
    """gRPC context operations shared across Runtime Web stream shapes."""

    async def abort(
        self,
        code: grpc.StatusCode,
        details: str,
    ) -> NoReturn: ...


class RuntimeWebTrustedGrpcContext(RuntimeWebGrpcContext, Protocol):
    """gRPC context with authenticated transport identity evidence."""

    def auth_context(self) -> Mapping[str, Iterable[bytes]]: ...


class RuntimeWebTrustedPeerAuthenticator(Protocol):
    """Authorize a trusted-service RPC role from transport identity."""

    async def authorize(
        self,
        context: RuntimeWebTrustedGrpcContext,
        *,
        role: str,
    ) -> None: ...


class AllowInsecureRuntimeWebTrustedPeerAuthenticator:
    """Explicit local-development trusted-service authenticator."""

    async def authorize(
        self,
        context: RuntimeWebTrustedGrpcContext,
        *,
        role: str,
    ) -> None:
        """Allow a call only when composition selected insecure development mode."""
        del context, role


class MtlsRuntimeWebTrustedPeerAuthenticator:
    """Authorize configured peer certificate identities by service role."""

    def __init__(
        self,
        *,
        gateway_identities: frozenset[str],
        control_identities: frozenset[str],
    ) -> None:
        if not gateway_identities or not control_identities:
            raise ValueError("Runtime Web trusted peer identities must not be empty")
        self.identities = {
            "gateway": gateway_identities,
            "control": control_identities,
        }

    async def authorize(
        self,
        context: RuntimeWebTrustedGrpcContext,
        *,
        role: str,
    ) -> None:
        """Require one SAN or common-name identity admitted for the exact role."""
        allowed = self.identities.get(role)
        if allowed is None:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                "Runtime Web trusted-service role is invalid",
            )
            raise AssertionError("unreachable")
        auth_context = context.auth_context()
        presented = {
            value.decode("utf-8", errors="strict")
            for key in ("x509_subject_alternative_name", "x509_common_name")
            for value in auth_context.get(key, ())
        }
        if presented.isdisjoint(allowed):
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                "Runtime Web trusted-service identity is not authorized",
            )
            raise AssertionError("unreachable")


class RuntimeRunnerWebBroker:
    """Resolve the exact owner and join locally or through one relay hop."""

    def __init__(
        self,
        *,
        coordinator: RuntimeWebRouteCoordinator,
        registry: RuntimeWebOwnerRegistry,
        relay_connector: RuntimeWebRelayConnector,
    ) -> None:
        self.coordinator = coordinator
        self.registry = registry
        self.relay_connector = relay_connector

    async def connect(
        self,
        identity: RunnerWebIdentity,
        *,
        credential: RuntimeRunnerCredential,
    ) -> RuntimeWebJoinedStream:
        """Fence Runner claims and resolve exactly one durable owner."""
        if (
            credential.runtime_id != identity.runtime_id
            or credential.desired_generation != identity.desired_generation
        ):
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.STALE_RUNTIME_GENERATION
            )
        route = await self.coordinator.resolve_route(identity)
        if route is None:
            raise RuntimeWebTunnelAdmissionError(RunnerWebStreamErrorCode.STALE_ROUTE)
        if route.owner_boot_id == self.coordinator.owner_boot_id:
            return await self.registry.join_runner(identity)
        return await self.relay_connector.connect(route, identity)


class RuntimeRunnerWebGrpcServicer(
    runtime_web_transport_pb2_grpc.RuntimeRunnerWebServicer
):
    """Authenticate and bridge one independently pooled Runner Web stream."""

    def __init__(
        self,
        *,
        broker: RuntimeRunnerWebBroker,
        runner_authenticator: RuntimeRunnerCredentialAuthenticator,
    ) -> None:
        self.broker = broker
        self.runner_authenticator = runner_authenticator
        self.auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)

    async def ConnectWeb(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage],
        context: grpc.aio.ServicerContext[
            runtime_web_transport_pb2.RunnerWebMessage,
            runtime_web_transport_pb2.RunnerWebControlMessage,
        ],
    ) -> AsyncIterator[runtime_web_transport_pb2.RunnerWebControlMessage]:
        """Authenticate, fence, and bridge one Runtime Web tunnel."""
        credential = await self.auth.authenticate(context)
        first = await _first_runner_registration(request_iterator, context)
        try:
            identity = runner_web_identity_from_message(first.register.identity)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web registration is invalid",
            )
            raise AssertionError("unreachable") from None
        if not await self.runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is no longer authorized",
            )
            raise AssertionError("unreachable")
        try:
            stream = await self.broker.connect(identity, credential=credential)
        except RuntimeWebTunnelAdmissionError as error:
            await _abort_admission(context, error)
            raise AssertionError("unreachable") from None
        inbound = asyncio.create_task(
            _consume_runner_events(
                request_iterator,
                context,
                stream=stream,
                credential=credential,
                runner_authenticator=self.runner_authenticator,
            ),
            name=f"runner-web-inbound:{identity.tunnel_id}",
        )
        try:
            yield runtime_web_transport_pb2.RunnerWebControlMessage(
                accepted=runtime_web_transport_pb2.RuntimeWebStreamAccepted(
                    tunnel_id=stream.accepted.tunnel_id
                )
            )
            async for frame in _joined_controls(stream, inbound):
                yield runner_web_control_to_message(frame)
        finally:
            inbound.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await inbound
            await stream.close()


class RuntimeWebRelayGrpcServicer(
    runtime_web_transport_pb2_grpc.RuntimeWebRelayServicer
):
    """Accept one trusted receiving-Control relay at the local owner."""

    def __init__(
        self,
        *,
        coordinator: RuntimeWebRouteCoordinator,
        registry: RuntimeWebOwnerRegistry,
        trusted_authenticator: RuntimeWebTrustedPeerAuthenticator,
    ) -> None:
        self.coordinator = coordinator
        self.registry = registry
        self.trusted_authenticator = trusted_authenticator

    async def RelayWeb(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.RelayWebMessage],
        context: grpc.aio.ServicerContext[
            runtime_web_transport_pb2.RelayWebMessage,
            runtime_web_transport_pb2.RelayWebMessage,
        ],
    ) -> AsyncIterator[runtime_web_transport_pb2.RelayWebMessage]:
        """Verify the owner lease and bridge a remote Runner without another hop."""
        await self.trusted_authenticator.authorize(context, role="control")
        first = await _first_relay_registration(request_iterator, context)
        try:
            identity = runner_web_identity_from_message(first.register.identity)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web relay registration is invalid",
            )
            raise AssertionError("unreachable") from None
        route = await self.coordinator.resolve_route(identity)
        if (
            route is None
            or route.owner_boot_id != self.coordinator.owner_boot_id
            or route.owner_boot_id != first.register.owner_boot_id
            or route.route_lease_id != first.register.route_lease_id
        ):
            await context.abort(
                grpc.StatusCode.ABORTED,
                "Runtime Web relay route is stale",
            )
            raise AssertionError("unreachable")
        try:
            stream = await self.registry.join_runner(identity)
        except RuntimeWebTunnelAdmissionError as error:
            await _abort_admission(context, error)
            raise AssertionError("unreachable") from None
        inbound = asyncio.create_task(
            _consume_relay_events(request_iterator, context, stream=stream),
            name=f"runtime-web-relay-inbound:{identity.tunnel_id}",
        )
        try:
            yield runtime_web_transport_pb2.RelayWebMessage(
                accepted=runtime_web_transport_pb2.RuntimeWebStreamAccepted(
                    tunnel_id=stream.accepted.tunnel_id
                )
            )
            async for frame in _joined_controls(stream, inbound):
                yield _relay_control_to_message(frame)
        finally:
            inbound.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await inbound
            await stream.close()


class RelayWebCall(Protocol):
    """Generated RelayWeb stream call surface."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.RelayWebMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_transport_pb2.RelayWebMessage]: ...


class GrpcRuntimeWebRelayConnector:
    """Create one independently pooled gRPC relay to the durable owner address."""

    def __init__(
        self,
        *,
        channel_factory: Callable[[str], grpc.aio.Channel],
    ) -> None:
        self.channel_factory = channel_factory

    async def connect(
        self,
        route: RuntimeWebTunnelRoute,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebJoinedStream:
        """Open and register one one-hop relay stream."""
        channel = self.channel_factory(route.owner_address)
        call = runtime_web_transport_pb2_grpc.RuntimeWebRelayStub(channel).RelayWeb
        stream = GrpcRuntimeWebRelayStream(call=call, channel=channel)
        remaining = (
            identity.registration_deadline_at - datetime.now(UTC)
        ).total_seconds()
        if remaining <= 0:
            await stream.close()
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
            )
        try:
            await asyncio.wait_for(stream.start(route, identity), timeout=remaining)
        except TimeoutError:
            await stream.close()
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
            ) from None
        except grpc.aio.AioRpcError:
            await stream.close()
            raise RuntimeWebTunnelAdmissionError(
                RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE
            ) from None
        return stream


class GrpcRuntimeWebRelayStream:
    """Runner-side adapter for one Control-to-owner relay."""

    def __init__(
        self,
        *,
        call: RelayWebCall,
        channel: grpc.aio.Channel | None,
    ) -> None:
        self.call = call
        self.channel = channel
        self.outbound: asyncio.Queue[
            runtime_web_transport_pb2.RelayWebMessage | None
        ] = asyncio.Queue(maxsize=_MAX_RELAY_FRAMES)
        self.control_queue: asyncio.Queue[RunnerWebControlFrame | None] = asyncio.Queue(
            maxsize=_MAX_RELAY_FRAMES
        )
        self.accepted_future: asyncio.Future[RunnerWebStreamAccepted] | None = None
        self.receiver: asyncio.Task[None] | None = None

    @property
    def accepted(self) -> RunnerWebStreamAccepted:
        """Return the completed relay registration."""
        if self.accepted_future is None or not self.accepted_future.done():
            raise RuntimeError("Runtime Web relay is not accepted")
        return self.accepted_future.result()

    async def start(
        self,
        route: RuntimeWebTunnelRoute,
        identity: RunnerWebIdentity,
    ) -> None:
        """Send exact route lease evidence and wait for owner acceptance."""
        self.accepted_future = asyncio.get_running_loop().create_future()
        responses = self.call(
            self._outbound_messages(
                runtime_web_transport_pb2.RelayWebMessage(
                    register=runtime_web_transport_pb2.RelayWebRegistration(
                        identity=runner_web_identity_to_message(identity),
                        owner_boot_id=route.owner_boot_id,
                        route_lease_id=route.route_lease_id,
                    )
                )
            )
        )
        self.receiver = asyncio.create_task(
            self._receive(responses),
            name=f"runtime-web-relay-client:{identity.tunnel_id}",
        )
        await self.accepted_future

    async def receive(self, frame: RunnerWebEventFrame) -> None:
        """Forward one Runner event to the owner Control."""
        await self.outbound.put(_relay_event_to_message(frame))

    def control_frames(self) -> AsyncIterator[RunnerWebControlFrame]:
        """Yield relayed owner controls."""
        return self._controls()

    async def close(self) -> None:
        """Close the relay without replay or resume."""
        if self.receiver is not None:
            self.receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, grpc.aio.AioRpcError):
                await self.receiver
            self.receiver = None
        _finish_queue(self.outbound)
        _finish_queue(self.control_queue)
        if self.channel is not None:
            await self.channel.close()
            self.channel = None

    async def _outbound_messages(
        self,
        registration: runtime_web_transport_pb2.RelayWebMessage,
    ) -> AsyncIterator[runtime_web_transport_pb2.RelayWebMessage]:
        yield registration
        while True:
            message = await self.outbound.get()
            if message is None:
                return
            yield message

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_transport_pb2.RelayWebMessage],
    ) -> None:
        try:
            async for message in responses:
                if message.WhichOneof("payload") == "accepted":
                    accepted = RunnerWebStreamAccepted(
                        tunnel_id=message.accepted.tunnel_id
                    )
                    if (
                        self.accepted_future is not None
                        and not self.accepted_future.done()
                    ):
                        self.accepted_future.set_result(accepted)
                    continue
                await self.control_queue.put(_relay_control_from_message(message))
            if self.accepted_future is not None and not self.accepted_future.done():
                self.accepted_future.set_exception(
                    RuntimeWebTunnelAdmissionError(
                        RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if self.accepted_future is not None and not self.accepted_future.done():
                self.accepted_future.set_exception(error)
            raise
        finally:
            _finish_queue(self.control_queue)

    async def _controls(self) -> AsyncIterator[RunnerWebControlFrame]:
        while True:
            frame = await self.control_queue.get()
            if frame is None:
                return
            yield frame


def add_runtime_runner_web_servicer(
    server: grpc.aio.Server,
    *,
    broker: RuntimeRunnerWebBroker,
    runner_authenticator: RuntimeRunnerCredentialAuthenticator,
) -> None:
    """Add the authenticated dedicated Runner Web service."""
    runtime_web_transport_pb2_grpc.add_RuntimeRunnerWebServicer_to_server(
        RuntimeRunnerWebGrpcServicer(
            broker=broker,
            runner_authenticator=runner_authenticator,
        ),
        server,
    )


def add_runtime_web_relay_servicer(
    server: grpc.aio.Server,
    *,
    coordinator: RuntimeWebRouteCoordinator,
    registry: RuntimeWebOwnerRegistry,
    trusted_authenticator: RuntimeWebTrustedPeerAuthenticator,
) -> None:
    """Add the trusted Control-to-owner Runtime Web relay service."""
    runtime_web_transport_pb2_grpc.add_RuntimeWebRelayServicer_to_server(
        RuntimeWebRelayGrpcServicer(
            coordinator=coordinator,
            registry=registry,
            trusted_authenticator=trusted_authenticator,
        ),
        server,
    )


async def _first_runner_registration(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.RunnerWebMessage,
        runtime_web_transport_pb2.RunnerWebControlMessage,
    ],
) -> runtime_web_transport_pb2.RunnerWebMessage:
    try:
        first = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web registration is required",
        )
        raise AssertionError("unreachable") from None
    if first.WhichOneof("payload") != "register":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web registration is required",
        )
        raise AssertionError("unreachable")
    return first


async def _first_relay_registration(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.RelayWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.RelayWebMessage,
        runtime_web_transport_pb2.RelayWebMessage,
    ],
) -> runtime_web_transport_pb2.RelayWebMessage:
    try:
        first = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web relay registration is required",
        )
        raise AssertionError("unreachable") from None
    if first.WhichOneof("payload") != "register":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web relay registration is required",
        )
        raise AssertionError("unreachable")
    return first


async def _consume_runner_events(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.RunnerWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.RunnerWebMessage,
        runtime_web_transport_pb2.RunnerWebControlMessage,
    ],
    *,
    stream: RuntimeWebJoinedStream,
    credential: RuntimeRunnerCredential,
    runner_authenticator: RuntimeRunnerCredentialAuthenticator,
) -> None:
    async for message in request_iterator:
        if not await runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is no longer authorized",
            )
            raise AssertionError("unreachable")
        try:
            frame = runner_web_event_from_message(message)
            await stream.receive(frame)
        except ValueError, RuntimeWebTunnelAdmissionError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web Runner frame is invalid",
            )
            raise AssertionError("unreachable") from None


async def _consume_relay_events(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.RelayWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.RelayWebMessage,
        runtime_web_transport_pb2.RelayWebMessage,
    ],
    *,
    stream: RuntimeWebRunnerTunnel,
) -> None:
    async for message in request_iterator:
        try:
            await stream.receive(_relay_event_from_message(message))
        except ValueError, RuntimeWebTunnelAdmissionError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web relay frame is invalid",
            )
            raise AssertionError("unreachable") from None


async def _joined_controls(
    stream: RuntimeWebJoinedStream,
    inbound: asyncio.Task[None],
) -> AsyncIterator[RunnerWebControlFrame]:
    controls = stream.control_frames().__aiter__()
    while True:
        control = asyncio.create_task(_next_control(controls))
        done, _pending = await asyncio.wait(
            (control, inbound),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if inbound in done:
            control.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await control
            await inbound
            return
        try:
            yield control.result()
        except StopAsyncIteration:
            return


async def _abort_admission(
    context: RuntimeWebGrpcContext,
    error: RuntimeWebTunnelAdmissionError,
) -> None:
    status = {
        RunnerWebStreamErrorCode.STALE_AUTHORITY: grpc.StatusCode.PERMISSION_DENIED,
        RunnerWebStreamErrorCode.STALE_RUNTIME_GENERATION: (
            grpc.StatusCode.PERMISSION_DENIED
        ),
        RunnerWebStreamErrorCode.STALE_ROUTE: grpc.StatusCode.ABORTED,
        RunnerWebStreamErrorCode.DUPLICATE_JOIN: grpc.StatusCode.ALREADY_EXISTS,
        RunnerWebStreamErrorCode.PROTOCOL_VIOLATION: grpc.StatusCode.INVALID_ARGUMENT,
        RunnerWebStreamErrorCode.RESOURCE_EXHAUSTED: (
            grpc.StatusCode.RESOURCE_EXHAUSTED
        ),
        RunnerWebStreamErrorCode.DEADLINE_EXCEEDED: (grpc.StatusCode.DEADLINE_EXCEEDED),
        RunnerWebStreamErrorCode.APPLICATION_UNAVAILABLE: (grpc.StatusCode.UNAVAILABLE),
        RunnerWebStreamErrorCode.TRANSPORT_UNAVAILABLE: grpc.StatusCode.UNAVAILABLE,
    }[error.code]
    await context.abort(status, f"Runtime Web tunnel rejected: {error.code.value}")


async def _next_control(
    controls: AsyncIterator[RunnerWebControlFrame],
) -> RunnerWebControlFrame:
    return await anext(controls)


def _relay_event_to_message(
    frame: RunnerWebEventFrame,
) -> runtime_web_transport_pb2.RelayWebMessage:
    message = runner_web_event_to_message(frame)
    payload = message.WhichOneof("payload")
    if payload == "response_head":
        return runtime_web_transport_pb2.RelayWebMessage(
            response_head=message.response_head
        )
    if payload == "body":
        return runtime_web_transport_pb2.RelayWebMessage(body=message.body)
    if payload == "end":
        return runtime_web_transport_pb2.RelayWebMessage(end=message.end)
    if payload == "websocket":
        return runtime_web_transport_pb2.RelayWebMessage(websocket=message.websocket)
    if payload == "heartbeat":
        return runtime_web_transport_pb2.RelayWebMessage(heartbeat=message.heartbeat)
    if payload == "heartbeat_ack":
        return runtime_web_transport_pb2.RelayWebMessage(
            heartbeat_ack=message.heartbeat_ack
        )
    if payload == "error":
        return runtime_web_transport_pb2.RelayWebMessage(error=message.error)
    raise ValueError("Runtime Web relay event is invalid")


def _relay_event_from_message(
    message: runtime_web_transport_pb2.RelayWebMessage,
) -> RunnerWebEventFrame:
    payload = message.WhichOneof("payload")
    if payload == "response_head":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(
                response_head=message.response_head
            )
        )
    if payload == "body":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(body=message.body)
        )
    if payload == "end":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(end=message.end)
        )
    if payload == "websocket":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(websocket=message.websocket)
        )
    if payload == "heartbeat":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(heartbeat=message.heartbeat)
        )
    if payload == "heartbeat_ack":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(
                heartbeat_ack=message.heartbeat_ack
            )
        )
    if payload == "error":
        return runner_web_event_from_message(
            runtime_web_transport_pb2.RunnerWebMessage(error=message.error)
        )
    raise ValueError("Runtime Web relay event is invalid")


def _relay_control_to_message(
    frame: RunnerWebControlFrame,
) -> runtime_web_transport_pb2.RelayWebMessage:
    message = runner_web_control_to_message(frame)
    payload = message.WhichOneof("payload")
    if payload == "request_head":
        return runtime_web_transport_pb2.RelayWebMessage(
            request_head=message.request_head
        )
    if payload == "body":
        return runtime_web_transport_pb2.RelayWebMessage(body=message.body)
    if payload == "end":
        return runtime_web_transport_pb2.RelayWebMessage(end=message.end)
    if payload == "websocket":
        return runtime_web_transport_pb2.RelayWebMessage(websocket=message.websocket)
    if payload == "heartbeat":
        return runtime_web_transport_pb2.RelayWebMessage(heartbeat=message.heartbeat)
    if payload == "heartbeat_ack":
        return runtime_web_transport_pb2.RelayWebMessage(
            heartbeat_ack=message.heartbeat_ack
        )
    if payload == "cancel":
        return runtime_web_transport_pb2.RelayWebMessage(cancel=message.cancel)
    if payload == "error":
        return runtime_web_transport_pb2.RelayWebMessage(error=message.error)
    raise ValueError("Runtime Web relay control is invalid")


def _relay_control_from_message(
    message: runtime_web_transport_pb2.RelayWebMessage,
) -> RunnerWebControlFrame:
    payload = message.WhichOneof("payload")
    if payload == "request_head":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(
                request_head=message.request_head
            )
        )
    if payload == "body":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(body=message.body)
        )
    if payload == "end":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(end=message.end)
        )
    if payload == "websocket":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(
                websocket=message.websocket
            )
        )
    if payload == "heartbeat":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(
                heartbeat=message.heartbeat
            )
        )
    if payload == "heartbeat_ack":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(
                heartbeat_ack=message.heartbeat_ack
            )
        )
    if payload == "cancel":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(cancel=message.cancel)
        )
    if payload == "error":
        return runner_web_control_from_message(
            runtime_web_transport_pb2.RunnerWebControlMessage(error=message.error)
        )
    raise ValueError("Runtime Web relay control is invalid")


def _finish_queue[FrameT](queue: asyncio.Queue[FrameT | None]) -> None:
    if queue.full():
        queue.get_nowait()
    queue.put_nowait(None)
