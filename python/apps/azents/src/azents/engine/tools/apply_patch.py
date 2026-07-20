"""GPT-aligned V4A apply_patch tool backed by one Runtime Runner operation."""

import dataclasses
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azcommon.types import JSONObject
from pydantic import BaseModel, ConfigDict, Field

from azents.engine.run.client_tool_compatibility import ClientToolProfile
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
)
from azents.engine.tooling.make_tool import make_tool
from azents.engine.tools.runtime_io import (
    RuntimeFileApplyPatchFailedError,
    RuntimeFileApplyPatchFailure,
    RuntimeFileApplyPatchResult,
    RuntimeFilePatchChange,
    RuntimeFilePatchOperation,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.services.runtime_storage_error import RuntimeStorageError

logger = logging.getLogger(__name__)

_APPLY_PATCH_SCHEMA_VERSION = 1
_APPLY_PATCH_TIMEOUT_SECONDS = 30
_OPERATION_RESULT_GRACE_SECONDS = 10

GPT_V4A_APPLY_PATCH_PROMPT = """\
Use `edit` for one small exact replacement. Use `apply_patch` for multiple hunks,
multiple files, or combined add/update/delete operations. Read existing files before
patching them. Send one complete V4A patch through the `patch` argument without Markdown
fences. Include each file only once, use exact context, and do not invent line numbers.
After an applicability failure, read the current source before retrying. A commit-phase
failure may have partially applied the patch, so re-read every affected file before
continuing.
"""


class ApplyPatchInput(BaseModel):
    """apply_patch tool input."""

    model_config = ConfigDict(extra="forbid")

    base_path: str = Field(
        description=(
            "Absolute Runtime directory used to resolve every relative patch path."
        )
    )
    patch: str = Field(
        description=(
            "One complete V4A patch from *** Begin Patch through *** End Patch."
        )
    )


@dataclasses.dataclass(frozen=True)
class RuntimePatchTarget:
    """Current Runtime identity used for one patch operation."""

    runtime_id: str
    runner_generation: int


type RuntimePatchTargetResolver = Callable[[], Awaitable[RuntimePatchTarget]]


class RuntimeApplyPatchOperationClient(Protocol):
    """Narrow Runtime operation dependency required by apply_patch."""

    async def apply_patch(
        self,
        *,
        runtime_id: str,
        runner_generation: int,
        owner_session_id: str | None,
        base_path: str,
        patch: bytes,
        schema_version: int,
        deadline_at: datetime,
    ) -> RuntimeFileApplyPatchResult:
        """Run one strict Runtime patch operation."""
        ...


def make_apply_patch_tool(
    *,
    runner_operations: RuntimeApplyPatchOperationClient,
    resolve_runtime_target: RuntimePatchTargetResolver,
    owner_session_id: str | None,
    agent_id: str,
) -> FunctionTool:
    """Create the strict Runtime-backed apply_patch function tool."""

    async def handler(input: ApplyPatchInput) -> FunctionToolResult:
        patch = input.patch.encode("utf-8")
        started_at = datetime.now(UTC)
        try:
            target = await resolve_runtime_target()
            result = await runner_operations.apply_patch(
                runtime_id=target.runtime_id,
                runner_generation=target.runner_generation,
                owner_session_id=owner_session_id,
                base_path=input.base_path,
                patch=patch,
                schema_version=_APPLY_PATCH_SCHEMA_VERSION,
                deadline_at=started_at
                + timedelta(
                    seconds=(
                        _APPLY_PATCH_TIMEOUT_SECONDS + _OPERATION_RESULT_GRACE_SECONDS
                    )
                ),
            )
        except RuntimeFileApplyPatchFailedError as exc:
            logger.info(
                "Runtime apply_patch failed",
                extra={
                    "agent_id": agent_id,
                    "session_id": owner_session_id,
                    "patch_bytes": len(patch),
                    "phase": exc.failure.phase,
                    "reason": exc.failure.reason,
                    "applied_count": len(exc.failure.applied),
                    "not_attempted_count": len(exc.failure.not_attempted),
                    "exact": exc.failure.exact,
                },
            )
            raise FunctionToolError(
                _failure_message(exc, exc.failure),
                metadata=_failure_metadata(exc.failure),
            ) from None
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
            raise FunctionToolError(f"Patch operation failed: {exc}") from None

        logger.info(
            "Runtime apply_patch completed",
            extra={
                "agent_id": agent_id,
                "session_id": owner_session_id,
                "patch_bytes": len(patch),
                "change_count": len(result.changes),
                "added_lines": sum(change.added_lines for change in result.changes),
                "removed_lines": sum(change.removed_lines for change in result.changes),
            },
        )
        return FunctionToolResult(
            output=_success_message(input.base_path, result.changes),
            metadata={
                "kind": "apply_patch_result",
                "base_path": input.base_path,
                "changes": [_change_metadata(change) for change in result.changes],
                "exact": True,
            },
        )

    return make_tool(
        handler,
        name="apply_patch",
        description=(
            "Apply one complete strict V4A patch under an absolute Runtime base "
            "directory. Supports Add File, Update File, and Delete File operations "
            "with exact context matching."
        ),
    ).with_required_client_tool_profile(ClientToolProfile.GPT_V4A_APPLY_PATCH)


def _success_message(
    base_path: str,
    changes: tuple[RuntimeFilePatchChange, ...],
) -> str:
    added_lines = sum(change.added_lines for change in changes)
    removed_lines = sum(change.removed_lines for change in changes)
    noun = "file" if len(changes) == 1 else "files"
    summary = (
        f"Applied patch under {base_path}: {len(changes)} {noun} changed "
        f"(+{added_lines} -{removed_lines}):"
    )
    return "\n".join((summary, *(_change_label(change) for change in changes)))


def _failure_message(
    exc: RuntimeFileApplyPatchFailedError,
    failure: RuntimeFileApplyPatchFailure,
) -> str:
    if failure.applied:
        applied = ", ".join(_change_label(change) for change in failure.applied)
        failed = (
            _operation_label(failure.failed)
            if failure.failed is not None
            else "unknown operation"
        )
        remaining = (
            " Remaining operations were not attempted." if failure.not_attempted else ""
        )
        exact = "" if failure.exact else " The committed delta may be incomplete."
        return (
            f"Patch failed after applying {len(failure.applied)} change(s). "
            f"Applied: {applied}. Failed: {failed}. {exc}.{remaining}{exact} "
            "Re-read the affected files before continuing."
        )
    return f"Patch was not applied. {exc}. {_retry_hint(failure)}"


def _retry_hint(failure: RuntimeFileApplyPatchFailure) -> str:
    if failure.reason == "cancelled":
        return "No files were changed."
    if failure.phase == "parse":
        return "Correct the V4A patch format and retry."
    if failure.reason == "ambiguous_context":
        return "Read the file and retry with more exact context."
    return "Read the current files and retry with exact context."


def _failure_metadata(failure: RuntimeFileApplyPatchFailure) -> JSONObject:
    return {
        "kind": "apply_patch_failure",
        "phase": failure.phase,
        "reason": failure.reason,
        "applied": [_change_metadata(change) for change in failure.applied],
        "failed": (
            _operation_metadata(failure.failed) if failure.failed is not None else None
        ),
        "not_attempted": [
            _operation_metadata(operation) for operation in failure.not_attempted
        ],
        "exact": failure.exact,
    }


def _change_metadata(change: RuntimeFilePatchChange) -> JSONObject:
    return {
        "path": change.path,
        "action": change.action,
        "added_lines": change.added_lines,
        "removed_lines": change.removed_lines,
        "content_sha256": change.content_sha256,
    }


def _operation_metadata(operation: RuntimeFilePatchOperation) -> JSONObject:
    return {"path": operation.path, "action": operation.action}


def _change_label(change: RuntimeFilePatchChange) -> str:
    return f"{_action_letter(change.action)} {change.path}"


def _operation_label(operation: RuntimeFilePatchOperation) -> str:
    return f"{_action_letter(operation.action)} {operation.path}"


def _action_letter(action: str) -> str:
    return {"add": "A", "update": "M", "delete": "D"}.get(action, "?")
