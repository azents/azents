"""Authenticated Runner client for one persistent Runtime Web session."""

import asyncio
import enum
import logging
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Sequence
from typing import TYPE_CHECKING, Protocol

import grpc

from azents_runtime_control.grpc_tls import GrpcClientTlsConfig, create_grpc_aio_channel
from azents_runtime_control.proto import runtime_web_session_pb2
from azents_runtime_control.runtime_web_session import (
    validate_runner_web_connect_address,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_web_session_pb2_grpc import (
        RuntimeRunnerWebSessionAsyncStub as _RuntimeRunnerWebSessionStub,
    )
else:
    from azents_runtime_control.proto.runtime_web_session_pb2_grpc import (
        RuntimeRunnerWebSessionStub as _RuntimeRunnerWebSessionStub,
    )

_MAX_PENDING_ENVELOPES = 8
_LOGGER = logging.getLogger(__name__)


class RunnerWebResourceExhausted(RuntimeError):
    """One process-local Runner Web hard-limit rejection."""


class _ClientState(enum.StrEnum):
    NEW = "new"
    ACTIVE = "active"
    FAILED = "failed"
    CLOSING = "closing"
    CLOSED = "closed"


class RunnerWebSessionStream(Protocol):
    """Generated persistent Runner session call surface."""

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_web_session_pb2.RuntimeWebSessionEnvelope
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope]: ...


