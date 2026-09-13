"""Trusted Gateway-to-owner Runtime Web transport edge."""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Protocol

import grpc
from azents_runtime_control.grpc_runner_web_client import (
    runner_web_control_from_message,
    runner_web_event_to_message,
)
from azents_runtime_control.proto import (
    runtime_web_transport_pb2,
    runtime_web_transport_pb2_grpc,
)
from azents_runtime_control.runner_web import (
    RunnerWebCancelReason,
    RunnerWebControlFrame,
    RunnerWebEventFrame,
    RunnerWebIdentity,
    RunnerWebRequestHead,
    RunnerWebStreamErrorCode,
)

from azents.repos.runtime_web.transport_repository import (
    RuntimeWebAdmissionCapacityExceeded,
    RuntimeWebRouteConflict,
)
from azents.runtime.control_protocol.grpc.runner_web_registry import (
    RuntimeWebTunnelAdmissionError,
)
from azents.runtime.control_protocol.grpc.runner_web_server import (
    RuntimeWebTrustedPeerAuthenticator,
)
from azents.runtime.web_transport_coordinator import (
    RuntimeWebOwnedTunnel,
)
from azents.runtime.web_transport_dispatcher import RuntimeWebDispatchUnavailable

_LOGGER = logging.getLogger(__name__)


class RuntimeWebOwnerCoordinator(Protocol):
    """Owner lifecycle needed by the trusted Gateway stream."""

    lease_seconds: float

    async def open_owner(
        self,
        identity: RunnerWebIdentity,
    ) -> RuntimeWebOwnedTunnel: ...

    async def renew_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        allow_replaced_cycle: bool,
    ) -> RuntimeWebOwnedTunnel: ...

    async def close_owner(
        self,
        owned: RuntimeWebOwnedTunnel,
        *,
        reason: RunnerWebCancelReason,
    ) -> None: ...


class RuntimeWebProxyGrpcServicer(
    runtime_web_transport_pb2_grpc.RuntimeWebProxyServicer
):
    """Create the owner route and stream trusted Gateway frames to one Runner."""

    def __init__(
        self,
        *,
        coordinator: RuntimeWebOwnerCoordinator,
        trusted_authenticator: RuntimeWebTrustedPeerAuthenticator,
    ) -> None:
        self.coordinator = coordinator
        self.trusted_authenticator = trusted_authenticator

    async def Proxy(
        self,
        request_iterator: AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage],
        context: grpc.aio.ServicerContext[
            runtime_web_transport_pb2.GatewayWebMessage,
            runtime_web_transport_pb2.GatewayWebMessage,
        ],
    ) -> AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage]:
        """Acquire ownership and bridge one non-replayable Gateway request."""
        await self.trusted_authenticator.authorize(context, role="gateway")
        first = await _first_gateway_head(request_iterator, context)
        try:
            head = _gateway_control_from_message(first)
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web Gateway request head is invalid",
            )
            raise AssertionError("unreachable") from None
        if not isinstance(head, RunnerWebRequestHead):
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web Gateway request head is required",
            )
            raise AssertionError("unreachable")
        try:
            owned = await self.coordinator.open_owner(head.identity)
        except RuntimeWebAdmissionCapacityExceeded:
            await context.abort(
                grpc.StatusCode.RESOURCE_EXHAUSTED,
                "Runtime Web connection capacity is exhausted",
            )
            raise AssertionError("unreachable") from None
        except RuntimeWebRouteConflict, RuntimeWebTunnelAdmissionError:
            await context.abort(
                grpc.StatusCode.ABORTED,
                "Runtime Web route authority is stale",
            )
            raise AssertionError("unreachable") from None
        except RuntimeWebDispatchUnavailable as error:
            _LOGGER.warning(
                "Runtime Web Runner dispatch unavailable",
                extra={
                    "runtime_id": head.identity.runtime_id,
                    "runner_generation": head.identity.runner_generation,
                    "reason": str(error),
                },
            )
            await context.abort(
                grpc.StatusCode.UNAVAILABLE,
                "Runtime Web Runner is unavailable",
            )
            raise AssertionError("unreachable") from None
        inbound: asyncio.Task[None] | None = None
        close_reason = RunnerWebCancelReason.CALLER
        renewal = asyncio.create_task(
            _renew_owner(self.coordinator, owned),
            name=f"runtime-web-route-renew:{head.identity.tunnel_id}",
        )
        try:
            await owned.tunnel.wait_for_runner()
            await owned.tunnel.send(head)
            inbound = asyncio.create_task(
                _consume_gateway_controls(
                    request_iterator,
                    context,
                    owned=owned,
                ),
                name=f"runtime-web-gateway-inbound:{head.identity.tunnel_id}",
            )
            yield runtime_web_transport_pb2.GatewayWebMessage(
                accepted=runtime_web_transport_pb2.RuntimeWebStreamAccepted(
                    tunnel_id=head.identity.tunnel_id
                )
            )
            async for frame in _owner_events(owned, inbound, renewal):
                yield _gateway_event_to_message(frame)
        except RuntimeWebTunnelAdmissionError as error:
            close_reason = (
                RunnerWebCancelReason.DEADLINE
                if error.code is RunnerWebStreamErrorCode.DEADLINE_EXCEEDED
                else RunnerWebCancelReason.PROTOCOL_VIOLATION
            )
            await context.abort(
                _admission_status(error.code),
                f"Runtime Web tunnel rejected: {error.code.value}",
            )
            raise AssertionError("unreachable") from None
        except RuntimeWebRouteConflict:
            close_reason = RunnerWebCancelReason.AUTHORITY_REVOKED
            await owned.tunnel.close()
        finally:
            if inbound is not None:
                inbound.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await inbound
            renewal.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeWebRouteConflict,
            ):
                await renewal
            await self.coordinator.close_owner(
                owned,
                reason=close_reason,
            )


