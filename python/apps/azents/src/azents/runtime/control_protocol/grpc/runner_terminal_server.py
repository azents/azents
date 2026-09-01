"""Authenticated Runtime Runner Terminal gRPC server boundary."""

import asyncio
import contextlib
import dataclasses
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol

import grpc
from azents_runtime_control.grpc_runner_terminal_client import (
    runner_terminal_control_to_message,
    runner_terminal_event_from_message,
    runner_terminal_stream_accepted_to_message,
    runner_terminal_stream_registration_from_message,
)
from azents_runtime_control.proto import (
    runtime_runner_terminal_pb2,
    runtime_runner_terminal_pb2_grpc,
)
from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalEventFrame,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
)

from azents.core.runtime_runner_credential import RuntimeRunnerCredential
from azents.runtime.control_protocol.grpc.auth import (
    RuntimeRunnerCredentialAuthenticator,
    RuntimeRunnerCredentialGrpcAuth,
)

_LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class RuntimeRunnerTerminalAuthority:
    """Exact Runtime and Runner authority presented to Terminal coordination."""

    credential_id: str
    runtime_id: str
    desired_generation: int
    runner_generation: int


class RuntimeRunnerTerminalStream(Protocol):
    """One generation-fenced Terminal stream admitted by coordination."""

    @property
    def accepted(self) -> RunnerTerminalStreamAccepted:
        """Return the accepted resume positions for the current stream."""
        ...

    async def receive(self, frame: RunnerTerminalEventFrame) -> None:
        """Apply one validated Runner event frame."""
        ...

    def control_frames(self) -> AsyncIterator[RunnerTerminalControlFrame]:
        """Yield ordered Control frames until the Terminal stream closes."""
        ...

    async def close(self) -> None:
        """Release the current stream generation without finalizing the Terminal."""
        ...


class RuntimeRunnerTerminalBroker(Protocol):
    """Atomically admit and bridge one Terminal against current coordination."""

    async def connect(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        authority: RuntimeRunnerTerminalAuthority,
        connected_at: datetime,
    ) -> RuntimeRunnerTerminalStream:
        """Verify exact Runtime, Runner, Terminal, nonce, and stream authority."""
        ...


class RuntimeRunnerTerminalAdmissionError(RuntimeError):
    """Bounded coordination rejection safe to project onto gRPC status."""

    def __init__(self, code: RunnerTerminalStreamErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class RejectingRuntimeRunnerTerminalBroker:
    """Phase-one broker that keeps the additive RPC hidden until coordination ships."""

    async def connect(
        self,
        registration: RunnerTerminalStreamRegistration,
        *,
        authority: RuntimeRunnerTerminalAuthority,
        connected_at: datetime,
    ) -> RuntimeRunnerTerminalStream:
        """Reject every stream without allocating Terminal state."""
        del registration, authority, connected_at
        raise RuntimeRunnerTerminalAdmissionError(
            RunnerTerminalStreamErrorCode.STALE_AUTHORITY
        )


class RuntimeRunnerTerminalGrpcServicer(
    runtime_runner_terminal_pb2_grpc.RuntimeRunnerTerminalServicer
):
    """Authenticate one independently pooled Runner stream per Terminal."""

    def __init__(
        self,
        *,
        broker: RuntimeRunnerTerminalBroker,
        runner_authenticator: RuntimeRunnerCredentialAuthenticator,
    ) -> None:
        """Initialize the Terminal stream servicer."""
        self._broker = broker
        self._runner_authenticator = runner_authenticator
        self._auth = RuntimeRunnerCredentialGrpcAuth(runner_authenticator)

    async def ConnectTerminal(
        self,
        request_iterator: AsyncIterator[
            runtime_runner_terminal_pb2.RunnerTerminalMessage
        ],
        context: grpc.aio.ServicerContext[
            runtime_runner_terminal_pb2.RunnerTerminalMessage,
            runtime_runner_terminal_pb2.TerminalControlMessage,
        ],
    ) -> AsyncIterator[runtime_runner_terminal_pb2.TerminalControlMessage]:
        """Authenticate, fence, and bridge one dedicated Terminal stream."""
        credential = await self._auth.authenticate(context)
        first_message = await _first_register_message(request_iterator, context)
        try:
            registration = runner_terminal_stream_registration_from_message(
                first_message.register
            )
        except ValueError:
            await context.abort(
                grpc.StatusCode.INVALID_ARGUMENT,
                "Terminal stream registration is invalid",
            )
            raise AssertionError("unreachable") from None
        if registration.identity.runtime_id != credential.runtime_id:
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                "Terminal Runtime identity does not match its credential",
            )
            raise AssertionError("unreachable")
        if not await self._runner_authenticator.authorize_runner(credential):
            await context.abort(
                grpc.StatusCode.UNAUTHENTICATED,
                "Runner credential is no longer authorized",
            )
            raise AssertionError("unreachable")
        authority = _authority(credential, registration)
        try:
            stream = await self._broker.connect(
                registration,
                authority=authority,
                connected_at=datetime.now(UTC),
            )
        except RuntimeRunnerTerminalAdmissionError as error:
            await context.abort(
                _admission_status(error.code),
                _admission_message(error.code),
            )
            raise AssertionError("unreachable") from None
        _LOGGER.info(
            "Runtime Runner Terminal stream registered",
            extra={
                "terminal_id": registration.identity.terminal_id,
                "runtime_id": registration.identity.runtime_id,
                "desired_generation": credential.desired_generation,
                "runner_generation": registration.identity.runner_generation,
                "stream_generation": registration.stream_generation,
            },
        )
        inbound_task = asyncio.create_task(
            self._consume_runner_frames(
                request_iterator,
                context,
                stream=stream,
                credential=credential,
            ),
            name=f"runner-terminal-inbound:{registration.identity.terminal_id}",
        )
        try:
            yield runner_terminal_stream_accepted_to_message(stream.accepted)
            async for message in _control_messages(stream, inbound_task):
                yield message
        finally:
            inbound_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await inbound_task
            await stream.close()
            _LOGGER.info(
                "Runtime Runner Terminal stream closed",
                extra={
                    "terminal_id": registration.identity.terminal_id,
                    "runtime_id": registration.identity.runtime_id,
                    "desired_generation": credential.desired_generation,
                    "runner_generation": registration.identity.runner_generation,
                    "stream_generation": registration.stream_generation,
                },
            )

    async def _consume_runner_frames(
        self,
        request_iterator: AsyncIterator[
            runtime_runner_terminal_pb2.RunnerTerminalMessage
        ],
        context: grpc.aio.ServicerContext[
            runtime_runner_terminal_pb2.RunnerTerminalMessage,
            runtime_runner_terminal_pb2.TerminalControlMessage,
        ],
        *,
        stream: RuntimeRunnerTerminalStream,
        credential: RuntimeRunnerCredential,
    ) -> None:
        async for message in request_iterator:
            if not await self._runner_authenticator.authorize_runner(credential):
                await context.abort(
                    grpc.StatusCode.UNAUTHENTICATED,
                    "Runner credential is no longer authorized",
                )
                raise AssertionError("unreachable")
            try:
                frame = runner_terminal_event_from_message(message)
            except ValueError:
                await context.abort(
                    grpc.StatusCode.INVALID_ARGUMENT,
                    "Terminal Runner message is invalid",
                )
                raise AssertionError("unreachable") from None
            await stream.receive(frame)


