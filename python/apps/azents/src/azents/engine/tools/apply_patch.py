"""GPT-aligned V4A apply_patch tool backed by one Runtime Runner operation."""

import dataclasses
import json
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from azcommon.types import JSONObject
from azents_runtime_control.apply_patch import (
    MAX_APPLY_PATCH_BASE_PATH_BYTES,
    MAX_APPLY_PATCH_BYTES,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from azents.engine.run.client_tool_compatibility import ClientToolProfile
from azents.engine.run.types import (
    FunctionTool,
    FunctionToolError,
    FunctionToolResult,
    FunctionToolSpec,
)
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
_PLAINTEXT_BASE_PATH_PREFIX = "*** Base Path: "
_PLAINTEXT_PATCH_START = "*** Begin Patch"
_PLAINTEXT_INPUT_MAX_BYTES = (
    len(_PLAINTEXT_BASE_PATH_PREFIX.encode("ascii"))
    + MAX_APPLY_PATCH_BASE_PATH_BYTES
    + 1
    + MAX_APPLY_PATCH_BYTES
)

GPT_V4A_APPLY_PATCH_PROMPT = """\
Use `edit` for one small exact replacement. Use `apply_patch` for multiple hunks,
multiple files, or combined add/update/delete operations. Read existing files before
patching them. Send one complete V4A patch through the `patch` argument without Markdown
fences. Include each file only once, use exact context, and do not invent line numbers.
After an applicability failure, read the current source before retrying. A commit-phase
failure may have partially applied the patch, so re-read every affected file before
continuing.
"""

GPT_V4A_PLAINTEXT_CUSTOM_APPLY_PATCH_PROMPT = """\
Use `edit` for one small exact replacement. Use `apply_patch` for multiple hunks,
multiple files, or combined add/update/delete operations. Read existing files before
patching them. Send exactly one plaintext input with this first line:
`*** Base Path: /absolute/runtime/path`
Immediately follow it with one complete V4A patch beginning `*** Begin Patch`. Use LF,
do not add a blank line, Markdown fence, or commentary, and include each file only once.
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


class ApplyPatchPlaintextInputError(Exception):
    """Rejected plaintext custom input without retaining untrusted text."""

    def __init__(self, reason: str) -> None:
        """Store one stable transport failure category."""
        super().__init__(reason)
        self.reason = reason


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
    return FunctionTool(
        spec=FunctionToolSpec(
            name="apply_patch",
            description=(
                "Apply one complete strict V4A patch under an absolute Runtime base "
                "directory. Supports Add File, Update File, and Delete File operations "
                "with exact context matching."
            ),
            input_schema=ApplyPatchInput.model_json_schema(),
        ),
        handler=_ApplyPatchHandler(
            runner_operations=runner_operations,
            resolve_runtime_target=resolve_runtime_target,
            owner_session_id=owner_session_id,
            agent_id=agent_id,
        ),
    ).with_required_client_tool_profile(ClientToolProfile.V4A_APPLY_PATCH_FUNCTION)


@dataclasses.dataclass(frozen=True)
class _ApplyPatchHandler:
    """JSON-function and plaintext-custom adapters over one Runtime operation."""

    runner_operations: RuntimeApplyPatchOperationClient
    resolve_runtime_target: RuntimePatchTargetResolver
    owner_session_id: str | None
    agent_id: str

    async def __call__(self, arguments: str) -> FunctionToolResult:
        """Execute the JSON-function variant."""
        try:
            input = ApplyPatchInput.model_validate(json.loads(arguments))
        except json.JSONDecodeError as exc:
            raise FunctionToolError(f"Invalid JSON in tool arguments: {exc}") from None
        except ValidationError as exc:
            raise FunctionToolError(str(exc)) from None
        return await self._execute(input)

    async def execute_plaintext_custom(self, arguments: str) -> FunctionToolResult:
        """Execute the exact plaintext-custom envelope variant."""
        try:
            input = parse_plaintext_custom_apply_patch_input(arguments)
        except ApplyPatchPlaintextInputError as exc:
            raise FunctionToolError(
                "Invalid apply_patch plaintext input.",
                metadata={
                    "kind": "apply_patch_input_failure",
                    "phase": "transport",
                    "reason": exc.reason,
                    "applied": [],
                    "not_attempted": [],
                    "exact": True,
                },
            ) from None
        return await self._execute(input)

    async def _execute(self, input: ApplyPatchInput) -> FunctionToolResult:
        """Run one already-adapted V4A operation."""
        patch = input.patch.encode("utf-8")
        started_at = datetime.now(UTC)
        try:
            target = await self.resolve_runtime_target()
            result = await self.runner_operations.apply_patch(
                runtime_id=target.runtime_id,
                runner_generation=target.runner_generation,
                owner_session_id=self.owner_session_id,
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
                    "agent_id": self.agent_id,
                    "session_id": self.owner_session_id,
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
                "agent_id": self.agent_id,
                "session_id": self.owner_session_id,
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


def parse_plaintext_custom_apply_patch_input(arguments: str) -> ApplyPatchInput:
    """Parse one exact plaintext custom envelope without modifying its V4A body."""
    try:
        encoded = arguments.encode("utf-8")
    except UnicodeEncodeError:
        raise ApplyPatchPlaintextInputError("invalid_base_path_character") from None
    if len(encoded) > _PLAINTEXT_INPUT_MAX_BYTES:
        raise ApplyPatchPlaintextInputError("input_too_large")
    newline_index = arguments.find("\n")
    if newline_index < 0:
        raise ApplyPatchPlaintextInputError("invalid_base_path_header")
    header = arguments[:newline_index]
    if not header.startswith(_PLAINTEXT_BASE_PATH_PREFIX):
        raise ApplyPatchPlaintextInputError("invalid_base_path_header")
    base_path = header.removeprefix(_PLAINTEXT_BASE_PATH_PREFIX)
    if not base_path:
        raise ApplyPatchPlaintextInputError("invalid_base_path_header")
    if len(base_path.encode("utf-8")) > MAX_APPLY_PATCH_BASE_PATH_BYTES:
        raise ApplyPatchPlaintextInputError("base_path_too_long")
    if _contains_prohibited_base_path_character(base_path):
        raise ApplyPatchPlaintextInputError("invalid_base_path_character")
    if not os.path.isabs(base_path):
        raise ApplyPatchPlaintextInputError("base_path_not_absolute")
    patch = arguments[newline_index + 1 :]
    if not patch:
        raise ApplyPatchPlaintextInputError("missing_patch_body")
    if not patch.startswith(_PLAINTEXT_PATCH_START):
        raise ApplyPatchPlaintextInputError("invalid_patch_start")
    if len(patch.encode("utf-8")) > MAX_APPLY_PATCH_BYTES:
        raise ApplyPatchPlaintextInputError("input_too_large")
    return ApplyPatchInput(base_path=base_path, patch=patch)


def _contains_prohibited_base_path_character(value: str) -> bool:
    """Return whether a header path contains prohibited transport characters."""
    return any(
        ord(character) <= 0x1F
        or 0x7F <= ord(character) <= 0x9F
        or character in {"\u2028", "\u2029"}
        for character in value
    )


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
