"""Shared Runtime directory validation boundary."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import assert_never

from azcommon.result import Failure, Result, Success

from azents.core.enums import RuntimeRunnerState
from azents.repos.agent_runtime.data import AgentRuntime
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)

_RUNTIME_DIRECTORY_VALIDATION_TIMEOUT_SECONDS = 120


@dataclasses.dataclass(frozen=True)
class RuntimeDirectoryNotFound:
    """Requested Runtime directory does not exist."""

    path: str


@dataclasses.dataclass(frozen=True)
class RuntimeDirectoryNotDirectory:
    """Requested Runtime path does not resolve to a directory."""

    path: str


@dataclasses.dataclass(frozen=True)
class RuntimeDirectoryValidationUnavailable:
    """Runtime directory validation cannot currently be performed."""

    message: str


RuntimeDirectoryValidationError = (
    RuntimeDirectoryNotFound
    | RuntimeDirectoryNotDirectory
    | RuntimeDirectoryValidationUnavailable
)


def _runtime_directory_validation_deadline() -> datetime:
    """Return a deadline for one Runtime directory validation."""
    return datetime.now(UTC) + timedelta(
        seconds=_RUNTIME_DIRECTORY_VALIDATION_TIMEOUT_SECONDS
    )


async def validate_runtime_directory(
    runner_operations: RuntimeRunnerOperationClient | None,
    *,
    runtime: AgentRuntime | None,
    path: str,
) -> Result[None, RuntimeDirectoryValidationError]:
    """Confirm one path resolves to an existing Runtime directory."""
    if runtime is None or runtime.runner_state != RuntimeRunnerState.READY:
        return Failure(
            RuntimeDirectoryValidationUnavailable(
                message=(
                    "Start the Agent runtime and wait for its Runner to become "
                    "ready, then retry."
                )
            )
        )
    if runner_operations is None:
        return Failure(
            RuntimeDirectoryValidationUnavailable(
                message=(
                    "Agent Runtime Runner operations are unavailable. Start the "
                    "Agent runtime and retry."
                )
            )
        )
    try:
        stat = await runner_operations.stat_file(
            runtime_id=runtime.id,
            runner_generation=runtime.runner_generation,
            owner_session_id=None,
            path=path,
            deadline_at=_runtime_directory_validation_deadline(),
        )
    except (
        RuntimeRunnerOperationUnavailable,
        RuntimeRunnerOperationGenerationError,
    ):
        return Failure(
            RuntimeDirectoryValidationUnavailable(
                message=(
                    "Agent Runtime Runner is unavailable. Start the Agent runtime "
                    "and retry."
                )
            )
        )
    except RuntimeRunnerOperationFailedError as error:
        if error.code == "NOT_FOUND":
            return Failure(RuntimeDirectoryNotFound(path=path))
        return Failure(
            RuntimeDirectoryValidationUnavailable(
                message=(
                    "Agent Runtime Runner could not validate the Project path. "
                    "Retry after the Runtime is ready."
                )
            )
        )
    return _validate_directory_stat(path=path, stat=stat)


def _validate_directory_stat(
    *,
    path: str,
    stat: RuntimeFileStatResult,
) -> Result[None, RuntimeDirectoryValidationError]:
    """Map a Runtime stat result to a neutral directory-validation outcome."""
    target_kind = stat.resolved_kind if stat.kind == "symlink" else stat.kind
    match target_kind:
        case "directory":
            return Success(None)
        case "missing":
            return Failure(RuntimeDirectoryNotFound(path=path))
        case "file" | "symlink" | "other" | None:
            return Failure(RuntimeDirectoryNotDirectory(path=path))
        case _:
            assert_never(target_kind)
