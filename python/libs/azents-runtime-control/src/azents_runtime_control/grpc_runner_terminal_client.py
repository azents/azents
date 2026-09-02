"""Typed authenticated data-stream client for one Runtime Runner Terminal."""

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Sequence
from typing import TYPE_CHECKING, Protocol

import grpc

from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.proto import runtime_runner_terminal_pb2
from azents_runtime_control.runner_terminal import (
    RunnerTerminalControlFrame,
    RunnerTerminalControlFrameHandler,
    RunnerTerminalEventFrame,
    RunnerTerminalExit,
    RunnerTerminalHeartbeat,
    RunnerTerminalHeartbeatAcknowledgement,
    RunnerTerminalIdentity,
    RunnerTerminalInputAcknowledgement,
    RunnerTerminalInputFrame,
    RunnerTerminalOutputAcknowledgement,
    RunnerTerminalOutputFrame,
    RunnerTerminalResize,
    RunnerTerminalStreamAccepted,
    RunnerTerminalStreamError,
    RunnerTerminalStreamErrorCode,
    RunnerTerminalStreamRegistration,
    RunnerTerminalTerminate,
    RunnerTerminalTerminationReason,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_runner_terminal_pb2_grpc import (
        RuntimeRunnerTerminalAsyncStub as _RuntimeRunnerTerminalStub,
    )
else:
    from azents_runtime_control.proto.runtime_runner_terminal_pb2_grpc import (
        RuntimeRunnerTerminalStub as _RuntimeRunnerTerminalStub,
    )

_MAX_OUTBOUND_MESSAGES = 256
_LOCAL_SUBCHANNEL_POOL = (("grpc.use_local_subchannel_pool", 1),)


class RunnerTerminalStream(Protocol):
    """Callable gRPC stream constructor for one independently owned Terminal."""

    def __call__(
        self,
        request_iterator: AsyncIterator[
            runtime_runner_terminal_pb2.RunnerTerminalMessage
        ],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_runner_terminal_pb2.TerminalControlMessage]:
        """Open a bidirectional Runtime Runner Terminal stream."""
        ...


class RuntimeRunnerTerminalStreamClosed(RuntimeError):
    """Terminal gRPC stream closed before Terminal work completed."""


class GrpcRunnerTerminalClient:
    """Own one independently pooled authenticated Terminal data stream."""

    def __init__(
        self,
        stream: RunnerTerminalStream,
        *,
        runner_auth_token: str,
        channel: grpc.aio.Channel | None = None,
    ) -> None:
        """Initialize a client for one Terminal RPC."""
        if not runner_auth_token:
            raise ValueError("Runner authentication token must not be empty")
        self._stream = stream
        self._channel = channel
        self._metadata = (("authorization", f"Bearer {runner_auth_token}"),)
        self._outbound: asyncio.Queue[
            runtime_runner_terminal_pb2.RunnerTerminalMessage | None
        ] = asyncio.Queue(maxsize=_MAX_OUTBOUND_MESSAGES)
        self._control_handler: RunnerTerminalControlFrameHandler | None = None
        self._accepted: asyncio.Future[RunnerTerminalStreamAccepted] | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._finished = False

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        runner_auth_token: str,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRunnerTerminalClient":
        """Create a separately pooled authenticated Terminal data channel."""
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
            options=_LOCAL_SUBCHANNEL_POOL,
        )
        return cls(
            _RuntimeRunnerTerminalStub(channel).ConnectTerminal,
            runner_auth_token=runner_auth_token,
            channel=channel,
        )

    def set_control_handler(self, handler: RunnerTerminalControlFrameHandler) -> None:
        """Set the handler for ordered Control-to-Runner Terminal frames."""
        self._control_handler = handler

    async def start(
        self,
        registration: RunnerTerminalStreamRegistration,
    ) -> RunnerTerminalStreamAccepted:
        """Open the stream, register exact resume evidence, and await acceptance."""
        if self._accepted is not None:
            raise RuntimeError("Terminal stream is already registered")
        self._accepted = asyncio.get_running_loop().create_future()
        responses = self._stream(
            self._outbound_messages(_registration_message(registration)),
            metadata=self._metadata,
        )
        self._receiver_task = asyncio.create_task(self._receive(responses))
        return await self._accepted

    async def send(self, frame: RunnerTerminalEventFrame) -> None:
        """Send one bounded Runner-to-Control Terminal frame."""
        if self._finished:
            raise RuntimeError("Terminal stream is already finished")
        if self._receiver_task is not None and self._receiver_task.done():
            raise RuntimeRunnerTerminalStreamClosed("Terminal stream is closed")
        await self._outbound.put(runner_terminal_event_to_message(frame))

    async def finish(self, frame: RunnerTerminalEventFrame) -> None:
        """Flush one final Runner event and finish the request stream."""
        if self._finished:
            raise RuntimeError("Terminal stream is already finished")
        if self._receiver_task is None:
            raise RuntimeError("Terminal stream is not registered")
        if self._receiver_task.done():
            await self._receiver_task
            raise RuntimeRunnerTerminalStreamClosed("Terminal stream is closed")
        self._finished = True
        await self._outbound.put(runner_terminal_event_to_message(frame))
        await self._outbound.join()
        await self._outbound.put(None)
        await self._receiver_task

    async def close(self) -> None:
        """Close the Terminal stream and its independently pooled channel."""
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeRunnerTerminalStreamClosed,
                grpc.aio.AioRpcError,
            ):
                await self._receiver_task
            self._receiver_task = None
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def _outbound_messages(
        self,
        registration: runtime_runner_terminal_pb2.RunnerTerminalMessage,
    ) -> AsyncIterator[runtime_runner_terminal_pb2.RunnerTerminalMessage]:
        yield registration
        while True:
            message = await self._outbound.get()
            if message is None:
                self._outbound.task_done()
                return
            try:
                yield message
            finally:
                self._outbound.task_done()

    async def _receive(
        self,
        responses: AsyncIterable[runtime_runner_terminal_pb2.TerminalControlMessage],
    ) -> None:
        try:
            async for message in responses:
                await self._handle_control_message(message)
            self._fail_pending(RuntimeRunnerTerminalStreamClosed("stream closed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
            raise

    async def _handle_control_message(
        self,
        message: runtime_runner_terminal_pb2.TerminalControlMessage,
    ) -> None:
        payload = message.WhichOneof("payload")
        if payload == "accepted":
            accepted = runner_terminal_stream_accepted_from_message(message.accepted)
            if self._accepted is not None and not self._accepted.done():
                self._accepted.set_result(accepted)
            return
        handler = self._control_handler
        if handler is None:
            raise RuntimeRunnerTerminalStreamClosed(
                "Terminal control handler is not registered"
            )
        await handler(_control_frame_from_message(message, payload))

    def _fail_pending(self, exc: Exception) -> None:
        if self._accepted is not None and not self._accepted.done():
            self._accepted.set_exception(exc)


def runner_terminal_stream_registration_from_message(
    message: runtime_runner_terminal_pb2.TerminalStreamRegistration,
) -> RunnerTerminalStreamRegistration:
    """Deserialize exact Runner Terminal stream registration evidence."""
    return RunnerTerminalStreamRegistration(
        identity=_identity_from_message(message.identity),
        stream_generation=message.stream_generation,
        stream_nonce=message.stream_nonce,
        last_control_acknowledged_output_sequence=(
            message.last_control_acknowledged_output_sequence
        ),
        highest_completely_applied_input_sequence=(
            message.highest_completely_applied_input_sequence
        ),
        partial_input_sequence=(
            message.partial_input_sequence
            if message.HasField("partial_input_sequence")
            else None
        ),
        partial_input_bytes_written=(
            message.partial_input_bytes_written
            if message.HasField("partial_input_bytes_written")
            else None
        ),
    )


def runner_terminal_stream_accepted_from_message(
    message: runtime_runner_terminal_pb2.TerminalStreamAccepted,
) -> RunnerTerminalStreamAccepted:
    """Deserialize Terminal stream acceptance and resume position."""
    return RunnerTerminalStreamAccepted(
        stream_generation=message.stream_generation,
        resume_from_output_sequence=message.resume_from_output_sequence,
        next_input_sequence=message.next_input_sequence,
    )


def runner_terminal_stream_accepted_to_message(
    accepted: RunnerTerminalStreamAccepted,
) -> runtime_runner_terminal_pb2.TerminalControlMessage:
    """Serialize exact Terminal data-stream acceptance and resume evidence."""
    return runtime_runner_terminal_pb2.TerminalControlMessage(
        accepted=runtime_runner_terminal_pb2.TerminalStreamAccepted(
            stream_generation=accepted.stream_generation,
            resume_from_output_sequence=accepted.resume_from_output_sequence,
            next_input_sequence=accepted.next_input_sequence,
        )
    )


def runner_terminal_event_from_message(
    message: runtime_runner_terminal_pb2.RunnerTerminalMessage,
) -> RunnerTerminalEventFrame:
    """Deserialize one non-registration Runner Terminal event frame."""
    payload = message.WhichOneof("payload")
    if payload == "output":
        return RunnerTerminalOutputFrame(
            sequence=message.output.sequence,
            data=bytes(message.output.data),
        )
    if payload == "input_ack":
        return RunnerTerminalInputAcknowledgement(sequence=message.input_ack.sequence)
    if payload == "heartbeat":
        return RunnerTerminalHeartbeat(
            monotonic_sequence=message.heartbeat.monotonic_sequence
        )
    if payload == "exit":
        return RunnerTerminalExit(
            reason=_termination_reason_from_message(message.exit.reason),
            exit_code=(
                message.exit.exit_code if message.exit.HasField("exit_code") else None
            ),
        )
    if payload == "error":
        return RunnerTerminalStreamError(
            code=_stream_error_code_from_message(message.error.code)
        )
    raise ValueError("Runner Terminal event payload is invalid")


def runner_terminal_event_to_message(
    frame: RunnerTerminalEventFrame,
) -> runtime_runner_terminal_pb2.RunnerTerminalMessage:
    """Serialize one bounded Runner-to-Control Terminal event frame."""
    return _event_message(frame)


def runner_terminal_control_to_message(
    frame: RunnerTerminalControlFrame,
) -> runtime_runner_terminal_pb2.TerminalControlMessage:
    """Serialize one ordered Control-to-Runner Terminal frame."""
    match frame:
        case RunnerTerminalInputFrame(sequence=sequence, data=data):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                input=runtime_runner_terminal_pb2.TerminalInputFrame(
                    sequence=sequence,
                    data=data,
                )
            )
        case RunnerTerminalResize(
            sequence=sequence,
            columns=columns,
            rows=rows,
        ):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                resize=runtime_runner_terminal_pb2.TerminalResize(
                    sequence=sequence,
                    columns=columns,
                    rows=rows,
                )
            )
        case RunnerTerminalOutputAcknowledgement(sequence=sequence):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                output_ack=runtime_runner_terminal_pb2.TerminalOutputAcknowledgement(
                    sequence=sequence
                )
            )
        case RunnerTerminalTerminate(reason=reason):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                terminate=runtime_runner_terminal_pb2.TerminalTerminate(
                    reason=_termination_reason_to_message(reason)
                )
            )
        case RunnerTerminalHeartbeatAcknowledgement(
            monotonic_sequence=monotonic_sequence
        ):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                heartbeat_ack=(
                    runtime_runner_terminal_pb2.TerminalHeartbeatAcknowledgement(
                        monotonic_sequence=monotonic_sequence
                    )
                )
            )
        case RunnerTerminalStreamError(code=code):
            return runtime_runner_terminal_pb2.TerminalControlMessage(
                error=runtime_runner_terminal_pb2.TerminalStreamError(
                    code=_stream_error_code_to_message(code)
                )
            )


