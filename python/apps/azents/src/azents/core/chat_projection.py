"""Pure Chat projection and Session Workspace presentation policy."""

import dataclasses
import datetime
from typing import NamedTuple, assert_never

from azcommon.result import Failure, Result, Success

from azents.core.chat_data import (
    NewSessionDefaultExistingProjectWorkspaceItem,
    NewSessionDefaultGitWorktreeWorkspaceItem,
    NewSessionProjectDefaultWorkspaceItem,
    SubagentTreeNode,
)
from azents.core.enums import (
    AgentProjectDefaultItemType,
    AgentRunStatus,
    AgentSessionRunState,
)
from azents.core.inference_profile import AppliedInferenceProfile
from azents.core.llm_catalog import ModelReasoningEffort
from azents.core.session_workspace_items import (
    ExistingProjectWorkspaceItem,
    GitWorktreeWorkspaceItem,
    NewSessionWorkspaceItem,
)
from azents.core.session_workspace_paths import (
    InvalidProjectPath,
    normalize_session_workspace_path,
    normalize_session_workspace_project_paths,
)
from azents.engine.events.action_messages import (
    CreateGitWorktreeAction,
)
from azents.engine.events.types import AgentRunState
from azents.repos.agent.data import Agent
from azents.repos.agent_project_default.data import (
    AgentProjectDefault,
    AgentProjectDefaultCreate,
)
from azents.repos.agent_session.data import (
    AgentSession,
    SessionAgent,
)
from azents.runtime.control_protocol.runner_operations import (
    RuntimeRunnerOperationFailedError,
)


class _SubagentTreeSortKey(NamedTuple):
    """Field-named result for ``_subagent_tree_sort_key``."""

    missing_sent_at: bool
    descending_sent_at: float
    status_rank: int
    name: str


class _SessionProfileFallback(NamedTuple):
    """Field-named result for ``_session_profile_fallback``."""

    label: str
    reasoning_effort: ModelReasoningEffort | None


def _latest_agent_message_at(
    agent: SessionAgent,
    latest_run: AgentRunState | None,
) -> datetime.datetime | None:
    """Return the latest explicit or terminal message activity for an agent."""
    timestamps = [agent.last_message_at]
    if latest_run is not None and latest_run.terminal_result_message is not None:
        timestamps.append(latest_run.ended_at)
    present = [timestamp for timestamp in timestamps if timestamp is not None]
    return max(present) if present else None


def _subagent_tree_node(
    agent: SessionAgent,
    *,
    session: AgentSession | None,
    latest_run: AgentRunState | None,
) -> SubagentTreeNode:
    """Build a Subagent Tree projection node."""
    run_status = latest_run.status if latest_run is not None else None
    run_index = latest_run.run_index if latest_run is not None else None
    terminal_result_event_id = (
        latest_run.terminal_result_event_id if latest_run is not None else None
    )
    terminal_result_message = (
        latest_run.terminal_result_message if latest_run is not None else None
    )
    return SubagentTreeNode(
        session_agent_id=agent.id,
        agent_session_id=agent.agent_session_id,
        parent_session_agent_id=agent.parent_session_agent_id,
        name=agent.name,
        path=agent.path,
        agent_type=agent.agent_type,
        status=_project_subagent_status(session, run_status),
        last_task_message=agent.last_task_message,
        last_message_at=_latest_agent_message_at(agent, latest_run),
        unread_result=_has_unread_subagent_result(agent, run_status, run_index),
        latest_run_id=latest_run.id if latest_run is not None else None,
        latest_run_index=run_index,
        latest_run_status=run_status,
        terminal_result_event_id=terminal_result_event_id,
        terminal_result_message=terminal_result_message,
    )


