"""Runner operation ingress and terminal diagnostic regressions."""

import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest
from azents_runtime_control.grpc_runner_client import RuntimeRunnerControlStreamClosed
from azents_runtime_control.runner import (
    JsonValue,
    RunnerOperationEnvelope,
    RunnerOperationEvent,
    RuntimeRunnerEventType,
)

import azents_runtime_runner.operation_payloads as payloads
from azents_runtime_runner.execution import (
    DirectExecutionBackend,
    ExecutionProcess,
    ExecutionSpec,
)
from azents_runtime_runner.operations import (
    RunnerOperations,
    _expand_braces,
    _find_expandable_brace,
)
from azents_runtime_runner.workspace import Workspace


class _Sink:
    def __init__(self) -> None:
        self.events: list[RunnerOperationEvent] = []

    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        self.events.append(event)


def _operation(
    operation_type: str, raw: dict[str, JsonValue]
) -> RunnerOperationEnvelope:
    return RunnerOperationEnvelope(
        request_id="request-fixture",
        runtime_id="runtime-fixture",
        runner_generation=1,
        operation_type=operation_type,
        owner_session_id="session-fixture",
        payload=raw,
        reply_stream_id="reply-fixture",
        body_stream_id=None,
        body_chunks=(),
        deadline_at=None,
    )