def _registration_message(
    registration: RunnerTerminalStreamRegistration,
) -> runtime_runner_terminal_pb2.RunnerTerminalMessage:
    message = runtime_runner_terminal_pb2.RunnerTerminalMessage(
        register=runtime_runner_terminal_pb2.TerminalStreamRegistration(
            identity=_identity_message(registration.identity),
            stream_generation=registration.stream_generation,
            stream_nonce=registration.stream_nonce,
            last_control_acknowledged_output_sequence=(
                registration.last_control_acknowledged_output_sequence
            ),
            highest_completely_applied_input_sequence=(
                registration.highest_completely_applied_input_sequence
            ),
        )
    )
    if registration.partial_input_sequence is not None:
        message.register.partial_input_sequence = registration.partial_input_sequence
    if registration.partial_input_bytes_written is not None:
        message.register.partial_input_bytes_written = (
            registration.partial_input_bytes_written
        )
    return message


def _event_message(
    frame: RunnerTerminalEventFrame,
) -> runtime_runner_terminal_pb2.RunnerTerminalMessage:
    match frame:
        case RunnerTerminalOutputFrame(sequence=sequence, data=data):
            return runtime_runner_terminal_pb2.RunnerTerminalMessage(
                output=runtime_runner_terminal_pb2.TerminalOutputFrame(
                    sequence=sequence,
                    data=data,
                )
            )
        case RunnerTerminalInputAcknowledgement(sequence=sequence):
            return runtime_runner_terminal_pb2.RunnerTerminalMessage(
                input_ack=runtime_runner_terminal_pb2.TerminalInputAcknowledgement(
                    sequence=sequence
                )
            )
        case RunnerTerminalHeartbeat(monotonic_sequence=monotonic_sequence):
            return runtime_runner_terminal_pb2.RunnerTerminalMessage(
                heartbeat=runtime_runner_terminal_pb2.TerminalHeartbeat(
                    monotonic_sequence=monotonic_sequence
                )
            )
        case RunnerTerminalExit(reason=reason, exit_code=exit_code):
            exit_message = runtime_runner_terminal_pb2.TerminalExit(
                reason=_termination_reason_to_message(reason)
            )
            if exit_code is not None:
                exit_message.exit_code = exit_code
            return runtime_runner_terminal_pb2.RunnerTerminalMessage(exit=exit_message)
        case RunnerTerminalStreamError(code=code):
            return runtime_runner_terminal_pb2.RunnerTerminalMessage(
                error=runtime_runner_terminal_pb2.TerminalStreamError(
                    code=_stream_error_code_to_message(code)
                )
            )


