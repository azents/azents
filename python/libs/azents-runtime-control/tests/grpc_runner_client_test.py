"""gRPC Runner Control client tests."""

# pyright: reportAttributeAccessIssue=false
# protobuf generated modules expose dynamic message attributes.

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest
from google.protobuf import timestamp_pb2

from azents_runtime_control.grpc_runner_client import (
    GrpcRunnerControlClient,
    RuntimeRunnerControlStreamClosed,
    runner_event_from_message,
)
from azents_runtime_control.proto import runtime_runner_control_pb2
from azents_runtime_control.runner import (
    RunnerOperationCancel,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RunnerRegistration,
    RuntimeRunnerEventType,
)


@pytest.mark.asyncio
async def test_grpc_client_registers_heartbeats_claims_and_appends_events() -> None:
    """The client maps the gRPC stream onto the RunnerControlClient protocol."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        sent.append(register)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-1",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="process.start",
                owner_session_id="session-1",
                process_start=runtime_runner_control_pb2.ProcessStartOperationPayload(
                    command="python -m http.server",
                    workdir="/workspace/agent",
                    yield_time_ms=1000,
                    max_output_bytes=4096,
                    env={"PYTHONUNBUFFERED": "1"},
                ),
                reply_stream_id="reply:req-1",
            ),
        )
        operation_start = await anext(requests)
        sent.append(operation_start)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=operation_start.request_id,
            operation_start_ack=runtime_runner_control_pb2.RunnerOperationStartAck(
                allowed=True
            ),
        )
        heartbeat = await anext(requests)
        sent.append(heartbeat)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=heartbeat.request_id,
            heartbeat_ack=runtime_runner_control_pb2.RunnerHeartbeatAck(
                monotonic_sequence=heartbeat.heartbeat.monotonic_sequence,
            ),
        )
        event = await anext(requests)
        sent.append(event)

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(operation_received.wait(), timeout=1)
    operation = received[0]

    assert accepted.generation == 7
    assert operation.request_id == "req-1"
    assert operation.operation_type == "process.start"
    assert operation.owner_session_id == "session-1"
    assert operation.payload == {
        "command": "python -m http.server",
        "workdir": "/workspace/agent",
        "yield_time_ms": 1000,
        "max_output_bytes": 4096,
        "env": {"PYTHONUNBUFFERED": "1"},
    }
    assert await client.start_runner_operation(operation)
    assert await client.heartbeat_runner(
        runtime_id="runtime-1",
        generation=accepted.generation,
        heartbeat_at=_now(),
    )

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-1",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "process_id": "proc_123",
                "status": "running",
                "stdout": "Serving HTTP",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
                "stdout_omitted_bytes": 0,
                "stderr_omitted_bytes": 0,
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if len(sent) >= 4:
            break
        await asyncio.sleep(0)

    assert sent[0].WhichOneof("payload") == "register"
    assert sent[0].register.workspace_path == "/workspace/agent"
    assert sent[1].WhichOneof("payload") == "operation_start"
    assert sent[1].operation_start.operation_id == "operation:req-1"
    assert sent[2].WhichOneof("payload") == "heartbeat"
    event = sent[3].operation_event
    assert event.event_type == "final_success"
    assert event.WhichOneof("payload") == "final_success"
    assert event.final_success.WhichOneof("result") == "process"
    assert event.final_success.process.process_id == "proc_123"
    assert event.final_success.process.status == "running"
    assert not event.final_success.process.HasField("exit_code")
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_maps_file_glob_payload_and_result() -> None:
    """File glob requests and final matches round-trip through protobuf."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-glob",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="file.glob",
                file_glob=runtime_runner_control_pb2.FileGlobOperationPayload(
                    pattern="/workspace/agent/**/*.py",
                    exclude_patterns=[".git", "node_modules"],
                ),
                reply_stream_id="reply:req-glob",
            ),
        )
        event = await anext(requests)
        sent.append(event)

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(operation_received.wait(), timeout=1)

    assert received[0].operation_type == "file.glob"
    assert received[0].payload == {
        "pattern": "/workspace/agent/**/*.py",
        "exclude_patterns": [".git", "node_modules"],
    }

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-glob",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "matches": [
                    {
                        "path": "/workspace/agent/src/app.py",
                        "type": "file",
                        "size_bytes": 12,
                        "modified_at": "2026-07-20T00:00:00+00:00",
                    }
                ]
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if sent:
            break
        await asyncio.sleep(0)

    event = sent[0].operation_event
    assert event.final_success.WhichOneof("result") == "file_glob"
    assert event.final_success.file_glob.entries[0].path == (
        "/workspace/agent/src/app.py"
    )
    assert event.final_success.file_glob.entries[0].type == "file"
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_backpressures_operation_delivery() -> None:
    """The stream waits for scheduler admission before reading another operation."""
    first_received = asyncio.Event()
    release_first = asyncio.Event()
    second_received = asyncio.Event()
    received: list[RunnerOperationEnvelope] = []
    release_stream = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        if operation.request_id == "req-1":
            first_received.set()
            await release_first.wait()
        else:
            second_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield _operation_message("req-1")
        yield _operation_message("req-2")
        await release_stream.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    assert accepted.generation == 7
    await asyncio.wait_for(first_received.wait(), timeout=1)

    assert [operation.request_id for operation in received] == ["req-1"]
    assert not second_received.is_set()

    release_first.set()
    await asyncio.wait_for(second_received.wait(), timeout=1)
    assert [operation.request_id for operation in received] == ["req-1", "req-2"]

    release_stream.set()
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_delivers_operation_cancel_command() -> None:
    """The client dispatches typed cancellation commands from Control."""
    received: list[RunnerOperationCancel] = []
    cancel_received = asyncio.Event()
    release_stream = asyncio.Event()

    async def handle_cancel(cancel: RunnerOperationCancel) -> None:
        received.append(cancel)
        cancel_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-cancel",
            operation_cancel=runtime_runner_control_pb2.RunnerOperationCancel(
                runtime_id="runtime-1",
                operation_id="operation:req-patch",
            ),
        )
        await release_stream.wait()

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_cancel_handler(handle_cancel)
    await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(cancel_received.wait(), timeout=1)

    assert received == [
        RunnerOperationCancel(
            runtime_id="runtime-1",
            operation_id="operation:req-patch",
        )
    ]
    release_stream.set()
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_close_suppresses_completed_stream_failure() -> None:
    """A control-plane stream close should not escape during client cleanup."""
    closed = asyncio.Event()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        closed.set()
        raise RuntimeRunnerControlStreamClosed("stream closed")

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(closed.wait(), timeout=1)
    await asyncio.sleep(0)

    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_sends_runner_credential_metadata() -> None:
    """The client sends its signed Runner credential as bearer metadata."""
    observed_metadata: list[tuple[str, str]] = []

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del requests
        observed_metadata.extend(metadata or ())
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="register",
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id="runtime-1",
                runner_id="runner-1",
                connection_id="connection-1",
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await client.close()

    assert ("authorization", "Bearer runner-token") in observed_metadata


