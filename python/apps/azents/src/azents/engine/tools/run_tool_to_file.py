"""Higher-order client Tool output materialization into Runtime files."""

from __future__ import annotations

import asyncio
import dataclasses
import datetime
import hashlib
import json
import logging
import posixpath
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, assert_never, runtime_checkable

from azcommon.result import Failure
from azcommon.uuid import uuid7
from pydantic import BaseModel, Field

from azents.engine.client_tools import ClientToolWireDialect
from azents.engine.events.generated_files import (
    GeneratedFileOutput,
    PendingGeneratedFileOutput,
)
from azents.engine.events.output_parts import iter_output_parts, lower_output_to_text
from azents.engine.events.tool_invocation import (
    ClientToolInvoker,
    PreparedClientToolInvocation,
    UnboundedClientToolResult,
)
from azents.engine.events.types import (
    ArtifactOutputPart,
    AttachmentOutputPart,
    FileOutputPart,
    OutputTextPart,
    ToolOutputPart,
)
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolCancelRequest,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.execution_context import (
    get_client_tool_execution_context,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.import_file import ImportFileStagingConfiguration
from azents.engine.tools.import_resolver import (
    ArtifactImportResolver,
    ExchangeImportResolver,
    ImportResolveError,
    ResolvedArtifactImportSource,
    ResolvedExchangeImportSource,
)
from azents.runtime.transfer.bytes_source import BytesServerToRuntimeSource
from azents.runtime.transfer.managed_source import (
    managed_source_from_artifact,
    managed_source_from_exchange,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeSource,
    ServerToRuntimeTarget,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferLimitExceeded,
    ServerToRuntimeTransferRequest,
)
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.file_storage import FileStorage
from azents.services.model_file import ModelFileService
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority

logger = logging.getLogger(__name__)

RUN_TOOL_TO_FILE_NAME = "run_tool_to_file"
_MANIFEST_NAME = "manifest.json"
_TOOL_DESCRIPTION = (
    "Run one currently visible client tool and save its output parts to a Runtime "
    "directory. Use this when Runtime commands or scripts will consume the output; "
    "call the target tool directly when the model must inspect it. Activate deferred "
    "tools first. Saved parts are summarized. Parts that fail to save are returned "
    "normally with notice that the target already ran."
)
_PARTIAL_FAILURE_NOTICE = (
    "The target tool already ran successfully. Only the output parts shown above "
    "failed to save in the Runtime."
)
_MANIFEST_FAILURE_NOTICE = (
    "The target tool already ran successfully. Stored output files were not "
    "rolled back."
)
_TARGET_FAILURE_NOTICE = "No Runtime output was stored."


class RunToolToFileInput(BaseModel):
    """Model-visible higher-order Tool input."""

    tool_name: str = Field(
        min_length=1,
        description="Exact name of the visible client tool to run.",
    )
    arguments: str = Field(
        description=(
            "Target tool input as a string; JSON object string for JSON-function "
            "tools, raw text for plaintext-custom tools."
        ),
    )
    directory: str = Field(
        min_length=1,
        description="Absolute Runtime directory for saved output parts.",
    )
    overwrite: bool = Field(
        default=False,
        description="Replace conflicting files; false preserves them.",
    )


class ServerToRuntimeTransferExecutor(Protocol):
    """Server-to-Runtime transfer operation required by the higher-order Tool."""

    async def transfer(self, request: ServerToRuntimeTransferRequest) -> None:
        """Transfer one verified source into Runtime."""
        ...


RuntimeTargetResolver = Callable[[], Awaitable[ServerToRuntimeTarget]]
AuthorityRevalidator = Callable[[], Awaitable[bool]]


@runtime_checkable
class RunToolToFileToolkitProvider(Protocol):
    """Runtime Toolkit surface used by Engine catalog assembly."""

    def make_run_tool_to_file(
        self,
        binding: "LateBoundClientToolInvoker",
    ) -> FunctionTool | None:
        """Build the Runtime-owned higher-order Tool for one prepared turn."""
        ...


@dataclass
class LateBoundClientToolInvoker:
    """One-shot binding from a Tool closure to its final prepared target invoker."""

    invoker: ClientToolInvoker | None = None
    wire_dialects: Mapping[str, ClientToolWireDialect] | None = None
    active_calls: dict[str, PreparedClientToolInvocation] = dataclasses.field(
        default_factory=dict
    )

    def bind(
        self,
        *,
        invoker: ClientToolInvoker,
        wire_dialects: Mapping[str, ClientToolWireDialect],
    ) -> None:
        """Bind the exact same-turn visible target catalog once."""
        if self.invoker is not None or self.wire_dialects is not None:
            raise RuntimeError("Client Tool invoker is already bound")
        self.invoker = invoker
        self.wire_dialects = dict(wire_dialects)

    async def invoke(
        self,
        *,
        outer_call_id: str,
        tool_name: str,
        arguments: str,
    ) -> UnboundedClientToolResult:
        """Invoke one bound target with ordinary prepared Tool semantics."""
        invoker = self.invoker
        wire_dialects = self.wire_dialects
        if invoker is None or wire_dialects is None:
            raise FunctionToolError("Target tool catalog is unavailable.")
        if tool_name == RUN_TOOL_TO_FILE_NAME:
            raise FunctionToolError("run_tool_to_file cannot call itself.")
        wire_dialect = wire_dialects.get(tool_name)
        if wire_dialect is None:
            raise FunctionToolError(f"Tool not found: {tool_name}")
        call = PreparedClientToolInvocation(
            call_id=outer_call_id,
            name=tool_name,
            arguments=arguments,
            wire_dialect=wire_dialect,
        )
        self.active_calls[outer_call_id] = call
        try:
            return await invoker.invoke(call)
        finally:
            self.active_calls.pop(outer_call_id, None)

    def request_cancel(self, outer_call_id: str) -> None:
        """Forward cancellation to the active target invocation."""
        invoker = self.invoker
        call = self.active_calls.get(outer_call_id)
        if invoker is not None and call is not None:
            invoker.request_cancel(call)


@dataclass(frozen=True)
class RunToolToFileRuntimeContext:
    """Runtime and file-resource dependencies for one prepared model turn."""

    session_storage: FileStorage
    exchange_file_service: ExchangeFileService
    artifact_service: ArtifactService
    model_file_service: ModelFileService
    authority: SessionResourceAuthority
    transfer_service: ServerToRuntimeTransferExecutor
    resolve_runtime_target: RuntimeTargetResolver
    staging_configuration: ImportFileStagingConfiguration
    revalidate_authority: AuthorityRevalidator


@dataclass(frozen=True)
class _PlannedPart:
    """One output body selected for Runtime materialization."""

    order: int
    kind: str
    name: str
    media_type: str
    original_part: ToolOutputPart | None
    generated_file: PendingGeneratedFileOutput | None


@dataclass(frozen=True)
class _StoredPart:
    """One successfully committed Runtime output file."""

    planned: _PlannedPart
    relative_path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class _FailedPart:
    """One output part that could not be stored."""

    planned: _PlannedPart
    relative_path: str
    category: str


@dataclass(frozen=True)
class _PartSource:
    """Resolved transfer source and final display metadata."""

    source: ServerToRuntimeSource
    name: str
    media_type: str


def make_run_tool_to_file_tool(
    *,
    binding: LateBoundClientToolInvoker,
    runtime: RunToolToFileRuntimeContext,
) -> FunctionTool:
    """Create the Runtime-owned higher-order client Tool."""

    async def run_tool_to_file(input: RunToolToFileInput) -> FunctionToolResult:
        """Run one Tool and save returned output parts into Runtime."""
        directory = _normalize_directory(input.directory)
        if directory is None:
            raise FunctionToolError("Runtime output directory must be absolute.")

        target = await runtime.resolve_runtime_target()
        await _preflight_directory(
            runtime.session_storage,
            directory=directory,
            agent_id=runtime.authority.agent_id,
            overwrite=input.overwrite,
        )

        execution = get_client_tool_execution_context()
        result = await binding.invoke(
            outer_call_id=execution.call_id,
            tool_name=input.tool_name,
            arguments=input.arguments,
        )
        if result.status == "failed" or not result.execution_succeeded:
            message = lower_output_to_text(result.output).strip()
            if not message:
                message = f"Target tool failed: {input.tool_name}"
            raise FunctionToolError(
                f"{message}\n{_TARGET_FAILURE_NOTICE}",
                metadata=dict(result.metadata),
            )

        planned = _plan_parts(result)
        stored: list[_StoredPart] = []
        failed: list[_FailedPart] = []
        used_names: set[str] = {_MANIFEST_NAME}
        for part in planned:
            try:
                relative_path = await _select_relative_path(
                    runtime.session_storage,
                    directory=directory,
                    requested_name=part.name,
                    used_names=used_names,
                    overwrite=input.overwrite,
                    agent_id=runtime.authority.agent_id,
                )
            except asyncio.CancelledError:
                raise
            except (
                PermissionError,
                RuntimeStorageError,
                ValueError,
            ) as exc:
                failed.append(
                    _FailedPart(
                        planned=part,
                        relative_path=_reserve_fallback_relative_path(
                            part.name,
                            used_names=used_names,
                        ),
                        category=_failure_category(exc),
                    )
                )
                continue
            except Exception:
                logger.exception(
                    "Failed to select higher-order Tool output path",
                    extra={
                        "tool_name": input.tool_name,
                        "part_order": part.order,
                        "part_kind": part.kind,
                        "session_id": runtime.authority.session_id,
                        "run_id": runtime.authority.run_id,
                    },
                )
                failed.append(
                    _FailedPart(
                        planned=part,
                        relative_path=_reserve_fallback_relative_path(
                            part.name,
                            used_names=used_names,
                        ),
                        category="internal_storage_failure",
                    )
                )
                continue
            destination = posixpath.join(directory, relative_path)
            try:
                resolved = await _resolve_part_source(
                    part,
                    runtime=runtime,
                    call_id=execution.call_id,
                )
                await runtime.transfer_service.transfer(
                    ServerToRuntimeTransferRequest(
                        source=resolved.source,
                        target=target,
                        agent_id=runtime.authority.agent_id,
                        session_id=runtime.authority.session_id,
                        operation_id=_transfer_operation_id(runtime.authority.run_id),
                        destination=destination,
                        overwrite=input.overwrite,
                        product_maximum_size=(
                            runtime.staging_configuration.maximum_size
                        ),
                        provider_maximum_size=(
                            runtime.staging_configuration.maximum_size
                        ),
                        deadline_at=(
                            datetime.datetime.now(datetime.UTC)
                            + runtime.staging_configuration.deadline_after
                        ),
                    )
                )
            except asyncio.CancelledError:
                raise
            except (
                FileExistsError,
                ImportResolveError,
                PermissionError,
                RuntimeStorageError,
                ServerToRuntimeTransferError,
                ValueError,
            ) as exc:
                failed.append(
                    _FailedPart(
                        planned=part,
                        relative_path=relative_path,
                        category=_failure_category(exc),
                    )
                )
                continue
            except Exception:
                logger.exception(
                    "Failed to store higher-order Tool output part",
                    extra={
                        "tool_name": input.tool_name,
                        "part_order": part.order,
                        "part_kind": part.kind,
                        "session_id": runtime.authority.session_id,
                        "run_id": runtime.authority.run_id,
                    },
                )
                failed.append(
                    _FailedPart(
                        planned=part,
                        relative_path=relative_path,
                        category="internal_storage_failure",
                    )
                )
                continue

            metadata = resolved.source.metadata
            if metadata.sha256 is None:
                raise RuntimeError("Stored Tool output source requires SHA-256")
            stored.append(
                _StoredPart(
                    planned=part,
                    relative_path=relative_path,
                    size=metadata.size,
                    sha256=metadata.sha256,
                )
            )

        manifest_bytes = _manifest_bytes(
            target_tool_name=input.tool_name,
            stored=stored,
            failed=failed,
        )
        manifest_failure: str | None = None
        try:
            await runtime.transfer_service.transfer(
                ServerToRuntimeTransferRequest(
                    source=_bytes_source(
                        body=manifest_bytes,
                        canonical_uri=(
                            f"tool-output://{runtime.authority.run_id}/"
                            f"{execution.call_id}/manifest"
                        ),
                        source_kind="tool_output_manifest",
                        display_name=_MANIFEST_NAME,
                        media_type="application/json",
                        runtime=runtime,
                    ),
                    target=target,
                    agent_id=runtime.authority.agent_id,
                    session_id=runtime.authority.session_id,
                    operation_id=_transfer_operation_id(runtime.authority.run_id),
                    destination=posixpath.join(directory, _MANIFEST_NAME),
                    overwrite=input.overwrite,
                    product_maximum_size=runtime.staging_configuration.maximum_size,
                    provider_maximum_size=runtime.staging_configuration.maximum_size,
                    deadline_at=(
                        datetime.datetime.now(datetime.UTC)
                        + runtime.staging_configuration.deadline_after
                    ),
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            manifest_failure = _failure_category(exc)

        output = _result_output(
            tool_name=input.tool_name,
            directory=directory,
            manifest_bytes=manifest_bytes,
            stored=stored,
            failed=failed,
            manifest_failure=manifest_failure,
        )
        failed_generated = [
            _generated_file(part.planned.generated_file)
            for part in failed
            if part.planned.generated_file is not None
        ]
        return FunctionToolResult(
            output=output,
            metadata={
                "target_tool_name": input.tool_name,
                "directory": directory,
                "stored_part_count": len(stored),
                "failed_part_count": len(failed),
                "manifest_stored": manifest_failure is None,
            },
            generated_files=failed_generated,
            terminal_run=result.terminal_run,
        )

    tool = make_tool(
        run_tool_to_file,
        name=RUN_TOOL_TO_FILE_NAME,
        description=_TOOL_DESCRIPTION,
        input_model=RunToolToFileInput,
    )

    async def request_cancel(request: FunctionToolCancelRequest) -> None:
        binding.request_cancel(request.call_id)

    return dataclasses.replace(tool, cancel_handler=request_cancel)


def _normalize_directory(path: str) -> str | None:
    """Normalize one absolute lexical Runtime directory."""
    if not path.startswith("/"):
        return None
    normalized = posixpath.normpath(path)
    return normalized if normalized != "." else None


def _transfer_operation_id(run_id: str) -> str:
    """Create one unique coordination identity for each output-file transfer."""
    return f"{run_id}:run-tool-to-file:{uuid7().hex}"


async def _preflight_directory(
    storage: FileStorage,
    *,
    directory: str,
    agent_id: str,
    overwrite: bool,
) -> None:
    """Reject known directory and manifest conflicts before target execution."""
    try:
        metadata = await storage.stat(directory, agent_id=agent_id)
    except FileNotFoundError:
        metadata = None
    except RuntimeStorageError as exc:
        raise FunctionToolError(
            f"Failed to inspect Runtime output directory: {exc.detail}"
        ) from None
    if metadata is not None and not metadata.get("is_directory"):
        raise FunctionToolError(f"Runtime output path is not a directory: {directory}")
    manifest = posixpath.join(directory, _MANIFEST_NAME)
    try:
        manifest_exists = await storage.exists(manifest, agent_id=agent_id)
    except PermissionError:
        raise FunctionToolError(
            f"Cannot inspect Runtime output directory: {directory}"
        ) from None
    except RuntimeStorageError as exc:
        raise FunctionToolError(
            f"Failed to inspect Runtime output directory: {exc.detail}"
        ) from None
    if not overwrite and manifest_exists:
        raise FunctionToolError(
            f"File already exists: {manifest}. Set overwrite=true to replace it."
        )


def _plan_parts(result: UnboundedClientToolResult) -> list[_PlannedPart]:
    """Build one stable ordered list of every returned body-bearing part."""
    output_parts = list(iter_output_parts(result.output))
    text_count = sum(isinstance(part, OutputTextPart) for part in output_parts)
    generated_by_index: dict[int, list[PendingGeneratedFileOutput]] = {}
    for generated in sorted(
        result.pending_generated_files,
        key=lambda item: (item.output_index, item.filename),
    ):
        insert_at = min(generated.output_index, len(output_parts))
        generated_by_index.setdefault(insert_at, []).append(generated)

    planned: list[_PlannedPart] = []
    text_index = 0
    order = 0
    for output_index in range(len(output_parts) + 1):
        for generated in generated_by_index.get(output_index, []):
            planned.append(
                _PlannedPart(
                    order=order,
                    kind="generated_file",
                    name=generated.filename,
                    media_type=generated.media_type,
                    original_part=None,
                    generated_file=generated,
                )
            )
            order += 1
        if output_index == len(output_parts):
            continue
        part = output_parts[output_index]
        match part:
            case OutputTextPart():
                text_index += 1
                name = "output.txt" if text_count == 1 else f"output-{text_index}.txt"
                planned.append(
                    _PlannedPart(
                        order=order,
                        kind="text",
                        name=name,
                        media_type="text/plain",
                        original_part=part,
                        generated_file=None,
                    )
                )
            case AttachmentOutputPart():
                planned.append(
                    _PlannedPart(
                        order=order,
                        kind="attachment",
                        name=part.name,
                        media_type=part.media_type,
                        original_part=part,
                        generated_file=None,
                    )
                )
            case ArtifactOutputPart():
                planned.append(
                    _PlannedPart(
                        order=order,
                        kind="artifact",
                        name=part.name,
                        media_type=part.media_type,
                        original_part=part,
                        generated_file=None,
                    )
                )
            case FileOutputPart():
                planned.append(
                    _PlannedPart(
                        order=order,
                        kind="file",
                        name=part.name or f"file-{order}",
                        media_type=part.media_type,
                        original_part=part,
                        generated_file=None,
                    )
                )
            case _ as unreachable:
                assert_never(unreachable)
        order += 1
    return planned


async def _select_relative_path(
    storage: FileStorage,
    *,
    directory: str,
    requested_name: str,
    used_names: set[str],
    overwrite: bool,
    agent_id: str,
) -> str:
    """Choose one safe collision-free relative output filename."""
    basename = _sanitize_filename(requested_name)
    candidate = basename
    index = 1
    while candidate in used_names or (
        not overwrite
        and await storage.exists(
            posixpath.join(directory, candidate),
            agent_id=agent_id,
        )
    ):
        candidate = _suffixed_filename(basename, index)
        index += 1
    used_names.add(candidate)
    return candidate


def _sanitize_filename(name: str) -> str:
    """Normalize one output filename to a safe basename."""
    basename = posixpath.basename(name)
    sanitized = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", basename).strip().strip(".")
    return sanitized[:255] if sanitized else "output"


def _reserve_fallback_relative_path(
    requested_name: str,
    *,
    used_names: set[str],
) -> str:
    """Reserve a deterministic safe name when Runtime collision lookup fails."""
    basename = _sanitize_filename(requested_name)
    candidate = basename
    index = 1
    while candidate in used_names:
        candidate = _suffixed_filename(basename, index)
        index += 1
    used_names.add(candidate)
    return candidate


def _suffixed_filename(name: str, index: int) -> str:
    """Add a deterministic numeric suffix before a filename extension."""
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        return f"{name}-{index}"
    return f"{stem}-{index}.{suffix}"


async def _resolve_part_source(
    part: _PlannedPart,
    *,
    runtime: RunToolToFileRuntimeContext,
    call_id: str,
) -> _PartSource:
    """Resolve one output part into the closed Runtime transfer source union."""
    original = part.original_part
    if isinstance(original, OutputTextPart):
        return _PartSource(
            source=_bytes_source(
                body=original.text.encode("utf-8"),
                canonical_uri=(
                    f"tool-output://{runtime.authority.run_id}/{call_id}/{part.order}"
                ),
                source_kind="tool_output_text",
                display_name=part.name,
                media_type=part.media_type,
                runtime=runtime,
            ),
            name=part.name,
            media_type=part.media_type,
        )
    if isinstance(original, AttachmentOutputPart):
        resolved = await ExchangeImportResolver(
            exchange_file_service=runtime.exchange_file_service,
            authority=runtime.authority,
        ).resolve(original.uri)
        assert isinstance(resolved, ResolvedExchangeImportSource)
        return _PartSource(
            source=managed_source_from_exchange(
                resolved.source,
                s3_service=runtime.staging_configuration.s3_service,
                bucket=runtime.staging_configuration.workspace_bucket,
                transfer_object_prefix=(
                    runtime.staging_configuration.transfer_object_prefix
                ),
                multipart_copy_threshold=(
                    runtime.staging_configuration.multipart_copy_threshold
                ),
                multipart_part_size=(runtime.staging_configuration.multipart_part_size),
                revalidate_authority=resolved.revalidate,
            ),
            name=resolved.name,
            media_type=resolved.media_type,
        )
    if isinstance(original, ArtifactOutputPart):
        resolved = await ArtifactImportResolver(
            artifact_service=runtime.artifact_service,
            authority=runtime.authority,
        ).resolve(original.uri)
        assert isinstance(resolved, ResolvedArtifactImportSource)
        return _PartSource(
            source=managed_source_from_artifact(
                resolved.source,
                s3_service=runtime.staging_configuration.s3_service,
                bucket=runtime.staging_configuration.workspace_bucket,
                transfer_object_prefix=(
                    runtime.staging_configuration.transfer_object_prefix
                ),
                multipart_copy_threshold=(
                    runtime.staging_configuration.multipart_copy_threshold
                ),
                multipart_part_size=(runtime.staging_configuration.multipart_part_size),
                revalidate_authority=resolved.revalidate,
            ),
            name=resolved.name,
            media_type=resolved.media_type,
        )
    if isinstance(original, FileOutputPart):
        downloaded = await runtime.model_file_service.download_for_authority(
            model_file_id=original.model_file_id,
            authority=runtime.authority,
        )
        if isinstance(downloaded, Failure):
            raise ValueError("ModelFile output is unavailable")
        return _PartSource(
            source=_bytes_source(
                body=downloaded.value.body,
                canonical_uri=(
                    f"model-file://{runtime.authority.run_id}/{original.model_file_id}"
                ),
                source_kind="model_file",
                display_name=part.name,
                media_type=downloaded.value.model_file.media_type,
                runtime=runtime,
            ),
            name=part.name,
            media_type=downloaded.value.model_file.media_type,
        )
    if original is None and part.generated_file is not None:
        generated = part.generated_file
        return _PartSource(
            source=_bytes_source(
                body=generated.body,
                canonical_uri=(
                    f"generated-file://{runtime.authority.run_id}/"
                    f"{call_id}/{generated.output_index}"
                ),
                source_kind="generated_file",
                display_name=generated.filename,
                media_type=generated.media_type,
                runtime=runtime,
            ),
            name=generated.filename,
            media_type=generated.media_type,
        )
    raise ValueError("Tool output part has no materializable body")


def _bytes_source(
    *,
    body: bytes,
    canonical_uri: str,
    source_kind: str,
    display_name: str,
    media_type: str,
    runtime: RunToolToFileRuntimeContext,
) -> BytesServerToRuntimeSource:
    """Build one authority-bound in-memory transfer source."""
    config = runtime.staging_configuration
    return BytesServerToRuntimeSource(
        body=body,
        canonical_uri=canonical_uri,
        source_kind=source_kind,
        display_name=display_name,
        media_type=media_type,
        revalidate_authority=runtime.revalidate_authority,
        s3_service=config.s3_service,
        bucket=config.workspace_bucket,
        transfer_object_prefix=config.transfer_object_prefix,
        part_size=config.multipart_part_size,
    )


def _manifest_bytes(
    *,
    target_tool_name: str,
    stored: list[_StoredPart],
    failed: list[_FailedPart],
) -> bytes:
    """Render the bounded Runtime-local output-part manifest."""
    entries = [
        {
            "order": item.planned.order,
            "kind": item.planned.kind,
            "name": item.planned.name,
            "media_type": item.planned.media_type,
            "path": item.relative_path,
            "status": "stored",
            "size": item.size,
            "sha256": item.sha256,
        }
        for item in stored
    ]
    entries.extend(
        {
            "order": item.planned.order,
            "kind": item.planned.kind,
            "name": item.planned.name,
            "media_type": item.planned.media_type,
            "path": item.relative_path,
            "status": "failed",
            "failure": item.category,
        }
        for item in failed
    )
    entries.sort(key=lambda item: int(item["order"]))
    return json.dumps(
        {
            "schema_version": 1,
            "target_tool_name": target_tool_name,
            "parts": entries,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _result_output(
    *,
    tool_name: str,
    directory: str,
    manifest_bytes: bytes,
    stored: list[_StoredPart],
    failed: list[_FailedPart],
    manifest_failure: str | None,
) -> str | list[dict[str, object]]:
    """Build the bounded success or part-level failure Tool result."""
    aggregate_bytes = sum(item.size for item in stored)
    bundle_digest = hashlib.sha256(manifest_bytes).hexdigest()
    summary = (
        f"Ran {tool_name} and stored {len(stored)} output part(s) in {directory} "
        f"({aggregate_bytes} bytes, manifest SHA-256 {bundle_digest})."
    )
    if not failed and manifest_failure is None:
        return f"{summary}\nManifest: {posixpath.join(directory, _MANIFEST_NAME)}"

    output: list[dict[str, object]] = [
        {"type": "text", "text": summary},
    ]
    for item in sorted(failed, key=lambda value: value.planned.order):
        original = item.planned.original_part
        if original is not None:
            output.append(original.model_dump(mode="json", exclude_none=True))
    notices: list[str] = []
    if failed:
        notices.append(f"{len(failed)} output part(s) failed Runtime storage.")
    if manifest_failure is not None:
        notices.append(f"The Runtime manifest failed to save ({manifest_failure}).")
    notices.append(_PARTIAL_FAILURE_NOTICE if failed else _MANIFEST_FAILURE_NOTICE)
    output.append({"type": "text", "text": " ".join(notices)})
    return output


def _generated_file(pending: PendingGeneratedFileOutput) -> GeneratedFileOutput:
    """Drop outer-call routing fields from one failed generated file."""
    return GeneratedFileOutput(
        output_index=pending.output_index,
        filename=pending.filename,
        media_type=pending.media_type,
        sha256=pending.sha256,
        body=pending.body,
    )


def _failure_category(error: BaseException) -> str:
    """Return one bounded stable storage-failure category."""
    if isinstance(error, ServerToRuntimeTransferLimitExceeded):
        return "size_limit"
    if isinstance(error, ImportResolveError):
        return error.code
    if isinstance(error, FileExistsError):
        return "destination_exists"
    if isinstance(error, PermissionError):
        return "permission_denied"
    if isinstance(error, RuntimeStorageError):
        return "runtime_storage"
    if isinstance(error, ServerToRuntimeTransferError):
        return error.failure.value if error.failure is not None else "runtime_transfer"
    if isinstance(error, ValueError):
        return "source_unavailable"
    return "internal_storage_failure"