def _control_frame_from_message(
    message: runtime_runner_terminal_pb2.TerminalControlMessage,
    payload: str | None,
) -> RunnerTerminalControlFrame:
    if payload == "input":
        return RunnerTerminalInputFrame(
            sequence=message.input.sequence,
            data=bytes(message.input.data),
        )
    if payload == "resize":
        return RunnerTerminalResize(
            sequence=message.resize.sequence,
            columns=message.resize.columns,
            rows=message.resize.rows,
        )
    if payload == "output_ack":
        return RunnerTerminalOutputAcknowledgement(sequence=message.output_ack.sequence)
    if payload == "terminate":
        return RunnerTerminalTerminate(
            reason=_termination_reason_from_message(message.terminate.reason)
        )
    if payload == "heartbeat_ack":
        return RunnerTerminalHeartbeatAcknowledgement(
            monotonic_sequence=message.heartbeat_ack.monotonic_sequence
        )
    if payload == "error":
        return RunnerTerminalStreamError(
            code=_stream_error_code_from_message(message.error.code)
        )
    raise ValueError("Terminal Control message payload is invalid")


def _identity_message(
    identity: RunnerTerminalIdentity,
) -> runtime_runner_terminal_pb2.TerminalIdentity:
    return runtime_runner_terminal_pb2.TerminalIdentity(
        terminal_id=identity.terminal_id,
        runtime_id=identity.runtime_id,
        runner_generation=identity.runner_generation,
    )


