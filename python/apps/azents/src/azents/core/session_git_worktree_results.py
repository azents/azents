"""Pure typed worktree allocation and durable continuation result helpers."""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Literal, NamedTuple

from pydantic import TypeAdapter, ValidationError

from azents.core.action_execution_data import (
    ActionExecutionProjection,
)
from azents.core.enums import (
    ActionExecutionStatus,
    SessionGitWorktreeBranchCreatedBy,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import (
    AgentCreateGitWorktreeContinuationResult,
    AgentRemoveGitWorktreeContinuationResult,
    MailboxPresentationItem,
    TurnActionContinuationMailboxPayload,
)
from azents.core.session_working_folder import validate_session_working_folder_path
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
)
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
)

_AGENT_WORKTREE_BRIDGE_ACTION_TYPES = frozenset(
    {"agent_create_git_worktree", "agent_remove_git_worktree"}
)

_MAX_CONTINUATION_SUMMARY_LENGTH = 1000


class _WorktreeTargets(NamedTuple):
    """Generated worktree path and branch name."""

    worktree_path: str
    branch_name: str


class _CleanupClassification(NamedTuple):
    """Cleanup classification and optional ownership error."""

    classification: Literal["legacy", "canonical"] | None
    ownership_error: str | None


type _CleanupOutcome = Literal[
    "unresolved", "protected", "removed", "already_absent", "failed"
]
_CLEANUP_OUTCOME_ADAPTER = TypeAdapter[_CleanupOutcome](_CleanupOutcome)


@dataclasses.dataclass(frozen=True)
class _CleanupCandidate:
    """Typed fields with opaque legacy data retained only for compatible egress."""

    path: str | None
    outcome: _CleanupOutcome | None
    reason_code: str | None
    summary: str | None
    historical_payload: Mapping[str, JSONValue] | None
    cancellation_applied: bool

    @classmethod
    def decode(cls, payload: dict[str, JSONValue]) -> "_CleanupCandidate":
        """Decode consumed fields once, preserving historical unknown-field behavior."""
        try:
            outcome = _CLEANUP_OUTCOME_ADAPTER.validate_python(payload.get("outcome"))
        except ValidationError:
            outcome = None
        return cls(
            path=_optional_result_string(payload, "path"),
            outcome=outcome,
            reason_code=_optional_result_string(payload, "reason_code"),
            summary=_optional_result_string(payload, "summary"),
            historical_payload=MappingProxyType(dict(payload)),
            cancellation_applied=False,
        )

    def with_cancellation(self, reason: str) -> "_CleanupCandidate":
        """Update unresolved typed candidates without changing captured wire data."""
        if self.outcome != "unresolved":
            return self
        return dataclasses.replace(
            self, reason_code="cancelled", summary=reason, cancellation_applied=True
        )

    def to_json(self) -> dict[str, JSONValue]:
        """Encode known fields or transparently retain legacy extensions at egress."""
        if self.historical_payload is not None:
            payload = dict(self.historical_payload)
            if self.cancellation_applied:
                payload["reason_code"] = self.reason_code
                payload["summary"] = self.summary
            return payload
        return {
            "path": self.path,
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "summary": self.summary,
        }


@dataclasses.dataclass(frozen=True)
class _CleanupResult:
    """Immutable application result until its explicit durable JSON encoding."""

    phase: str
    candidates: tuple[_CleanupCandidate, ...]

    def to_json(self) -> dict[str, JSONValue]:
        """Encode unchanged version/count/phase fields from typed outcomes."""
        values: list[JSONValue] = [candidate.to_json() for candidate in self.candidates]
        return {
            "schema_version": 1,
            "phase": self.phase,
            "examined_count": len(self.candidates),
            "protected_count": _cleanup_candidate_count(self.candidates, "protected"),
            "removed_count": _cleanup_candidate_count(self.candidates, "removed"),
            "already_absent_count": _cleanup_candidate_count(
                self.candidates, "already_absent"
            ),
            "failed_count": _cleanup_candidate_count(self.candidates, "failed"),
            "unresolved_count": _cleanup_candidate_count(self.candidates, "unresolved"),
            "candidates": values,
        }