@pytest.mark.asyncio
async def test_grpc_client_maps_file_apply_patch_request_and_success() -> None:
    """Patch request metadata, body chunks, and success changes round-trip."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-patch",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="file.apply_patch",
                owner_session_id="session-1",
                file_apply_patch=(
                    runtime_runner_control_pb2.FileApplyPatchOperationPayload(
                        base_path="/workspace/agent/project",
                        total_bytes=12,
                        schema_version=1,
                    )
                ),
                body_chunks=[
                    runtime_runner_control_pb2.RunnerBodyChunk(
                        chunk_id=1,
                        data=b"patch-body",
                        final=True,
                    )
                ],
                reply_stream_id="reply:req-patch",
                body_stream_id="body:req-patch",
            ),
        )
        event = await anext(requests)
        sent.append(event)

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(operation_received.wait(), timeout=1)
    operation = received[0]

    assert operation.operation_type == "file.apply_patch"
    assert operation.payload == {
        "base_path": "/workspace/agent/project",
        "total_bytes": 12,
        "schema_version": 1,
    }
    assert operation.body_chunks[0].data == b"patch-body"

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-patch",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "changes": [
                    {
                        "path": "src/app.py",
                        "action": "update",
                        "added_lines": 2,
                        "removed_lines": 1,
                        "content_sha256": "abc123",
                    }
                ]
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if sent:
            break
        await asyncio.sleep(0)

    event = sent[0].operation_event
    assert event.final_success.WhichOneof("result") == "file_apply_patch"
    change = event.final_success.file_apply_patch.changes[0]
    assert change.path == "src/app.py"
    assert change.action == "update"
    assert change.added_lines == 2
    assert change.removed_lines == 1
    assert change.content_sha256 == "abc123"
    await client.close()


def test_grpc_client_maps_file_apply_patch_failure_detail() -> None:
    """Patch failure details survive protobuf-to-domain conversion."""
    message = runtime_runner_control_pb2.RunnerOperationEvent(
        runtime_id="runtime-1",
        operation_id="operation:req-patch",
        generation=7,
        event_type="final_error",
        created_at=_timestamp(_now()),
        final=True,
        final_error=runtime_runner_control_pb2.RunnerOperationFinalErrorPayload(
            error_code="PATCH_COMMIT_FAILED",
            error_message="Source changed before delete",
            file_apply_patch=runtime_runner_control_pb2.FileApplyPatchFailure(
                phase="commit",
                reason="source_changed",
                applied=[
                    runtime_runner_control_pb2.RuntimeFilePatchChange(
                        path="src/app.py",
                        action="update",
                        added_lines=2,
                        removed_lines=1,
                        content_sha256="abc123",
                    )
                ],
                failed=runtime_runner_control_pb2.RuntimeFilePatchOperation(
                    path="src/legacy.py",
                    action="delete",
                ),
                not_attempted=[
                    runtime_runner_control_pb2.RuntimeFilePatchOperation(
                        path="src/after.py",
                        action="add",
                    )
                ],
                exact=True,
            ),
        ),
    )

    event = runner_event_from_message(message, request_id="req-patch")

    assert event.payload == {
        "error_code": "PATCH_COMMIT_FAILED",
        "error_message": "Source changed before delete",
        "file_apply_patch": {
            "phase": "commit",
            "reason": "source_changed",
            "applied": [
                {
                    "path": "src/app.py",
                    "action": "update",
                    "added_lines": 2,
                    "removed_lines": 1,
                    "content_sha256": "abc123",
                }
            ],
            "failed": {"path": "src/legacy.py", "action": "delete"},
            "not_attempted": [{"path": "src/after.py", "action": "add"}],
            "exact": True,
        },
    }


@pytest.mark.asyncio
async def test_grpc_client_maps_file_edit_request_and_success() -> None:
    """Native edit request fields and replacement count round-trip through gRPC."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-edit",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="file.edit",
                owner_session_id="session-1",
                file_edit=runtime_runner_control_pb2.FileEditOperationPayload(
                    path="/workspace/agent/note.txt",
                    old_string="before",
                    new_string="after",
                    replace_all=True,
                ),
                reply_stream_id="reply:req-edit",
            ),
        )
        sent.append(await anext(requests))

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(operation_received.wait(), timeout=1)

    assert received[0].operation_type == "file.edit"
    assert received[0].payload == {
        "path": "/workspace/agent/note.txt",
        "old_string": "before",
        "new_string": "after",
        "replace_all": True,
    }

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-edit",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={"replacements": 3},
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if sent:
            break
        await asyncio.sleep(0)

    event = sent[0].operation_event
    assert event.final_success.WhichOneof("result") == "file_edit"
    assert event.final_success.file_edit.replacements == 3
    await client.close()