@pytest.mark.parametrize("replacement", [None, 1, False, [], {}])
async def test_malformed_edit_replacement_is_rejected_without_writing(
    tmp_path: Path, replacement: JsonValue
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("before\n")
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations.handle(
            _operation(
                "file.edit",
                {
                    "path": str(target),
                    "old_string": "before",
                    "new_string": replacement,
                },
            )
        )
    finally:
        await operations.close()
    assert target.read_text() == "before\n"
    assert [event.event_type for event in sink.events] == [
        RuntimeRunnerEventType.ACCEPTED,
        RuntimeRunnerEventType.FINAL_ERROR,
    ]
    assert sink.events[-1].payload["error_code"] == "INVALID_PAYLOAD"


async def test_omitted_edit_replacement_is_rejected_but_explicit_empty_is_deletion(
    tmp_path: Path,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("before\n")
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations.handle(
            _operation(
                "file.edit",
                {
                    "path": str(target),
                    "old_string": "before",
                },
            )
        )
        assert sink.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
        assert target.read_text() == "before\n"
        await operations.handle(
            _operation(
                "file.edit",
                {
                    "path": str(target),
                    "old_string": "before",
                    "new_string": "",
                    "future_extension": {"opaque": True},
                },
            )
        )
    finally:
        await operations.close()
    assert sink.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert sink.events[-1].payload == {"replacements": 1}
    assert target.read_text() == "\n"


@pytest.mark.parametrize(
    ("operation_type", "options", "code"),
    [
        ("file.read", {"offset": "1"}, "INVALID_FILE_READ_RANGE"),
        ("file.download", {"max_bytes": True}, "INVALID_FILE_READ_RANGE"),
        (
            "file.read_text",
            {"character_offset": False, "max_characters": 1},
            "INVALID_FILE_READ_TEXT_RANGE",
        ),
        ("file.read_text", {"max_characters": "1"}, "INVALID_FILE_READ_TEXT_RANGE"),
        ("file.bulk_delete", {"paths": ["source.txt", None]}, "INVALID_PAYLOAD"),
        ("file.list", {"exclude_patterns": ["*.txt", 1]}, "INVALID_PAYLOAD"),
    ],
)
async def test_malformed_file_fields_produce_terminal_errors_without_effects(
    tmp_path: Path,
    operation_type: str,
    options: dict[str, JsonValue],
    code: str,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("unchanged")
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations.handle(
            _operation(operation_type, {"path": str(target), **options})
        )
    finally:
        await operations.close()
    assert target.read_text() == "unchanged"
    assert [event.event_type for event in sink.events] == [
        RuntimeRunnerEventType.ACCEPTED,
        RuntimeRunnerEventType.FINAL_ERROR,
    ]
    assert sink.events[-1].payload["error_code"] == code


class _NoLaunchBackend(DirectExecutionBackend):
    def __init__(self) -> None:
        super().__init__()
        self.launches = 0

    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        self.launches += 1
        raise AssertionError("Invalid ingress must not reach process launch")


@pytest.mark.parametrize("operation_type", ["bash", "process.start"])
async def test_invalid_environment_members_are_rejected_before_launch(
    tmp_path: Path, operation_type: str
) -> None:
    sink = _Sink()
    backend = _NoLaunchBackend()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=backend,
    )
    try:
        await operations.handle(
            _operation(
                operation_type,
                {
                    "command": "fixture",
                    "env": {"VALID": "value", "INVALID": 1},
                },
            )
        )
    finally:
        await operations.close()
    assert backend.launches == 0
    assert sink.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert sink.events[-1].payload["error_code"] == "INVALID_ENVIRONMENT"


async def test_payload_is_decoded_once_and_handler_never_reads_raw_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "source.txt"
    target.write_text("typed")
    raw: dict[str, JsonValue] = {"path": str(target), "max_characters": 10}
    original_decode = payloads.decode_operation_payload
    calls: list[str] = []

    def decode_once(
        operation_type: str, supplied: Mapping[str, JsonValue]
    ) -> payloads.OperationPayload:
        calls.append(operation_type)
        result = original_decode(operation_type, supplied)
        raw.clear()
        return result

    monkeypatch.setattr(payloads, "decode_operation_payload", decode_once)
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations.handle(_operation("file.read_text", raw))
    finally:
        await operations.close()
    assert calls == ["file.read_text"]
    assert sink.events[-1].event_type == RuntimeRunnerEventType.FINAL_SUCCESS
    assert sink.events[1].payload == {"text": "typed"}


class _OriginFailureBackend(DirectExecutionBackend):
    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        return self._raise_origin()

    def _raise_origin(self) -> ExecutionProcess:
        try:
            raise ValueError("synthetic-private-cause")
        except ValueError as cause:
            raise LookupError("synthetic-private-detail") from cause


async def test_terminal_error_logs_safe_origin_once_and_preserves_final_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=_OriginFailureBackend(),
    )
    try:
        await operations.handle(_operation("bash", {"command": "fixture"}))
    finally:
        await operations.close()
    assert sink.events[-1].event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert sink.events[-1].payload["error_code"] == "RUNNER_OPERATION_ERROR"
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Runner operation failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.exc_info is not None
    assert record.exc_info[2] is None
    assert record.exc_info[1] is not None
    assert str(record.exc_info[1]) == "runner_operation_failed"
    assert record.exc_info[1].__cause__ is None
    assert record.__dict__["error_type"] == "LookupError"
    assert any(
        frame["function"] == "_raise_origin"
        for frame in record.__dict__["error_frames"]
    )
    assert "synthetic-private-detail" not in caplog.text
    assert "synthetic-private-cause" not in caplog.text
    assert "raise LookupError" not in caplog.text


class _CancellationBackend(DirectExecutionBackend):
    async def start(self, spec: ExecutionSpec) -> ExecutionProcess:
        del spec
        raise asyncio.CancelledError


async def test_cancellation_remains_propagated_without_error_conversion(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=_CancellationBackend(),
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await operations.handle(_operation("bash", {"command": "fixture"}))
    finally:
        await operations.close()
    assert [event.event_type for event in sink.events] == [
        RuntimeRunnerEventType.ACCEPTED
    ]
    assert "Runner operation failed" not in caplog.text


class _FinalClosedSink(_Sink):
    async def append_runner_event(self, event: RunnerOperationEvent) -> None:
        if event.event_type == RuntimeRunnerEventType.FINAL_ERROR:
            raise RuntimeRunnerControlStreamClosed("synthetic closed stream")
        await super().append_runner_event(event)


async def test_invalid_payload_final_delivery_failure_is_not_disguised_as_success(
    tmp_path: Path,
) -> None:
    sink = _FinalClosedSink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        with pytest.raises(RuntimeRunnerControlStreamClosed):
            await operations.handle(_operation("file.edit", {"new_string": 1}))
    finally:
        await operations.close()
    assert [event.event_type for event in sink.events] == [
        RuntimeRunnerEventType.ACCEPTED
    ]


@pytest.mark.parametrize(
    ("field", "reason", "phase"),
    [
        ("base_path", "base_path_required", "preflight"),
        ("schema_version", "unsupported_schema_version", "parse"),
        ("total_bytes", "patch_size_mismatch", "parse"),
    ],
)
async def test_malformed_patch_metadata_retains_structured_terminal_failure(
    tmp_path: Path,
    field: str,
    reason: str,
    phase: str,
) -> None:
    raw: dict[str, JsonValue] = {
        "base_path": str(tmp_path),
        "schema_version": 1,
        "total_bytes": 0,
    }
    raw[field] = False
    sink = _Sink()
    operations = RunnerOperations(
        client=sink,
        workspace=Workspace(str(tmp_path)),
        execution_backend=DirectExecutionBackend(),
    )
    try:
        await operations.handle(_operation("file.apply_patch", raw))
    finally:
        await operations.close()
    event = sink.events[-1]
    assert event.event_type == RuntimeRunnerEventType.FINAL_ERROR
    assert event.payload["error_code"] == "FILE_APPLY_PATCH_FAILED"
    detail = event.payload["file_apply_patch"]
    assert isinstance(detail, dict)
    assert detail["phase"] == phase
    assert detail["reason"] == reason
    assert detail["applied"] == []


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("a/{first,second}/z", ("a/first/z", "a/second/z")),
        (
            "{one,{two,three}}.{a,b}",
            ("one.a", "one.b", "two.a", "two.b", "three.a", "three.b"),
        ),
        ("{plain}", ("{plain}",)),
        ("{a,b", ("{a,b",)),
    ],
)
def test_named_brace_span_preserves_nested_expansion_order(
    pattern: str,
    expected: tuple[str, ...],
) -> None:
    assert _expand_braces(pattern) == expected
    span = _find_expandable_brace("a/{first,second}/z")
    assert span is not None
    assert span.opening == 2
    assert span.closing == 15
    assert span.alternatives == ("first", "second")
