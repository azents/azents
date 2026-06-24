"""import_file tool."""

import logging
import posixpath
import re

from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.import_resolver import (
    ArtifactImportResolver,
    ExchangeImportResolver,
    ImportFileResolverRegistry,
    ImportResolveError,
)
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.services.artifact import ArtifactService
from azents.services.exchange_file import ExchangeFileService
from azents.services.file_storage import FileStorage
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

_DEFAULT_IMPORT_DIR = "/tmp/agent/imports"


class ImportFileInput(BaseModel):
    """import_file tool input."""

    uri: str = Field(
        description=(
            "File-location URI to import. Supports exchange:// and artifact:// "
            "resources."
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
    session_id: str,
    agent_id: str,
    user_id: str,
) -> FunctionTool:
    """Create import_file tool."""
    resolver_registry = ImportFileResolverRegistry(
        {
            "exchange": ExchangeImportResolver(
                exchange_file_service=exchange_file_service,
                user_id=user_id,
            ),
            "artifact": ArtifactImportResolver(
                artifact_service=artifact_service,
                user_id=user_id,
            ),
        }
    )

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
                agent_id=agent_id,
            )
        elif not input.overwrite:
            await _raise_if_exists(session_storage, destination, agent_id=agent_id)

        try:
            await session_storage.put(
                destination,
                resolved.body,
                resolved.media_type,
                agent_id=agent_id,
            )
        except PermissionError:
            raise FunctionToolError(
                f"Cannot write to read-only scope: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
            ) from None
        except ValueError as exc:
            raise FunctionToolError(str(exc)) from None
        except RuntimeStorageError as exc:
            raise FunctionToolError(
                f"Failed to write imported file: {exc.detail}"
            ) from None
        except OSError:
            logger.exception(
                "Failed to import file into runtime workspace",
                extra={
                    "uri": input.uri,
                    "path": destination,
                    "session_id": session_id,
                },
            )
            raise FunctionToolError(
                f"Failed to write imported file: {destination}. "
                f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
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
            "exchange:// and artifact:// resources. If path is omitted, the file "
            "is written under /tmp/agent/imports/. Files under /tmp/agent/imports/ "
            "are temporary; copy important files to a durable working directory "
            "before presenting them."
        ),
    )


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
        return False
    except ValueError:
        return False
    except RuntimeStorageError as exc:
        raise FunctionToolError(
            f"Failed to check destination file: {exc.detail}"
        ) from None