def _decode_cleanup_candidates(
    result: dict[str, JSONValue],
) -> tuple[_CleanupCandidate, ...]:
    """Decode the historical list once with the original non-dict skip rule."""
    values = result.get("candidates")
    if not isinstance(values, list):
        return ()
    return tuple(
        _CleanupCandidate.decode(value) for value in values if isinstance(value, dict)
    )


def _is_agent_worktree_bridge_action(action_type: str) -> bool:
    """Return whether terminalization requires a fresh-Run continuation."""
    return action_type in _AGENT_WORKTREE_BRIDGE_ACTION_TYPES


def _optional_result_string(
    result: dict[str, JSONValue] | None,
    key: str,
) -> str | None:
    """Read one optional bounded string from an action result."""
    if result is None:
        return None
    value = result.get(key)
    return value if isinstance(value, str) and value else None


def _bounded_terminal_summary(value: str | None) -> str | None:
    """Bound one terminal explanation before exposing it to model continuation."""
    if value is None:
        return None
    summary = value.strip()
    return summary[:_MAX_CONTINUATION_SUMMARY_LENGTH] if summary else None


def _bridge_continuation_payload(
    projection: ActionExecutionProjection,
    *,
    predecessor_run_id: str,
) -> TurnActionContinuationMailboxPayload:
    """Build a closed bounded continuation from one terminal bridge projection."""
    execution = projection.execution
    match execution.status:
        case ActionExecutionStatus.COMPLETED:
            terminal_status = ActionExecutionStatus.COMPLETED
        case ActionExecutionStatus.FAILED:
            terminal_status = ActionExecutionStatus.FAILED
        case ActionExecutionStatus.CANCELLED:
            terminal_status = ActionExecutionStatus.CANCELLED
        case _:
            raise ValueError("Bridge continuation requires terminal execution status")
    reason_code = _optional_result_string(execution.result, "reason_code")
    presentation = MailboxPresentationItem(
        item_key="turn_action_continuation:0",
        presentation_kind="turn_action_continuation",
    )
    match execution.action_type:
        case "agent_create_git_worktree":
            action = AgentCreateGitWorktreeAction.model_validate(execution.action)
            result = AgentCreateGitWorktreeContinuationResult(
                type=action.type,
                source_project_path=action.source_project_path,
                generated_worktree_path=_optional_result_string(
                    execution.result,
                    "worktree_path",
                ),
                requested_starting_ref=action.starting_ref,
                resolved_base_commit=_optional_result_string(
                    execution.result,
                    "base_commit",
                ),
                branch_name=_optional_result_string(
                    execution.result,
                    "branch_name",
                ),
            )
            bridge_identity = action.bridge_identity
            originating_run_id = action.originating_run_id
        case "agent_remove_git_worktree":
            action = AgentRemoveGitWorktreeAction.model_validate(execution.action)
            dirty_content_discarded = (
                execution.result is not None
                and execution.result.get("dirty_content_discarded") is True
            )
            result = AgentRemoveGitWorktreeContinuationResult(
                type=action.type,
                worktree_path=action.worktree_path,
                preserved_branch_name=_optional_result_string(
                    execution.result,
                    "branch_name",
                ),
                force=action.force,
                dirty_content_discarded=dirty_content_discarded,
                retry_guidance=_optional_result_string(
                    execution.result,
                    "retry_guidance",
                ),
            )
            bridge_identity = action.bridge_identity
            originating_run_id = action.originating_run_id
        case _:
            raise ValueError("ActionExecution is not a registered worktree bridge")
    return TurnActionContinuationMailboxPayload(
        type="turn_action_continuation",
        items=[presentation],
        bridge_identity=bridge_identity,
        action_execution_id=execution.id,
        originating_run_id=originating_run_id,
        predecessor_run_id=predecessor_run_id,
        terminal_status=terminal_status,
        reason_code=reason_code,
        failure_summary=_bounded_terminal_summary(execution.failure_summary),
        cancellation_summary=_bounded_terminal_summary(execution.cancellation_summary),
        result=result,
    )


