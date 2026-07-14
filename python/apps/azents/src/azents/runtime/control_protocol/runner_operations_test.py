"""Runner operation client tests."""

import asyncio
import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from azents.runtime.control_protocol.data import (
    RuntimeProtocolCapabilities,
    RuntimeReplyAppendResult,
    RuntimeRunnerRegistration,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeBashResult,
    RuntimeFileDeleteResult,
    RuntimeFileListResult,
    RuntimeFileMkdirResult,
    RuntimeFileMoveResult,
    RuntimeFileReadResult,
    RuntimeFileStatResult,
    RuntimeGrepResult,
    RuntimeOperationTextDelta,
    RuntimeProcessOutputDelta,
    RuntimeProcessResult,
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    encode_file_chunk,
    runner_reply_target,
)
from azents.runtime.control_protocol.service import (
    RuntimeControlProtocolService,
)
from azents.runtime.coordination.data import (
    JsonValue,
    RuntimeBodyChunk,
    RuntimeReplyEvent,
    RuntimeReplyEventType,
)
from azents.runtime.coordination.memory import (
    InMemoryRuntimeCoordinationStore,
)


@pytest.mark.asyncio
async def test_run_bash_folds_stdout_stderr_and_final_exit_code() -> None:
    """Bash operation result is folded from reply stream events."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.run_bash(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            command="echo ok",
            timeout_seconds=30,
            env={"A": "B"},
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "bash"
    assert request.payload["owner_session_id"] == "session-1"
    assert request.payload["payload"] == {
        "command": "echo ok",
        "timeout_seconds": 30,
        "env": {"A": "B"},
    }

    await harness.reply(
        request.request_id, RuntimeReplyEventType.STDOUT, {"text": "ok"}
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.STDERR,
        {"text": "warn"},
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"exit_code": 0},
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeBashResult(
        stdout="ok",
        stderr="warn",
        exit_code=0,
        final_cursor="3",
    )


@pytest.mark.asyncio
async def test_run_bash_filters_interleaved_shared_reply_stream() -> None:
    """Skip events for other operations from shared reply stream."""
    harness = await _make_harness()
    first_task = asyncio.create_task(
        harness.client.run_bash(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            command="echo first",
            timeout_seconds=30,
            env=None,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    first_request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    second_task = asyncio.create_task(
        harness.client.run_bash(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            command="echo second",
            timeout_seconds=30,
            env=None,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    second_request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert first_request is not None
    assert second_request is not None

    await harness.reply(
        second_request.request_id,
        RuntimeReplyEventType.STDOUT,
        {"text": "second"},
    )
    await harness.reply(
        second_request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"exit_code": 0},
        final=True,
    )
    await harness.reply(
        first_request.request_id,
        RuntimeReplyEventType.STDOUT,
        {"text": "first"},
    )
    await harness.reply(
        first_request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"exit_code": 0},
        final=True,
    )

    first = await asyncio.wait_for(first_task, timeout=1)
    second = await asyncio.wait_for(second_task, timeout=1)
    assert first.stdout == "first"
    assert first.final_cursor == "4"
    assert second.stdout == "second"
    assert second.final_cursor == "2"


@pytest.mark.asyncio
async def test_run_bash_cancel_check_records_cancelled_final() -> None:
    """Foreground wait records a cancelled final event instead of hanging."""
    harness = await _make_harness()

    with pytest.raises(RuntimeRunnerOperationCanceledError):
        await harness.client.run_bash(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            command="sleep 60",
            timeout_seconds=30,
            env=None,
            deadline_at=_now() + timedelta(seconds=30),
            cancel_check=_always_cancel,
        )

    replies = await harness.control.read_replies(
        reply_stream_id="runner:runtime-1:generation:1:replies",
        after_cursor=None,
        limit=10,
    )
    assert replies[-1].event.final is True
    assert replies[-1].event.payload["error_code"] == "canceled"


@pytest.mark.asyncio
async def test_resume_file_read_continues_after_cursor() -> None:
    """File read resume returns only chunks after the supplied cursor."""
    harness = await _make_harness()
    await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.FILE_CHUNK,
            payload={"data_base64": encode_file_chunk(b"old")},
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    second = await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.FILE_CHUNK,
            payload={"data_base64": encode_file_chunk(b"new")},
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    assert isinstance(second, RuntimeReplyAppendResult)
    cursor = second.cursor
    await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.FINAL_SUCCESS,
            payload={},
            final=True,
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )

    result = await harness.client.resume_file_read(
        reply_stream_id="reply:req-1",
        after_cursor=cursor,
        deadline_at=_now() + timedelta(seconds=30),
    )

    assert isinstance(result, RuntimeFileReadResult)
    assert result.data == b""
    assert result.final_cursor == "3"


@pytest.mark.asyncio
async def test_read_file_collects_file_chunks_until_final() -> None:
    """File read operation collects file chunks from the reply stream."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.read_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/report.txt",
            offset=0,
            max_bytes=None,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.read"
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FILE_CHUNK,
        {"data_base64": encode_file_chunk(b"hello ")},
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FILE_CHUNK,
        {"data_base64": encode_file_chunk(b"world")},
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {},
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeFileReadResult(data=b"hello world", final_cursor="3")