def _timestamp(value: datetime) -> timestamp_pb2.Timestamp:
    timestamp = timestamp_pb2.Timestamp()
    timestamp.FromDatetime(value)
    return timestamp


def _operation_message(
    request_id: str,
) -> runtime_runner_control_pb2.RunnerControlMessage:
    return runtime_runner_control_pb2.RunnerControlMessage(
        request_id=request_id,
        operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
            runtime_id="runtime-1",
            runner_generation=7,
            operation_type="file.stat",
            owner_session_id="session-1",
            file_stat=runtime_runner_control_pb2.FileStatOperationPayload(
                path="/workspace/agent"
            ),
            reply_stream_id=f"reply:{request_id}",
        ),
    )


def _registration() -> RunnerRegistration:
    return RunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="agent-runtime-runner.v1",
        capabilities=("bash", "file.read"),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={"workspace_path_source": "provider"},
        auth_credential_id="credential-1",
    )


def _now() -> datetime:
    return datetime(2026, 5, 25, tzinfo=UTC)


@pytest.mark.asyncio
async def test_grpc_client_maps_git_operation_payloads_and_results() -> None:
    """Git operation payloads and final results round-trip through protobuf."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-git",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="create_git_worktree",
                git_create_worktree=(
                    runtime_runner_control_pb2.GitCreateWorktreeOperationPayload(
                        source_project_path="/workspace/agent/repo",
                        worktree_path="/workspace/agent/.azents/worktrees/session/repo",
                        branch_name="azents/session",
                        starting_ref="main",
                    )
                ),
                reply_stream_id="reply:req-git",
            ),
        )
        event = await anext(requests)
        sent.append(event)

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )
    await asyncio.wait_for(operation_received.wait(), timeout=1)
    operation = received[0]

    assert operation.operation_type == "create_git_worktree"
    assert operation.payload == {
        "source_project_path": "/workspace/agent/repo",
        "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "branch_name": "azents/session",
        "starting_ref": "main",
    }

    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-git",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "base_commit": "abc123",
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "branch_name": "azents/session",
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if sent:
            break
        await asyncio.sleep(0)

    event = sent[0].operation_event
    assert event.final_success.WhichOneof("result") == "git_create_worktree"
    assert event.final_success.git_create_worktree.base_commit == "abc123"
    assert (
        event.final_success.git_create_worktree.worktree_path
        == "/workspace/agent/.azents/worktrees/session/repo"
    )
    await client.close()


@pytest.mark.asyncio
async def test_grpc_client_maps_git_worktree_integrity_operations() -> None:
    """Inspection and guarded cleanup fields round-trip through protobuf."""
    sent: list[runtime_runner_control_pb2.RunnerMessage] = []
    received: list[RunnerOperationEnvelope] = []
    operation_received = asyncio.Event()

    async def handle_operation(operation: RunnerOperationEnvelope) -> None:
        received.append(operation)
        operation_received.set()

    async def stream(
        requests: AsyncIterator[runtime_runner_control_pb2.RunnerMessage],
        *,
        metadata: Sequence[tuple[str, str]] | None = None,
    ) -> AsyncIterator[runtime_runner_control_pb2.RunnerControlMessage]:
        del metadata
        register = await anext(requests)
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id=register.request_id,
            register_accepted=runtime_runner_control_pb2.RunnerRegisterAccepted(
                runtime_id=register.register.runtime_id,
                runner_id=register.register.runner_id,
                connection_id=register.connection_id,
                generation=7,
                heartbeat_interval_seconds=20,
            ),
        )
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-inspect",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="inspect_git_worktree",
                owner_session_id="session-1",
                git_inspect_worktree=(
                    runtime_runner_control_pb2.GitInspectWorktreeOperationPayload(
                        source_project_path="/workspace/agent/repo",
                        worktree_path=(
                            "/workspace/agent/.azents/worktrees/session/repo"
                        ),
                        branch_name="azents/session",
                    )
                ),
                reply_stream_id="reply:req-inspect",
            ),
        )
        sent.append(await anext(requests))
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-remove",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="remove_git_worktree",
                owner_session_id="session-1",
                git_remove_worktree=(
                    runtime_runner_control_pb2.GitRemoveWorktreeOperationPayload(
                        source_project_path="/workspace/agent/repo",
                        worktree_path=(
                            "/workspace/agent/.azents/worktrees/session/repo"
                        ),
                        force=True,
                        branch_name="azents/session",
                    )
                ),
                reply_stream_id="reply:req-remove",
            ),
        )
        sent.append(await anext(requests))
        yield runtime_runner_control_pb2.RunnerControlMessage(
            request_id="req-delete-branch",
            operation_request=runtime_runner_control_pb2.RunnerOperationRequest(
                runtime_id="runtime-1",
                runner_generation=7,
                operation_type="delete_git_branch",
                owner_session_id="session-1",
                git_delete_branch=(
                    runtime_runner_control_pb2.GitDeleteBranchOperationPayload(
                        source_project_path="/workspace/agent/repo",
                        branch_name="azents/session",
                    )
                ),
                reply_stream_id="reply:req-delete-branch",
            ),
        )
        sent.append(await anext(requests))

    client = GrpcRunnerControlClient(stream, runner_auth_token="runner-token")
    client.set_operation_handler(handle_operation)
    accepted = await client.register_runner(
        _registration(),
        connection_id="connection-1",
        registered_at=_now(),
    )

    await asyncio.wait_for(operation_received.wait(), timeout=1)
    assert received[0].operation_type == "inspect_git_worktree"
    assert received[0].payload == {
        "source_project_path": "/workspace/agent/repo",
        "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "branch_name": "azents/session",
    }
    operation_received.clear()
    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-inspect",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
                "worktree_registered": True,
                "registered_branch_name": "azents/session",
                "target_kind": "directory",
                "dirty": True,
            },
            created_at=_now(),
            final=True,
        )
    )

    await asyncio.wait_for(operation_received.wait(), timeout=1)
    assert received[1].operation_type == "remove_git_worktree"
    assert received[1].payload == {
        "source_project_path": "/workspace/agent/repo",
        "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "force": True,
        "branch_name": "azents/session",
    }
    operation_received.clear()
    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-remove",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "removed_worktree_path": (
                    "/workspace/agent/.azents/worktrees/session/repo"
                ),
                "outcome": "already_absent",
            },
            created_at=_now(),
            final=True,
        )
    )

    await asyncio.wait_for(operation_received.wait(), timeout=1)
    assert received[2].operation_type == "delete_git_branch"
    assert received[2].payload == {
        "source_project_path": "/workspace/agent/repo",
        "branch_name": "azents/session",
    }
    await client.append_runner_event(
        RunnerOperationEvent(
            request_id="req-delete-branch",
            runtime_id="runtime-1",
            generation=accepted.generation,
            event_type=RuntimeRunnerEventType.FINAL_SUCCESS,
            payload={
                "deleted_branch_name": "azents/session",
                "outcome": "already_absent",
            },
            created_at=_now(),
            final=True,
        )
    )
    for _ in range(10):
        if len(sent) == 3:
            break
        await asyncio.sleep(0)

    inspect = sent[0].operation_event.final_success.git_inspect_worktree
    assert inspect.worktree_path == "/workspace/agent/.azents/worktrees/session/repo"
    assert inspect.registered is True
    assert inspect.registered_branch_name == "azents/session"
    assert inspect.target_kind == "directory"
    assert inspect.dirty is True

    removal = sent[1].operation_event.final_success.git_remove_worktree
    assert removal.worktree_path == "/workspace/agent/.azents/worktrees/session/repo"
    assert removal.outcome == "already_absent"

    branch = sent[2].operation_event.final_success.git_delete_branch
    assert branch.branch_name == "azents/session"
    assert branch.outcome == "already_absent"
    await client.close()


def test_grpc_client_reads_git_worktree_integrity_results() -> None:
    """Typed Git integrity results survive protobuf-to-domain conversion."""
    inspect_event = runner_event_from_message(
        runtime_runner_control_pb2.RunnerOperationEvent(
            runtime_id="runtime-1",
            operation_id="operation:req-inspect",
            generation=7,
            event_type="final_success",
            created_at=_timestamp(_now()),
            final=True,
            final_success=runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                git_inspect_worktree=(
                    runtime_runner_control_pb2.GitInspectWorktreeFinalSuccess(
                        worktree_path=(
                            "/workspace/agent/.azents/worktrees/session/repo"
                        ),
                        registered=True,
                        registered_branch_name="azents/session",
                        target_kind="directory",
                        dirty=False,
                    )
                )
            ),
        ),
        request_id="req-inspect",
    )
    removal_event = runner_event_from_message(
        runtime_runner_control_pb2.RunnerOperationEvent(
            runtime_id="runtime-1",
            operation_id="operation:req-remove",
            generation=7,
            event_type="final_success",
            created_at=_timestamp(_now()),
            final=True,
            final_success=runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                git_remove_worktree=(
                    runtime_runner_control_pb2.GitRemoveWorktreeFinalSuccess(
                        worktree_path=(
                            "/workspace/agent/.azents/worktrees/session/repo"
                        ),
                        outcome="removed",
                    )
                )
            ),
        ),
        request_id="req-remove",
    )
    branch_event = runner_event_from_message(
        runtime_runner_control_pb2.RunnerOperationEvent(
            runtime_id="runtime-1",
            operation_id="operation:req-delete-branch",
            generation=7,
            event_type="final_success",
            created_at=_timestamp(_now()),
            final=True,
            final_success=runtime_runner_control_pb2.RunnerOperationFinalSuccessPayload(
                git_delete_branch=(
                    runtime_runner_control_pb2.GitDeleteBranchFinalSuccess(
                        branch_name="azents/session",
                        outcome="deleted",
                    )
                )
            ),
        ),
        request_id="req-delete-branch",
    )

    assert inspect_event.payload == {
        "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "worktree_registered": True,
        "registered_branch_name": "azents/session",
        "target_kind": "directory",
        "dirty": False,
    }
    assert removal_event.payload == {
        "removed_worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "outcome": "removed",
    }
    assert branch_event.payload == {
        "deleted_branch_name": "azents/session",
        "outcome": "deleted",
    }