def _project_subagent_status(
    session: AgentSession | None,
    latest_run_status: AgentRunStatus | None,
) -> str:
    """Project AgentSession/run status for Subagent Tree consumers."""
    if session is None:
        return "not_found"
    if session.run_state == AgentSessionRunState.RUNNING:
        return "running"
    if latest_run_status is None:
        return "idle"
    if latest_run_status == AgentRunStatus.COMPLETED:
        return "completed"
    if latest_run_status == AgentRunStatus.FAILED:
        return "errored"
    if latest_run_status in {
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return "interrupted"
    return latest_run_status.value


def _subagent_status_sort_rank(status: str) -> int:
    """Return Subagent Tree display order rank for a projected status."""
    match status:
        case "running":
            return 0
        case "failed" | "errored" | "completed":
            return 1
        case "interrupted":
            return 2
        case "pending" | "idle" | "not_found":
            return 3
        case _:
            return 4


def _subagent_tree_sort_key(
    node: SubagentTreeNode,
) -> _SubagentTreeSortKey:
    """Sort siblings with recent message activity first, then stable fallbacks."""
    sent_at = node.last_message_at
    return _SubagentTreeSortKey(
        missing_sent_at=sent_at is None,
        descending_sent_at=-sent_at.timestamp() if sent_at is not None else 0.0,
        status_rank=_subagent_status_sort_rank(node.status),
        name=node.name,
    )


def _finalize_subagent_tree_nodes(
    nodes: list[SubagentTreeNode],
    *,
    ancestor_interrupted: bool = False,
) -> list[SubagentTreeNode]:
    """Sort tree nodes and propagate interrupted status to descendants."""
    finalized: list[SubagentTreeNode] = []
    for node in nodes:
        effective_status = "interrupted" if ancestor_interrupted else node.status
        node_interrupted = ancestor_interrupted or effective_status == "interrupted"
        finalized.append(
            dataclasses.replace(
                node,
                status=effective_status,
                children=_finalize_subagent_tree_nodes(
                    node.children,
                    ancestor_interrupted=node_interrupted,
                ),
            )
        )
    return sorted(finalized, key=_subagent_tree_sort_key)


def _has_unread_subagent_result(
    agent: SessionAgent,
    latest_run_status: AgentRunStatus | None,
    latest_run_index: int | None,
) -> bool:
    """Return whether latest terminal result is unread by the parent."""
    if agent.parent_session_agent_id is None:
        return False
    if latest_run_status not in {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.STOPPED,
        AgentRunStatus.INTERRUPTED,
        AgentRunStatus.CANCELLED,
    }:
        return False
    if latest_run_index is None:
        return False
    if agent.parent_observed_run_index is None:
        return True
    return latest_run_index > agent.parent_observed_run_index


def _require_session_inference_profile(
    session: AgentSession,
) -> AppliedInferenceProfile:
    """Return the prepared public inference profile for an active run."""
    if session.inference_state is None:
        raise ValueError("Active AgentRun has no Session inference state")
    return session.inference_state.applied_profile


def _session_profile_fallback(
    agent: Agent,
) -> _SessionProfileFallback:
    """Return the Agent default label and safe reasoning effort for repair."""
    if not agent.selectable_model_options:
        raise ValueError("Agent has no selectable model options")
    option = next(
        (
            candidate
            for candidate in agent.selectable_model_options
            if candidate.label == agent.main_model_label
        ),
        agent.selectable_model_options[0],
    )
    reasoning_effort = (
        agent.model_parameters.reasoning_effort
        if agent.model_parameters is not None
        else None
    )
    capabilities = option.candidates[0].model_selection.normalized_capabilities
    if reasoning_effort is not None and (
        capabilities.semantic_contract is None
        and not capabilities.reasoning.supported
        or reasoning_effort not in capabilities.configurable_reasoning_efforts()
    ):
        reasoning_effort = None
    return _SessionProfileFallback(
        label=option.label,
        reasoning_effort=reasoning_effort,
    )


def _session_profile_is_stale(
    agent: Agent,
    agent_session: AgentSession,
) -> bool:
    """Return whether a Session's applied label is absent from Agent options."""
    applied = agent_session.applied_inference_profile
    return (
        bool(agent.selectable_model_options)
        and applied is not None
        and not any(
            option.label == applied.model_target_label
            for option in agent.selectable_model_options
        )
    )


_SESSION_TITLE_MAX_LENGTH = 200

_WORKING_FOLDER_CLEANUP_SUMMARY_MAX_LENGTH = 500

_WORKING_FOLDER_CLEANUP_TIMEOUT_SECONDS = 300


def _working_folder_cleanup_failure_summary(
    error: RuntimeRunnerOperationFailedError,
) -> str:
    """Return a bounded cleanup failure summary without Runner error text."""
    reason_code = (error.code or "runner_operation_failed")[:100]
    return f"Session working-folder cleanup failed: {reason_code}."


def _workspace_item_from_default(
    default: AgentProjectDefault,
) -> NewSessionProjectDefaultWorkspaceItem:
    """Convert stored default metadata to a workspace item default."""
    if default.item_type is AgentProjectDefaultItemType.GIT_WORKTREE:
        return NewSessionDefaultGitWorktreeWorkspaceItem(
            source_project_path=default.path,
            starting_ref=None,
        )
    return NewSessionDefaultExistingProjectWorkspaceItem(path=default.path)


def _workspace_items_from_request(
    *,
    existing_project_paths: list[str],
    setup_actions: list[CreateGitWorktreeAction],
    workspace_root: str,
) -> Result[list[NewSessionWorkspaceItem], InvalidProjectPath]:
    """Normalize direct Project paths and setup actions for session creation."""
    try:
        normalized_project_paths = normalize_session_workspace_project_paths(
            existing_project_paths,
            workspace_root=workspace_root,
        )
    except ValueError as exc:
        return Failure(InvalidProjectPath(path="", reason=str(exc)))
    workspace_items: list[NewSessionWorkspaceItem] = [
        ExistingProjectWorkspaceItem(path=path) for path in normalized_project_paths
    ]
    for action in setup_actions:
        try:
            normalized_source_path = normalize_session_workspace_path(
                action.source_project_path,
                workspace_root=workspace_root,
            )
        except ValueError as exc:
            return Failure(
                InvalidProjectPath(
                    path=action.source_project_path,
                    reason=str(exc),
                )
            )
        starting_ref = action.starting_ref.strip()
        if not starting_ref:
            return Failure(
                InvalidProjectPath(
                    path=normalized_source_path,
                    reason="Starting Git ref is required.",
                )
            )
        workspace_items.append(
            GitWorktreeWorkspaceItem(
                source_project_path=normalized_source_path,
                starting_ref=starting_ref,
            )
        )
    return Success(_dedupe_existing_project_items(workspace_items))


def _dedupe_existing_project_items(
    items: list[NewSessionWorkspaceItem],
) -> list[NewSessionWorkspaceItem]:
    """Deduplicate exact existing Project rows while preserving worktree items."""
    seen_project_paths: set[str] = set()
    deduped: list[NewSessionWorkspaceItem] = []
    for item in items:
        match item:
            case ExistingProjectWorkspaceItem(path=path):
                if path in seen_project_paths:
                    continue
                seen_project_paths.add(path)
                deduped.append(item)
            case GitWorktreeWorkspaceItem():
                deduped.append(item)
            case _:
                assert_never(item)
    return deduped


def _default_item_from_workspace_item(
    item: NewSessionWorkspaceItem,
) -> AgentProjectDefaultCreate:
    """Convert a selected workspace item to reusable default metadata."""
    match item:
        case ExistingProjectWorkspaceItem(path=path):
            return AgentProjectDefaultCreate(
                path=path,
                item_type=AgentProjectDefaultItemType.EXISTING_PROJECT,
            )
        case GitWorktreeWorkspaceItem(source_project_path=source_project_path):
            return AgentProjectDefaultCreate(
                path=source_project_path,
                item_type=AgentProjectDefaultItemType.GIT_WORKTREE,
            )
        case _:
            assert_never(item)
