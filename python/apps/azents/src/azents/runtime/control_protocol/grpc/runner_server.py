"""Agent Runtime Runner Control gRPC server bridge."""

# pyright: reportAttributeAccessIssue=false, reportUntypedBaseClass=false
# protobuf generated modules expose dynamic message/RPC attributes.

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol

import grpc
from azents_runtime_control.grpc_runner_client import (
    runner_event_from_message,
    runner_state_report_from_message,
)
from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_control_pb2_grpc,
)
from azents_runtime_control.runner import RunnerStateReport as SharedRunnerStateReport
from azents_runtime_control.runner import RuntimeRunnerState as SharedRunnerState
from google.protobuf import timestamp_pb2

from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeRunnerRegistration,
    RuntimeRunnerRegistrationAccepted,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBodyChunkRecord,
    RuntimeCoordinationTarget,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
    RuntimeRequestEnvelope,
)
from azents.runtime.coordination.store import RuntimeCoordinationStore

_DEFAULT_OPERATION_BLOCK_MS = 500
_BODY_CHUNK_READ_LIMIT = 100
_LOGGER = logging.getLogger(__name__)


class RuntimeRunnerStateSink(Protocol):
    """Durable Runner state sink used by the gRPC bridge."""

    async def record_runner_state(
        self,
        report: SharedRunnerStateReport,
    ) -> None:
        """Persist one Runner state report."""
        ...


