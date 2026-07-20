"""gRPC Runner Control client for Runtime Runner processes."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
import contextlib
from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

import grpc
from google.protobuf import timestamp_pb2

from azents_runtime_control.proto import (
    runtime_runner_control_pb2,
    runtime_runner_control_pb2_grpc,
)
from azents_runtime_control.runner import (
    JsonValue,
    RunnerBodyChunk,
    RunnerControlClient,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerOperationHandler,
    RunnerRegistration,
    RunnerRegistrationAccepted,
    RunnerStateReport,
    RuntimeRunnerEventType,
    RuntimeRunnerState,
)


class RunnerControlStream(Protocol):
    """Callable gRPC stream constructor."""

    def __call__(
        self,
        request_iterator: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        /,
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        """Open a bidirectional Runtime Control stream."""
        ...


class RuntimeRunnerControlStreamClosed(RuntimeError):
    """Runner Control gRPC stream closed before the requested operation finished."""


class GrpcRunnerControlClient(RunnerControlClient):
    """RunnerControlClient implementation backed by a bidirectional gRPC stream."""

    def __init__(
        self,
        stream: RunnerControlStream,
        *,
        channel: grpc.aio.Channel | None = None,
        heartbeat_ack_timeout_seconds: float = 10.0,
        control_auth_token: str | None = None,
    ) -> None:
        """Initialize the gRPC client with a stream callable."""
        self._stream = stream
        self._channel = channel
        self._heartbeat_ack_timeout_seconds = heartbeat_ack_timeout_seconds
        self._metadata = _auth_metadata(control_auth_token)
        self._outbound: asyncio.Queue[runtime_runner_control_pb2.RunnerMessage] = (
            asyncio.Queue()
        )
        self._operation_handler: RunnerOperationHandler | None = None
        self._pending_heartbeat_acks: dict[str, asyncio.Future[bool]] = {}
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
        heartbeat_ack_timeout_seconds: float = 10.0,
        control_auth_token: str | None = None,
    ) -> "GrpcRunnerControlClient":
        """Create a client using an insecure gRPC channel."""
        channel = grpc.aio.insecure_channel(endpoint)
        stub = runtime_runner_control_pb2_grpc.RuntimeRunnerControlStub(channel)
        return cls(
            stub.ConnectRunner,
            channel=channel,
            heartbeat_ack_timeout_seconds=heartbeat_ack_timeout_seconds,
            control_auth_token=control_auth_token,
        )

    def set_operation_handler(self, handler: RunnerOperationHandler) -> None:
        """Set the direct operation admission handler."""
        self._operation_handler = handler

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
        if self._metadata is None:
            responses = self._stream(outbound)
        else:
            responses = self._stream(outbound, metadata=self._metadata)
        self._receiver_task = asyncio.create_task(self._receive(responses))
        return await self._accepted

    async def heartbeat_runner(
        self,
        *,
        runtime_id: str,
        generation: int,
        heartbeat_at: datetime,
    ) -> bool:
        """Send a heartbeat and wait for the matching ack."""
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
        responses: AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage],
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
                future.set_result(True)
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


def _auth_metadata(token: str | None) -> tuple[tuple[str, str], ...] | None:
    if token is None or not token:
        return None
    return (("authorization", f"Bearer {token}"),)


def _register_message(
    registration: RunnerRegistration,
    *,
    connection_id: str,
    request_id: str,
) -> runtime_runner_control_pb2.RunnerMessage:
    return runtime_runner_control_pb2.RunnerMessage(
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
    return runtime_runner_control_pb2.RunnerStateReport(
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
        deadline_at=_optional_datetime(operation, "deadline_at"),
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
    if payload_kind == "file_write":
        return {
            "path": operation.file_write.path,
            "total_bytes": operation.file_write.total_bytes,
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
    if payload_kind == "git_remove_worktree":
        payload = operation.git_remove_worktree
        return {
            "source_project_path": payload.source_project_path,
            "worktree_path": payload.worktree_path,
            "force": payload.force,
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
    if "bytes_written" in payload:
        message.file_write.bytes_written = _int_payload(payload, "bytes_written")
        return
    if "matches" in payload:
        message.file_glob.entries.extend(
            _file_list_entries(payload, field_name="matches")
        )
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
        return
    if "base_commit" in payload:
        worktree = message.git_create_worktree
        worktree.base_commit = _str_payload(payload, "base_commit")
        worktree.worktree_path = _str_payload(payload, "worktree_path")
        worktree.branch_name = _str_payload(payload, "branch_name")
        return
    if "removed_worktree_path" in payload:
        message.git_remove_worktree.worktree_path = _str_payload(
            payload, "removed_worktree_path"
        )
        return
    if "deleted_branch_name" in payload:
        message.git_delete_branch.branch_name = _str_payload(
            payload, "deleted_branch_name"
        )
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
        return {
            "error_code": message.final_error.error_code,
            "error_message": message.final_error.error_message,
        }
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
    if result_kind == "file_write":
        return {"bytes_written": message.file_write.bytes_written}
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
        }
    if result_kind == "git_create_worktree":
        return {
            "base_commit": message.git_create_worktree.base_commit,
            "worktree_path": message.git_create_worktree.worktree_path,
            "branch_name": message.git_create_worktree.branch_name,
        }
    if result_kind == "git_remove_worktree":
        return {"removed_worktree_path": message.git_remove_worktree.worktree_path}
    if result_kind == "git_delete_branch":
        return {"deleted_branch_name": message.git_delete_branch.branch_name}
    return {}


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
    field_name: str,
) -> datetime | None:
    if not message.HasField(field_name):
        return None
    return _datetime(message.deadline_at)


__all__ = [
    "GrpcRunnerControlClient",
    "RunnerControlStream",
    "RuntimeRunnerControlStreamClosed",
    "runner_event_from_message",
    "runner_state_report_from_message",
]