class RunnerWebEnvelopeResources(Protocol):
    """Process-local resource accounting for the Runner outbound queue."""

    def try_reserve_envelope(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> bool: ...

    def release_envelope(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None: ...


class GrpcRunnerWebSessionClient:
    """Own one bounded persistent Runner-to-Owner gRPC session."""

    def __init__(
        self,
        stream: RunnerWebSessionStream,
        *,
        runner_auth_token: str,
        channel: grpc.aio.Channel | None,
        outbound_resources: RunnerWebEnvelopeResources | None,
    ) -> None:
        if not runner_auth_token:
            raise ValueError("Runner authentication token must not be empty")
        self.stream = stream
        self.channel = channel
        self.outbound_resources = outbound_resources
        self.metadata = (("authorization", f"Bearer {runner_auth_token}"),)
        self.outbound: deque[runtime_web_session_pb2.RuntimeWebSessionEnvelope] = (
            deque()
        )
        self.condition = asyncio.Condition()
        self.shutdown_lock = asyncio.Lock()
        self.activated = asyncio.Event()
        self.state = _ClientState.NEW
        self.receiver_task: asyncio.Task[None] | None = None
        self.accepted: (
            asyncio.Future[runtime_web_session_pb2.RuntimeWebSessionEnvelope] | None
        ) = None

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        tls_server_name: str,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
        outbound_resources: RunnerWebEnvelopeResources | None,
    ) -> "GrpcRunnerWebSessionClient":
        validate_runner_web_connect_address(endpoint)
        options: tuple[tuple[str, int | str], ...] = (
            ("grpc.use_local_subchannel_pool", 1),
            ("grpc.max_send_message_length", 2 * 1024 * 1024),
            ("grpc.max_receive_message_length", 2 * 1024 * 1024),
        )
        if tls is not None:
            if not tls_server_name:
                raise ValueError("Runner Web TLS server name must not be empty")
            options = (*options, ("grpc.ssl_target_name_override", tls_server_name))
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
            options=options,
        )
        return cls(
            _RuntimeRunnerWebSessionStub(channel).Connect,
            runner_auth_token=runner_auth_token,
            channel=channel,
            outbound_resources=outbound_resources,
        )

    async def start(
        self,
        hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        handler: "EnvelopeHandler",
        failure_handler: "FailureHandler",
        *,
        timeout_seconds: float,
    ) -> runtime_web_session_pb2.RuntimeWebSessionEnvelope:
        """Start and await the exact first session-accepted envelope."""
        if timeout_seconds <= 0:
            raise ValueError("Runner Web session timeout must be positive")
        stream_error: Exception | None = None
        async with self.condition:
            if self.state is not _ClientState.NEW:
                raise RuntimeError("Runner Web session is already started")
            self.state = _ClientState.ACTIVE
            self.accepted = asyncio.get_running_loop().create_future()
            try:
                responses = self.stream(
                    self._outbound_messages(hello),
                    metadata=self.metadata,
                )
            except Exception as error:
                self.state = _ClientState.FAILED
                self.condition.notify_all()
                stream_error = error
            else:
                self.receiver_task = asyncio.create_task(
                    self._receive(responses, handler, failure_handler)
                )
        if stream_error is not None:
            await self._shutdown(propagate_receiver_error=False)
            raise stream_error
        try:
            return await asyncio.wait_for(self.accepted, timeout=timeout_seconds)
        except asyncio.CancelledError:
            await self._shutdown(propagate_receiver_error=False)
            raise
        except Exception:
            await self._shutdown(propagate_receiver_error=False)
            raise

    def activate(self) -> None:
        """Permit frame dispatch after Manager authority validation."""
        if (
            self.state is not _ClientState.ACTIVE
            or self.receiver_task is None
            or self.receiver_task.done()
        ):
            raise RuntimeError("Runner Web session is not active")
        self.activated.set()

    async def send(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> None:
        """Queue one bounded session envelope."""
        async with self.condition:
            await self.condition.wait_for(
                lambda: (
                    len(self.outbound) < _MAX_PENDING_ENVELOPES
                    or self.state is not _ClientState.ACTIVE
                    or self.receiver_task is None
                    or self.receiver_task.done()
                )
            )
            if (
                self.state is not _ClientState.ACTIVE
                or self.receiver_task is None
                or self.receiver_task.done()
            ):
                raise RuntimeError("Runner Web session is not active")
            if (
                self.outbound_resources is not None
                and not self.outbound_resources.try_reserve_envelope(envelope)
            ):
                raise RunnerWebResourceExhausted(
                    "Runner Web outbound hard limit is exhausted"
                )
            self.outbound.append(envelope)
            self.condition.notify_all()

    async def close(self) -> None:
        """Close the session without replaying queued envelopes."""
        await self._shutdown(propagate_receiver_error=True)

    async def _outbound_messages(
        self,
        hello: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
    ) -> AsyncIterator[runtime_web_session_pb2.RuntimeWebSessionEnvelope]:
        yield hello
        while True:
            async with self.condition:
                await self.condition.wait_for(
                    lambda: bool(self.outbound) or self.state is not _ClientState.ACTIVE
                )
                if self.state is not _ClientState.ACTIVE:
                    return
                message = self.outbound.popleft()
                if self.outbound_resources is not None:
                    self.outbound_resources.release_envelope(message)
                self.condition.notify_all()
            yield message

    async def _receive(
        self,
        responses: AsyncIterable[runtime_web_session_pb2.RuntimeWebSessionEnvelope],
        handler: "EnvelopeHandler",
        failure_handler: "FailureHandler",
    ) -> None:
        first = True
        try:
            async for response in responses:
                if first:
                    first = False
                    if (
                        response.WhichOneof("payload") != "session_accepted"
                        or response.stream_id != 0
                    ):
                        raise RuntimeError(
                            "Runner Web session acceptance must be session-scoped"
                        )
                    if self.accepted is not None and not self.accepted.done():
                        self.accepted.set_result(response)
                    await self.activated.wait()
                    continue
                await handler(response)
            if self.accepted is not None and not self.accepted.done():
                self.accepted.set_exception(
                    RuntimeError("Runner Web session closed before acceptance")
                )
            _LOGGER.warning("Runtime Web Runner session closed by Control")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _LOGGER.exception("Runtime Web Runner session receive failed")
            if self.accepted is not None and not self.accepted.done():
                self.accepted.set_exception(error)
            raise
        finally:
            failed = False
            async with self.condition:
                if self.state is _ClientState.ACTIVE:
                    self.state = _ClientState.FAILED
                    failed = True
                self.condition.notify_all()
            if failed:
                await failure_handler()

    async def _shutdown(self, *, propagate_receiver_error: bool) -> None:
        async with self.shutdown_lock:
            async with self.condition:
                if self.state is _ClientState.CLOSED:
                    return
                self.state = _ClientState.CLOSING
                self._release_outbound()
                receiver_task = self.receiver_task
                self.receiver_task = None
                self.condition.notify_all()
            receiver_error: Exception | None = None
            if receiver_task is not None:
                if not receiver_task.done():
                    receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass
                except Exception as error:
                    receiver_error = error
            channel = self.channel
            self.channel = None
            try:
                if channel is not None:
                    await channel.close()
            finally:
                async with self.condition:
                    self._release_outbound()
                    if self.accepted is not None and not self.accepted.done():
                        self.accepted.cancel()
                    self.state = _ClientState.CLOSED
                    self.condition.notify_all()
            if propagate_receiver_error and receiver_error is not None:
                raise receiver_error

    def _release_outbound(self) -> None:
        """Release all exact queued process reservations before clearing."""
        if self.outbound_resources is not None:
            for envelope in self.outbound:
                self.outbound_resources.release_envelope(envelope)
        self.outbound.clear()


class EnvelopeHandler(Protocol):
    """Handle one inbound persistent session envelope."""

    def __call__(
        self,
        envelope: runtime_web_session_pb2.RuntimeWebSessionEnvelope,
        /,
    ) -> Awaitable[None]: ...


class FailureHandler(Protocol):
    """Handle independent persistent-session receiver failure."""

    def __call__(self) -> Awaitable[None]: ...