def _target_names(
    *,
    session_handle: str,
    worktree_parent_path: str,
    source_project_path: str,
    path_suffix: int,
    branch_suffix: int,
) -> _WorktreeTargets:
    repo_leaf = _repo_leaf(source_project_path)
    path_leaf = repo_leaf if path_suffix == 1 else f"{repo_leaf}-{path_suffix}"
    branch_base = f"azents/{session_handle}"
    branch_name = (
        branch_base if branch_suffix == 1 else f"{branch_base}-{branch_suffix}"
    )
    return _WorktreeTargets(
        worktree_path=(PurePosixPath(worktree_parent_path) / path_leaf).as_posix(),
        branch_name=branch_name,
    )


def _repo_leaf(source_project_path: str) -> str:
    """Return a filesystem-safe source repository leaf."""
    name = PurePosixPath(source_project_path).name
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-_")
    return sanitized or "repo"


def _cleanup_classification(
    *,
    allocation: SessionGitWorktree,
    session_id: str,
    workspace_root: str,
    working_folder_path: str | None,
) -> _CleanupClassification:
    """Classify a recorded allocation or return its cleanup safety error."""
    if allocation.session_id != session_id:
        return _CleanupClassification(
            classification=None,
            ownership_error="Cleanup request does not match the owning session.",
        )
    worktree_path = PurePosixPath(allocation.worktree_path)
    legacy_worktree_root = PurePosixPath(workspace_root) / ".azents" / "worktrees"
    try:
        worktree_path.relative_to(legacy_worktree_root)
    except ValueError:
        if working_folder_path is None:
            return _CleanupClassification(
                classification=None,
                ownership_error="Session working-folder context is missing.",
            )
        try:
            canonical_working_folder_path = validate_session_working_folder_path(
                working_folder_path,
                workspace_root=workspace_root,
            )
        except ValueError:
            return _CleanupClassification(
                classification=None,
                ownership_error="Session working-folder path is invalid.",
            )
        canonical_parent = PurePosixPath(canonical_working_folder_path) / "worktrees"
        try:
            relative_worktree_path = worktree_path.relative_to(canonical_parent)
        except ValueError:
            return _CleanupClassification(
                classification=None,
                ownership_error="Recorded worktree path is outside the managed roots.",
            )
        if not relative_worktree_path.parts:
            return _CleanupClassification(
                classification=None,
                ownership_error="Recorded worktree path is not a worktree child.",
            )
        classification: Literal["legacy", "canonical"] = "canonical"
    else:
        classification = "legacy"
    if not allocation.branch_name:
        return _CleanupClassification(
            classification=None,
            ownership_error="Recorded Git branch name is missing.",
        )
    if allocation.branch_created_by is not SessionGitWorktreeBranchCreatedBy.AZENTS:
        return _CleanupClassification(
            classification=None,
            ownership_error="Recorded Git branch is not Azents-created.",
        )
    return _CleanupClassification(
        classification=classification,
        ownership_error=None,
    )


def _cleanup_result(
    *,
    phase: str,
    candidates: Sequence[_CleanupCandidate],
) -> _CleanupResult:
    """Build the versioned durable result for one cleanup action."""
    return _CleanupResult(phase=phase, candidates=tuple(candidates))


def _cleanup_candidate_count(
    candidates: Sequence[_CleanupCandidate],
    outcome: str,
) -> int:
    """Count one candidate outcome without exposing candidate contents."""
    return sum(1 for candidate in candidates if candidate.outcome == outcome)