class RuntimeRunnerControlGrpcServicer(
    runtime_runner_control_pb2_grpc.RuntimeRunnerControlServicer
):
    """Bidirectional gRPC stream bridge for Runtime-internal Runners."""

    def __init__(
        self,
        *,
        control_protocol: RuntimeControlProtocolService,
        coordination_store: RuntimeCoordinationStore,
        state_sink: RuntimeRunnerStateSink,
        owner_replica_id: str,
        consumer_id: str,
        operation_block_ms: int = _DEFAULT_OPERATION_BLOCK_MS,
    ) -> None:
        """Initialize the Runner Control gRPC servicer."""
        self._control_protocol = control_protocol
        self._coordination_store = coordination_store
        self._state_sink = state_sink
        self._owner_replica_id = owner_replica_id
        self._consumer_id = consumer_id
        self._operation_block_ms = operation_block_ms

    async def ConnectRunner(
        self,
        request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        context: grpc.aio.ServicerContext[
            runtime_runner_control_pb2.RunnerMessage,
            runtime_runner_control_pb2.RunnerControlMessage,
        ],
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        """Register a Runner, then bridge heartbeat/state/operation messages."""
        first_message = await _first_register_message(request_iterator, context)
        registration = _registration(
            first_message,
            owner_replica_id=self._owner_replica_id,
        )
        accepted = await self._control_protocol.register_runner(
            registration,
            registered_at=datetime.now(UTC),
        )
        _LOGGER.info(
            "Runtime Runner stream registered",
            extra={
                "runtime_id": accepted.runtime_id,
                "runner_id": accepted.runner_id,
                "connection_id": accepted.connection_id,
                "runner_generation": accepted.generation,
                "owner_replica_id": self._owner_replica_id,
            },
        )
        outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerControlMessage] = (
            asyncio.Queue()
        )
        inbound_task = asyncio.create_task(
            self._consume_runner_messages(
                request_iterator,
                outbound,
                runtime_id=accepted.runtime_id,
                generation=accepted.generation,
            )
        )
        operation_task = asyncio.create_task(
            self._relay_runner_operations(
                outbound,
                runtime_id=accepted.runtime_id,
                generation=accepted.generation,
            )
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=first_message.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=accepted.runtime_id,
                runner_id=accepted.runner_id,
                connection_id=accepted.connection_id,
                generation=accepted.generation,
                heartbeat_interval_seconds=accepted.heartbeat_interval_seconds,
            ),
        )
        try:
            async for message in _outbound_messages(
                outbound,
                inbound_task,
                operation_task,
            ):
                yield message
        finally:
            _LOGGER.info(
                "Runtime Runner stream closing",
                extra={
                    "runtime_id": accepted.runtime_id,
                    "runner_id": accepted.runner_id,
                    "connection_id": accepted.connection_id,
                    "runner_generation": accepted.generation,
                },
            )
            await self._record_runner_stream_closed(accepted, registration)
            for task in (inbound_task, operation_task):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _record_runner_stream_closed(
        self,
        accepted: RuntimeRunnerRegistrationAccepted,
        registration: RuntimeRunnerRegistration,
    ) -> None:
        try:
            await self._state_sink.record_runner_state(
                SharedRunnerStateReport(
                    runtime_id=accepted.runtime_id,
                    runner_id=accepted.runner_id,
                    runner_generation=accepted.generation,
                    runner_state=SharedRunnerState.UNKNOWN,
                    capabilities=registration.capabilities.values,
                    active_operation_ids=(),
                    health="stream_closed",
                    diagnostic={
                        "reason": "runner_stream_closed",
                        "connection_id": accepted.connection_id,
                    },
                    workspace_path=registration.workspace_path,
                    reported_at=datetime.now(UTC),
                )
            )
        except Exception:
            _LOGGER.warning(
                "Failed to persist Runtime Runner stream close state",
                exc_info=True,
                extra={
                    "runtime_id": accepted.runtime_id,
                    "runner_id": accepted.runner_id,
                    "runner_generation": accepted.generation,
                },
            )

    async def _consume_runner_messages(
        self,
        request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerControlMessage],
        *,
        runtime_id: str,
        generation: int,
    ) -> None:
        async for message in request_iterator:
            payload = message.WhichOneof("payload")
            if payload == "heartbeat":
                ok = await self._control_protocol.heartbeat_runner(
                    runtime_id=runtime_id,
                    generation=generation,
                    heartbeat_at=datetime.now(UTC),
                )
                if not ok:
                    _LOGGER.warning(
                        "Runtime Runner heartbeat rejected",
                        extra={
                            "runtime_id": runtime_id,
                            "runner_generation": generation,
                            "request_id": message.request_id,
                        },
                    )
                    await outbound.put(
                        _error(message.request_id, "STALE_RUNNER_GENERATION")
                    )
                    return
                await outbound.put(
                    runtime_runner_control_pb2.RunnerControlMessage(
                        request_id=message.request_id,
                        heartbeat_ack=runtime_runner_control_pb2.RunnerHeartbeatAck(
                            monotonic_sequence=message.heartbeat.monotonic_sequence,
                        ),
                    )
                )
                continue
            if payload == "state_report":
                report = runner_state_report_from_message(message.state_report)
                await self._state_sink.record_runner_state(report)
                _LOGGER.info(
                    "Runtime Runner state report persisted",
                    extra={
                        "runtime_id": report.runtime_id,
                        "runner_id": report.runner_id,
                        "runner_generation": report.runner_generation,
                        "runner_state": report.runner_state.value,
                        "active_operation_count": len(report.active_operation_ids),
                    },
                )
                continue
            if payload == "operation_event":
                await self._append_runner_event(message)

    async def _relay_runner_operations(
        self,
        outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerControlMessage],
        *,
        runtime_id: str,
        generation: int,
    ) -> None:
        while True:
            envelope = await self._control_protocol.claim_next_runner_request(
                runtime_id=runtime_id,
                generation=generation,
                consumer_id=self._consumer_id,
                block_ms=self._operation_block_ms,
            )
            if envelope is None:
                await asyncio.sleep(max(self._operation_block_ms, 1) / 1000)
                continue
            _LOGGER.info(
                "Runtime Runner operation routed",
                extra={
                    "runtime_id": runtime_id,
                    "runner_generation": generation,
                    "request_id": envelope.request_id,
                    "operation_type": envelope.operation_type,
                },
            )
            outbound.put_nowait(
                runtime_runner_control_pb2.RunnerControlMessage(
                    request_id=envelope.request_id,
                    operation_request=await self._runner_operation(envelope),
                )
            )

    async def _runner_operation(
        self,
        envelope: RuntimeRequestEnvelope,
    ) -> runtime_runner_control_pb2.RunnerOperationRequest:
        payload = envelope.payload.get("payload", {})
        if not isinstance(payload, dict):
            raise ValueError("Runner operation payload must be an object")
        message = runtime_runner_control_pb2.RunnerOperationRequest(
            runtime_id=envelope.runtime_id,
            runner_generation=envelope.generation,
            operation_type=envelope.operation_type,
            reply_stream_id=envelope.reply_stream_id,
            body_stream_id=envelope.body_stream_id or "",
            background=bool(envelope.payload.get("background")),
        )
        _copy_operation_payload(message, envelope.operation_type, payload)
        if envelope.deadline_at is not None:
            message.deadline_at.CopyFrom(_timestamp(envelope.deadline_at))
        if envelope.body_stream_id:
            message.body_chunks.extend(
                [
                    runtime_runner_control_pb2.RunnerBodyChunk(
                        chunk_id=record.chunk.chunk_id,
                        data=record.chunk.data,
                        final=record.chunk.final,
                    )
                    for record in await self._read_all_body_chunks(
                        envelope.body_stream_id
                    )
                ]
            )
        return message

    async def _read_all_body_chunks(
        self, body_stream_id: str
    ) -> list[RuntimeBodyChunkRecord]:
        records: list[RuntimeBodyChunkRecord] = []
        after_cursor: str | None = None
        while True:
            batch = await self._coordination_store.read_body_chunks(
                body_stream_id,
                after_cursor=after_cursor,
                limit=_BODY_CHUNK_READ_LIMIT,
            )
            if not batch:
                return records
            records.extend(batch)
            if any(record.chunk.final for record in batch):
                return records
            after_cursor = batch[-1].cursor

    async def _append_runner_event(
        self,
        message: runtime_runner_control_pb2.RunnerMessage,
    ) -> None:
        event = runner_event_from_message(
            message.operation_event,
            request_id=message.request_id,
        )
        operation_id = f"operation:{event.request_id}"
        operation = await self._coordination_store.get_operation(operation_id)
        if operation is None:
            return
        await self._control_protocol.append_reply_event(
            RuntimeReplyEvent(
                request_id=event.request_id,
                runtime_id=event.runtime_id,
                generation=event.generation,
                event_type=RuntimeReplyEventType(event.event_type.value),
                payload=dict(event.payload),
                created_at=event.created_at,
                final=event.final,
            ),
            reply_stream_id=operation.reply_stream_id,
            operation_id=operation_id,
            expected_target=RuntimeCoordinationTarget.RUNNER,
            expected_subject_id=event.runtime_id,
        )


