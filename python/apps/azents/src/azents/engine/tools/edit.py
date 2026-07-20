"""Runtime-native edit tool."""

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel, Field

from azents.engine.run.types import FunctionTool, FunctionToolError
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.path_policy import RUNTIME_ACCESSIBLE_PATHS_MSG
from azents.engine.tools.runtime_io import (
    RuntimeFileEditResult,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

_EDIT_TIMEOUT_SECONDS = 30
_OPERATION_RESULT_GRACE_SECONDS = 10


class EditInput(BaseModel):
    """edit tool input."""

    path: str = Field(
        description="Absolute path to edit (e.g. /workspace/agent/config.json)",
    )
    old_string: str = Field(
        description="The exact text to find and replace",
    )
    new_string: str = Field(
        description="The replacement text",
    )
    replace_all: bool = Field(
        default=False,
        description=(
            "Replace all occurrences (default: false, requires exactly one match)"
        ),
    )


@dataclasses.dataclass(frozen=True)
class RuntimeEditTarget:
    """Current Runtime identity used for one edit operation."""

    runtime_id: str
    runner_generation: int


type RuntimeEditTargetResolver = Callable[[], Awaitable[RuntimeEditTarget]]


class RuntimeEditOperationClient(Protocol):
    """Narrow Runtime operation dependency required by edit."""

    async def edit_file(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool,
        deadline_at: datetime,
    ) -> RuntimeFileEditResult:
        """Run one atomic Runtime text replacement."""
        ...


def make_edit_tool(
    *,
    runner_operations: RuntimeEditOperationClient,
    resolve_runtime_target: RuntimeEditTargetResolver,
    owner_session_id: str | None,
    agent_id: str,
) -> FunctionTool:
    """Create the Runtime-native exact text replacement tool."""

    async def handler(input: EditInput) -> str:
        """Replace exact text in one Runtime file transaction."""
        try:
            target = await resolve_runtime_target()
            result = await runner_operations.edit_file(
                runtime_id=target.runtime_id,
                runner_generation=target.runner_generation,
                owner_session_id=owner_session_id,
                path=input.path,
                old_string=input.old_string,
                new_string=input.new_string,
                replace_all=input.replace_all,
                deadline_at=datetime.now(UTC)
                + timedelta(
                    seconds=_EDIT_TIMEOUT_SECONDS + _OPERATION_RESULT_GRACE_SECONDS
                ),
            )
        except RuntimeStorageError as exc:
            raise FunctionToolError(str(exc)) from None
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            raise FunctionToolError(
                "Runtime is temporarily unavailable. Please try again in a moment."
            ) from None
        except RuntimeRunnerOperationFailedError as exc:
            code, _detail = _operation_failure(exc)
            logger.info(
                "Runtime edit failed",
                extra={
                    "agent_id": agent_id,
                    "session_id": owner_session_id,
                    "path": input.path,
                    "failure_code": code,
                },
            )
            raise FunctionToolError(_failure_message(exc, input.path)) from None

        logger.info(
            "Runtime edit completed",
            extra={
                "agent_id": agent_id,
                "session_id": owner_session_id,
                "path": input.path,
                "replacement_count": result.replacements,
            },
        )
        return (
            f"Edited {input.path}: replaced {result.replacements} occurrence(s) "
            "of old_string with new_string."
        )

    return make_tool(
        handler,
        name="edit",
        description=(
            "Edit a text file by replacing exact string matches. "
            "Provide an absolute path like /workspace/agent/config.json, "
            "the old_string to find, and new_string to replace it with. "
            f"{RUNTIME_ACCESSIBLE_PATHS_MSG}"
        ),
    )


def _failure_message(exc: RuntimeRunnerOperationFailedError, path: str) -> str:
    """Map safe Runner edit failure codes to existing model-visible messages."""
    code, detail = _operation_failure(exc)
    if code == "FILE_EDIT_NOT_FOUND":
        return f"File not found: {path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
    if code == "FILE_EDIT_INVALID_UTF8":
        return f"File is not valid UTF-8 text: {path}"
    if code == "FILE_EDIT_OLD_STRING_NOT_FOUND":
        return (
            f"old_string not found in {path}. "
            "Make sure the text matches exactly, including whitespace."
        )
    if code == "FILE_EDIT_MULTIPLE_MATCHES":
        return (
            f"old_string found {_match_count(detail)} times in {path}. "
            "Use replace_all=true to replace all occurrences, "
            "or provide a more specific old_string."
        )
    if code == "FILE_EDIT_PERMISSION_DENIED":
        return (
            f"Cannot write to read-only scope: {path}. {RUNTIME_ACCESSIBLE_PATHS_MSG}"
        )
    if code.startswith("FILE_EDIT_WRITE"):
        return f"Failed to save file: {detail}"
    if code.startswith("FILE_EDIT"):
        return f"Failed to read file: {detail}"
    return f"Failed to edit file: {exc}"


def _operation_failure(exc: RuntimeRunnerOperationFailedError) -> tuple[str, str]:
    """Split a Runner error without interpreting raw operation input."""
    code, separator, detail = str(exc).partition(": ")
    return (code, detail) if separator else (code, "Runtime edit operation failed")


def _match_count(detail: str) -> int:
    """Return the Runner-reported safe match count."""
    try:
        return int(detail)
    except ValueError:
        return 0
