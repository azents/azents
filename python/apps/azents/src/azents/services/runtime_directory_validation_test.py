"""Shared Runtime directory validation tests."""

import datetime

from azcommon.result import Failure, Success

from azents.core.enums import RuntimeRunnerState
from azents.repos.agent_runtime.data import AgentRuntime
from azents.runtime.control_protocol.runner_operations import (
    RuntimeFileStatResult,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
)

from .runtime_directory_validation import (
    RuntimeDirectoryNotDirectory,
    RuntimeDirectoryNotFound,
    RuntimeDirectoryValidationUnavailable,
    validate_runtime_directory,
)


class _FakeRunnerOperations(RuntimeRunnerOperationClient):
    """Return one configured Runtime stat outcome."""

    def __init__(
        self,
        *,
        kind: str = "directory",
        error_code: str | None = None,
    ) -> None:
        self.kind = kind
        self.error_code = error_code

    async def stat_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        deadline_at: datetime.datetime,
    ) -> RuntimeFileStatResult:
        """Return a configured stat or stable Runner failure."""
        del runtime_id, runner_generation, owner_session_id, deadline_at
        if self.error_code is not None:
            raise RuntimeRunnerOperationFailedError(
                "Runtime stat failed.",
                code=self.error_code,
            )
        return RuntimeFileStatResult(
            path=path,
            kind="file" if self.kind == "file" else "directory",
            size_bytes=1 if self.kind == "file" else None,
            symlink=False,
            real_path=None,
            resolved_kind="file" if self.kind == "file" else "directory",
            modified_at=None,
            final_cursor="0",
        )


def _ready_runtime() -> AgentRuntime:
    """Build one ready Runtime domain object."""
    now = datetime.datetime.now(datetime.UTC)
    return AgentRuntime(
        id="runtime-1",
        workspace_id="workspace-1",
        agent_id="agent-1",
        runner_state=RuntimeRunnerState.READY,
        runner_generation=3,
        created_at=now,
        updated_at=now,
    )


async def test_validate_runtime_directory_accepts_directory() -> None:
    """A directory stat is valid."""
    result = await validate_runtime_directory(
        _FakeRunnerOperations(),
        runtime=_ready_runtime(),
        path="/workspace/agent/app",
    )

    assert isinstance(result, Success)


async def test_validate_runtime_directory_classifies_not_found() -> None:
    """Stable Runner NOT_FOUND proves the target is absent."""
    result = await validate_runtime_directory(
        _FakeRunnerOperations(error_code="NOT_FOUND"),
        runtime=_ready_runtime(),
        path="/workspace/agent/missing",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, RuntimeDirectoryNotFound)


async def test_validate_runtime_directory_rejects_non_directory() -> None:
    """A successful file stat is not a valid Project directory."""
    result = await validate_runtime_directory(
        _FakeRunnerOperations(kind="file"),
        runtime=_ready_runtime(),
        path="/workspace/agent/file",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, RuntimeDirectoryNotDirectory)


async def test_validate_runtime_directory_classifies_timeout_as_unavailable() -> None:
    """Runner timeouts remain retryable validation unavailability."""
    result = await validate_runtime_directory(
        _FakeRunnerOperations(error_code="operation_timeout"),
        runtime=_ready_runtime(),
        path="/workspace/agent/app",
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, RuntimeDirectoryValidationUnavailable)