def add_runtime_runner_control_servicer(
    server: grpc.aio.Server,
    *,
    control_protocol: RuntimeControlProtocolService,
    coordination_store: RuntimeCoordinationStore,
    state_sink: RuntimeRunnerStateSink,
    owner_replica_id: str,
    consumer_id: str,
    operation_block_ms: int = _DEFAULT_OPERATION_BLOCK_MS,
) -> None:
    """Add the Agent Runtime Runner Control servicer to a gRPC server."""
    runtime_runner_control_pb2_grpc.add_RuntimeRunnerControlServicer_to_server(
        RuntimeRunnerControlGrpcServicer(
            control_protocol=control_protocol,
            coordination_store=coordination_store,
            state_sink=state_sink,
            owner_replica_id=owner_replica_id,
            consumer_id=consumer_id,
            operation_block_ms=operation_block_ms,
        ),
        server,
    )


async def _first_register_message(
    request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
    context: grpc.aio.ServicerContext[
        runtime_runner_control_pb2.RunnerMessage,
        runtime_runner_control_pb2.RunnerControlMessage,
    ],
) -> runtime_runner_control_pb2.RunnerMessage:
    try:
        first_message = await anext(request_iterator)
    except StopAsyncIteration:
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runner register message required",
        )
        raise AssertionError("unreachable") from None
    if first_message.WhichOneof("payload") != "register":
        await context.abort(
            grpc.StatusCode.INVALID_ARGUMENT,
            "Runner register message required",
        )
        raise AssertionError("unreachable") from None
    return first_message


