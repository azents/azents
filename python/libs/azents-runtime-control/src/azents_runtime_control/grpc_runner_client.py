"""gRPC Runner Control client for Runtime Runner processes."""

import asyncio
import contextlib
from collections.abc import AsyncIterable, AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import grpc
from google.protobuf import timestamp_pb2

from azents_runtime_control.grpc_runner_stream_session_client import (
    GrpcRunnerStreamSessionClient,
    RunnerStreamEnvelopeResources,
)
from azents_runtime_control.grpc_tls import (
    GrpcClientTlsConfig,
    create_grpc_aio_channel,
)
from azents_runtime_control.proto import (
    runtime_configuration_pb2,
    runtime_runner_control_pb2,
    runtime_runner_terminal_pb2,
    runtime_runner_transfer_pb2,
    runtime_stream_session_pb2,
)
from azents_runtime_control.runner import (
    JsonValue,
    RunnerBodyChunk,
    RunnerControlClient,
    RunnerHeartbeatAcknowledgement,
    RunnerOperationCancel,
    RunnerOperationCancelHandler,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerOperationHandler,
    RunnerRegistration,
    RunnerRegistrationAccepted,
    RunnerStateReport,
    RunnerTransferCancelHandler,
    RunnerTransferIntentHandler,
    RuntimeRunnerEventType,
    RuntimeRunnerState,
)
from azents_runtime_control.runner_terminal import (
    RunnerTerminalIdentity,
    RunnerTerminalOpenIntent,
    RunnerTerminalOpenIntentHandler,
    RunnerTerminalTerminateIntent,
    RunnerTerminalTerminateIntentHandler,
    RunnerTerminalTerminationReason,
)
from azents_runtime_control.runner_transfer import (
    RunnerTransferCancel,
    RunnerTransferCancelReason,
    RunnerTransferDestinationConflictEvidence,
    RunnerTransferDirection,
    RunnerTransferFailure,
    RunnerTransferIdentity,
    RunnerTransferIntent,
    RunnerTransferOutcome,
    RunnerTransferResult,
    RunnerTransferSourceTransport,
)
from azents_runtime_control.runtime_configuration import (
    RuntimeConfigurationEvidence,
    parse_configuration_sequence,
    serialize_configuration_sequence,
)
from azents_runtime_control.runtime_stream_session import (
    CloseReason,
    OwnerSessionEpoch,
    RunnerSessionOffer,
    RunnerSessionOfferHandler,
    StreamDirection,
    StreamProtocol,
)
from azents_runtime_control.system_metrics import (
    RunnerRuntimeWebMetrics,
    RunnerRuntimeWebProtocolCount,
    RunnerRuntimeWebReasonCount,
    RunnerRuntimeWebTrafficCount,
    RunnerSystemMetricAvailability,
    RunnerSystemMetricObservation,
    RunnerSystemMetricsReport,
    RunnerSystemMetricsScope,
)

if TYPE_CHECKING:
    from azents_runtime_control.proto.runtime_runner_control_pb2_grpc import (
        RuntimeRunnerControlAsyncStub as _RuntimeRunnerControlStub,
    )
    from azents_runtime_control.proto.runtime_stream_session_pb2_grpc import (
        RuntimeRunnerStreamSessionAsyncStub as _RuntimeRunnerStreamSessionStub,
    )
else:
    from azents_runtime_control.proto.runtime_runner_control_pb2_grpc import (
        RuntimeRunnerControlStub as _RuntimeRunnerControlStub,
    )
    from azents_runtime_control.proto.runtime_stream_session_pb2_grpc import (
        RuntimeRunnerStreamSessionStub as _RuntimeRunnerStreamSessionStub,
    )