@pytest.mark.asyncio
async def test_read_file_deadline_records_final_error_when_runner_drops_reply() -> None:
    """Record final error by deadline when file read reply is missing."""
    harness = await _make_harness()
    deadline_at = _now() + timedelta(milliseconds=10)

    with pytest.raises(RuntimeRunnerOperationFailedError, match="timed out"):
        await harness.client.read_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/missing-reply.txt",
            offset=0,
            max_bytes=None,
            deadline_at=deadline_at,
        )

    replies = await harness.control.read_replies(
        reply_stream_id="runner:runtime-1:generation:1:replies",
        after_cursor=None,
        limit=10,
    )
    assert replies[-1].event.final is True
    assert replies[-1].event.payload["error_code"] == "operation_timeout"


@pytest.mark.asyncio
async def test_write_file_uses_body_stream_chunks() -> None:
    """File write sends content through request body stream chunks."""
    harness = await _make_harness(body_chunk_size_bytes=3)
    task = asyncio.create_task(
        harness.client.write_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/out.txt",
            data=b"abcdefg",
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.body_stream_id is not None
    chunks = await harness.store.read_body_chunks(
        request.body_stream_id,
        after_cursor=None,
        limit=10,
    )
    assert [chunk.chunk.data for chunk in chunks] == [b"abc", b"def", b"g"]
    assert chunks[-1].chunk.final is True

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"bytes_written": 7},
        final=True,
    )
    result = await asyncio.wait_for(task, timeout=1)
    assert result.bytes_written == 7


@pytest.mark.asyncio
async def test_write_file_deadline_covers_all_body_chunks_before_dispatch() -> None:
    """Slow successful chunks share one deadline instead of resetting it."""
    store = _SlowBodyChunkStore(delay_seconds=0.03)
    harness = await _make_harness(
        body_chunk_size_bytes=1,
        coordination_store=store,
    )

    with pytest.raises(RuntimeRunnerOperationFailedError, match="timed out"):
        await asyncio.wait_for(
            harness.client.write_file(
                runtime_id="runtime-1",
                runner_generation=harness.runner_generation,
                owner_session_id="session-1",
                path="/workspace/agent/out.txt",
                data=b"abc",
                deadline_at=_now() + timedelta(milliseconds=70),
            ),
            timeout=0.3,
        )

    assert 0 < store.committed_chunks < 3
    assert store.append_attempts == store.committed_chunks + 1
    assert (
        await harness.control.claim_next_runner_request(
            runtime_id="runtime-1",
            generation=harness.runner_generation,
            consumer_id="runner-a",
            block_ms=0,
        )
        is None
    )


@pytest.mark.asyncio
async def test_run_bash_caller_cancellation_stays_cancelled_and_finalizes() -> None:
    """The overall deadline wrapper preserves explicit caller cancellation."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.run_bash(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            command="sleep 60",
            timeout_seconds=30,
            env=None,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=0.2)

    replies = await harness.control.read_replies(
        reply_stream_id=request.reply_stream_id,
        after_cursor=None,
        limit=10,
    )
    assert replies[-1].event.payload["error_code"] == "canceled"
    assert replies[-1].event.final is True


@pytest.mark.asyncio
async def test_list_files_returns_final_entries() -> None:
    """File list final payload is decoded into entries."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.list_files(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent",
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "entries": [
                {
                    "path": "/workspace/agent/a.txt",
                    "type": "file",
                    "size_bytes": 12,
                }
            ]
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert isinstance(result, RuntimeFileListResult)
    assert result.entries[0].path == "/workspace/agent/a.txt"
    assert result.entries[0].size_bytes == 12


