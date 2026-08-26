"""present_file tool tests."""

import datetime
import json
import logging
from dataclasses import dataclass, field

import pytest

from azents.core.enums import (
    ExchangeFileOrigin,
    ExchangeFileProvenanceKind,
    ExchangeFileStatus,
)
from azents.engine.run.types import FunctionTool, FunctionToolError, FunctionToolResult
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tools.present_file import (
    _is_presentable_path,  # Exercise root containment directly.
    make_present_file_tool,
)
from azents.engine.tools.testing import FakeSharedStorage
from azents.repos.exchange_file.data import ExchangeFile
from azents.runtime.transfer.present_file_publication import (
    PresentFilePublicationAccessDenied,
    PresentFilePublicationRequest,
)
from azents.runtime.transfer.runtime_to_server import RuntimeToServerTransferError
from azents.runtime.transfer.server_to_runtime import ServerToRuntimeTarget
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority

_NOW = datetime.datetime.now(datetime.timezone.utc)
_TARGET = ServerToRuntimeTarget(runtime_id="runtime-1", desired_generation=3)


def test_presentable_path_supports_filesystem_root_workspace() -> None:
    """Filesystem root can be the Runner-reported Agent Workspace."""
    assert _is_presentable_path("/result.png", "/")


class _NoBodyReadStorage(FakeSharedStorage):
    """Fail if present_file attempts a complete body read."""

    def __init__(self, files: dict[str, bytes] | None = None) -> None:
        super().__init__(files)
        self.get_calls: list[str] = []

    async def get(
        self,
        path: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> bytes:
        """Record an invalid body relay attempt."""
        del agent_id, user_id, limit
        self.get_calls.append(path)
        raise AssertionError("present_file must not read the complete file body")


class _UnavailableStatStorage(FakeSharedStorage):
    """Simulate an unavailable Runtime metadata operation."""

    async def stat(
        self,
        path: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, object]:
        """Raise a Runtime storage error instead of returning metadata."""
        del path, agent_id, user_id
        raise RuntimeStorageError("runner disconnected")


@dataclass
class _PublicationService:
    """High-level publication fake retaining only request metadata."""

    requests: list[PresentFilePublicationRequest] = field(default_factory=list)
    failures: dict[str, Exception] = field(default_factory=dict)

    async def publish(self, request: PresentFilePublicationRequest) -> ExchangeFile:
        """Return an Exchange file after observing a metadata-only request."""
        self.requests.append(request)
        failure = self.failures.get(request.runtime_path)
        if failure is not None:
            raise failure
        return _make_exchange_file(
            filename=request.filename,
            size_bytes=request.expected_size,
        )


def _make_exchange_file(*, filename: str, size_bytes: int) -> ExchangeFile:
    """Create Exchange publication result for tests."""
    return ExchangeFile(
        id="b" * 32,
        workspace_id="workspace-1",
        agent_id="agent-1",
        origin_type=ExchangeFileOrigin.ARTIFACT,
        status=ExchangeFileStatus.AVAILABLE,
        object_key="exchange/workspace-1/files/b/original",
        filename=filename,
        media_type="text/plain",
        size_bytes=size_bytes,
        sha256="1" * 64,
        provenance_kind=ExchangeFileProvenanceKind.TOOL,
        source_user_id=None,
        source_agent_id=None,
        source_run_id="run-1",
        source_tool_name="present_file",
        source_provider=None,
        source_exchange_file_id=None,
        retention_root_session_id="session-1",
        retention_bound_at=_NOW,
        preview_thumbnail_file_id=None,
        preview_thumbnail_uri=None,
        preview_title=filename,
        preview_summary="stored preview",
        preview_thumbnail_media_type=None,
        preview_thumbnail_width=None,
        preview_thumbnail_height=None,
        preview_generated_at=None,
        expires_at=_NOW + datetime.timedelta(days=30),
        expired_at=None,
        blob_deleted_at=None,
        created_at=_NOW,
    )


async def _resolve_runtime_target() -> ServerToRuntimeTarget:
    return _TARGET


def _tool(
    storage: FakeSharedStorage,
    service: _PublicationService,
) -> FunctionTool:
    """Create the tool under test."""
    return make_present_file_tool(
        session_storage=storage,
        publication_service=service,
        resolve_runtime_target=_resolve_runtime_target,
        authority=_authority(),
        workspace_root="/runtime/home",
    )


async def _invoke(
    tool: FunctionTool,
    *,
    paths: list[str],
    call_id: str = "call-1",
) -> FunctionToolResult:
    """Run present_file under one durable client tool execution identity."""
    with client_tool_execution_context(call_id=call_id, name="present_file"):
        result = await tool.handler(json.dumps({"paths": paths}))
    assert isinstance(result, FunctionToolResult)
    return result


def _output_item(result: FunctionToolResult, index: int) -> dict[str, object]:
    """Return one structured tool output item after type validation."""
    assert isinstance(result.output, list)
    item = result.output[index]
    assert isinstance(item, dict)
    return item


def _output_text(result: FunctionToolResult) -> str:
    """Return validated text from the first output item."""
    text = _output_item(result, 0).get("text")
    assert isinstance(text, str)
    return text


@pytest.mark.asyncio
async def test_present_file_publishes_large_file_without_body_relay() -> None:
    """Use only metadata for a file larger than the old complete-body relay path."""
    path = "/runtime/home/large.bin"
    storage = _NoBodyReadStorage({path: b"x" * (5 * 1024 * 1024)})
    service = _PublicationService()

    result = await _invoke(
        _tool(storage, service),
        paths=[path],
    )

    assert isinstance(result, FunctionToolResult)
    attachment = _output_item(result, 1)
    assert attachment["type"] == "attachment"
    assert attachment["size"] == 5 * 1024 * 1024
    assert storage.get_calls == []
    assert len(service.requests) == 1
    request = service.requests[0]
    assert request.runtime_path == path
    assert request.expected_size == 5 * 1024 * 1024
    assert request.target == _TARGET
    assert request.filename == "large.bin"
    assert not hasattr(request, "body")


@pytest.mark.asyncio
async def test_present_file_preserves_partial_multi_path_results() -> None:
    """Continue after a missing path and return the successfully published file."""
    good_path = "/runtime/home/result.txt"
    missing_path = "/runtime/home/missing.txt"
    storage = _NoBodyReadStorage({good_path: b"hello"})
    service = _PublicationService()

    result = await _invoke(
        _tool(storage, service),
        paths=[missing_path, good_path],
    )

    assert isinstance(result, FunctionToolResult)
    output_text = _output_text(result)
    assert "Presented 1 file(s)" in output_text
    assert "File not found or inaccessible" in output_text
    assert (
        _output_item(result, 1)["uri"]
        == "exchange://exchange/workspace-1/files/b/original"
    )
    assert [request.runtime_path for request in service.requests] == [good_path]
    assert storage.get_calls == []


@pytest.mark.asyncio
async def test_present_file_reports_authority_failure_and_continues() -> None:
    """Keep authority denial as a controlled per-path tool observation."""
    denied_path = "/runtime/home/denied.txt"
    good_path = "/runtime/home/result.txt"
    storage = _NoBodyReadStorage({denied_path: b"denied", good_path: b"hello"})
    service = _PublicationService(
        failures={
            denied_path: PresentFilePublicationAccessDenied(
                "Exchange publication was denied"
            )
        }
    )

    result = await _invoke(
        _tool(storage, service),
        paths=[denied_path, good_path],
    )

    assert isinstance(result, FunctionToolResult)
    assert "Session resource access denied while presenting file." in _output_text(
        result
    )
    assert _output_item(result, 1)["name"] == "result.txt"
    assert len(service.requests) == 2
    assert storage.get_calls == []


@pytest.mark.asyncio
async def test_present_file_reports_terminal_upload_failure_and_continues() -> None:
    """Return success only for paths whose upload publication settles successfully."""
    failed_path = "/runtime/home/failed.txt"
    good_path = "/runtime/home/result.txt"
    storage = _NoBodyReadStorage({failed_path: b"failed", good_path: b"hello"})
    service = _PublicationService(
        failures={
            failed_path: RuntimeToServerTransferError("Runtime upload terminated")
        }
    )

    result = await _invoke(
        _tool(storage, service),
        paths=[failed_path, good_path],
    )

    assert isinstance(result, FunctionToolResult)
    assert f"Failed to present file: {failed_path}" in _output_text(result)
    assert _output_item(result, 1)["name"] == "result.txt"
    assert storage.get_calls == []


@pytest.mark.asyncio
async def test_present_file_logs_bounded_publication_failure_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log safe correlation fields without storage paths or object identities."""
    failed_path = "/runtime/home/private-output.txt"
    storage = _NoBodyReadStorage({failed_path: b"failed"})
    service = _PublicationService(
        failures={
            failed_path: RuntimeToServerTransferError("Runtime upload terminated")
        }
    )

    with caplog.at_level(logging.WARNING):
        await _invoke(
            _tool(storage, service),
            paths=[failed_path],
            call_id="call-observability",
        )

    records = [
        record
        for record in caplog.records
        if record.message == "Present file publication failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.__dict__["agent_id"] == "agent-1"
    assert record.__dict__["session_id"] == "session-1"
    assert record.__dict__["run_id"] == "run-1"
    assert record.__dict__["call_id"] == "call-observability"
    assert record.__dict__["runtime_id"] == "runtime-1"
    assert record.__dict__["runtime_generation"] == 3
    assert record.__dict__["failure_stage"] == "runtime_transfer"
    assert record.__dict__["failure_type"] == "RuntimeToServerTransferError"
    assert isinstance(record.__dict__["publication_id"], str)
    assert "path" not in record.__dict__
    assert "object_handle" not in record.__dict__


@pytest.mark.asyncio
async def test_present_file_rejects_disallowed_path_without_publication() -> None:
    """Retain workspace allowlist behavior before publication admission."""
    service = _PublicationService()
    tool = _tool(
        _NoBodyReadStorage({"/tmp/output.txt": b"temporary"}),
        service,
    )

    result = await _invoke(tool, paths=["/tmp/output.txt"])

    assert isinstance(result, FunctionToolResult)
    assert "Only files under the Agent Workspace can be presented" in _output_text(
        result
    )
    assert service.requests == []


@pytest.mark.asyncio
async def test_present_file_propagates_runtime_stat_failure() -> None:
    """Retain Runtime metadata failure behavior without trying a body fallback."""
    service = _PublicationService()

    with pytest.raises(FunctionToolError, match="Failed to access file"):
        await _invoke(
            _tool(_UnavailableStatStorage(), service),
            paths=["/runtime/home/result.txt"],
        )

    assert service.requests == []


@pytest.mark.asyncio
async def test_present_file_reuses_publication_id_for_a_retried_tool_call() -> None:
    """Make a repeated durable tool call converge on one verified publication."""
    path = "/runtime/home/result.txt"
    storage = _NoBodyReadStorage({path: b"hello"})
    service = _PublicationService()
    tool = _tool(storage, service)

    await _invoke(tool, paths=[path], call_id="call-retry")
    await _invoke(tool, paths=[path], call_id="call-retry")

    publication_ids = [request.publication_id for request in service.requests]
    assert publication_ids[0] == publication_ids[1]
    assert len(service.requests[0].publication_id) == 32


@pytest.mark.asyncio
async def test_present_file_scopes_publication_id_to_runtime_path() -> None:
    """Avoid merging different files from one multi-path tool call."""
    first_path = "/runtime/home/first.txt"
    second_path = "/runtime/home/second.txt"
    storage = _NoBodyReadStorage({first_path: b"first", second_path: b"second"})
    service = _PublicationService()

    await _invoke(
        _tool(storage, service),
        paths=[first_path, second_path],
        call_id="call-multiple",
    )

    assert len(service.requests) == 2
    assert service.requests[0].publication_id != service.requests[1].publication_id


def _authority() -> SessionResourceAuthority:
    """Create canonical Session/Run authority for tests."""
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )
