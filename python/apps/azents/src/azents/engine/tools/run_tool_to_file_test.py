"""Tests for higher-order client Tool output Runtime materialization."""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import List, Literal
from unittest.mock import AsyncMock

import pytest
from azcommon.result import Success

from azents.core.enums import ArtifactStatus, ModelFileStatus
from azents.engine.events.generated_files import PendingGeneratedFileOutput
from azents.engine.events.tool_invocation import (
    ClientToolInvoker,
    PreparedClientToolInvocation,
    UnboundedClientToolResult,
)
from azents.engine.events.tools import (
    ToolCatalog,
    ToolCatalogClientToolExecutor,
)
from azents.engine.events.types import (
    ArtifactOutputPart,
    AttachmentOutputPart,
    ClientToolCallPayload,
    FileOutputPart,
    NativeArtifact,
    OutputTextPart,
    ToolOutput,
)
from azents.engine.io.attachments import RuntimeAttachment
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.execution_context import client_tool_execution_context
from azents.engine.tooling.tool_search import (
    CatalogTool,
    ToolCatalogSource,
    ToolExposure,
)
from azents.engine.tools.import_file import ImportFileStagingConfiguration
from azents.engine.tools.run_tool_to_file import (
    RUN_TOOL_TO_FILE_NAME,
    LateBoundClientToolInvoker,
    RunToolToFileRuntimeContext,
    make_run_tool_to_file_tool,
)
from azents.repos.artifact.data import Artifact
from azents.repos.exchange_file.data import ExchangeFile
from azents.repos.model_file.data import ModelFile
from azents.runtime.transfer.bytes_source import BytesServerToRuntimeSource
from azents.runtime.transfer.managed_source import ManagedServerToRuntimeSource
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferRequest,
)
from azents.services.artifact import ArtifactTransferSource
from azents.services.exchange_file import ExchangeFileTransferSource
from azents.services.file_storage import GrepResult, TextReadResult
from azents.services.model_file import ModelFileDownload
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority


class _Invoker(ClientToolInvoker):
    """Return one configured unbounded target result."""

    def __init__(self, result: UnboundedClientToolResult) -> None:
        self.result = result
        self.calls: list[PreparedClientToolInvocation] = []
        self.cancelled: list[PreparedClientToolInvocation] = []

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        self.calls.append(call)
        return self.result

    def request_cancel(self, call: PreparedClientToolInvocation) -> None:
        self.cancelled.append(call)


class _BlockingInvoker(_Invoker):
    """Keep one target invocation active until the test releases it."""

    def __init__(self, result: UnboundedClientToolResult) -> None:
        super().__init__(result)
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def invoke(
        self,
        call: PreparedClientToolInvocation,
    ) -> UnboundedClientToolResult:
        self.calls.append(call)
        self.started.set()
        await self.release.wait()
        return self.result


class _Storage:
    """Minimal Runtime storage fake for path preflight and collision checks."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.directories: set[str] = set()

    async def stat(self, path: str, *, agent_id: str) -> dict[str, object]:
        del agent_id
        if path in self.directories:
            return {"is_directory": True, "is_file": False}
        if path in self.files:
            return {"is_directory": False, "is_file": True}
        raise FileNotFoundError(path)

    async def exists(self, path: str, *, agent_id: str) -> bool:
        del agent_id
        return path in self.files or path in self.directories

    async def get(self, path: str, *, agent_id: str) -> bytes:
        del agent_id
        return self.files[path]

    async def get_text(
        self,
        path: str,
        *,
        agent_id: str,
        offset: int,
        limit: int,
        encoding: str,
    ) -> TextReadResult:
        del agent_id
        text = self.files[path].decode(encoding)[offset : offset + limit]
        return TextReadResult(
            text=text,
            start_character=offset,
            end_character=offset + len(text),
            truncated=False,
        )

    async def put(
        self,
        path: str,
        data: bytes,
        media_type: str | None = None,
        *,
        agent_id: str,
    ) -> RuntimeAttachment:
        del agent_id
        self.files[path] = data
        return RuntimeAttachment(
            uri=path,
            media_type=media_type or "application/octet-stream",
            size=len(data),
            name=path.rsplit("/", 1)[-1],
            text_preview=None,
        )

    async def delete(self, path: str, *, agent_id: str) -> None:
        del agent_id
        self.files.pop(path, None)
        self.directories.discard(path)

    async def list(
        self,
        path: str,
        *,
        agent_id: str,
        recursive: bool = False,
        exclude_patterns: List[str] | None = None,
        include_directories: bool = False,
    ) -> List[RuntimeAttachment]:
        del path, agent_id, recursive, exclude_patterns, include_directories
        raise NotImplementedError

    async def glob(
        self,
        pattern: str,
        *,
        agent_id: str,
        exclude_patterns: List[str] | None,
    ) -> List[RuntimeAttachment]:
        del pattern, agent_id, exclude_patterns
        raise NotImplementedError

    async def list_dirs(self, path: str, *, agent_id: str) -> List[str]:
        del path, agent_id
        raise NotImplementedError

    async def grep(
        self,
        path: str,
        *,
        agent_id: str,
        pattern: str,
        recursive: bool = True,
        exclude_patterns: List[str] | None = None,
        max_matching_files: int = 50,
        max_lines_per_file: int = 10,
        max_searched_files: int | None = None,
        max_scanned_bytes: int | None = None,
    ) -> GrepResult:
        del (
            path,
            agent_id,
            pattern,
            recursive,
            exclude_patterns,
            max_matching_files,
            max_lines_per_file,
            max_searched_files,
            max_scanned_bytes,
        )
        raise NotImplementedError


class _CollisionFailureStorage(_Storage):
    """Fail only output-part collision lookup after manifest preflight."""

    async def exists(self, path: str, *, agent_id: str) -> bool:
        if path == "/tmp/result/output.txt":
            raise RuntimeStorageError("collision lookup unavailable")
        return await super().exists(path, agent_id=agent_id)


class _ManifestPreflightFailureStorage(_Storage):
    """Fail manifest lookup before the target can execute."""

    async def exists(self, path: str, *, agent_id: str) -> bool:
        if path == "/tmp/result/manifest.json":
            raise RuntimeStorageError("manifest lookup unavailable")
        return await super().exists(path, agent_id=agent_id)


class _Transfer:
    """Write byte sources directly into the Runtime storage fake."""

    def __init__(
        self,
        storage: _Storage,
        *,
        failed_destinations: set[str] | None = None,
    ) -> None:
        self.storage = storage
        self.failed_destinations = failed_destinations or set()
        self.requests: list[ServerToRuntimeTransferRequest] = []

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        self.requests.append(request)
        if request.destination in self.failed_destinations:
            raise ServerToRuntimeTransferError("forced transfer failure")
        source = request.source
        if isinstance(source, BytesServerToRuntimeSource):
            body = source.body
        elif isinstance(source, ManagedServerToRuntimeSource):
            body = b""
        else:
            raise AssertionError("Unexpected transfer source")
        self.storage.files[request.destination] = body
        parent = request.destination.rsplit("/", 1)[0]
        self.storage.directories.add(parent)


def _authority() -> SessionResourceAuthority:
    return SessionResourceAuthority(
        workspace_id="workspace-1",
        agent_id="agent-1",
        session_id="session-1",
        root_session_id="session-1",
        run_id="run-1",
        run_index=1,
        owner_generation=1,
    )


def _target_result(
    output: ToolOutput,
    *,
    status: Literal["completed", "failed"] = "completed",
    execution_succeeded: bool = True,
    pending_generated_files: tuple[PendingGeneratedFileOutput, ...] = (),
) -> UnboundedClientToolResult:
    return UnboundedClientToolResult(
        call_id="outer-call",
        name="service__target",
        wire_dialect="json_function",
        status=status,
        execution_succeeded=execution_succeeded,
        output=output,
        metadata={},
        pending_generated_files=pending_generated_files,
        terminal_run=False,
    )


def _runtime(
    storage: _Storage,
    transfer: _Transfer,
    *,
    exchange_file_service: AsyncMock | None = None,
    artifact_service: AsyncMock | None = None,
    model_file_service: AsyncMock | None = None,
) -> RunToolToFileRuntimeContext:
    return RunToolToFileRuntimeContext(
        session_storage=storage,
        exchange_file_service=exchange_file_service or AsyncMock(),
        artifact_service=artifact_service or AsyncMock(),
        model_file_service=model_file_service or AsyncMock(),
        authority=_authority(),
        transfer_service=transfer,
        resolve_runtime_target=AsyncMock(
            return_value=ServerToRuntimeTarget(
                runtime_id="runtime-1",
                desired_generation=1,
            )
        ),
        staging_configuration=ImportFileStagingConfiguration(
            s3_service=AsyncMock(),
            workspace_bucket="workspace",
            transfer_object_prefix="runtime-transfer",
            multipart_copy_threshold=1024,
            multipart_part_size=1024,
            maximum_size=1_000_000,
            deadline_after=datetime.timedelta(minutes=1),
        ),
        revalidate_authority=AsyncMock(return_value=True),
    )


def _binding(
    result: UnboundedClientToolResult,
    *,
    wire_dialect: Literal["json_function", "plaintext_custom"] = "json_function",
) -> tuple[LateBoundClientToolInvoker, _Invoker]:
    binding = LateBoundClientToolInvoker()
    invoker = _Invoker(result)
    binding.bind(
        invoker=invoker,
        wire_dialects=MappingProxyType({"service__target": wire_dialect}),
    )
    return binding, invoker


async def _call(
    *,
    result: UnboundedClientToolResult,
    storage: _Storage | None = None,
    transfer: _Transfer | None = None,
    overwrite: bool = False,
    arguments: str = '{"value": 1}',
    wire_dialect: Literal["json_function", "plaintext_custom"] = "json_function",
) -> tuple[FunctionToolResult, _Storage, _Transfer, _Invoker]:
    storage = storage or _Storage()
    transfer = transfer or _Transfer(storage)
    binding, invoker = _binding(result, wire_dialect=wire_dialect)
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, transfer),
    )
    with client_tool_execution_context(
        call_id="outer-call",
        name=RUN_TOOL_TO_FILE_NAME,
    ):
        returned = await tool.handler(
            json.dumps(
                {
                    "tool_name": "service__target",
                    "arguments": arguments,
                    "directory": "/tmp/result",
                    "overwrite": overwrite,
                }
            )
        )
    assert isinstance(returned, FunctionToolResult)
    return returned, storage, transfer, invoker


async def test_saves_full_text_without_engine_cap() -> None:
    """Store target text exactly and keep it out of the success result."""
    html = "<html>" + ("x" * 35_000) + "</html>"

    returned, storage, transfer, invoker = await _call(result=_target_result(html))

    assert storage.files["/tmp/result/output.txt"] == html.encode()
    assert "/tmp/result/manifest.json" in storage.files
    assert html not in str(returned)
    assert len(transfer.requests) == 2
    assert invoker.calls == [
        PreparedClientToolInvocation(
            call_id="outer-call",
            name="service__target",
            arguments='{"value": 1}',
            wire_dialect="json_function",
        )
    ]


async def test_target_validation_failure_never_starts_storage() -> None:
    """Treat target input failure as failure instead of storable output."""
    returned = _target_result(
        "Input validation failed.",
        status="failed",
        execution_succeeded=False,
    )
    storage = _Storage()
    transfer = _Transfer(storage)
    binding, _ = _binding(returned)
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, transfer),
    )

    with client_tool_execution_context(
        call_id="outer-call",
        name=RUN_TOOL_TO_FILE_NAME,
    ):
        try:
            await tool.handler(
                json.dumps(
                    {
                        "tool_name": "service__target",
                        "arguments": "{}",
                        "directory": "/tmp/result",
                        "overwrite": False,
                    }
                )
            )
        except Exception as exc:
            assert str(exc) == (
                "Input validation failed.\nNo Runtime output was stored."
            )
        else:
            raise AssertionError("Target validation failure must raise")

    assert transfer.requests == []
    assert storage.files == {}


async def test_manifest_preflight_failure_never_invokes_target() -> None:
    """Convert Runtime lookup failure to a Tool error before target execution."""
    storage = _ManifestPreflightFailureStorage()
    transfer = _Transfer(storage)
    binding, invoker = _binding(_target_result("unused"))
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, transfer),
    )

    with (
        client_tool_execution_context(
            call_id="outer-call",
            name=RUN_TOOL_TO_FILE_NAME,
        ),
        pytest.raises(
            FunctionToolError,
            match="Failed to inspect Runtime output directory",
        ),
    ):
        await tool.handler(
            json.dumps(
                {
                    "tool_name": "service__target",
                    "arguments": "{}",
                    "directory": "/tmp/result",
                    "overwrite": False,
                }
            )
        )

    assert invoker.calls == []
    assert transfer.requests == []


async def test_failed_part_returns_normal_capped_output_and_notice() -> None:
    """Return only a failed text part and preserve the final success notice."""
    text = "prefix-" + ("x" * 35_000)
    storage = _Storage()
    transfer = _Transfer(
        storage,
        failed_destinations={"/tmp/result/output.txt"},
    )
    binding, _ = _binding(_target_result(text))
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, transfer),
    )
    catalog = _catalog({RUN_TOOL_TO_FILE_NAME: tool})
    call = ClientToolCallPayload(
        call_id="outer-call",
        name=RUN_TOOL_TO_FILE_NAME,
        arguments=json.dumps(
            {
                "tool_name": "service__target",
                "arguments": "{}",
                "directory": "/tmp/result",
                "overwrite": False,
            }
        ),
        wire_dialect="json_function",
        native_artifact=NativeArtifact(
            adapter="openai",
            native_format="responses",
            provider="openai",
            model="gpt-test",
            schema_version="1",
            item={"type": "function_call"},
            compat_key="openai:responses:openai:gpt-test:1",
        ),
    )

    result = await ToolCatalogClientToolExecutor(catalog).execute(call)

    assert result.status == "completed"
    assert isinstance(result.output, list)
    rendered = "\n".join(
        part.text for part in result.output if isinstance(part, OutputTextPart)
    )
    assert rendered.startswith("... (truncated)\n")
    assert "prefix-" not in rendered
    assert "The target tool already ran successfully." in rendered
    assert "/tmp/result/manifest.json" in storage.files


async def test_stores_generated_file_without_publishing_it() -> None:
    """Consume a successful generated file into Runtime output storage."""
    generated = PendingGeneratedFileOutput(
        call_id="outer-call",
        tool_name="service__target",
        output_index=0,
        filename="image.png",
        media_type="image/png",
        sha256=hashlib.sha256(b"png").hexdigest(),
        body=b"png",
    )

    returned, storage, _, _ = await _call(
        result=_target_result(
            [],
            pending_generated_files=(generated,),
        )
    )

    assert storage.files["/tmp/result/image.png"] == b"png"
    assert returned.generated_files == []


async def test_mixed_output_uses_authorized_sources_and_manifest_order() -> None:
    """Store every supported source type in one stable ordered bundle."""
    now = datetime.datetime.now(datetime.UTC)
    exchange = ExchangeFile.model_construct(
        id="exchange-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        object_key="exchange/workspace-1/report.csv",
        filename="report.csv",
        media_type="text/csv",
        size_bytes=3,
        sha256=hashlib.sha256(b"csv").hexdigest(),
        expires_at=now + datetime.timedelta(days=1),
    )
    artifact = Artifact.model_construct(
        id="artifact-1",
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        created_run_id="run-1",
        created_run_index=1,
        expires_at=now + datetime.timedelta(days=1),
        name="artifact.txt",
        media_type="text/plain",
        size_bytes=8,
        storage_key="artifacts/workspace-1/artifact.txt",
        status=ArtifactStatus.AVAILABLE,
        sha256=hashlib.sha256(b"artifact").hexdigest(),
        created_at=now,
    )
    model_file = ModelFile.model_construct(
        id="model-file-1",
        workspace_id="workspace-1",
        session_id="session-1",
        agent_id="agent-1",
        name="model.bin",
        media_type="application/octet-stream",
        kind="binary",
        size_bytes=5,
        created_run_id="run-1",
        created_run_index=1,
        storage_key="model-files/workspace-1/model.bin",
        status=ModelFileStatus.AVAILABLE,
        normalized_format="original",
        sha256=hashlib.sha256(b"model").hexdigest(),
        created_at=now,
    )
    exchange_service = AsyncMock()
    exchange_service.resolve_transfer_source_for_authority.return_value = Success(
        ExchangeFileTransferSource(file=exchange)
    )
    artifact_service = AsyncMock()
    artifact_service.resolve_transfer_source_for_authority.return_value = Success(
        ArtifactTransferSource(artifact=artifact)
    )
    model_file_service = AsyncMock()
    model_file_service.download_for_authority.return_value = Success(
        ModelFileDownload(model_file=model_file, body=b"model")
    )
    generated = PendingGeneratedFileOutput(
        call_id="outer-call",
        tool_name="service__target",
        output_index=1,
        filename="image.png",
        media_type="image/png",
        sha256=hashlib.sha256(b"png").hexdigest(),
        body=b"png",
    )
    output = [
        OutputTextPart(text="text"),
        AttachmentOutputPart(
            uri=exchange.uri,
            name=exchange.filename,
            media_type=exchange.media_type,
            size=exchange.size_bytes,
        ),
        ArtifactOutputPart(
            artifact_id=artifact.id,
            uri=artifact.uri,
            name=artifact.name,
            media_type=artifact.media_type,
            size=artifact.size_bytes,
        ),
        FileOutputPart(
            model_file_id=model_file.id,
            name=model_file.name,
            media_type=model_file.media_type,
            size=model_file.size_bytes,
        ),
    ]
    storage = _Storage()
    transfer = _Transfer(storage)
    binding, _ = _binding(_target_result(output, pending_generated_files=(generated,)))
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(
            storage,
            transfer,
            exchange_file_service=exchange_service,
            artifact_service=artifact_service,
            model_file_service=model_file_service,
        ),
    )

    with client_tool_execution_context(
        call_id="outer-call",
        name=RUN_TOOL_TO_FILE_NAME,
    ):
        returned = await tool.handler(
            json.dumps(
                {
                    "tool_name": "service__target",
                    "arguments": "{}",
                    "directory": "/tmp/result",
                    "overwrite": False,
                }
            )
        )

    assert isinstance(returned, FunctionToolResult)
    assert [
        request.destination.rsplit("/", 1)[-1] for request in transfer.requests
    ] == [
        "output.txt",
        "image.png",
        "report.csv",
        "artifact.txt",
        "model.bin",
        "manifest.json",
    ]
    assert isinstance(transfer.requests[2].source, ManagedServerToRuntimeSource)
    assert isinstance(transfer.requests[3].source, ManagedServerToRuntimeSource)
    assert len({request.operation_id for request in transfer.requests}) == 6
    manifest = json.loads(storage.files["/tmp/result/manifest.json"])
    assert [part["kind"] for part in manifest["parts"]] == [
        "text",
        "generated_file",
        "attachment",
        "artifact",
        "file",
    ]


async def test_preserves_existing_destination_with_numeric_suffix() -> None:
    """Keep an existing part and select a deterministic new filename."""
    storage = _Storage()
    storage.files["/tmp/result/output.txt"] = b"old"

    _, returned_storage, _, _ = await _call(
        result=_target_result("new"),
        storage=storage,
    )

    assert returned_storage.files["/tmp/result/output.txt"] == b"old"
    assert returned_storage.files["/tmp/result/output-1.txt"] == b"new"


async def test_manifest_failure_keeps_stored_files_and_reports_target_success() -> None:
    """Keep committed parts when only the final manifest transfer fails."""
    storage = _Storage()
    transfer = _Transfer(
        storage,
        failed_destinations={"/tmp/result/manifest.json"},
    )

    returned, returned_storage, _, _ = await _call(
        result=_target_result("saved"),
        storage=storage,
        transfer=transfer,
    )

    assert returned_storage.files["/tmp/result/output.txt"] == b"saved"
    assert isinstance(returned.output, list)
    rendered_parts: list[str] = []
    for part in returned.output:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if isinstance(text, str):
            rendered_parts.append(text)
    rendered = " ".join(rendered_parts)
    assert "The Runtime manifest failed to save" in rendered
    assert "Stored output files were not rolled back." in rendered
    assert "Only the output parts shown above" not in rendered


async def test_collision_lookup_failure_returns_failed_part_and_notice() -> None:
    """Preserve target-success semantics when path preflight fails after execution."""
    storage = _CollisionFailureStorage()
    transfer = _Transfer(storage)

    returned, _, _, invoker = await _call(
        result=_target_result("target output"),
        storage=storage,
        transfer=transfer,
    )

    assert isinstance(returned.output, list)
    rendered = json.dumps(returned.output)
    assert "target output" in rendered
    assert "The target tool already ran successfully." in rendered
    manifest = json.loads(storage.files["/tmp/result/manifest.json"])
    assert manifest["parts"][0]["status"] == "failed"
    assert manifest["parts"][0]["failure"] == "runtime_storage"
    assert len(invoker.calls) == 1
    assert [request.destination for request in transfer.requests] == [
        "/tmp/result/manifest.json"
    ]


async def test_plaintext_custom_arguments_are_forwarded_without_rewriting() -> None:
    """Pass raw target text through the selected plaintext-custom dialect."""
    returned, storage, _, invoker = await _call(
        result=_target_result("stored"),
        arguments="raw plaintext input",
        wire_dialect="plaintext_custom",
    )

    assert isinstance(returned, FunctionToolResult)
    assert storage.files["/tmp/result/output.txt"] == b"stored"
    assert invoker.calls[0].arguments == "raw plaintext input"
    assert invoker.calls[0].wire_dialect == "plaintext_custom"


async def test_cancel_handler_forwards_to_active_target_once() -> None:
    """Forward the outer call cancellation to the active target invocation."""
    binding = LateBoundClientToolInvoker()
    invoker = _BlockingInvoker(_target_result("stored"))
    binding.bind(
        invoker=invoker,
        wire_dialects=MappingProxyType({"service__target": "json_function"}),
    )
    storage = _Storage()
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, _Transfer(storage)),
    )
    assert tool.cancel_handler is not None

    async def execute() -> str | FunctionToolResult:
        return await tool.handler(
            json.dumps(
                {
                    "tool_name": "service__target",
                    "arguments": "{}",
                    "directory": "/tmp/result",
                    "overwrite": False,
                }
            )
        )

    with client_tool_execution_context(
        call_id="outer-call",
        name=RUN_TOOL_TO_FILE_NAME,
    ):
        task = asyncio.create_task(execute())
    await invoker.started.wait()

    await tool.cancel_handler(
        FunctionToolCancelRequest(
            call_id="outer-call",
            name=RUN_TOOL_TO_FILE_NAME,
            arguments="{}",
        )
    )
    invoker.release.set()
    await task

    assert invoker.cancelled == invoker.calls


async def test_unknown_target_fails_before_invocation_or_transfer() -> None:
    """Reject names outside the same-turn visible target registry."""
    binding, invoker = _binding(_target_result("unused"))
    storage = _Storage()
    transfer = _Transfer(storage)
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(storage, transfer),
    )

    with (
        client_tool_execution_context(
            call_id="outer-call",
            name=RUN_TOOL_TO_FILE_NAME,
        ),
        pytest.raises(FunctionToolError, match="Tool not found: hidden"),
    ):
        await tool.handler(
            json.dumps(
                {
                    "tool_name": "hidden",
                    "arguments": "{}",
                    "directory": "/tmp/result",
                    "overwrite": False,
                }
            )
        )

    assert invoker.calls == []
    assert transfer.requests == []


def test_description_and_schema_are_concise() -> None:
    """Expose the approved name, description, and four input fields."""
    binding, _ = _binding(_target_result("ok"))
    tool = make_run_tool_to_file_tool(
        binding=binding,
        runtime=_runtime(_Storage(), _Transfer(_Storage())),
    )

    assert tool.spec.name == RUN_TOOL_TO_FILE_NAME
    assert "Run one currently visible client tool" in tool.spec.description
    properties = tool.spec.input_schema.get("properties")
    assert isinstance(properties, dict)
    assert set(properties) == {
        "tool_name",
        "arguments",
        "directory",
        "overwrite",
    }


def _catalog(tools: Mapping[str, FunctionTool]) -> ToolCatalog:
    typed_tools = {name: tool for name, tool in tools.items()}
    source = ToolCatalogSource(
        slug="builtin",
        toolkit_type=None,
        toolkit_class="RuntimeBuiltinTool",
        display_name="Runtime",
        use_prefix=False,
    )
    return ToolCatalog(
        tools=MappingProxyType(typed_tools),
        wire_dialects=MappingProxyType({name: "json_function" for name in typed_tools}),
        entries=MappingProxyType(
            {
                name: CatalogTool(
                    tool=tool,
                    source=source,
                    exposure=ToolExposure.DIRECT,
                )
                for name, tool in typed_tools.items()
            }
        ),
        static_prompt_fragment_inputs=[],
        dynamic_prompt_fragment_inputs=[],
        active_toolkit_bindings=[],
    )