@pytest.mark.asyncio
async def test_stat_file_returns_final_metadata() -> None:
    """Decode File stat final payload as metadata."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.stat_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/AGENTS.md",
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.stat"
    assert request.payload["payload"] == {"path": "/workspace/agent/AGENTS.md"}
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "path": "/workspace/agent/AGENTS.md",
            "kind": "file",
            "size_bytes": 12,
            "symlink": False,
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeFileStatResult(
        path="/workspace/agent/AGENTS.md",
        kind="file",
        size_bytes=12,
        symlink=False,
        real_path=None,
        resolved_kind=None,
        modified_at=None,
        final_cursor="1",
    )


@pytest.mark.asyncio
async def test_delete_file_returns_final_path() -> None:
    """File delete operation returns final deleted path."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.delete_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/old.txt",
            recursive=False,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.delete"
    assert request.payload["payload"] == {
        "path": "/workspace/agent/old.txt",
        "recursive": False,
    }
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"deleted_path": "/workspace/agent/old.txt"},
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeFileDeleteResult(
        path="/workspace/agent/old.txt",
        final_cursor="1",
    )


@pytest.mark.asyncio
async def test_mkdir_file_returns_final_path() -> None:
    """File mkdir operation returns final created path."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.mkdir_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent/reports",
            parents=True,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.mkdir"
    assert request.payload["payload"] == {
        "path": "/workspace/agent/reports",
        "parents": True,
    }
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"created_path": "/workspace/agent/reports"},
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeFileMkdirResult(
        path="/workspace/agent/reports",
        final_cursor="1",
    )


@pytest.mark.asyncio
async def test_move_file_returns_final_paths() -> None:
    """File move operation returns final source and destination paths."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.move_file(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            source_path="/workspace/agent/a.txt",
            destination_path="/workspace/agent/b.txt",
            overwrite=False,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.move"
    assert request.payload["payload"] == {
        "source_path": "/workspace/agent/a.txt",
        "destination_path": "/workspace/agent/b.txt",
        "overwrite": False,
    }
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "moved_source_path": "/workspace/agent/a.txt",
            "moved_destination_path": "/workspace/agent/b.txt",
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeFileMoveResult(
        source_path="/workspace/agent/a.txt",
        destination_path="/workspace/agent/b.txt",
        final_cursor="1",
    )


@pytest.mark.asyncio
async def test_grep_files_returns_final_matches() -> None:
    """File grep final payload is decoded into file and line matches."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.grep_files(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            path="/workspace/agent",
            pattern="needle",
            recursive=True,
            exclude_patterns=["node_modules"],
            max_matching_files=10,
            max_lines_per_file=2,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "file.grep"
    payload = request.payload.get("payload")
    assert isinstance(payload, dict)
    assert payload["pattern"] == "needle"
    assert payload["recursive"] is True
    assert payload["exclude_patterns"] == ["node_modules"]
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "files": [
                {
                    "path": "/workspace/agent/a.txt",
                    "lines": [{"line_number": 3, "text": "needle here"}],
                    "truncated": False,
                }
            ],
            "searched_file_count": 4,
            "matched_file_count": 1,
            "truncated": False,
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert isinstance(result, RuntimeGrepResult)
    assert result.searched_file_count == 4
    assert result.matched_file_count == 1
    assert result.files[0].path == "/workspace/agent/a.txt"
    assert result.files[0].lines[0].line_number == 3
    assert result.files[0].lines[0].text == "needle here"


@pytest.mark.asyncio
async def test_start_process_dispatches_and_folds_protocol_events() -> None:
    """Process start protocol returns a folded process snapshot."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.start_process(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            command="python -m http.server",
            workdir="/workspace/agent",
            yield_time_ms=1000,
            max_output_bytes=4096,
            env={"PYTHONUNBUFFERED": "1"},
            owner_session_id="session-1",
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "process.start"
    assert request.payload["payload"] == {
        "command": "python -m http.server",
        "workdir": "/workspace/agent",
        "yield_time_ms": 1000,
        "max_output_bytes": 4096,
        "env": {"PYTHONUNBUFFERED": "1"},
    }
    assert request.payload["owner_session_id"] == "session-1"

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.PROCESS_OUTPUT,
        {
            "process_id": "proc_123",
            "stream": "stdout",
            "chunk_id": 1,
            "text": "Serving ",
            "truncated": False,
            "omitted_bytes": 0,
        },
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "process_id": "proc_123",
            "status": "running",
            "stdout": "HTTP on :8000",
            "stderr": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_omitted_bytes": 0,
            "stderr_omitted_bytes": 0,
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result == RuntimeProcessResult(
        process_id="proc_123",
        status="running",
        exit_code=None,
        stdout="HTTP on :8000",
        stderr="",
        stdout_truncated=False,
        stderr_truncated=False,
        stdout_omitted_bytes=0,
        stderr_omitted_bytes=0,
        missing_reason=None,
        final_cursor="2",
    )