class RunnerControlStream(Protocol):
    """Callable gRPC stream constructor."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterable[runtime_runner_control_pb2.RunnerControlMessage]:
        """Open a bidirectional Runtime Control stream."""
        ...


class RuntimeRunnerControlStreamClosed(RuntimeError):
    """Runner Control gRPC stream closed before the requested operation finished."""


_MAX_OUTBOUND_MESSAGES = 256


class GrpcRunnerControlClient(RunnerControlClient):
    """RunnerControlClient implementation backed by a bidirectional gRPC stream."""

    def __init__(
        self,
        stream: RunnerControlStream,
        *,
        runner_auth_token: str,
        channel: grpc.aio.Channel | None = None,
        heartbeat_ack_timeout_seconds: float = 10.0,
    ) -> None:
        """Initialize the gRPC client with a stream callable."""
        self._stream = stream
        self._channel = channel
        self._runner_auth_token = runner_auth_token
        self._heartbeat_ack_timeout_seconds = heartbeat_ack_timeout_seconds
        self._metadata = _auth_metadata(runner_auth_token)
        self._outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerMessage] = (
            asyncio.Queue(maxsize=_MAX_OUTBOUND_MESSAGES)
        )
        self._operation_handler: RunnerOperationHandler | None = None
        self._operation_cancel_handler: RunnerOperationCancelHandler | None = None
        self._transfer_intent_handler: RunnerTransferIntentHandler | None = None
        self._transfer_cancel_handler: RunnerTransferCancelHandler | None = None
        self._terminal_open_intent_handler: RunnerTerminalOpenIntentHandler | None = (
            None
        )
        self._terminal_terminate_intent_handler: (
            RunnerTerminalTerminateIntentHandler | None
        ) = None
        self._stream_session_offer_handler: RunnerSessionOfferHandler | None = None
        self._pending_heartbeat_acks: dict[
            str, asyncio.Future[RunnerHeartbeatAcknowledgement]
        ] = {}
        self._pending_operation_start_acks: dict[str, asyncio.Future[bool]] = {}
        self._accepted: asyncio.Future[RunnerRegistrationAccepted] | None = None
        self._receiver_task: asyncio.Task[None] | None = None
        self._connection_id: str | None = None
        self._heartbeat_sequence = 0

    @classmethod
    def from_endpoint(
        cls,
        endpoint: str,
        *,
        runner_auth_token: str,
        heartbeat_ack_timeout_seconds: float = 10.0,
        tls: GrpcClientTlsConfig | None,
        allow_insecure: bool,
    ) -> "GrpcRunnerControlClient":
        """Create a client using authenticated TLS or explicit insecure mode."""
        channel = create_grpc_aio_channel(
            endpoint,
            tls=tls,
            allow_insecure=allow_insecure,
            options=(("grpc.use_local_subchannel_pool", 1),),
        )
        stub = _RuntimeRunnerControlStub(channel)
        return cls(
            stub.ConnectRunner,
            channel=channel,
            heartbeat_ack_timeout_seconds=heartbeat_ack_timeout_seconds,
            runner_auth_token=runner_auth_token,
        )

    def set_operation_handler(self, handler: RunnerOperationHandler) -> None:
        """Set the direct operation admission handler."""
        self._operation_handler = handler

    def set_operation_cancel_handler(
        self,
        handler: RunnerOperationCancelHandler,
    ) -> None:
        """Set the direct operation cancellation handler."""
        self._operation_cancel_handler = handler

    def set_transfer_intent_handler(
        self,
        handler: RunnerTransferIntentHandler,
    ) -> None:
        """Set the direct metadata-only transfer admission handler."""
        self._transfer_intent_handler = handler

    def set_transfer_cancel_handler(
        self,
        handler: RunnerTransferCancelHandler,
    ) -> None:
        """Set the direct metadata-only transfer cancellation handler."""
        self._transfer_cancel_handler = handler

    def set_terminal_open_intent_handler(
        self,
        handler: RunnerTerminalOpenIntentHandler,
    ) -> None:
        """Set the direct metadata-only Terminal admission handler."""
        self._terminal_open_intent_handler = handler

    def set_terminal_terminate_intent_handler(
        self,
        handler: RunnerTerminalTerminateIntentHandler,
    ) -> None:
        """Set the direct metadata-only Terminal termination handler."""
        self._terminal_terminate_intent_handler = handler

    def set_stream_session_offer_handler(
        self,
        handler: RunnerSessionOfferHandler,
    ) -> None:
        """Set the exact replacement Runtime Web session offer handler."""
        self._stream_session_offer_handler = handler

    def create_stream_session_client(
        self,
        *,
        outbound_resources: RunnerStreamEnvelopeResources | None,
    ) -> GrpcRunnerStreamSessionClient:
        """Create one Runner Web RPC client borrowing this Control channel."""
        if self._channel is None:
            raise RuntimeError("Runner Control client does not own a gRPC channel")
        return GrpcRunnerStreamSessionClient(
            _RuntimeRunnerStreamSessionStub(self._channel).Connect,
            runner_auth_token=self._runner_auth_token,
            channel=None,
            outbound_resources=outbound_resources,
        )

    async def register_runner(
        self,
        registration: RunnerRegistration,
        *,
        connection_id: str,
        registered_at: datetime,
    ) -> RunnerRegistrationAccepted:
        """Open the stream, send Runner registration, and wait for acceptance."""
        del registered_at
        if self._accepted is not None:
            raise RuntimeError("Runner Control stream is already registered")
        self._connection_id = connection_id
        self._accepted = asyncio.get_running_loop().create_future()
        outbound = self._outbound_messages(
            _register_message(
                registration,
                connection_id=connection_id,
                request_id="register",
            )
        )
        responses = self._stream(outbound, metadata=self._metadata)
        self._receiver_task = asyncio.create_task(self._receive(responses))
        return await self._accepted

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> RunnerHeartbeatAcknowledgement:
        """Send a heartbeat and wait for optional configuration evidence."""
        del runtime_id, heartbeat_at
        self._heartbeat_sequence += 1
        request_id = f"heartbeat:{self._heartbeat_sequence}"
        future = asyncio.get_running_loop().create_future()
        self._pending_heartbeat_acks[request_id] = future
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=request_id,
                generation=generation,
                heartbeat=runtime_runner_control_pb2.RunnerHeartbeat(
                    monotonic_sequence=self._heartbeat_sequence,
                ),
            )
        )
        try:
            return await asyncio.wait_for(
                future,
                timeout=self._heartbeat_ack_timeout_seconds,
            )
        finally:
            self._pending_heartbeat_acks.pop(request_id, None)

    async def report_runner_state(self, report: RunnerStateReport) -> None:
        """Publish one Runner state report."""
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=f"state:{report.runtime_id}:{report.runner_generation}",
                generation=report.runner_generation,
                state_report=_state_report_message(report),
            )
        )

    async def report_runner_system_metrics(
        self,
        report: RunnerSystemMetricsReport,
        *,
        generation: int,
    ) -> None:
        """Publish one informational system-metrics report."""
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=f"system-metrics:{report.sequence}",
                generation=generation,
                system_metrics=runner_system_metrics_to_message(report),
            )
        )

    async def claim_next_runner_operation(
        self,
        *,
        runtime_id: str,
        generation: int,
        consumer_id: str,
        block_ms: int,
    ) -> RunnerOperationEnvelope | None:
        """Return no operation because stream delivery uses direct admission."""
        del runtime_id, generation, consumer_id, block_ms
        return None

    async def start_runner_operation(
        self,
        operation: RunnerOperationEnvelope,
    ) -> bool:
        """Authorize a pending operation immediately before execution."""
        request_id = f"start:{operation.request_id}"
        future = asyncio.get_running_loop().create_future()
        self._pending_operation_start_acks[request_id] = future
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=request_id,
                generation=operation.runner_generation,
                operation_start=runtime_runner_control_pb2.RunnerOperationStart(
                    runtime_id=operation.runtime_id,
                    operation_id=f"operation:{operation.request_id}",
                ),
            )
        )
        try:
            return await future
        finally:
            self._pending_operation_start_acks.pop(request_id, None)

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        """Append one Runner operation event."""
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=event.request_id,
                generation=event.generation,
                operation_event=_event_message(event),
            )
        )

    async def append_runner_transfer_result(
        self,
        result: RunnerTransferResult,
    ) -> None:
        """Append one bounded metadata-only transfer result."""
        await self._send(
            runtime_runner_control_pb2.RunnerMessage(
                connection_id=self._require_connection_id(),
                request_id=f"transfer:{result.dispatch_id}",
                generation=result.identity.runner_generation,
                transfer_result=_transfer_result_message(result),
            )
        )

    async def close(self) -> None:
        """Close receiver task resources."""
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            with contextlib.suppress(
                asyncio.CancelledError,
                RuntimeRunnerControlStreamClosed,
                grpc.aio.AioRpcError,
            ):
                await self._receiver_task
            self._receiver_task = None
        if self._channel is not None:
            await self._channel.close()
            self._channel = None

    async def _send(self, message: runtime_runner_control_pb2.RunnerMessage) -> None:
        if self._receiver_task is not None and self._receiver_task.done():
            raise RuntimeRunnerControlStreamClosed("Runner Control stream is closed")
        await self._outbound.put(message)

    async def _outbound_messages(
        self,
        register: runtime_runner_control_pb2.RunnerMessage,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerMessage]:
        yield register
        while True:
            yield await self._outbound.get()

    async def _receive(
        self,
        responses: AsyncIterable[runtime_runner_control_pb2.RunnerControlMessage],
    ) -> None:
        try:
            async for message in responses:
                await self._handle_control_message(message)
            self._fail_pending(RuntimeRunnerControlStreamClosed("stream closed"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._fail_pending(exc)
            raise

    async def _handle_control_message(
        self,
        message: runtime_runner_control_pb2.RunnerControlMessage,
    ) -> None:
        payload = message.WhichOneof("payload")
        if payload == "register_accepted":
            accepted = _accepted(message.register_accepted)
            if self._accepted is not None and not self._accepted.done():
                self._accepted.set_result(accepted)
            return
        if payload == "heartbeat_ack":
            future = self._pending_heartbeat_acks.get(message.request_id)
            if future is not None and not future.done():
                future.set_result(
                    RunnerHeartbeatAcknowledgement(
                        accepted=True,
                        runtime_configuration=(
                            _runtime_configuration_evidence(
                                message.heartbeat_ack.runtime_configuration
                            )
                            if message.heartbeat_ack.HasField("runtime_configuration")
                            else None
                        ),
                    )
                )
            return
        if payload == "operation_start_ack":
            future = self._pending_operation_start_acks.get(message.request_id)
            if future is not None and not future.done():
                future.set_result(message.operation_start_ack.allowed)
            return
        if payload == "operation_request":
            if self._operation_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner operation handler is not registered"
                )
            await self._operation_handler(_operation(message))
            return
        if payload == "operation_cancel":
            if self._operation_cancel_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner operation cancellation handler is not registered"
                )
            await self._operation_cancel_handler(
                RunnerOperationCancel(
                    runtime_id=message.operation_cancel.runtime_id,
                    operation_id=message.operation_cancel.operation_id,
                )
            )
            return
        if payload == "transfer_intent":
            if self._transfer_intent_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner transfer intent handler is not registered"
                )
            await self._transfer_intent_handler(
                runner_transfer_intent_from_message(message.transfer_intent)
            )
            return
        if payload == "transfer_cancel":
            if self._transfer_cancel_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner transfer cancellation handler is not registered"
                )
            await self._transfer_cancel_handler(
                runner_transfer_cancel_from_message(message.transfer_cancel)
            )
            return
        if payload == "terminal_open_intent":
            if self._terminal_open_intent_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner Terminal admission handler is not registered"
                )
            await self._terminal_open_intent_handler(
                runner_terminal_open_intent_from_message(message.terminal_open_intent)
            )
            return
        if payload == "terminal_terminate_intent":
            if self._terminal_terminate_intent_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner Terminal termination handler is not registered"
                )
            await self._terminal_terminate_intent_handler(
                runner_terminal_terminate_intent_from_message(
                    message.terminal_terminate_intent
                )
            )
            return
        if payload == "stream_session_offer":
            if self._stream_session_offer_handler is None:
                raise RuntimeRunnerControlStreamClosed(
                    "Runner Web session offer handler is not registered"
                )
            await self._stream_session_offer_handler(
                runner_session_offer_from_message(message.stream_session_offer)
            )
            return
        if payload == "error":
            raise RuntimeRunnerControlStreamClosed(message.error.message)

    def _fail_pending(self, exc: Exception) -> None:
        if self._accepted is not None and not self._accepted.done():
            self._accepted.set_exception(exc)
        for future in (
            *self._pending_heartbeat_acks.values(),
            *self._pending_operation_start_acks.values(),
        ):
            if not future.done():
                future.set_exception(exc)

    def _require_connection_id(self) -> str:
        if self._connection_id is None:
            raise RuntimeError("Runner Control stream is not registered")
        return self._connection_id


def _auth_metadata(token: str) -> tuple[tuple[str, str], ...]:
    if not token:
        raise ValueError("Runner authentication token must not be empty")
    return (("authorization", f"Bearer {token}"),)


def _register_message(
    registration: RunnerRegistration,
    *,
    connection_id: str,
    request_id: str,
) -> runtime_runner_control_pb2.RunnerMessage:
    message = runtime_runner_control_pb2.RunnerMessage(
        connection_id=connection_id,
        request_id=request_id,
        register=runtime_runner_control_pb2.RunnerRegister(
            runtime_id=registration.runtime_id,
            runner_id=registration.runner_id,
            protocol_version=registration.protocol_version,
            capabilities=list(registration.capabilities),
            health=registration.health,
            metadata=_str_map(registration.metadata),
            auth_credential_id=registration.auth_credential_id,
            workspace_path=registration.workspace_path,
        ),
    )
    message.register.runtime_configuration.CopyFrom(
        _runtime_configuration_evidence_message(registration.runtime_configuration)
    )
    return message


def _accepted(
    message: runtime_runner_control_pb2.RunnerRegisterAccepted,
) -> RunnerRegistrationAccepted:
    return RunnerRegistrationAccepted(
        runtime_id=message.runtime_id,
        runner_id=message.runner_id,
        connection_id=message.connection_id,
        generation=message.generation,
        heartbeat_interval_seconds=message.heartbeat_interval_seconds,
    )


def _state_report_message(
    report: RunnerStateReport,
) -> runtime_runner_control_pb2.RunnerStateReport:
    message = runtime_runner_control_pb2.RunnerStateReport(
        runtime_id=report.runtime_id,
        runner_id=report.runner_id,
        runner_generation=report.runner_generation,
        runner_state=report.runner_state.value,
        capabilities=list(report.capabilities),
        active_operation_ids=list(report.active_operation_ids),
        health=report.health,
        diagnostic=_str_map(report.diagnostic),
        workspace_path=report.workspace_path,
        reported_at=_timestamp(report.reported_at),
    )
    message.runtime_configuration.CopyFrom(
        _runtime_configuration_evidence_message(report.runtime_configuration)
    )
    return message


def _operation(
    message: runtime_runner_control_pb2.RunnerControlMessage,
) -> RunnerOperationEnvelope:
    operation = message.operation_request
    return RunnerOperationEnvelope(
        request_id=message.request_id,
        runtime_id=operation.runtime_id,
        runner_generation=operation.runner_generation,
        operation_type=operation.operation_type,
        owner_session_id=(
            operation.owner_session_id
            if operation.HasField("owner_session_id")
            else None
        ),
        payload=_operation_payload(operation),
        reply_stream_id=operation.reply_stream_id,
        body_stream_id=operation.body_stream_id or None,
        body_chunks=tuple(
            RunnerBodyChunk(
                chunk_id=chunk.chunk_id,
                data=chunk.data,
                final=chunk.final,
            )
            for chunk in operation.body_chunks
        ),
        deadline_at=_optional_datetime(operation),
    )


def _event_message(
    event: RunnerOperationEvent,
) -> runtime_runner_control_pb2.RunnerOperationEvent:
    message = runtime_runner_control_pb2.RunnerOperationEvent(
        runtime_id=event.runtime_id,
        operation_id=f"operation:{event.request_id}",
        generation=event.generation,
        event_type=event.event_type.value,
        created_at=_timestamp(event.created_at),
        final=event.final,
    )
    _copy_event_payload(message, event)
    return message


def runner_state_report_from_message(
    message: runtime_runner_control_pb2.RunnerStateReport,
) -> RunnerStateReport:
    if not message.HasField("runtime_configuration"):
        raise ValueError("Runtime Runner configuration evidence is required.")
    return RunnerStateReport(
        runtime_id=message.runtime_id,
        runner_id=message.runner_id,
        runner_generation=message.runner_generation,
        runner_state=RuntimeRunnerState(message.runner_state),
        capabilities=tuple(message.capabilities),
        active_operation_ids=tuple(message.active_operation_ids),
        health=message.health,
        diagnostic=dict(message.diagnostic),
        workspace_path=message.workspace_path,
        reported_at=_datetime(message.reported_at),
        runtime_configuration=_runtime_configuration_evidence(
            message.runtime_configuration
        ),
    )


def runner_system_metrics_from_message(
    message: runtime_runner_control_pb2.RunnerSystemMetrics,
) -> RunnerSystemMetricsReport:
    """Deserialize one validated Runner system-metrics report."""
    return RunnerSystemMetricsReport(
        runtime_id=message.runtime_id,
        sequence=message.sequence,
        scope=_system_metrics_scope_from_message(message.scope),
        cpu=_system_metric_observation_from_message(message.cpu),
        memory=_system_metric_observation_from_message(message.memory),
        disk=_system_metric_observation_from_message(message.disk),
        runtime_web=_runtime_web_metrics_from_message(message.runtime_web),
    )


def runner_system_metrics_to_message(
    report: RunnerSystemMetricsReport,
) -> runtime_runner_control_pb2.RunnerSystemMetrics:
    """Serialize one Runner system-metrics report."""
    return runtime_runner_control_pb2.RunnerSystemMetrics(
        runtime_id=report.runtime_id,
        sequence=report.sequence,
        scope=_system_metrics_scope_to_message(report.scope),
        cpu=_system_metric_observation_to_message(report.cpu),
        memory=_system_metric_observation_to_message(report.memory),
        disk=_system_metric_observation_to_message(report.disk),
        runtime_web=_runtime_web_metrics_to_message(report.runtime_web),
    )


def _runtime_web_metrics_from_message(
    message: runtime_runner_control_pb2.RunnerRuntimeWebMetrics,
) -> RunnerRuntimeWebMetrics:
    return RunnerRuntimeWebMetrics(
        active_sessions=message.active_sessions,
        active_streams=message.active_streams,
        maximum_sessions=message.maximum_sessions,
        maximum_active_streams=message.maximum_active_streams,
        application_buffer_bytes=message.application_buffer_bytes,
        application_buffer_limit_bytes=message.application_buffer_limit_bytes,
        control_buffer_bytes=message.control_buffer_bytes,
        control_buffer_limit_bytes=message.control_buffer_limit_bytes,
        queued_envelopes=message.queued_envelopes,
        queued_envelope_limit=message.queued_envelope_limit,
        pending_tasks=message.pending_tasks,
        pending_task_limit=message.pending_task_limit,
        event_loop_lag_milliseconds=message.event_loop_lag_milliseconds,
        event_loop_lag_limit_milliseconds=(message.event_loop_lag_limit_milliseconds),
        resident_memory_bytes=message.resident_memory_bytes,
        resident_memory_limit_bytes=message.resident_memory_limit_bytes,
        credit_stalls_total=message.credit_stalls_total,
        credit_stall_seconds=message.credit_stall_seconds,
        request_consumed_bytes=message.request_consumed_bytes,
        response_sent_bytes=message.response_sent_bytes,
        response_consumed_bytes=message.response_consumed_bytes,
        heartbeats_total=message.heartbeats_total,
        go_aways_total=message.go_aways_total,
        epoch_transitions_total=message.epoch_transitions_total,
        setup_seconds_sum=message.setup_seconds_sum,
        setup_count=message.setup_count,
        ttfb_seconds_sum=message.ttfb_seconds_sum,
        ttfb_count=message.ttfb_count,
        duration_seconds_sum=message.duration_seconds_sum,
        duration_count=message.duration_count,
        goodput_bytes=message.goodput_bytes,
        active_streams_by_protocol=tuple(
            RunnerRuntimeWebProtocolCount(
                protocol=_runtime_web_protocol_from_message(item.protocol),
                value=item.value,
            )
            for item in message.active_streams_by_protocol
        ),
        opens_accepted_by_protocol=tuple(
            RunnerRuntimeWebProtocolCount(
                protocol=_runtime_web_protocol_from_message(item.protocol),
                value=item.value,
            )
            for item in message.opens_accepted_by_protocol
        ),
        opens_rejected_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_from_message(item.reason),
                value=item.value,
            )
            for item in message.opens_rejected_by_reason
        ),
        resets_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_from_message(item.reason),
                value=item.value,
            )
            for item in message.resets_by_reason
        ),
        closes_by_reason=tuple(
            RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_from_message(item.reason),
                value=item.value,
            )
            for item in message.closes_by_reason
        ),
        traffic=tuple(
            RunnerRuntimeWebTrafficCount(
                protocol=_runtime_web_protocol_from_message(item.protocol),
                direction=_runtime_web_direction_from_message(item.direction),
                frames=item.frames,
                bytes=item.bytes,
            )
            for item in message.traffic
        ),
    )


def _runtime_web_metrics_to_message(
    metrics: RunnerRuntimeWebMetrics,
) -> runtime_runner_control_pb2.RunnerRuntimeWebMetrics:
    return runtime_runner_control_pb2.RunnerRuntimeWebMetrics(
        active_sessions=metrics.active_sessions,
        active_streams=metrics.active_streams,
        maximum_sessions=metrics.maximum_sessions,
        maximum_active_streams=metrics.maximum_active_streams,
        application_buffer_bytes=metrics.application_buffer_bytes,
        application_buffer_limit_bytes=metrics.application_buffer_limit_bytes,
        control_buffer_bytes=metrics.control_buffer_bytes,
        control_buffer_limit_bytes=metrics.control_buffer_limit_bytes,
        queued_envelopes=metrics.queued_envelopes,
        queued_envelope_limit=metrics.queued_envelope_limit,
        pending_tasks=metrics.pending_tasks,
        pending_task_limit=metrics.pending_task_limit,
        event_loop_lag_milliseconds=metrics.event_loop_lag_milliseconds,
        event_loop_lag_limit_milliseconds=metrics.event_loop_lag_limit_milliseconds,
        resident_memory_bytes=metrics.resident_memory_bytes,
        resident_memory_limit_bytes=metrics.resident_memory_limit_bytes,
        credit_stalls_total=metrics.credit_stalls_total,
        credit_stall_seconds=metrics.credit_stall_seconds,
        request_consumed_bytes=metrics.request_consumed_bytes,
        response_sent_bytes=metrics.response_sent_bytes,
        response_consumed_bytes=metrics.response_consumed_bytes,
        heartbeats_total=metrics.heartbeats_total,
        go_aways_total=metrics.go_aways_total,
        epoch_transitions_total=metrics.epoch_transitions_total,
        setup_seconds_sum=metrics.setup_seconds_sum,
        setup_count=metrics.setup_count,
        ttfb_seconds_sum=metrics.ttfb_seconds_sum,
        ttfb_count=metrics.ttfb_count,
        duration_seconds_sum=metrics.duration_seconds_sum,
        duration_count=metrics.duration_count,
        goodput_bytes=metrics.goodput_bytes,
        active_streams_by_protocol=[
            runtime_runner_control_pb2.RunnerRuntimeWebProtocolCount(
                protocol=_runtime_web_protocol_to_message(item.protocol),
                value=item.value,
            )
            for item in metrics.active_streams_by_protocol
        ],
        opens_accepted_by_protocol=[
            runtime_runner_control_pb2.RunnerRuntimeWebProtocolCount(
                protocol=_runtime_web_protocol_to_message(item.protocol),
                value=item.value,
            )
            for item in metrics.opens_accepted_by_protocol
        ],
        opens_rejected_by_reason=[
            runtime_runner_control_pb2.RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_to_message(item.reason),
                value=item.value,
            )
            for item in metrics.opens_rejected_by_reason
        ],
        resets_by_reason=[
            runtime_runner_control_pb2.RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_to_message(item.reason),
                value=item.value,
            )
            for item in metrics.resets_by_reason
        ],
        closes_by_reason=[
            runtime_runner_control_pb2.RunnerRuntimeWebReasonCount(
                reason=_runtime_web_reason_to_message(item.reason),
                value=item.value,
            )
            for item in metrics.closes_by_reason
        ],
        traffic=[
            runtime_runner_control_pb2.RunnerRuntimeWebTrafficCount(
                protocol=_runtime_web_protocol_to_message(item.protocol),
                direction=_runtime_web_direction_to_message(item.direction),
                frames=item.frames,
                bytes=item.bytes,
            )
            for item in metrics.traffic
        ],
    )


def _runtime_web_protocol_from_message(
    value: runtime_stream_session_pb2.RuntimeStreamSessionProtocol.ValueType,
) -> StreamProtocol:
    mapping = {
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_HTTP: (
            StreamProtocol.HTTP
        ),
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET: (
            StreamProtocol.WEBSOCKET
        ),
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise ValueError("Runtime Web metrics protocol is invalid") from error


def _runtime_web_protocol_to_message(
    protocol: StreamProtocol,
) -> runtime_stream_session_pb2.RuntimeStreamSessionProtocol.ValueType:
    return {
        StreamProtocol.HTTP: (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_HTTP
        ),
        StreamProtocol.WEBSOCKET: (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_PROTOCOL_WEBSOCKET
        ),
    }[protocol]


def _runtime_web_direction_from_message(
    value: runtime_stream_session_pb2.RuntimeStreamSessionDirection.ValueType,
) -> StreamDirection:
    mapping = {
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST: (
            StreamDirection.REQUEST
        ),
        runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE: (
            StreamDirection.RESPONSE
        ),
    }
    try:
        return mapping[value]
    except KeyError as error:
        raise ValueError("Runtime Web metrics direction is invalid") from error


def _runtime_web_direction_to_message(
    direction: StreamDirection,
) -> runtime_stream_session_pb2.RuntimeStreamSessionDirection.ValueType:
    return {
        StreamDirection.REQUEST: (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_REQUEST
        ),
        StreamDirection.RESPONSE: (
            runtime_stream_session_pb2.RUNTIME_STREAM_SESSION_DIRECTION_RESPONSE
        ),
    }[direction]


def _runtime_web_reason_from_message(
    value: runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.ValueType,
) -> CloseReason:
    try:
        name = runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.Name(value)
    except ValueError as error:
        raise ValueError("Runtime Web metrics reason is invalid") from error
    prefix = "RUNTIME_STREAM_SESSION_CLOSE_REASON_"
    if not name.startswith(prefix) or name == f"{prefix}UNSPECIFIED":
        raise ValueError("Runtime Web metrics reason is invalid")
    return CloseReason(name.removeprefix(prefix).lower())


def _runtime_web_reason_to_message(
    reason: CloseReason,
) -> runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.ValueType:
    return runtime_stream_session_pb2.RuntimeStreamSessionCloseReason.Value(
        f"RUNTIME_STREAM_SESSION_CLOSE_REASON_{reason.value.upper()}"
    )


def _system_metrics_scope_from_message(
    value: runtime_runner_control_pb2.RunnerSystemMetricsScope.ValueType,
) -> RunnerSystemMetricsScope:
    scopes = {
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_HOST: (
            RunnerSystemMetricsScope.HOST
        ),
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_VM: (
            RunnerSystemMetricsScope.VM
        ),
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_CONTAINER: (
            RunnerSystemMetricsScope.CONTAINER
        ),
    }
    try:
        return scopes[value]
    except KeyError as exc:
        raise ValueError("Runtime metrics scope is invalid") from exc


def _system_metrics_scope_to_message(
    scope: RunnerSystemMetricsScope,
) -> runtime_runner_control_pb2.RunnerSystemMetricsScope.ValueType:
    return {
        RunnerSystemMetricsScope.HOST: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_HOST
        ),
        RunnerSystemMetricsScope.VM: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_VM
        ),
        RunnerSystemMetricsScope.CONTAINER: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRICS_SCOPE_CONTAINER
        ),
    }[scope]


def _system_metric_observation_from_message(
    message: runtime_runner_control_pb2.RunnerSystemMetricObservation,
) -> RunnerSystemMetricObservation:
    availabilities = {
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_AVAILABLE: (
            RunnerSystemMetricAvailability.AVAILABLE
        ),
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_UNAVAILABLE: (
            RunnerSystemMetricAvailability.UNAVAILABLE
        ),
        runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_UNSUPPORTED: (
            RunnerSystemMetricAvailability.UNSUPPORTED
        ),
    }
    try:
        availability = availabilities[message.availability]
    except KeyError as exc:
        raise ValueError("Runtime metric availability is invalid") from exc
    return RunnerSystemMetricObservation(
        availability=availability,
        used=message.used if message.HasField("used") else None,
        total=message.total if message.HasField("total") else None,
    )


def _system_metric_observation_to_message(
    observation: RunnerSystemMetricObservation,
) -> runtime_runner_control_pb2.RunnerSystemMetricObservation:
    availability = {
        RunnerSystemMetricAvailability.AVAILABLE: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_AVAILABLE
        ),
        RunnerSystemMetricAvailability.UNAVAILABLE: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_UNAVAILABLE
        ),
        RunnerSystemMetricAvailability.UNSUPPORTED: (
            runtime_runner_control_pb2.RUNNER_SYSTEM_METRIC_AVAILABILITY_UNSUPPORTED
        ),
    }[observation.availability]
    message = runtime_runner_control_pb2.RunnerSystemMetricObservation(
        availability=availability
    )
    if observation.used is not None:
        message.used = observation.used
    if observation.total is not None:
        message.total = observation.total
    return message


def _runtime_configuration_evidence(
    message: runtime_configuration_pb2.RuntimeConfigurationEvidence,
) -> RuntimeConfigurationEvidence:
    return RuntimeConfigurationEvidence(
        configuration_sequence=parse_configuration_sequence(
            message.configuration_sequence
        ),
        digest=message.digest,
        desired_generation=message.desired_generation,
    )


def runner_runtime_configuration_evidence_from_message(
    message: runtime_configuration_pb2.RuntimeConfigurationEvidence,
) -> RuntimeConfigurationEvidence:
    """Deserialize required Runner configuration evidence."""
    return _runtime_configuration_evidence(message)


def runner_runtime_configuration_evidence_to_message(
    evidence: RuntimeConfigurationEvidence,
) -> runtime_configuration_pb2.RuntimeConfigurationEvidence:
    """Serialize required Runner configuration evidence."""
    return _runtime_configuration_evidence_message(evidence)


def _runtime_configuration_evidence_message(
    evidence: RuntimeConfigurationEvidence,
) -> runtime_configuration_pb2.RuntimeConfigurationEvidence:
    return runtime_configuration_pb2.RuntimeConfigurationEvidence(
        configuration_sequence=serialize_configuration_sequence(
            evidence.configuration_sequence
        ),
        digest=evidence.digest,
        desired_generation=evidence.desired_generation,
    )


def runner_event_from_message(
    message: runtime_runner_control_pb2.RunnerOperationEvent,
    *,
    request_id: str,
) -> RunnerOperationEvent:
    return RunnerOperationEvent(
        request_id=request_id,
        runtime_id=message.runtime_id,
        generation=message.generation,
        event_type=RuntimeRunnerEventType(message.event_type),
        payload=_event_payload(message),
        created_at=_datetime(message.created_at),
        final=message.final,
    )


def _operation_payload(
    operation: runtime_runner_control_pb2.RunnerOperationRequest,
) -> dict[str, JsonValue]:
    payload_kind = operation.WhichOneof("payload")
    if payload_kind == "bash":
        payload = operation.bash
        result: dict[str, JsonValue] = {"command": payload.command}
        if payload.timeout_seconds:
            result["timeout_seconds"] = payload.timeout_seconds
        if payload.env:
            result["env"] = dict(payload.env)
        return result
    if payload_kind == "file_read":
        payload = operation.file_read
        result = {"path": payload.path, "offset": payload.offset}
        if payload.HasField("max_bytes"):
            result["max_bytes"] = payload.max_bytes
        return result
    if payload_kind == "file_read_text":
        payload = operation.file_read_text
        return {
            "path": payload.path,
            "character_offset": payload.character_offset,
            "max_characters": payload.max_characters,
            "encoding": payload.encoding,
        }
    if payload_kind == "file_write":
        return {
            "path": operation.file_write.path,
            "total_bytes": operation.file_write.total_bytes,
        }
    if payload_kind == "file_apply_patch":
        return {
            "base_path": operation.file_apply_patch.base_path,
            "total_bytes": operation.file_apply_patch.total_bytes,
            "schema_version": operation.file_apply_patch.schema_version,
        }
    if payload_kind == "file_edit":
        return {
            "path": operation.file_edit.path,
            "old_string": operation.file_edit.old_string,
            "new_string": operation.file_edit.new_string,
            "replace_all": operation.file_edit.replace_all,
        }
    if payload_kind == "file_list":
        payload = operation.file_list
        return {
            "path": payload.path,
            "recursive": payload.recursive,
            "exclude_patterns": list(payload.exclude_patterns),
        }
    if payload_kind == "file_glob":
        payload = operation.file_glob
        return {
            "pattern": payload.pattern,
            "exclude_patterns": list(payload.exclude_patterns),
        }
    if payload_kind == "file_grep":
        payload = operation.file_grep
        result = {
            "path": payload.path,
            "pattern": payload.pattern,
            "exclude_patterns": list(payload.exclude_patterns),
            "max_matching_files": payload.max_matching_files,
            "max_lines_per_file": payload.max_lines_per_file,
        }
        if payload.HasField("recursive"):
            result["recursive"] = payload.recursive
        return result
    if payload_kind == "file_stat":
        return {"path": operation.file_stat.path}
    if payload_kind == "process_start":
        payload = operation.process_start
        result: dict[str, JsonValue] = {
            "command": payload.command,
            "yield_time_ms": payload.yield_time_ms,
            "max_output_bytes": payload.max_output_bytes,
        }
        if payload.HasField("workdir"):
            result["workdir"] = payload.workdir
        if payload.env:
            result["env"] = dict(payload.env)
        return result
    if payload_kind == "process_write":
        payload = operation.process_write
        return {
            "process_id": payload.process_id,
            "stdin": payload.stdin,
            "yield_time_ms": payload.yield_time_ms,
            "max_output_bytes": payload.max_output_bytes,
        }
    if payload_kind == "file_delete":
        return {
            "path": operation.file_delete.path,
            "recursive": operation.file_delete.recursive,
        }
    if payload_kind == "file_mkdir":
        return {
            "path": operation.file_mkdir.path,
            "parents": operation.file_mkdir.parents,
        }
    if payload_kind == "file_move":
        return {
            "source_path": operation.file_move.source_path,
            "destination_path": operation.file_move.destination_path,
            "overwrite": operation.file_move.overwrite,
        }
    if payload_kind == "process_terminate_session":
        payload = operation.process_terminate_session
        return {"owner_session_id": payload.owner_session_id}
    if payload_kind == "file_bulk_delete":
        return {
            "paths": list(operation.file_bulk_delete.paths),
            "recursive": operation.file_bulk_delete.recursive,
        }
    if payload_kind == "file_bulk_move":
        return {
            "source_paths": list(operation.file_bulk_move.source_paths),
            "destination_directory": operation.file_bulk_move.destination_directory,
            "overwrite": operation.file_bulk_move.overwrite,
        }
    if payload_kind == "git_list_refs":
        return {"source_project_path": operation.git_list_refs.source_project_path}
    if payload_kind == "git_create_worktree":
        payload = operation.git_create_worktree
        return {
            "source_project_path": payload.source_project_path,
            "worktree_path": payload.worktree_path,
            "branch_name": payload.branch_name,
            "starting_ref": payload.starting_ref,
        }
    if payload_kind == "git_inspect_worktree":
        payload = operation.git_inspect_worktree
        return {
            "source_project_path": payload.source_project_path,
            "worktree_path": payload.worktree_path,
            "branch_name": payload.branch_name,
        }
    if payload_kind == "git_discover_managed_worktrees":
        return {}
    if payload_kind == "git_remove_discovered_worktree":
        payload = operation.git_remove_discovered_worktree
        return {
            "worktree_path": payload.worktree_path,
            "repository_anchor_path": payload.repository_anchor_path,
            "branch_name": payload.branch_name,
            "fingerprint": payload.fingerprint,
            "force": payload.force,
        }
    if payload_kind == "git_remove_worktree":
        payload = operation.git_remove_worktree
        return {
            "source_project_path": payload.source_project_path,
            "worktree_path": payload.worktree_path,
            "force": payload.force,
            "branch_name": payload.branch_name,
        }
    if payload_kind == "git_delete_branch":
        payload = operation.git_delete_branch
        return {
            "source_project_path": payload.source_project_path,
            "branch_name": payload.branch_name,
        }
    return {}


def _copy_event_payload(
    message: runtime_runner_control_pb2.RunnerOperationEvent,
    event: RunnerOperationEvent,
) -> None:
    payload = event.payload
    match event.event_type:
        case RuntimeRunnerEventType.ACCEPTED:
            message.accepted.operation_type = _str_payload(payload, "operation_type")
        case RuntimeRunnerEventType.STDOUT:
            message.stdout.text = _str_payload(payload, "text")
        case RuntimeRunnerEventType.STDERR:
            message.stderr.text = _str_payload(payload, "text")
        case RuntimeRunnerEventType.FILE_CHUNK:
            message.file_chunk.data_base64 = _str_payload(payload, "data_base64")
        case RuntimeRunnerEventType.PROCESS_OUTPUT:
            process_output = message.process_output
            process_output.process_id = _str_payload(payload, "process_id")
            process_output.stream = _str_payload(payload, "stream")
            process_output.chunk_id = _int_payload(payload, "chunk_id")
            process_output.text = _str_payload(payload, "text")
            process_output.truncated = _bool_payload(payload, "truncated")
            process_output.omitted_bytes = _int_payload(payload, "omitted_bytes")
        case RuntimeRunnerEventType.FINAL_SUCCESS:
            _copy_final_success(message.final_success, payload)
        case RuntimeRunnerEventType.FINAL_ERROR:
            message.final_error.error_code = _str_payload(payload, "error_code")
            message.final_error.error_message = _str_payload(payload, "error_message")
            patch_failure = payload.get("file_apply_patch")
            if isinstance(patch_failure, dict):
                _copy_file_apply_patch_failure(
                    message.final_error.file_apply_patch,
                    patch_failure,
                )
        case _:
            pass


def _copy_final_success(
    message: runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload,
    payload: Mapping[str, JsonValue],
) -> None:
    if "process_id" in payload or "status" in payload:
        process = message.process
        process.process_id = _str_payload(payload, "process_id")
        process.status = _str_payload(payload, "status")
        exit_code = _optional_int_payload(payload, "exit_code")
        if exit_code is not None:
            process.exit_code = exit_code
        process.stdout = _str_payload(payload, "stdout")
        process.stderr = _str_payload(payload, "stderr")
        process.stdout_truncated = _bool_payload(payload, "stdout_truncated")
        process.stderr_truncated = _bool_payload(payload, "stderr_truncated")
        process.stdout_omitted_bytes = _int_payload(payload, "stdout_omitted_bytes")
        process.stderr_omitted_bytes = _int_payload(payload, "stderr_omitted_bytes")
        process.missing_reason = _str_payload(payload, "missing_reason")
        return
    if "exit_code" in payload:
        message.bash.exit_code = _int_payload(payload, "exit_code")
        return
    if "bytes_read" in payload:
        message.file_read.bytes_read = _int_payload(payload, "bytes_read")
        return
    if "start_character" in payload:
        message.file_read_text.start_character = _int_payload(
            payload,
            "start_character",
        )
        message.file_read_text.end_character = _int_payload(
            payload,
            "end_character",
        )
        message.file_read_text.truncated = _bool_payload(payload, "truncated")
        return
    if "bytes_written" in payload:
        message.file_write.bytes_written = _int_payload(payload, "bytes_written")
        return
    if "matches" in payload:
        message.file_glob.entries.extend(
            _file_list_entries(payload, field_name="matches")
        )
        return
    if "changes" in payload:
        message.file_apply_patch.changes.extend(
            _file_patch_change_entries(payload, "changes")
        )
        return
    if "replacements" in payload:
        message.file_edit.replacements = _int_payload(payload, "replacements")
        return
    if "entries" in payload:
        message.file_list.entries.extend(_file_list_entries(payload))
        return
    if "files" in payload:
        grep = message.file_grep
        grep.files.extend(_grep_file_matches(payload))
        grep.searched_file_count = _int_payload(payload, "searched_file_count")
        grep.matched_file_count = _int_payload(payload, "matched_file_count")
        grep.truncated = _bool_payload(payload, "truncated")
        return
    if "kind" in payload:
        stat = message.file_stat
        stat.path = _str_payload(payload, "path")
        stat.kind = _str_payload(payload, "kind")
        size_bytes = _optional_int_payload(payload, "size_bytes")
        if size_bytes is not None:
            stat.size_bytes = size_bytes
        stat.symlink = _bool_payload(payload, "symlink")
        real_path = _optional_str_payload(payload, "real_path")
        if real_path is not None:
            stat.real_path = real_path
        resolved_kind = _optional_str_payload(payload, "resolved_kind")
        if resolved_kind is not None:
            stat.resolved_kind = resolved_kind
        modified_at = _optional_str_payload(payload, "modified_at")
        if modified_at is not None:
            stat.modified_at = modified_at
        return
    if "deleted_paths" in payload:
        message.file_bulk_delete.paths.extend(
            _str_list_payload(payload, "deleted_paths")
        )
        return
    if "deleted_path" in payload:
        message.file_delete.path = _str_payload(payload, "deleted_path")
        return
    if "created_path" in payload:
        message.file_mkdir.path = _str_payload(payload, "created_path")
        return
    if "moved_entries" in payload:
        message.file_bulk_move.entries.extend(_move_entries(payload))
        return
    if "moved_source_path" in payload or "moved_destination_path" in payload:
        message.file_move.source_path = _str_payload(payload, "moved_source_path")
        message.file_move.destination_path = _str_payload(
            payload, "moved_destination_path"
        )
        return
    if "git_refs" in payload:
        git_refs = message.git_list_refs
        git_refs.refs.extend(_git_ref_entries(payload))
        git_refs.default_branch = _str_payload(payload, "default_branch")
        git_refs.head_commit = _str_payload(payload, "head_commit")
        git_refs.repository_anchor_path = _str_payload(
            payload,
            "repository_anchor_path",
        )
        return
    if "base_commit" in payload:
        worktree = message.git_create_worktree
        worktree.base_commit = _str_payload(payload, "base_commit")
        worktree.worktree_path = _str_payload(payload, "worktree_path")
        worktree.branch_name = _str_payload(payload, "branch_name")
        return
    if "worktree_registered" in payload:
        worktree = message.git_inspect_worktree
        worktree.worktree_path = _str_payload(payload, "worktree_path")
        worktree.registered = _bool_payload(payload, "worktree_registered")
        registered_branch_name = _optional_str_payload(
            payload, "registered_branch_name"
        )
        if registered_branch_name is not None:
            worktree.registered_branch_name = registered_branch_name
        worktree.target_kind = _str_payload(payload, "target_kind")
        dirty = payload.get("dirty")
        if isinstance(dirty, bool):
            worktree.dirty = dirty
        return
    if "discovered_worktrees" in payload:
        message.git_discover_managed_worktrees.SetInParent()
        message.git_discover_managed_worktrees.entries.extend(
            _discovered_worktree_entries(payload)
        )
        return
    if "removed_discovered_worktree_path" in payload:
        message.git_remove_discovered_worktree.worktree_path = _str_payload(
            payload,
            "removed_discovered_worktree_path",
        )
        message.git_remove_discovered_worktree.outcome = _str_payload(
            payload,
            "outcome",
        )
        return
    if "removed_worktree_path" in payload:
        message.git_remove_worktree.worktree_path = _str_payload(
            payload, "removed_worktree_path"
        )
        message.git_remove_worktree.outcome = _str_payload(payload, "outcome")
        return
    if "deleted_branch_name" in payload:
        message.git_delete_branch.branch_name = _str_payload(
            payload, "deleted_branch_name"
        )
        message.git_delete_branch.outcome = _str_payload(payload, "outcome")
        return


def _event_payload(
    message: runtime_runner_control_pb2.RunnerOperationEvent,
) -> dict[str, JsonValue]:
    payload_kind = message.WhichOneof("payload")
    if payload_kind == "accepted":
        return {"operation_type": message.accepted.operation_type}
    if payload_kind == "stdout":
        return {"text": message.stdout.text}
    if payload_kind == "stderr":
        return {"text": message.stderr.text}
    if payload_kind == "file_chunk":
        return {"data_base64": message.file_chunk.data_base64}
    if payload_kind == "process_output":
        return {
            "process_id": message.process_output.process_id,
            "stream": message.process_output.stream,
            "chunk_id": message.process_output.chunk_id,
            "text": message.process_output.text,
            "truncated": message.process_output.truncated,
            "omitted_bytes": message.process_output.omitted_bytes,
        }
    if payload_kind == "final_error":
        payload: dict[str, JsonValue] = {
            "error_code": message.final_error.error_code,
            "error_message": message.final_error.error_message,
        }
        if message.final_error.WhichOneof("detail") == "file_apply_patch":
            payload["file_apply_patch"] = _file_apply_patch_failure_payload(
                message.final_error.file_apply_patch
            )
        return payload
    if payload_kind == "final_success":
        return _final_success_payload(message.final_success)
    return {}


def _final_success_payload(
    message: runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload,
) -> dict[str, JsonValue]:
    result_kind = message.WhichOneof("result")
    if result_kind == "bash":
        return {"exit_code": message.bash.exit_code}
    if result_kind == "file_read":
        return {"bytes_read": message.file_read.bytes_read}
    if result_kind == "file_read_text":
        return {
            "start_character": message.file_read_text.start_character,
            "end_character": message.file_read_text.end_character,
            "truncated": message.file_read_text.truncated,
        }
    if result_kind == "file_write":
        return {"bytes_written": message.file_write.bytes_written}
    if result_kind == "file_apply_patch":
        return {
            "changes": [
                _file_patch_change_payload(change)
                for change in message.file_apply_patch.changes
            ]
        }
    if result_kind == "file_edit":
        return {"replacements": message.file_edit.replacements}
    if result_kind == "file_list":
        return {"entries": _file_list_entry_payloads(message.file_list.entries)}
    if result_kind == "file_glob":
        return {"entries": _file_list_entry_payloads(message.file_glob.entries)}
    if result_kind == "file_grep":
        return {
            "files": [
                {
                    "path": file.path,
                    "lines": [
                        {"line_number": line.line_number, "text": line.text}
                        for line in file.lines
                    ],
                    "truncated": file.truncated,
                }
                for file in message.file_grep.files
            ],
            "searched_file_count": message.file_grep.searched_file_count,
            "matched_file_count": message.file_grep.matched_file_count,
            "truncated": message.file_grep.truncated,
        }
    if result_kind == "file_stat":
        payload = {
            "path": message.file_stat.path,
            "kind": message.file_stat.kind,
            "size_bytes": (
                message.file_stat.size_bytes
                if message.file_stat.HasField("size_bytes")
                else None
            ),
            "symlink": message.file_stat.symlink,
        }
        if message.file_stat.HasField("real_path"):
            payload["real_path"] = message.file_stat.real_path
        if message.file_stat.HasField("resolved_kind"):
            payload["resolved_kind"] = message.file_stat.resolved_kind
        if message.file_stat.HasField("modified_at"):
            payload["modified_at"] = message.file_stat.modified_at
        return payload
    if result_kind == "process":
        payload: dict[str, JsonValue] = {
            "process_id": message.process.process_id,
            "status": message.process.status,
            "stdout": message.process.stdout,
            "stderr": message.process.stderr,
            "stdout_truncated": message.process.stdout_truncated,
            "stderr_truncated": message.process.stderr_truncated,
            "stdout_omitted_bytes": message.process.stdout_omitted_bytes,
            "stderr_omitted_bytes": message.process.stderr_omitted_bytes,
            "missing_reason": message.process.missing_reason,
        }
        if message.process.HasField("exit_code"):
            payload["exit_code"] = message.process.exit_code
        return payload
    if result_kind == "file_delete":
        return {"deleted_path": message.file_delete.path}
    if result_kind == "file_mkdir":
        return {"created_path": message.file_mkdir.path}
    if result_kind == "file_move":
        return {
            "moved_source_path": message.file_move.source_path,
            "moved_destination_path": message.file_move.destination_path,
        }
    if result_kind == "file_bulk_delete":
        return {"deleted_paths": list(message.file_bulk_delete.paths)}
    if result_kind == "file_bulk_move":
        return {
            "moved_entries": [
                {
                    "source_path": entry.source_path,
                    "destination_path": entry.destination_path,
                }
                for entry in message.file_bulk_move.entries
            ]
        }
    if result_kind == "git_list_refs":
        return {
            "git_refs": [
                {
                    "name": entry.name,
                    "ref": entry.ref,
                    "type": entry.type,
                    "target": entry.target,
                    "default": entry.default,
                }
                for entry in message.git_list_refs.refs
            ],
            "default_branch": message.git_list_refs.default_branch,
            "head_commit": message.git_list_refs.head_commit,
            "repository_anchor_path": (message.git_list_refs.repository_anchor_path),
        }
    if result_kind == "git_create_worktree":
        return {
            "base_commit": message.git_create_worktree.base_commit,
            "worktree_path": message.git_create_worktree.worktree_path,
            "branch_name": message.git_create_worktree.branch_name,
        }
    if result_kind == "git_inspect_worktree":
        payload: dict[str, JsonValue] = {
            "worktree_path": message.git_inspect_worktree.worktree_path,
            "worktree_registered": message.git_inspect_worktree.registered,
            "target_kind": message.git_inspect_worktree.target_kind,
        }
        if message.git_inspect_worktree.HasField("registered_branch_name"):
            payload["registered_branch_name"] = (
                message.git_inspect_worktree.registered_branch_name
            )
        if message.git_inspect_worktree.HasField("dirty"):
            payload["dirty"] = message.git_inspect_worktree.dirty
        return payload
    if result_kind == "git_discover_managed_worktrees":
        return {
            "discovered_worktrees": [
                {
                    "worktree_path": entry.worktree_path,
                    "registered": entry.registered,
                    "repository_anchor_path": entry.repository_anchor_path,
                    "branch_name": entry.branch_name,
                    "fingerprint": entry.fingerprint,
                    "failure_code": entry.failure_code,
                }
                for entry in message.git_discover_managed_worktrees.entries
            ]
        }
    if result_kind == "git_remove_discovered_worktree":
        return {
            "removed_discovered_worktree_path": (
                message.git_remove_discovered_worktree.worktree_path
            ),
            "outcome": message.git_remove_discovered_worktree.outcome,
        }
    if result_kind == "git_remove_worktree":
        return {
            "removed_worktree_path": message.git_remove_worktree.worktree_path,
            "outcome": message.git_remove_worktree.outcome,
        }
    if result_kind == "git_delete_branch":
        return {
            "deleted_branch_name": message.git_delete_branch.branch_name,
            "outcome": message.git_delete_branch.outcome,
        }
    return {}


def _copy_file_apply_patch_failure(
    message: runtime_runner_control_pb2.FileApplyPatchFailure,
    payload: Mapping[str, JsonValue],
) -> None:
    message.phase = _str_payload(payload, "phase")
    message.reason = _str_payload(payload, "reason")
    message.applied.extend(_file_patch_change_entries(payload, "applied"))
    failed = payload.get("failed")
    if isinstance(failed, dict):
        message.failed.path = _str_payload(failed, "path")
        message.failed.action = _str_payload(failed, "action")
    message.not_attempted.extend(
        _file_patch_operation_entries(payload, "not_attempted")
    )
    message.exact = _bool_payload(payload, "exact")


def _file_apply_patch_failure_payload(
    message: runtime_runner_control_pb2.FileApplyPatchFailure,
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "phase": message.phase,
        "reason": message.reason,
        "applied": [_file_patch_change_payload(change) for change in message.applied],
        "not_attempted": [
            _file_patch_operation_payload(operation)
            for operation in message.not_attempted
        ],
        "exact": message.exact,
    }
    if message.HasField("failed"):
        payload["failed"] = _file_patch_operation_payload(message.failed)
    return payload


def _file_patch_change_entries(
    payload: Mapping[str, JsonValue],
    key: str,
) -> list[runtime_runner_control_pb2.RuntimeFilePatchChange]:
    raw_entries = payload.get(key)
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeFilePatchChange] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        path = raw_entry.get("path")
        action = raw_entry.get("action")
        if not isinstance(path, str) or not isinstance(action, str):
            continue
        entry = runtime_runner_control_pb2.RuntimeFilePatchChange(
            path=path,
            action=action,
            added_lines=_int_payload(raw_entry, "added_lines"),
            removed_lines=_int_payload(raw_entry, "removed_lines"),
        )
        content_sha256 = _optional_str_payload(raw_entry, "content_sha256")
        if content_sha256 is not None:
            entry.content_sha256 = content_sha256
        entries.append(entry)
    return entries


def _file_patch_operation_entries(
    payload: Mapping[str, JsonValue],
    key: str,
) -> list[runtime_runner_control_pb2.RuntimeFilePatchOperation]:
    raw_entries = payload.get(key)
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeFilePatchOperation] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        path = raw_entry.get("path")
        action = raw_entry.get("action")
        if isinstance(path, str) and isinstance(action, str):
            entries.append(
                runtime_runner_control_pb2.RuntimeFilePatchOperation(
                    path=path,
                    action=action,
                )
            )
    return entries


def _file_patch_change_payload(
    message: runtime_runner_control_pb2.RuntimeFilePatchChange,
) -> dict[str, JsonValue]:
    payload: dict[str, JsonValue] = {
        "path": message.path,
        "action": message.action,
        "added_lines": message.added_lines,
        "removed_lines": message.removed_lines,
    }
    if message.HasField("content_sha256"):
        payload["content_sha256"] = message.content_sha256
    return payload


def _file_patch_operation_payload(
    message: runtime_runner_control_pb2.RuntimeFilePatchOperation,
) -> dict[str, JsonValue]:
    return {"path": message.path, "action": message.action}


def _git_ref_entries(
    payload: Mapping[str, JsonValue],
) -> list[runtime_runner_control_pb2.RuntimeGitRefEntry]:
    raw_entries = payload.get("git_refs")
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeGitRefEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        name = raw_entry.get("name")
        ref = raw_entry.get("ref")
        ref_type = raw_entry.get("type")
        target = raw_entry.get("target")
        if (
            isinstance(name, str)
            and isinstance(ref, str)
            and isinstance(ref_type, str)
            and isinstance(target, str)
        ):
            entries.append(
                runtime_runner_control_pb2.RuntimeGitRefEntry(
                    name=name,
                    ref=ref,
                    type=ref_type,
                    target=target,
                    default=_bool_payload(raw_entry, "default"),
                )
            )
    return entries


def _move_entries(
    payload: Mapping[str, JsonValue],
) -> list[runtime_runner_control_pb2.RuntimeFileMoveEntry]:
    raw_entries = payload.get("moved_entries")
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeFileMoveEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        source_path = raw_entry.get("source_path")
        destination_path = raw_entry.get("destination_path")
        if isinstance(source_path, str) and isinstance(destination_path, str):
            entries.append(
                runtime_runner_control_pb2.RuntimeFileMoveEntry(
                    source_path=source_path,
                    destination_path=destination_path,
                )
            )
    return entries


def _discovered_worktree_entries(
    payload: Mapping[str, JsonValue],
) -> list[runtime_runner_control_pb2.RuntimeDiscoveredGitWorktree]:
    raw_entries = payload.get("discovered_worktrees")
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeDiscoveredGitWorktree] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        worktree_path = raw_entry.get("worktree_path")
        repository_anchor_path = raw_entry.get("repository_anchor_path")
        branch_name = raw_entry.get("branch_name")
        fingerprint = raw_entry.get("fingerprint")
        failure_code = raw_entry.get("failure_code")
        if not all(
            isinstance(value, str)
            for value in (
                worktree_path,
                repository_anchor_path,
                branch_name,
                fingerprint,
                failure_code,
            )
        ):
            continue
        entries.append(
            runtime_runner_control_pb2.RuntimeDiscoveredGitWorktree(
                worktree_path=worktree_path,
                registered=_bool_payload(raw_entry, "registered"),
                repository_anchor_path=repository_anchor_path,
                branch_name=branch_name,
                fingerprint=fingerprint,
                failure_code=failure_code,
            )
        )
    return entries


def _file_list_entry_payloads(
    entries: Sequence[runtime_runner_control_pb2.RuntimeFileListEntry],
) -> list[JsonValue]:
    """Convert protobuf file entries to JSON payload values."""
    payloads: list[JsonValue] = []
    for entry in entries:
        payloads.append(
            {
                "path": entry.path,
                "type": entry.type,
                "size_bytes": (
                    entry.size_bytes if entry.HasField("size_bytes") else None
                ),
                "modified_at": (
                    entry.modified_at if entry.HasField("modified_at") else None
                ),
            }
        )
    return payloads


def _file_list_entries(
    payload: Mapping[str, JsonValue],
    *,
    field_name: str = "entries",
) -> list[runtime_runner_control_pb2.RuntimeFileListEntry]:
    raw_entries = payload.get(field_name)
    if not isinstance(raw_entries, list):
        return []
    entries: list[runtime_runner_control_pb2.RuntimeFileListEntry] = []
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, dict):
            continue
        path = raw_entry.get("path")
        entry_type = raw_entry.get("type")
        if not isinstance(path, str) or not isinstance(entry_type, str):
            continue
        entry = runtime_runner_control_pb2.RuntimeFileListEntry(
            path=path,
            type=entry_type,
        )
        size_bytes = _optional_int_payload(raw_entry, "size_bytes")
        if size_bytes is not None:
            entry.size_bytes = size_bytes
        modified_at = _optional_str_payload(raw_entry, "modified_at")
        if modified_at is not None:
            entry.modified_at = modified_at
        entries.append(entry)
    return entries


def _grep_file_matches(
    payload: Mapping[str, JsonValue],
) -> list[runtime_runner_control_pb2.RuntimeGrepFileMatch]:
    raw_files = payload.get("files")
    if not isinstance(raw_files, list):
        return []
    files: list[runtime_runner_control_pb2.RuntimeGrepFileMatch] = []
    for raw_file in raw_files:
        if not isinstance(raw_file, dict):
            continue
        path = raw_file.get("path")
        if not isinstance(path, str):
            continue
        files.append(
            runtime_runner_control_pb2.RuntimeGrepFileMatch(
                path=path,
                lines=_grep_line_matches(raw_file),
                truncated=_bool_payload(raw_file, "truncated"),
            )
        )
    return files


def _grep_line_matches(
    payload: Mapping[str, JsonValue],
) -> list[runtime_runner_control_pb2.RuntimeGrepLineMatch]:
    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list):
        return []
    lines: list[runtime_runner_control_pb2.RuntimeGrepLineMatch] = []
    for raw_line in raw_lines:
        if not isinstance(raw_line, dict):
            continue
        text = raw_line.get("text")
        line_number = _optional_int_payload(raw_line, "line_number")
        if not isinstance(text, str) or line_number is None:
            continue
        lines.append(
            runtime_runner_control_pb2.RuntimeGrepLineMatch(
                line_number=line_number,
                text=text,
            )
        )
    return lines


def _str_list_payload(payload: Mapping[str, JsonValue], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _str_payload(payload: Mapping[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _optional_str_payload(payload: Mapping[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _int_payload(payload: Mapping[str, JsonValue], key: str) -> int:
    value = _optional_int_payload(payload, key)
    return value if value is not None else 0


def _optional_int_payload(payload: Mapping[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _bool_payload(payload: Mapping[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else False


def _str_map(metadata: Mapping[str, object]) -> dict[str, str]:
    return {
        str(key): value for key, value in metadata.items() if isinstance(value, str)
    }


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value.astimezone(UTC))
    return timestamp


def _datetime(value: timestamp_pb2.Timestamp) -> datetime:
    return value.ToDatetime(tzinfo=UTC)


def _optional_datetime(
    message: runtime_runner_control_pb2.RunnerOperationRequest,
) -> datetime | None:
    if not message.HasField("deadline_at"):
        return None
    return _datetime(message.deadline_at)


def runner_transfer_intent_from_message(
    message: runtime_runner_control_pb2.RunnerTransferIntent,
) -> RunnerTransferIntent:
    """Map one top-level Runner transfer intent.

    :param message: protobuf Runner transfer intent
    :returns: metadata-only Runner transfer intent
    """
    return RunnerTransferIntent(
        identity=_transfer_identity(message.identity),
        direction=_transfer_direction(message.direction),
        operation_id=message.operation_id,
        owner_session_id=(
            message.owner_session_id if message.HasField("owner_session_id") else None
        ),
        runtime_path=message.runtime_path,
        overwrite=message.overwrite if message.HasField("overwrite") else None,
        expected_size=(
            message.expected_size if message.HasField("expected_size") else None
        ),
        expected_sha256=(
            message.expected_sha256 if message.HasField("expected_sha256") else None
        ),
        deadline_at=_datetime(message.deadline_at),
        protocol_version=message.protocol_version,
        capability=message.capability,
        dispatch_id=message.dispatch_id,
        conflict_precondition=(
            bytes(message.conflict_precondition)
            if message.HasField("conflict_precondition")
            else None
        ),
        source_transport=_transfer_source_transport(message.source_transport),
    )


def runner_transfer_cancel_from_message(
    message: runtime_runner_control_pb2.RunnerTransferCancel,
) -> RunnerTransferCancel:
    """Map one top-level Runner transfer cancellation.

    :param message: protobuf Runner transfer cancellation
    :returns: metadata-only Runner transfer cancellation
    """
    return RunnerTransferCancel(
        identity=_transfer_identity(message.identity),
        operation_id=message.operation_id,
        dispatch_id=message.dispatch_id,
        reason={
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_CALLER: (
                RunnerTransferCancelReason.CALLER
            ),
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_DEADLINE: (
                RunnerTransferCancelReason.DEADLINE
            ),
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_SUPERSEDED: (
                RunnerTransferCancelReason.SUPERSEDED
            ),
            runtime_runner_control_pb2.RUNNER_TRANSFER_CANCEL_REASON_SHUTDOWN: (
                RunnerTransferCancelReason.SHUTDOWN
            ),
        }[message.reason],
    )


def runner_terminal_open_intent_from_message(
    message: runtime_runner_control_pb2.RunnerTerminalOpenIntent,
) -> RunnerTerminalOpenIntent:
    """Deserialize one bounded Runner Terminal open intent."""
    if (
        not message.HasField("idle_deadline_at")
        or not message.HasField("maximum_deadline_at")
        or not message.HasField("data_stream_grace_deadline_at")
    ):
        raise ValueError("Runner Terminal open intent deadlines are required")
    return RunnerTerminalOpenIntent(
        identity=_terminal_identity_from_message(message.identity),
        owner_session_id=message.owner_session_id,
        working_directory=message.working_directory,
        columns=message.columns,
        rows=message.rows,
        idle_deadline_at=_datetime(message.idle_deadline_at),
        maximum_deadline_at=_datetime(message.maximum_deadline_at),
        data_stream_grace_deadline_at=_datetime(message.data_stream_grace_deadline_at),
        stream_nonce=message.stream_nonce,
        initial_stream_generation=message.initial_stream_generation,
    )


def runner_terminal_open_intent_to_message(
    intent: RunnerTerminalOpenIntent,
) -> runtime_runner_control_pb2.RunnerTerminalOpenIntent:
    """Serialize one bounded Runner Terminal open intent."""
    return runtime_runner_control_pb2.RunnerTerminalOpenIntent(
        identity=_terminal_identity_to_message(intent.identity),
        owner_session_id=intent.owner_session_id,
        working_directory=intent.working_directory,
        columns=intent.columns,
        rows=intent.rows,
        idle_deadline_at=_timestamp(intent.idle_deadline_at),
        maximum_deadline_at=_timestamp(intent.maximum_deadline_at),
        data_stream_grace_deadline_at=_timestamp(intent.data_stream_grace_deadline_at),
        stream_nonce=intent.stream_nonce,
        initial_stream_generation=intent.initial_stream_generation,
    )


def runner_terminal_terminate_intent_from_message(
    message: runtime_runner_control_pb2.RunnerTerminalTerminateIntent,
) -> RunnerTerminalTerminateIntent:
    """Deserialize one bounded Runner Terminal terminate intent."""
    return RunnerTerminalTerminateIntent(
        identity=_terminal_identity_from_message(message.identity),
        reason=_terminal_termination_reason_from_message(message.reason),
    )


def runner_terminal_terminate_intent_to_message(
    intent: RunnerTerminalTerminateIntent,
) -> runtime_runner_control_pb2.RunnerTerminalTerminateIntent:
    """Serialize one bounded Runner Terminal terminate intent."""
    return runtime_runner_control_pb2.RunnerTerminalTerminateIntent(
        identity=_terminal_identity_to_message(intent.identity),
        reason=_terminal_termination_reason_to_message(intent.reason),
    )


def runner_session_offer_from_message(
    message: runtime_runner_control_pb2.RunnerSessionOffer,
) -> RunnerSessionOffer:
    """Deserialize one exact replacement Runtime Web session offer."""
    if not message.HasField("registration_deadline_at"):
        raise ValueError("Runner Web session registration deadline is required")
    return RunnerSessionOffer(
        owner=OwnerSessionEpoch(
            owner_boot_id=message.owner_boot_id,
            session_lease_id=message.session_lease_id,
            lease_generation=message.lease_generation,
            runtime_id=message.runtime_id,
            desired_generation=message.desired_generation,
            runner_generation=message.runner_generation,
        ),
        session_nonce=message.join_nonce,
        protocol_fingerprint=message.protocol_fingerprint,
        deadline_at=_datetime(message.registration_deadline_at),
    )


def runner_session_offer_to_message(
    offer: RunnerSessionOffer,
) -> runtime_runner_control_pb2.RunnerSessionOffer:
    """Serialize one exact replacement Runtime Web session offer."""
    return runtime_runner_control_pb2.RunnerSessionOffer(
        runtime_id=offer.owner.runtime_id,
        desired_generation=offer.owner.desired_generation,
        runner_generation=offer.owner.runner_generation,
        owner_boot_id=offer.owner.owner_boot_id,
        session_lease_id=offer.owner.session_lease_id,
        lease_generation=offer.owner.lease_generation,
        join_nonce=offer.session_nonce,
        protocol_fingerprint=offer.protocol_fingerprint,
        registration_deadline_at=_timestamp(offer.deadline_at),
    )


def runner_transfer_result_from_message(
    message: runtime_runner_control_pb2.RunnerTransferResult,
    *,
    direction: RunnerTransferDirection,
) -> RunnerTransferResult:
    """Map and validate one top-level Runner transfer result.

    :param message: protobuf Runner transfer result
    :param direction: direction correlated from the dispatched transfer
    :returns: validated Runner transfer result
    """
    return RunnerTransferResult(
        identity=_transfer_identity(message.identity),
        operation_id=message.operation_id,
        dispatch_id=message.dispatch_id,
        direction=direction,
        outcome={
            runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_SUCCEEDED: (
                RunnerTransferOutcome.SUCCEEDED
            ),
            runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_FAILED: (
                RunnerTransferOutcome.FAILED
            ),
            runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_CANCELLED: (
                RunnerTransferOutcome.CANCELLED
            ),
        }[message.outcome],
        actual_size=(message.actual_size if message.HasField("actual_size") else None),
        sha256=message.sha256 if message.HasField("sha256") else None,
        destination_committed=(
            message.destination_committed
            if message.HasField("destination_committed")
            else None
        ),
        failure=(
            _transfer_failure(message.failure) if message.HasField("failure") else None
        ),
        conflict_precondition=(
            bytes(message.conflict_precondition)
            if message.HasField("conflict_precondition")
            else None
        ),
        destination_conflict=(
            _destination_conflict_from_message(message.destination_conflict)
            if message.HasField("destination_conflict")
            else None
        ),
    )


def _transfer_result_message(
    result: RunnerTransferResult,
) -> runtime_runner_control_pb2.RunnerTransferResult:
    """Map one bounded Runner transfer result to protobuf."""
    message = runtime_runner_control_pb2.RunnerTransferResult(
        identity=runtime_runner_transfer_pb2.TransferIdentity(
            transfer_id=result.identity.transfer_id,
            attempt_id=result.identity.attempt_id,
            runtime_id=result.identity.runtime_id,
            runner_generation=result.identity.runner_generation,
        ),
        operation_id=result.operation_id,
        dispatch_id=result.dispatch_id,
        outcome={
            RunnerTransferOutcome.SUCCEEDED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_SUCCEEDED
            ),
            RunnerTransferOutcome.FAILED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_FAILED
            ),
            RunnerTransferOutcome.CANCELLED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_OUTCOME_CANCELLED
            ),
        }[result.outcome],
    )
    if result.actual_size is not None:
        message.actual_size = result.actual_size
    if result.sha256 is not None:
        message.sha256 = result.sha256
    if result.destination_committed is not None:
        message.destination_committed = result.destination_committed
    if result.failure is not None:
        message.failure = {
            RunnerTransferFailure.UNAVAILABLE: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_UNAVAILABLE
            ),
            RunnerTransferFailure.ALREADY_CLAIMED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_ALREADY_CLAIMED
            ),
            RunnerTransferFailure.RESOURCE_EXHAUSTED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_RESOURCE_EXHAUSTED
            ),
            RunnerTransferFailure.DEADLINE_EXCEEDED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DEADLINE_EXCEEDED
            ),
            RunnerTransferFailure.CANCELLED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_CANCELLED
            ),
            RunnerTransferFailure.INTEGRITY_FAILED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_INTEGRITY_FAILED
            ),
            RunnerTransferFailure.PROTOCOL_VIOLATION: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_PROTOCOL_VIOLATION
            ),
            RunnerTransferFailure.STREAM_FAILED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_STREAM_FAILED
            ),
            RunnerTransferFailure.DESTINATION_FAILED: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DESTINATION_FAILED
            ),
            RunnerTransferFailure.DESTINATION_CONFLICT: (
                runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DESTINATION_CONFLICT
            ),
        }[result.failure]
    if result.conflict_precondition is not None:
        message.conflict_precondition = result.conflict_precondition
    if result.destination_conflict is not None:
        message.destination_conflict.CopyFrom(
            _destination_conflict_to_message(result.destination_conflict)
        )
    return message


def _transfer_identity(
    message: runtime_runner_transfer_pb2.TransferIdentity,
) -> RunnerTransferIdentity:
    return RunnerTransferIdentity(
        transfer_id=message.transfer_id,
        attempt_id=message.attempt_id,
        runtime_id=message.runtime_id,
        runner_generation=message.runner_generation,
    )


def _destination_conflict_from_message(
    message: runtime_runner_control_pb2.DestinationConflictEvidence,
) -> RunnerTransferDestinationConflictEvidence:
    """Deserialize bounded safe destination-conflict evidence."""
    if not message.HasField("modified_at"):
        raise ValueError("destination conflict modified_at is required")
    return RunnerTransferDestinationConflictEvidence(
        kind=message.kind,
        size=message.size if message.HasField("size") else None,
        modified_at=_datetime(message.modified_at),
    )


def _destination_conflict_to_message(
    evidence: RunnerTransferDestinationConflictEvidence,
) -> runtime_runner_control_pb2.DestinationConflictEvidence:
    """Serialize bounded safe destination-conflict evidence."""
    return runtime_runner_control_pb2.DestinationConflictEvidence(
        kind=evidence.kind,
        size=evidence.size,
        modified_at=_timestamp(evidence.modified_at),
    )


def _terminal_identity_from_message(
    message: runtime_runner_terminal_pb2.TerminalIdentity,
) -> RunnerTerminalIdentity:
    return RunnerTerminalIdentity(
        terminal_id=message.terminal_id,
        runtime_id=message.runtime_id,
        runner_generation=message.runner_generation,
    )


def _terminal_identity_to_message(
    identity: RunnerTerminalIdentity,
) -> runtime_runner_terminal_pb2.TerminalIdentity:
    return runtime_runner_terminal_pb2.TerminalIdentity(
        terminal_id=identity.terminal_id,
        runtime_id=identity.runtime_id,
        runner_generation=identity.runner_generation,
    )


def _terminal_termination_reason_from_message(
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


def _terminal_termination_reason_to_message(
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


def _transfer_direction(
    value: runtime_runner_transfer_pb2.TransferDirection.ValueType,
) -> RunnerTransferDirection:
    return {
        runtime_runner_transfer_pb2.TRANSFER_DIRECTION_DOWNLOAD: (
            RunnerTransferDirection.DOWNLOAD
        ),
        runtime_runner_transfer_pb2.TRANSFER_DIRECTION_UPLOAD: (
            RunnerTransferDirection.UPLOAD
        ),
    }[value]


def _transfer_source_transport(
    value: runtime_runner_control_pb2.RunnerTransferSourceTransport.ValueType,
) -> RunnerTransferSourceTransport:
    return {
        runtime_runner_control_pb2.RUNNER_TRANSFER_SOURCE_TRANSPORT_UNSPECIFIED: (
            RunnerTransferSourceTransport.TRANSFER_OBJECT
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_SOURCE_TRANSPORT_TRANSFER_OBJECT: (
            RunnerTransferSourceTransport.TRANSFER_OBJECT
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_SOURCE_TRANSPORT_DIRECT_OBJECT: (
            RunnerTransferSourceTransport.DIRECT_OBJECT
        ),
    }[value]


def _transfer_failure(
    value: runtime_runner_control_pb2.RunnerTransferFailure.ValueType,
) -> RunnerTransferFailure:
    return {
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_UNAVAILABLE: (
            RunnerTransferFailure.UNAVAILABLE
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_ALREADY_CLAIMED: (
            RunnerTransferFailure.ALREADY_CLAIMED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_RESOURCE_EXHAUSTED: (
            RunnerTransferFailure.RESOURCE_EXHAUSTED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DEADLINE_EXCEEDED: (
            RunnerTransferFailure.DEADLINE_EXCEEDED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_CANCELLED: (
            RunnerTransferFailure.CANCELLED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_INTEGRITY_FAILED: (
            RunnerTransferFailure.INTEGRITY_FAILED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_PROTOCOL_VIOLATION: (
            RunnerTransferFailure.PROTOCOL_VIOLATION
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_STREAM_FAILED: (
            RunnerTransferFailure.STREAM_FAILED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DESTINATION_FAILED: (
            RunnerTransferFailure.DESTINATION_FAILED
        ),
        runtime_runner_control_pb2.RUNNER_TRANSFER_FAILURE_DESTINATION_CONFLICT: (
            RunnerTransferFailure.DESTINATION_CONFLICT
        ),
    }[value]


__all__ = [
    "GrpcRunnerControlClient",
    "RunnerControlStream",
    "RuntimeRunnerControlStreamClosed",
    "runner_runtime_configuration_evidence_from_message",
    "runner_event_from_message",
    "runner_state_report_from_message",
    "runner_terminal_open_intent_from_message",
    "runner_terminal_open_intent_to_message",
    "runner_terminal_terminate_intent_from_message",
    "runner_terminal_terminate_intent_to_message",
    "runner_session_offer_from_message",
    "runner_session_offer_to_message",
    "runner_transfer_cancel_from_message",
    "runner_transfer_intent_from_message",
    "runner_transfer_result_from_message",
]