def add_runtime_runner_terminal_servicer(
    server: grpc.aio.Server,
    *,
    broker: RuntimeRunnerTerminalBroker,
    runner_authenticator: RuntimeRunnerCredentialAuthenticator,
) -> None:
    """Add the dedicated Runtime Runner Terminal servicer."""
    runtime_runner_terminal_pb2_grpc.add_RuntimeRunnerTerminalServicer_to_server(
        RuntimeRunnerTerminalGrpcServicer(
            broker=broker,
            runner_authenticator=runner_authenticator,
        ),
        server,
    )


async def _first_register_message(
    request_iterator: AsyncIterator[runtime_runner_terminal_pb2.RunnerTerminalMessage],
    context: grpc.aio.ServicerContext[
        runtime_runner_terminal_pb2.RunnerTerminalMessage,
        runtime_runner_terminal_pb2.TerminalControlMessage,
    ],
) -> runtime_runner_terminal_pb2.RunnerTerminalMessage:
    try:
        first_message = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Terminal stream registration is required",
        )
        raise AssertionError("unreachable") from None
    if first_message.WhichOneof("payload") != "register":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Terminal stream registration is required",
        )
        raise AssertionError("unreachable")
    return first_message


async def _control_messages(
    stream: RuntimeRunnerTerminalStream,
    inbound_task: asyncio.Task[None],
) -> AsyncIterator[runtime_runner_terminal_pb2.TerminalControlMessage]:
    frames = stream.control_frames().__aiter__()
    while True:
        control_task = asyncio.create_task(_next_control_frame(frames))
        done, _pending = await asyncio.wait(
            (control_task, inbound_task),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if inbound_task in done:
            control_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await control_task
            await inbound_task
            return
        try:
            frame = control_task.result()
        except StopAsyncIteration:
            return
        yield runner_terminal_control_to_message(frame)


async def _next_control_frame(
    frames: AsyncIterator[RunnerTerminalControlFrame],
) -> RunnerTerminalControlFrame:
    return await anext(frames)


def _authority(
    credential: RuntimeRunnerCredential,
    registration: RunnerTerminalStreamRegistration,
) -> RuntimeRunnerTerminalAuthority:
    return RuntimeRunnerTerminalAuthority(
        credential_id=credential.credential_id,
        runtime_id=credential.runtime_id,
        desired_generation=credential.desired_generation,
        runner_generation=registration.identity.runner_generation,
    )


def _admission_status(code: RunnerTerminalStreamErrorCode) -> grpc.StatusCode:
    if code is RunnerTerminalStreamErrorCode.STALE_AUTHORITY:
        return grpc.StatusCode.PERMISSION_DENIED
    if code is RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION:
        return grpc.StatusCode.ABORTED
    if code is RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION:
        return grpc.StatusCode.INVALID_ARGUMENT
    if code is RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED:
        return grpc.StatusCode.RESOURCE_EXHAUSTED
    return grpc.StatusCode.FAILED_PRECONDITION


def _admission_message(code: RunnerTerminalStreamErrorCode) -> str:
    return {
        RunnerTerminalStreamErrorCode.STALE_AUTHORITY: (
            "Terminal authority is no longer current"
        ),
        RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION: (
            "Terminal stream generation is no longer current"
        ),
        RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION: (
            "Terminal stream registration violates the protocol"
        ),
        RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED: (
            "Terminal stream capacity is exhausted"
        ),
        RunnerTerminalStreamErrorCode.TERMINATED: "Terminal is already terminated",
    }[code]