@pytest.mark.asyncio
async def test_write_process_stdin_dispatches_empty_poll_and_missing_result() -> None:
    """Empty process stdin is a poll request and missing is a normal result."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.write_process_stdin(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            process_id="proc_missing",
            stdin="",
            yield_time_ms=0,
            max_output_bytes=2048,
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "process.write"
    assert request.payload["payload"] == {
        "process_id": "proc_missing",
        "stdin": "",
        "yield_time_ms": 0,
        "max_output_bytes": 2048,
    }
    assert request.payload["owner_session_id"] == "session-1"

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "process_id": "proc_missing",
            "status": "missing",
            "missing_reason": "runner_generation_changed",
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result.status == "missing"
    assert result.missing_reason == "runner_generation_changed"
    assert result.exit_code is None


@pytest.mark.asyncio
async def test_terminate_session_processes_dispatches_runner_operation() -> None:
    """Session process termination is dispatched as a runner operation."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.terminate_session_processes(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            deadline_at=_now() + timedelta(seconds=30),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "process.terminate_session"
    assert request.payload["payload"] == {"owner_session_id": "session-1"}

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {"terminated_count": 2},
        final=True,
    )

    await asyncio.wait_for(task, timeout=1)


@pytest.mark.asyncio
async def test_resume_process_uses_output_deltas_when_final_snapshot_is_empty() -> None:
    """Process output deltas can be folded when final payload omits text."""
    harness = await _make_harness()
    await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.PROCESS_OUTPUT,
            payload={
                "process_id": "proc_1",
                "stream": "stdout",
                "chunk_id": 1,
                "text": "hello",
                "truncated": False,
                "omitted_bytes": 0,
            },
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.PROCESS_OUTPUT,
            payload={
                "process_id": "proc_1",
                "stream": "stderr",
                "chunk_id": 1,
                "text": "warn",
                "truncated": False,
                "omitted_bytes": 0,
            },
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )
    await harness.control.append_reply_event(
        _event(
            request_id="req-1",
            generation=harness.runner_generation,
            event_type=RuntimeReplyEventType.FINAL_SUCCESS,
            payload={"process_id": "proc_1", "status": "exited_unread", "exit_code": 0},
            final=True,
        ),
        reply_stream_id="reply:req-1",
        operation_id=None,
        expected_target=runner_reply_target(),
        expected_subject_id="runtime-1",
    )

    deltas: list[RuntimeProcessOutputDelta] = []
    result = await harness.client.resume_process(
        reply_stream_id="reply:req-1",
        after_cursor=None,
        deadline_at=_now() + timedelta(seconds=30),
        process_output_callback=lambda delta: _append_delta(deltas, delta),
    )

    assert result.stdout == "hello"
    assert result.stderr == "warn"
    assert result.exit_code == 0
    assert result.status == "exited_unread"
    assert [delta.text for delta in deltas] == ["hello", "warn"]