def _identity_from_message(
    message: runtime_runner_terminal_pb2.TerminalIdentity,
) -> RunnerTerminalIdentity:
    return RunnerTerminalIdentity(
        terminal_id=message.terminal_id,
        runtime_id=message.runtime_id,
        runner_generation=message.runner_generation,
    )


def _termination_reason_to_message(
    reason: RunnerTerminalTerminationReason,
) -> runtime_runner_terminal_pb2.TerminalTerminationReason.ValueType:
    return {
        RunnerTerminalTerminationReason.CALLER: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_CALLER
        ),
        RunnerTerminalTerminationReason.IDLE: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_IDLE
        ),
        RunnerTerminalTerminationReason.MAXIMUM_LIFETIME: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_MAXIMUM_LIFETIME
        ),
        RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_DATA_STREAM_GRACE_EXPIRED
        ),
        RunnerTerminalTerminationReason.RUNTIME_INVALIDATED: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_RUNTIME_INVALIDATED
        ),
        RunnerTerminalTerminationReason.RUNNER_REPLACED: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_RUNNER_REPLACED
        ),
        RunnerTerminalTerminationReason.POLICY_REVOKED: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_POLICY_REVOKED
        ),
        RunnerTerminalTerminationReason.ACCESS_REVOKED: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_ACCESS_REVOKED
        ),
        RunnerTerminalTerminationReason.SHUTDOWN: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_SHUTDOWN
        ),
        RunnerTerminalTerminationReason.PROTOCOL_VIOLATION: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_PROTOCOL_VIOLATION
        ),
        RunnerTerminalTerminationReason.PROCESS_EXIT: (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_PROCESS_EXIT
        ),
    }[reason]


