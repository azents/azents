"""import_file tool."""

import datetime
import logging
import posixpath
import re
from dataclasses import dataclass
from typing import assert_never

from azcommon.infra.s3.service import S3Service, S3TransferCleanupRequired
from azents_runtime_control.grpc_transfer_coordinator_client import (
    CoordinatorTransferFailure,
)
from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.import_resolver import (
    ArtifactImportResolver,
    AzentsImportResolver,
    ExchangeImportResolver,
    ImportFileResolver,
    ImportFileResolverRegistry,
    ImportResolveError,
    ResolvedArtifactImportSource,
    ResolvedExchangeImportSource,
    ResolvedVfsImportSource,
    VfsTransferFileResolver,
)
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.engine.tools.runtime_instruction_context import (
    RuntimeTargetResolver,
    ServerToRuntimeTransferExecutor,
)
from azents.runtime.transfer.managed_source import (
    managed_source_from_artifact,
    managed_source_from_exchange,
)
from azents.runtime.transfer.server_to_runtime import (
    ServerToRuntimeSource,
    ServerToRuntimeTransferError,
    ServerToRuntimeTransferLimitExceeded,
    ServerToRuntimeTransferRequest,
)
from azents.runtime.transfer.vfs_source import VfsServerToRuntimeSource
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_resource_authority import SessionResourceAuthority

logger = logging.getLogger(__name__)

_DEFAULT_IMPORT_DIR = "/tmp/agent/imports"


@dataclass(frozen=True)
class ImportFileStagingConfiguration:
    """Trusted source-staging dependencies excluded from model-visible context."""

    s3_service: S3Service
    workspace_bucket: str
    transfer_object_prefix: str
    multipart_copy_threshold: int
    multipart_part_size: int
    maximum_size: int
    deadline_after: datetime.timedelta

    def __post_init__(self) -> None:
        """Validate bounded import transfer settings."""
        if (
            min(
                self.multipart_copy_threshold,
                self.multipart_part_size,
                self.maximum_size,
            )
            <= 0
        ):
            raise ValueError("Import transfer byte limits must be positive")
        if self.deadline_after <= datetime.timedelta():
            raise ValueError("Import transfer deadline must be positive")


class ImportFileInput(BaseModel):
    """import_file tool input."""

    uri: str = Field(
        description=(
            "File-location URI to import. Supports exchange://, artifact://, and "
            "azents:// resources."
        ),
    )
    path: str | None = Field(
        default=None,
        description=(
            "Destination absolute path in the runtime workspace. "
            "Defaults to /tmp/agent/imports/<filename>."
        ),
    )
    overwrite: bool = Field(
        default=False,
        description="Set to true to overwrite an existing destination file.",
    )