async def _outbound_messages(
    outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerControlMessage],
    inbound_task: asyncio.Task[None],
    operation_task: asyncio.Task[None],
) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
    get_task = asyncio.create_task(outbound.get())
    try:
        while True:
            done, _pending = await asyncio.wait(
                {inbound_task, operation_task, get_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if get_task in done:
                yield get_task.result()
                get_task = asyncio.create_task(outbound.get())
                continue
            for task in (inbound_task, operation_task):
                if task in done:
                    await task
                    return
    finally:
        get_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await get_task


def _registration(
    message: runtime_runner_control_pb2.RunnerMessage,
    *,
    owner_replica_id: str,
) -> RuntimeRunnerRegistration:
    register = message.register
    return RuntimeRunnerRegistration(
        runtime_id=register.runtime_id,
        runner_id=register.runner_id,
        protocol_version=register.protocol_version,
        capabilities=RuntimeProtocolCapabilities(tuple(register.capabilities)),
        health=register.health,
        workspace_path=register.workspace_path,
        metadata=dict(register.metadata),
        auth_credential_id=register.auth_credential_id,
        connection_id=message.connection_id,
        owner_replica_id=owner_replica_id,
    )


def _copy_operation_payload(
    message: runtime_runner_control_pb2.RunnerOperationRequest,
    operation_type: str,
    payload: dict[str, JsonValue],
) -> None:
    if operation_type == "bash":
        message.bash.command = _str_payload(payload, "command")
        timeout_seconds = _optional_int_payload(payload, "timeout_seconds")
        if timeout_seconds is not None:
            message.bash.timeout_seconds = timeout_seconds
        env = payload.get("env")
        if isinstance(env, dict):
            message.bash.env.update(
                {
                    str(key): value
                    for key, value in env.items()
                    if isinstance(value, str)
                }
            )
        return
    if operation_type in {"file.read", "file.download"}:
        message.file_read.path = _str_payload(payload, "path")
        message.file_read.offset = _int_payload(payload, "offset")
        max_bytes = _optional_int_payload(payload, "max_bytes")
        if max_bytes is not None:
            message.file_read.max_bytes = max_bytes
        return
    if operation_type in {"file.write", "file.upload"}:
        message.file_write.path = _str_payload(payload, "path")
        message.file_write.total_bytes = _int_payload(payload, "total_bytes")
        return
    if operation_type == "file.list":
        message.file_list.path = _str_payload(payload, "path")
        message.file_list.recursive = _bool_payload(payload, "recursive")
        message.file_list.exclude_patterns.extend(
            _str_list_payload(payload, "exclude_patterns")
        )
        return
    if operation_type == "file.grep":
        message.file_grep.path = _str_payload(payload, "path")
        message.file_grep.pattern = _str_payload(payload, "pattern")
        recursive = _optional_bool_payload(payload, "recursive")
        if recursive is not None:
            message.file_grep.recursive = recursive
        message.file_grep.exclude_patterns.extend(
            _str_list_payload(payload, "exclude_patterns")
        )
        message.file_grep.max_matching_files = _int_payload(
            payload, "max_matching_files"
        )
        message.file_grep.max_lines_per_file = _int_payload(
            payload, "max_lines_per_file"
        )
        return
    if operation_type == "file.stat":
        message.file_stat.path = _str_payload(payload, "path")
        return
    if operation_type == "process.start":
        message.process_start.command = _str_payload(payload, "command")
        workdir = _optional_str_payload(payload, "workdir")
        if workdir is not None:
            message.process_start.workdir = workdir
        message.process_start.yield_time_ms = _int_payload(payload, "yield_time_ms")
        message.process_start.max_output_bytes = _int_payload(
            payload, "max_output_bytes"
        )
        message.process_start.owner_session_id = _str_payload(
            payload, "owner_session_id"
        )
        env = payload.get("env")
        if isinstance(env, dict):
            message.process_start.env.update(
                {
                    str(key): value
                    for key, value in env.items()
                    if isinstance(value, str)
                }
            )
        return
    if operation_type == "process.write":
        message.process_write.process_id = _str_payload(payload, "process_id")
        message.process_write.stdin = _str_payload(payload, "stdin")
        message.process_write.yield_time_ms = _int_payload(payload, "yield_time_ms")
        message.process_write.max_output_bytes = _int_payload(
            payload, "max_output_bytes"
        )
        message.process_write.owner_session_id = _str_payload(
            payload, "owner_session_id"
        )
        return
    if operation_type == "file.delete":
        message.file_delete.path = _str_payload(payload, "path")
        message.file_delete.recursive = _bool_payload(payload, "recursive")
        return
    if operation_type == "file.mkdir":
        message.file_mkdir.path = _str_payload(payload, "path")
        message.file_mkdir.parents = _bool_payload(payload, "parents")
        return
    if operation_type == "file.move":
        message.file_move.source_path = _str_payload(payload, "source_path")
        message.file_move.destination_path = _str_payload(payload, "destination_path")
        message.file_move.overwrite = _bool_payload(payload, "overwrite")
        return
    if operation_type == "process.terminate_session":
        message.process_terminate_session.owner_session_id = _str_payload(
            payload, "owner_session_id"
        )
        return
    if operation_type == "file.bulk_delete":
        message.file_bulk_delete.paths.extend(_str_list_payload(payload, "paths"))
        message.file_bulk_delete.recursive = _bool_payload(payload, "recursive")
        return
    if operation_type == "file.bulk_move":
        message.file_bulk_move.source_paths.extend(
            _str_list_payload(payload, "source_paths")
        )
        message.file_bulk_move.destination_directory = _str_payload(
            payload, "destination_directory"
        )
        message.file_bulk_move.overwrite = _bool_payload(payload, "overwrite")
        return


def _str_payload(payload: dict[str, JsonValue], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _optional_str_payload(payload: dict[str, JsonValue], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _int_payload(payload: dict[str, JsonValue], key: str) -> int:
    value = _optional_int_payload(payload, key)
    return value if value is not None else 0


def _optional_int_payload(payload: dict[str, JsonValue], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _bool_payload(payload: dict[str, JsonValue], key: str) -> bool:
    value = payload.get(key)
    return value if isinstance(value, bool) else False


def _optional_bool_payload(payload: dict[str, JsonValue], key: str) -> bool | None:
    value = payload.get(key)
    return value if isinstance(value, bool) else None


def _str_list_payload(payload: dict[str, JsonValue], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value.astimezone(UTC))
    return timestamp


def _error(
    request_id: str,
    code: str,
    message: str | None = None,
) -> runtime_runner_control_pb2.RunnerControlMessage:
    return runtime_runner_control_pb2.RunnerControlMessage(
        request_id=request_id,
        error=runtime_runner_control_pb2.RunnerError(
            code=code,
            message=message or code,
        ),
    )