def _termination_reason_from_message(
    value: runtime_runner_terminal_pb2.TerminalTerminationReason.ValueType,
) -> RunnerTerminalTerminationReason:
    reasons = {
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_CALLER: (
            RunnerTerminalTerminationReason.CALLER
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_IDLE: (
            RunnerTerminalTerminationReason.IDLE
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_MAXIMUM_LIFETIME: (
            RunnerTerminalTerminationReason.MAXIMUM_LIFETIME
        ),
        (
            runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_DATA_STREAM_GRACE_EXPIRED
        ): (RunnerTerminalTerminationReason.DATA_STREAM_GRACE_EXPIRED),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_RUNTIME_INVALIDATED: (
            RunnerTerminalTerminationReason.RUNTIME_INVALIDATED
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_RUNNER_REPLACED: (
            RunnerTerminalTerminationReason.RUNNER_REPLACED
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_POLICY_REVOKED: (
            RunnerTerminalTerminationReason.POLICY_REVOKED
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_ACCESS_REVOKED: (
            RunnerTerminalTerminationReason.ACCESS_REVOKED
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_SHUTDOWN: (
            RunnerTerminalTerminationReason.SHUTDOWN
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_PROTOCOL_VIOLATION: (
            RunnerTerminalTerminationReason.PROTOCOL_VIOLATION
        ),
        runtime_runner_terminal_pb2.TERMINAL_TERMINATION_REASON_PROCESS_EXIT: (
            RunnerTerminalTerminationReason.PROCESS_EXIT
        ),
    }
    try:
        return reasons[value]
    except KeyError as error:
        raise ValueError("Terminal termination reason is invalid") from error


def _stream_error_code_to_message(
    code: RunnerTerminalStreamErrorCode,
) -> runtime_runner_terminal_pb2.TerminalStreamErrorCode.ValueType:
    return {
        RunnerTerminalStreamErrorCode.STALE_AUTHORITY: (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_STALE_AUTHORITY
        ),
        RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION: (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_STALE_STREAM_GENERATION
        ),
        RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION: (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_PROTOCOL_VIOLATION
        ),
        RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED: (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_RESOURCE_EXHAUSTED
        ),
        RunnerTerminalStreamErrorCode.TERMINATED: (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_TERMINATED
        ),
    }[code]


def _stream_error_code_from_message(
    value: runtime_runner_terminal_pb2.TerminalStreamErrorCode.ValueType,
) -> RunnerTerminalStreamErrorCode:
    codes = {
        runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_STALE_AUTHORITY: (
            RunnerTerminalStreamErrorCode.STALE_AUTHORITY
        ),
        (
            runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_STALE_STREAM_GENERATION
        ): (RunnerTerminalStreamErrorCode.STALE_STREAM_GENERATION),
        runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_PROTOCOL_VIOLATION: (
            RunnerTerminalStreamErrorCode.PROTOCOL_VIOLATION
        ),
        runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_RESOURCE_EXHAUSTED: (
            RunnerTerminalStreamErrorCode.RESOURCE_EXHAUSTED
        ),
        runtime_runner_terminal_pb2.TERMINAL_STREAM_ERROR_CODE_TERMINATED: (
            RunnerTerminalStreamErrorCode.TERMINATED
        ),
    }
    try:
        return codes[value]
    except KeyError as error:
        raise ValueError("Terminal stream error code is invalid") from error


__all__ = [
    "GrpcRunnerTerminalClient",
    "RunnerTerminalStream",
    "RuntimeRunnerTerminalStreamClosed",
    "runner_terminal_control_to_message",
    "runner_terminal_event_from_message",
    "runner_terminal_event_to_message",
    "runner_terminal_stream_accepted_from_message",
    "runner_terminal_stream_accepted_to_message",
    "runner_terminal_stream_registration_from_message",
]