@pytest.mark.asyncio
async def test_create_git_worktree_dispatches_and_folds_text_output() -> None:
    """Git worktree creation dispatches typed payload and streams text deltas."""
    harness = await _make_harness()
    deltas: list[RuntimeOperationTextDelta] = []
    task = asyncio.create_task(
        harness.client.create_git_worktree(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            source_project_path="/workspace/agent/repo",
            worktree_path="/workspace/agent/.azents/worktrees/session/repo",
            branch_name="azents/session",
            starting_ref="main",
            deadline_at=_now() + timedelta(seconds=30),
            text_output_callback=lambda delta: _append_text_delta(deltas, delta),
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "create_git_worktree"
    assert request.payload["payload"] == {
        "source_project_path": "/workspace/agent/repo",
        "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
        "branch_name": "azents/session",
        "starting_ref": "main",
    }

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.STDERR,
        {"text": "Preparing worktree\n"},
    )
    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "base_commit": "abc123",
            "worktree_path": "/workspace/agent/.azents/worktrees/session/repo",
            "branch_name": "azents/session",
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result.base_commit == "abc123"
    assert result.worktree_path == "/workspace/agent/.azents/worktrees/session/repo"
    assert result.branch_name == "azents/session"
    assert [(delta.stream, delta.text) for delta in deltas] == [
        ("stderr", "Preparing worktree\n")
    ]


@pytest.mark.asyncio
async def test_list_git_refs_returns_final_refs() -> None:
    """Git ref discovery final payload is decoded into ref entries."""
    harness = await _make_harness()
    task = asyncio.create_task(
        harness.client.list_git_refs(
            runtime_id="runtime-1",
            runner_generation=harness.runner_generation,
            owner_session_id="session-1",
            source_project_path="/workspace/agent/repo",
            deadline_at=_now() + timedelta(seconds=30),
            text_output_callback=None,
        )
    )
    await asyncio.sleep(0)
    request = await harness.control.claim_next_runner_request(
        runtime_id="runtime-1",
        generation=harness.runner_generation,
        consumer_id="runner-a",
        block_ms=0,
    )
    assert request is not None
    assert request.operation_type == "list_git_refs"
    assert request.payload["payload"] == {
        "source_project_path": "/workspace/agent/repo"
    }

    await harness.reply(
        request.request_id,
        RuntimeReplyEventType.FINAL_SUCCESS,
        {
            "git_refs": [
                {
                    "name": "main",
                    "ref": "refs/heads/main",
                    "type": "branch",
                    "target": "abc123",
                    "default": True,
                }
            ],
            "default_branch": "main",
            "head_commit": "abc123",
        },
        final=True,
    )

    result = await asyncio.wait_for(task, timeout=1)
    assert result.default_branch == "main"
    assert result.head_commit == "abc123"
    assert result.refs[0].name == "main"
    assert result.refs[0].default is True


@dataclasses.dataclass(frozen=True)
class _Harness:
    store: InMemoryRuntimeCoordinationStore
    control: RuntimeControlProtocolService
    client: RuntimeRunnerOperationClient
    runner_generation: int

    async def reply(
        self,
        request_id: str,
        event_type: RuntimeReplyEventType,
        payload: dict[str, JsonValue],
        *,
        final: bool = False,
    ) -> None:
        await self.control.append_operation_reply_event(
            _event(
                request_id=request_id,
                generation=self.runner_generation,
                event_type=event_type,
                payload=payload,
                final=final,
            ),
            operation_id=f"operation:{request_id}",
            expected_target=runner_reply_target(),
            expected_subject_id="runtime-1",
        )


async def _make_harness(
    *,
    body_chunk_size_bytes: int = 1024 * 1024,
    coordination_store: InMemoryRuntimeCoordinationStore | None = None,
) -> _Harness:
    store = coordination_store or InMemoryRuntimeCoordinationStore()
    control = RuntimeControlProtocolService(
        store,
        request_id_factory=_RequestIds(),
    )
    runner = await control.register_runner(_runner_registration(), registered_at=_now())
    client = RuntimeRunnerOperationClient(
        control_protocol=control,
        coordination_store=store,
        body_chunk_size_bytes=body_chunk_size_bytes,
    )
    return _Harness(
        store=store,
        control=control,
        client=client,
        runner_generation=runner.generation,
    )


class _SlowBodyChunkStore(InMemoryRuntimeCoordinationStore):
    """Coordination store whose body writes are slow but individually succeed."""

    def __init__(self, *, delay_seconds: float) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds
        self.append_attempts = 0
        self.committed_chunks = 0

    async def append_body_chunk(
        self,
        stream_id: str,
        chunk: RuntimeBodyChunk,
    ) -> str:
        self.append_attempts += 1
        await asyncio.sleep(self.delay_seconds)
        cursor = await super().append_body_chunk(stream_id, chunk)
        self.committed_chunks += 1
        return cursor


class _RequestIds:
    def __init__(self) -> None:
        self._next = 1

    def __call__(self) -> str:
        value = f"req-{self._next}"
        self._next += 1
        return value


def _runner_registration() -> RuntimeRunnerRegistration:
    return RuntimeRunnerRegistration(
        runtime_id="runtime-1",
        runner_id="runner-1",
        protocol_version="2026-05-25",
        capabilities=RuntimeProtocolCapabilities(("bash", "files")),
        health="ok",
        workspace_path="/workspace/agent",
        metadata={},
        auth_credential_id="credential-1",
        connection_id="runner-connection-1",
        owner_replica_id="control-a",
    )


def _event(
    *,
    request_id: str,
    generation: int,
    event_type: RuntimeReplyEventType,
    payload: dict[str, JsonValue],
    final: bool = False,
) -> RuntimeReplyEvent:
    return RuntimeReplyEvent(
        request_id=request_id,
        runtime_id="runtime-1",
        generation=generation,
        event_type=event_type,
        payload=payload,
        created_at=_now(),
        final=final,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _append_delta(
    deltas: list[RuntimeProcessOutputDelta],
    delta: RuntimeProcessOutputDelta,
) -> None:
    deltas.append(delta)


async def _append_text_delta(
    deltas: list[RuntimeOperationTextDelta],
    delta: RuntimeOperationTextDelta,
) -> None:
    deltas.append(delta)


async def _always_cancel() -> bool:
    return True