def add_runtime_web_proxy_servicer(
    server: grpc.aio.Server,
    *,
    coordinator: RuntimeWebOwnerCoordinator,
    trusted_authenticator: RuntimeWebTrustedPeerAuthenticator,
) -> None:
    """Add the trusted Gateway-facing Runtime Web proxy service."""
    runtime_web_transport_pb2_grpc.add_RuntimeWebProxyServicer_to_server(
        RuntimeWebProxyGrpcServicer(
            coordinator=coordinator,
            trusted_authenticator=trusted_authenticator,
        ),
        server,
    )


async def _first_gateway_head(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.GatewayWebMessage,
        runtime_web_transport_pb2.GatewayWebMessage,
    ],
) -> runtime_web_transport_pb2.GatewayWebMessage:
    try:
        first = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web Gateway request head is required",
        )
        raise AssertionError("unreachable") from None
    if first.WhichOneof("payload") != "request_head":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runtime Web Gateway request head is required",
        )
        raise AssertionError("unreachable")
    return first


async def _consume_gateway_controls(
    request_iterator: AsyncIterator[runtime_web_transport_pb2.GatewayWebMessage],
    context: grpc.aio.ServicerContext[
        runtime_web_transport_pb2.GatewayWebMessage,
        runtime_web_transport_pb2.GatewayWebMessage,
    ],
    *,
    owned: RuntimeWebOwnedTunnel,
) -> None:
    async for message in request_iterator:
        try:
            await owned.tunnel.send(_gateway_control_from_message(message))
        except ValueError, RuntimeWebTunnelAdmissionError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Runtime Web Gateway frame is invalid",
            )
            raise AssertionError("unreachable") from None


async def _renew_owner(
    coordinator: RuntimeWebOwnerCoordinator,
    owned: RuntimeWebOwnedTunnel,
) -> None:
    interval = min(max(coordinator.lease_seconds / 2, 0.1), 5.0)
    current = owned
    while True:
        await asyncio.sleep(interval)
        current = await coordinator.renew_owner(
            current,
            allow_replaced_cycle=current.tunnel.allows_replaced_cycle,
        )


async def _owner_events(
    owned: RuntimeWebOwnedTunnel,
    inbound: asyncio.Task[None],
    renewal: asyncio.Task[None],
) -> AsyncIterator[RunnerWebEventFrame]:
    events = owned.tunnel.events().__aiter__()
    inbound_task: asyncio.Task[None] | None = inbound
    while True:
        event = asyncio.create_task(_next_event(events))
        watched: set[asyncio.Task[object]] = {event, renewal}
        if inbound_task is not None:
            watched.add(inbound_task)
        done, _pending = await asyncio.wait(
            watched,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if event in done:
            try:
                yield event.result()
            except StopAsyncIteration:
                return
            continue
        if renewal in done:
            event.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await event
            await renewal
            return
        if inbound_task is not None and inbound_task in done:
            event.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await event
            await inbound_task
            inbound_task = None


async def _next_event(
    events: AsyncIterator[RunnerWebEventFrame],
) -> RunnerWebEventFrame:
    return await anext(events)


def _admission_status(code: RunnerWebStreamErrorCode) -> grpc.StatusCode:
    if code is RunnerWebStreamErrorCode.DEADLINE_EXCEEDED:
        return grpc.StatusCode.DEADLINE_EXCEEDED
    if code is RunnerWebStreamErrorCode.PROTOCOL_VIOLATION:
        return grpc.StatusCode.INVALID_ARGUMENT
    if code is RunnerWebStreamErrorCode.RESOURCE_EXHAUSTED:
        return grpc.StatusCode.RESOURCE_EXHAUSTED
    return grpc.StatusCode.ABORTED


def _gateway_control_from_message(
    message: runtime_web_transport_pb2.GatewayWebMessage,
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
    raise ValueError("Runtime Web Gateway control frame is invalid")


def _gateway_event_to_message(
    frame: RunnerWebEventFrame,
) -> runtime_web_transport_pb2.GatewayWebMessage:
    message = runner_web_event_to_message(frame)
    payload = message.WhichOneof("payload")
    if payload == "response_head":
        return runtime_web_transport_pb2.GatewayWebMessage(
            response_head=message.response_head
        )
    if payload == "body":
        return runtime_web_transport_pb2.GatewayWebMessage(body=message.body)
    if payload == "end":
        return runtime_web_transport_pb2.GatewayWebMessage(end=message.end)
    if payload == "websocket":
        return runtime_web_transport_pb2.GatewayWebMessage(websocket=message.websocket)
    if payload == "heartbeat":
        return runtime_web_transport_pb2.GatewayWebMessage(heartbeat=message.heartbeat)
    if payload == "heartbeat_ack":
        return runtime_web_transport_pb2.GatewayWebMessage(
            heartbeat_ack=message.heartbeat_ack
        )
    if payload == "error":
        return runtime_web_transport_pb2.GatewayWebMessage(error=message.error)
    raise ValueError("Runtime Web Gateway event frame is invalid")