def make_import_file_tool(
    *,
    session_storage: FileStorage,
    exchange_file_service: ExchangeFileService,
    artifact_service: ArtifactService,
    vfs_projection_service: VfsTransferFileResolver | None,
    authority: SessionResourceAuthority,
    transfer_service: ServerToRuntimeTransferExecutor,
    resolve_runtime_target: RuntimeTargetResolver,
    staging_configuration: ImportFileStagingConfiguration,
) -> FunctionTool:
    """Create import_file tool."""
    resolvers: dict[str, ImportFileResolver] = {
        "exchange": ExchangeImportResolver(
            exchange_file_service=exchange_file_service,
            authority=authority,
        ),
        "artifact": ArtifactImportResolver(
            artifact_service=artifact_service,
            authority=authority,
        ),
    }
    if vfs_projection_service is not None:
        resolvers["azents"] = AzentsImportResolver(
            vfs_projection_service=vfs_projection_service,
            authority=authority,
        )
    resolver_registry = ImportFileResolverRegistry(resolvers)

    async def handler(input: ImportFileInput) -> str:
        """Copy URI file into runtime workspace."""
        try:
            resolved = await resolver_registry.resolve(input.uri)
        except ImportResolveError as exc:
            raise FunctionToolError(exc.message) from None

        destination = _normalize_destination(
            input.path or f"{_DEFAULT_IMPORT_DIR}/{_sanitize_filename(resolved.name)}"
        )
        if destination is None:
            raise FunctionToolError("Destination path must be absolute.")

        if input.path is None and not input.overwrite:
            destination = await _dedupe_destination(
                session_storage,
                destination,
                agent_id=authority.agent_id,
            )
        elif not input.overwrite:
            await _raise_if_exists(
                session_storage,
                destination,
                agent_id=authority.agent_id,
            )

        source = _server_to_runtime_source(
            resolved=resolved,
            staging_configuration=staging_configuration,
        )
        try:
            target = await resolve_runtime_target()
            await transfer_service.transfer(
                ServerToRuntimeTransferRequest(
                    source=source,
                    target=target,
                    agent_id=authority.agent_id,
                    session_id=authority.session_id,
                    operation_id=authority.run_id,
                    destination=destination,
                    overwrite=input.overwrite,
                    product_maximum_size=staging_configuration.maximum_size,
                    provider_maximum_size=staging_configuration.maximum_size,
                    deadline_at=(
                        datetime.datetime.now(datetime.UTC)
                        + staging_configuration.deadline_after
                    ),
                )
            )
        except PermissionError:
            raise FunctionToolError(
                f"Cannot write to read-only scope: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except FileExistsError:
            raise FunctionToolError(
                f"File already exists: {destination}. Set overwrite=true to replace it."
            ) from None
        except ValueError as exc:
            raise FunctionToolError(_import_staging_error_message(exc)) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(
                f"Failed to write imported file: {exc.detail}"
            ) from None
        except S3TransferCleanupRequired:
            raise FunctionToolError(
                "Failed to prepare imported file for Runtime transfer."
            ) from None
        except OSError:
            logger.exception(
                "Failed to import file into runtime workspace",
                extra={
                    "uri": input.uri,
                    "path": destination,
                    "session_id": authority.session_id,
                    "run_id": authority.run_id,
                },
            )
            raise FunctionToolError(
                f"Failed to write imported file: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except ServerToRuntimeTransferLimitExceeded:
            raise FunctionToolError(
                "Imported file exceeds the configured Runtime transfer limit."
            ) from None
        except ServerToRuntimeTransferError as exc:
            raise FunctionToolError(
                _import_transfer_error_message(exc, destination=destination)
            ) from None

        content = (
            f"Imported {resolved.source_uri} to {destination} "
            f"({resolved.source_kind}, {resolved.media_type}, {resolved.size} bytes)."
        )
        if destination.startswith("/tmp/"):
            content += (
                " This file is temporary and may not survive runtime reset "
                f"hibernate/restore; re-import {resolved.source_uri} or copy it under "
                "a durable working directory before presenting it."
            )
        return content

    return make_tool(
        handler,
        name="import_file",
        description=(
            "Import a file-location URI into the runtime workspace. Supports "
            "exchange://, artifact://, and current-run azents:// resources. If path "
            "is omitted, the file is written under /tmp/agent/imports/. Files under "
            "/tmp/agent/imports/ are temporary; copy important files to a durable "
            "working directory before presenting them."
        ),
    )


def _server_to_runtime_source(
    *,
    resolved: (
        ResolvedExchangeImportSource
        | ResolvedArtifactImportSource
        | ResolvedVfsImportSource
    ),
    staging_configuration: ImportFileStagingConfiguration,
) -> ServerToRuntimeSource:
    """Build one closed trusted source adapter from an authorized resolver result."""
    match resolved:
        case ResolvedExchangeImportSource():
            return managed_source_from_exchange(
                resolved.source,
                s3_service=staging_configuration.s3_service,
                bucket=staging_configuration.workspace_bucket,
                transfer_object_prefix=staging_configuration.transfer_object_prefix,
                multipart_copy_threshold=staging_configuration.multipart_copy_threshold,
                multipart_part_size=staging_configuration.multipart_part_size,
                revalidate_authority=resolved.revalidate,
            )
        case ResolvedArtifactImportSource():
            return managed_source_from_artifact(
                resolved.source,
                s3_service=staging_configuration.s3_service,
                bucket=staging_configuration.workspace_bucket,
                transfer_object_prefix=staging_configuration.transfer_object_prefix,
                multipart_copy_threshold=staging_configuration.multipart_copy_threshold,
                multipart_part_size=staging_configuration.multipart_part_size,
                revalidate_authority=resolved.revalidate,
            )
        case ResolvedVfsImportSource():
            return VfsServerToRuntimeSource(
                entry=resolved.source.entry,
                revalidate_authority=resolved.revalidate,
                s3_service=staging_configuration.s3_service,
                bucket=staging_configuration.workspace_bucket,
                transfer_object_prefix=staging_configuration.transfer_object_prefix,
            )
        case _ as unreachable:
            assert_never(unreachable)


def _normalize_destination(path: str) -> str | None:
    """Normalize destination path to lexical event path."""
    if not path.startswith("/"):
        return None
    normalized = posixpath.normpath(path)
    if normalized == ".":
        return None
    return normalized


def _sanitize_filename(name: str) -> str:
    """Normalize file name to basename safe for import destination."""
    basename = posixpath.basename(name)
    sanitized = re.sub(r"[\x00-\x1f\x7f/\\]+", "_", basename).strip().strip(".")
    if sanitized:
        return sanitized[:255]
    return "file"


async def _dedupe_destination(
    session_storage: FileStorage,
    destination: str,
    *,
    agent_id: str,
) -> str:
    """Add numeric suffix on default import path collision."""
    if not await _exists(session_storage, destination, agent_id=agent_id):
        return destination
    directory = posixpath.dirname(destination)
    filename = posixpath.basename(destination)
    stem, dot, suffix = filename.rpartition(".")
    if not dot:
        stem = filename
        suffix = ""
    for index in range(1, 10_000):
        candidate_name = f"{stem}-{index}.{suffix}" if suffix else f"{stem}-{index}"
        candidate = posixpath.join(directory, candidate_name)
        if not await _exists(session_storage, candidate, agent_id=agent_id):
            return candidate
    raise FunctionToolError(f"Unable to find available import path for: {destination}")


async def _raise_if_exists(
    session_storage: FileStorage,
    destination: str,
    *,
    agent_id: str,
) -> None:
    """Fail when explicit destination already exists."""
    if await _exists(session_storage, destination, agent_id=agent_id):
        raise FunctionToolError(
            f"File already exists: {destination}. Set overwrite=true to replace it."
        )


async def _exists(
    session_storage: FileStorage,
    destination: str,
    *,
    agent_id: str,
) -> bool:
    """Return whether runtime storage path exists."""
    try:
        return await session_storage.exists(destination, agent_id=agent_id)
    except PermissionError:
        raise FunctionToolError(
            f"Cannot write to read-only scope: {destination}. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ) from None
    except ValueError as exc:
        raise FunctionToolError(str(exc)) from None
    except RuntimeStorageError as exc:
        raise FunctionToolError(
            f"Failed to check destination file: {exc.detail}"
        ) from None


def _import_transfer_error_message(
    error: ServerToRuntimeTransferError,
    *,
    destination: str,
) -> str:
    """Map bounded transfer outcomes to the established import_file contract."""
    if error.args[0] == "Transfer source authority changed before dispatch":
        return "Session resource authority changed before file import."
    match error.failure:
        case CoordinatorTransferFailure.CANCELLED:
            return "Runtime transfer was cancelled before destination commit."
        case CoordinatorTransferFailure.EXPIRED:
            return "Runtime transfer did not complete before its deadline."
        case CoordinatorTransferFailure.INTEGRITY:
            return (
                "Imported file integrity verification failed before destination commit."
            )
        case CoordinatorTransferFailure.CONSUMER:
            return (
                f"Failed to write imported file: Runtime destination is not writable: "
                f"{destination}."
            )
        case (
            CoordinatorTransferFailure.ADMISSION
            | CoordinatorTransferFailure.FENCED
            | CoordinatorTransferFailure.STREAM
            | None
        ):
            return (
                f"Failed to write imported file: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            )
        case _:
            return (
                f"Failed to write imported file: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            )


def _import_staging_error_message(error: ValueError) -> str:
    """Map source staging validation failures without exposing storage internals."""
    message = str(error).lower()
    if "exceeds" in message:
        return "Imported file exceeds the configured Runtime transfer limit."
    if "size" in message or "hash" in message or "integrity" in message:
        return "Imported file integrity verification failed before destination commit."
    return "Failed to prepare imported file for Runtime transfer."
