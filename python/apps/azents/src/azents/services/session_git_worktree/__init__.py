"""Session Git worktree initialization service."""

import asyncio
import dataclasses
import hashlib
import logging
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Annotated, Literal, NamedTuple, assert_never

from azcommon.logging import bind_extra
from azcommon.result import Failure, Result, Success
from azcommon.uuid import uuid7
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    AgentProjectCatalogStatus,
    AgentRuntimeCapability,
    AgentSessionKind,
    AgentSessionStatus,
    EventKind,
    GitWorktreePathClaimState,
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.core.session_working_folder import validate_session_working_folder_path
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
    CleanupOrphanGitWorktreesAction,
    CreateGitWorktreeAction,
    CreateSessionWorkingFolderAction,
)
from azents.engine.events.types import Event
from azents.engine.run.types import SHUTDOWN_CANCEL_MESSAGE, USER_STOP_CANCEL_MESSAGE
from azents.engine.tools.deps import get_skill_state_store
from azents.engine.tools.skill import SkillProjectionService, SkillStateStore
from azents.rdb.deps import get_session_manager
from azents.rdb.models.event import JSONValue
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.action_execution.data import (
    ActionExecution,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.mailbox.data import (
    AgentCreateGitWorktreeContinuationResult,
    AgentRemoveGitWorktreeContinuationResult,
    MailboxItemCreate,
    MailboxPresentationItem,
    TurnActionContinuationMailboxPayload,
)
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.session_workspace_project.data import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.runtime.control_protocol.runner_operations import (
    RuntimeGitRefEntry,
    RuntimeOperationTextCallback,
    RuntimeOperationTextDelta,
    RuntimeRunnerOperationCanceledError,
    RuntimeRunnerOperationClient,
    RuntimeRunnerOperationFailedError,
    RuntimeRunnerOperationGenerationError,
    RuntimeRunnerOperationUnavailable,
)
from azents.runtime.deps import get_runtime_runner_operation_client
from azents.runtime.runner_operation_adapter import adapt_runtime_runner_operations
from azents.services.agent_project_catalog import AgentProjectCatalogService
from azents.services.agent_runtime.lifecycle_data import (
    RuntimeOperationAuthority,
    RuntimeOperationTarget,
    RuntimeOperationTargetResolver,
)
from azents.services.agent_runtime.service import AgentRuntimeService
from azents.services.runtime_storage_error import RuntimeStorageError
from azents.services.session_working_folder_binding import (
    SessionWorkingFolderBindingError,
    SessionWorkingFolderBindingService,
)
from azents.services.session_workspace_project import (
    InvalidProjectPath,
    normalize_agent_workspace_root,
    normalize_session_workspace_path,
)

_GIT_OPERATION_TIMEOUT_SECONDS = 300
_MAX_COLLISION_ATTEMPTS = 20
logger = logging.getLogger(__name__)
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


@dataclasses.dataclass(frozen=True)
class ExistingProjectWorkspaceItem:
    """Existing Project item selected for a new AgentSession."""

    path: str


@dataclasses.dataclass(frozen=True)
class GitWorktreeWorkspaceItem:
    """Git worktree item selected for a new AgentSession."""

    source_project_path: str
    starting_ref: str


NewSessionWorkspaceItem = ExistingProjectWorkspaceItem | GitWorktreeWorkspaceItem


@dataclasses.dataclass(frozen=True)
class WorkspaceItemsWorkspaceMode:
    """Ordered workspace items selected for a new AgentSession."""

    items: list[NewSessionWorkspaceItem]


@dataclasses.dataclass(frozen=True)
class GitWorktreeWorkspaceMode:
    """Legacy single Git worktree mode selected for a new AgentSession."""

    source_project_path: str
    starting_ref: str


@dataclasses.dataclass(frozen=True)
class ExplicitProjectsWorkspaceMode:
    """Legacy existing explicit Project path mode selected for a new AgentSession."""

    project_paths: list[str]


NewSessionWorkspaceMode = (
    WorkspaceItemsWorkspaceMode
    | ExplicitProjectsWorkspaceMode
    | GitWorktreeWorkspaceMode
)


@dataclasses.dataclass(frozen=True)
class GitRefPreview:
    """Git refs available from a source Project."""

    refs: tuple[RuntimeGitRefEntry, ...]
    default_branch: str | None
    head_commit: str | None
    repository_anchor_path: str


@dataclasses.dataclass(frozen=True)
class GitRefPreviewAgentNotFound:
    """Agent for Git ref preview was not found."""


@dataclasses.dataclass(frozen=True)
class GitRefPreviewAccessDenied:
    """Requester cannot access the Agent workspace."""


@dataclasses.dataclass(frozen=True)
class GitRefPreviewRuntimeUnavailable:
    """Runtime Runner is not available for Git ref preview."""

    reason: str


GitRefPreviewError = (
    GitRefPreviewAgentNotFound
    | GitRefPreviewAccessDenied
    | GitRefPreviewRuntimeUnavailable
    | InvalidProjectPath
)


ActionExecutionProjectionCallback = Callable[
    [ActionExecutionProjection], Awaitable[None]
]
ActionExecutionHistoryEventCallback = Callable[[Event], Awaitable[None]]
ActionExecutionRemovedCallback = Callable[[str], Awaitable[None]]


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupRequest:
    """Cleanup request result."""

    cleanup_requested: bool


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupSessionNotFound:
    """Session for cleanup was not found."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupAccessDenied:
    """Requester cannot clean up this session worktree."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupSubagentReadOnly:
    """Child subagent sessions do not accept direct cleanup requests."""


@dataclasses.dataclass(frozen=True)
class GitWorktreeCleanupNotFound:
    """No session Git worktree allocation exists."""


GitWorktreeCleanupRequestError = (
    GitWorktreeCleanupSessionNotFound
    | GitWorktreeCleanupAccessDenied
    | GitWorktreeCleanupSubagentReadOnly
    | GitWorktreeCleanupNotFound
)


@dataclasses.dataclass(frozen=True)
class GitWorktreeActionExecutionResult:
    """Result of executing one create_git_worktree TurnAction."""

    completed: bool
    context_invalidated: bool
    complete_run: bool


@dataclasses.dataclass(frozen=True)
class AgentCreateGitWorktreeAdmission:
    """Durable acceptance result for one Agent create bridge call."""

    mailbox_item_id: str
    bridge_identity: str


@dataclasses.dataclass(frozen=True)
class AgentRemoveGitWorktreeAdmission:
    """Durable acceptance result for one Agent removal bridge call."""

    mailbox_item_id: str
    bridge_identity: str


@dataclasses.dataclass
class SessionGitWorktreeService:
    """Orchestrate session Git worktree allocation and initialization."""

    agent_repository: Annotated[AgentRepository, Depends(AgentRepository)]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    workspace_user_repository: Annotated[
        WorkspaceUserRepository, Depends(WorkspaceUserRepository)
    ]
    agent_runtime_repository: Annotated[
        AgentRuntimeRepository, Depends(AgentRuntimeRepository)
    ]
    session_git_worktree_repository: Annotated[
        SessionGitWorktreeRepository, Depends(SessionGitWorktreeRepository)
    ]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends(SessionWorkspaceProjectRepository)
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends(AgentProjectCatalogRepository)
    ]
    agent_project_catalog_service: Annotated[
        AgentProjectCatalogService, Depends(AgentProjectCatalogService)
    ]
    action_execution_repository: Annotated[
        ActionExecutionRepository, Depends(ActionExecutionRepository)
    ]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    event_transcript_repository: Annotated[
        EventTranscriptRepository, Depends(EventTranscriptRepository)
    ]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]
    runtime_target_resolver: Annotated[
        RuntimeOperationTargetResolver,
        Depends(AgentRuntimeService),
    ]
    session_working_folder_binding_service: Annotated[
        SessionWorkingFolderBindingService,
        Depends(),
    ]
    runner_operations: Annotated[
        RuntimeRunnerOperationClient | None,
        Depends(get_runtime_runner_operation_client),
    ] = None
    skill_store: Annotated[SkillStateStore | None, Depends(get_skill_state_store)] = (
        None
    )

    async def agent_create_git_worktree_available(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Return whether the current Session may project the Agent create tool."""
        if self.runner_operations is None or self.skill_store is None:
            return False
        try:
            await self.session_working_folder_binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                wait_timeout_seconds=0,
                start_if_stopped=False,
            )
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            return False
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        return (
            agent_session is not None
            and agent_session.agent_id == agent_id
            and agent_session.status is AgentSessionStatus.ACTIVE
        )

    async def admit_agent_create_git_worktree(
        self,
        *,
        agent_id: str,
        session_id: str,
        originating_run_id: str,
        client_tool_call_id: str,
        source_project_path: str,
        starting_ref: str | None,
        branch_name: str | None,
    ) -> AgentCreateGitWorktreeAdmission:
        """Pin current authority and durably enqueue one Agent create action."""
        if self.runner_operations is None or self.skill_store is None:
            raise ValueError("Agent-managed worktree creation is unavailable")
        normalized_starting_ref = _normalized_optional_tool_argument(
            starting_ref,
            field_name="starting_ref",
        )
        normalized_branch_name = _normalized_optional_tool_argument(
            branch_name,
            field_name="branch_name",
        )
        try:
            await self.session_working_folder_binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding_service = self.session_working_folder_binding_service
            authority = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_source_path = normalize_session_workspace_path(
                source_project_path,
                workspace_root=workspace_root,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as error:
            raise ValueError(str(error)) from None
        except ValueError as error:
            raise ValueError(str(error)) from None

        bridge_identity = _worktree_bridge_identity(
            session_id=session_id,
            run_id=originating_run_id,
            tool_name="create_git_worktree",
            client_tool_call_id=client_tool_call_id,
        )
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            session_agent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            project = (
                await self.session_workspace_project_repository.get_project_by_path(
                    session,
                    session_id=session_id,
                    path=normalized_source_path,
                )
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
                or session_agent is None
                or session_agent.context_id != authority.context_id
            ):
                raise ValueError("The current Session context is unavailable.")
            if (
                project is None
                or project.session_agent_context_id != authority.context_id
            ):
                raise ValueError(
                    "source_project_path must identify a current Session Project."
                )
            action = AgentCreateGitWorktreeAction(
                bridge_identity=bridge_identity,
                originating_run_id=originating_run_id,
                client_tool_call_id=client_tool_call_id,
                session_agent_context_id=authority.context_id,
                originating_agent_session_id=session_id,
                source_project_id=project.id,
                source_project_path=normalized_source_path,
                starting_ref=normalized_starting_ref,
                branch_name=normalized_branch_name,
            )
            existing = await self.mailbox_item_repository.get_by_idempotency_key(
                session,
                session_id=session_id,
                kind=MailboxItemKind.ACTION_MESSAGE,
                idempotency_key=bridge_identity,
            )
            admission = existing
            if admission is None:
                admission = await self.mailbox_item_repository.create_idempotent(
                    session,
                    MailboxItemCreate(
                        session_id=session_id,
                        kind=MailboxItemKind.ACTION_MESSAGE,
                        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        sender_user_id=None,
                        order_group=None,
                        order_sequence=0,
                        content="",
                        idempotency_key=bridge_identity,
                        metadata={"source": "agent_tool"},
                        action=action.model_dump(mode="json"),
                        attachments=[],
                        file_parts=[],
                        payload=None,
                    ),
                    idempotency_key=bridge_identity,
                )
            if admission.presentation.action != action.model_dump(mode="json"):
                raise ValueError(
                    "The client tool call identity is already bound to another request."
                )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                session_id,
            )
        return AgentCreateGitWorktreeAdmission(
            mailbox_item_id=admission.id,
            bridge_identity=bridge_identity,
        )

    async def agent_remove_git_worktree_available(
        self,
        *,
        agent_id: str,
        session_id: str,
    ) -> bool:
        """Return whether the current context has a removable managed Project."""
        if self.runner_operations is None or self.skill_store is None:
            return False
        try:
            await self.session_working_folder_binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                wait_timeout_seconds=0,
                start_if_stopped=False,
            )
        except RuntimeStorageError, SessionWorkingFolderBindingError:
            return False
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
            ):
                return False
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        return any(
            allocation.status is SessionGitWorktreeStatus.READY
            and allocation.session_workspace_project_id is not None
            for allocation in allocations
        )

    async def admit_agent_remove_git_worktree(
        self,
        *,
        agent_id: str,
        session_id: str,
        originating_run_id: str,
        client_tool_call_id: str,
        worktree_project_path: str,
        force: bool,
    ) -> AgentRemoveGitWorktreeAdmission:
        """Pin one exact current-context managed worktree removal request."""
        if self.runner_operations is None or self.skill_store is None:
            raise ValueError("Agent-managed worktree removal is unavailable")
        try:
            await self.session_working_folder_binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding_service = self.session_working_folder_binding_service
            authority = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_worktree_path = normalize_session_workspace_path(
                worktree_project_path,
                workspace_root=workspace_root,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as error:
            raise ValueError(str(error)) from None
        except ValueError as error:
            raise ValueError(str(error)) from None

        bridge_identity = _worktree_bridge_identity(
            session_id=session_id,
            run_id=originating_run_id,
            tool_name="remove_git_worktree",
            client_tool_call_id=client_tool_call_id,
        )
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            session_agent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            project = (
                await self.session_workspace_project_repository.get_project_by_path(
                    session,
                    session_id=session_id,
                    path=normalized_worktree_path,
                )
            )
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            allocation = next(
                (
                    candidate
                    for candidate in allocations
                    if project is not None
                    and candidate.session_workspace_project_id == project.id
                    and candidate.worktree_path == normalized_worktree_path
                    and candidate.status is SessionGitWorktreeStatus.READY
                ),
                None,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
                or session_agent is None
                or session_agent.context_id != authority.context_id
            ):
                raise ValueError("The current Session context is unavailable.")
            if (
                project is None
                or project.session_agent_context_id != authority.context_id
                or allocation is None
            ):
                raise ValueError(
                    "worktree_project_path must identify a current Session "
                    "Agent-managed worktree Project."
                )
            action = AgentRemoveGitWorktreeAction(
                bridge_identity=bridge_identity,
                originating_run_id=originating_run_id,
                client_tool_call_id=client_tool_call_id,
                session_agent_context_id=authority.context_id,
                originating_agent_session_id=session_id,
                worktree_project_id=project.id,
                worktree_allocation_id=allocation.id,
                worktree_path=normalized_worktree_path,
                force=force,
            )
            existing = await self.mailbox_item_repository.get_by_idempotency_key(
                session,
                session_id=session_id,
                kind=MailboxItemKind.ACTION_MESSAGE,
                idempotency_key=bridge_identity,
            )
            admission = existing
            if admission is None:
                admission = await self.mailbox_item_repository.create_idempotent(
                    session,
                    MailboxItemCreate(
                        session_id=session_id,
                        kind=MailboxItemKind.ACTION_MESSAGE,
                        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                        requested_model_target_label=None,
                        requested_reasoning_effort=None,
                        sender_user_id=None,
                        order_group=None,
                        order_sequence=0,
                        content="",
                        idempotency_key=bridge_identity,
                        metadata={"source": "agent_tool"},
                        action=action.model_dump(mode="json"),
                        attachments=[],
                        file_parts=[],
                        payload=None,
                    ),
                    idempotency_key=bridge_identity,
                )
            if admission.presentation.action != action.model_dump(mode="json"):
                raise ValueError(
                    "The client tool call identity is already bound to another request."
                )
            await self.agent_session_repository.mark_running_for_input_wakeup(
                session,
                session_id,
            )
        return AgentRemoveGitWorktreeAdmission(
            mailbox_item_id=admission.id,
            bridge_identity=bridge_identity,
        )

    async def preview_git_refs(
        self,
        *,
        agent_id: str,
        user_id: str,
        source_project_path: str,
    ) -> Result[GitRefPreview, GitRefPreviewError]:
        """List Git refs for a source Project after access validation."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return Failure(GitRefPreviewAgentNotFound())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(GitRefPreviewAccessDenied())
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
        except RuntimeStorageError as error:
            return Failure(GitRefPreviewRuntimeUnavailable(reason=str(error)))
        if self.runner_operations is None:
            return Failure(
                GitRefPreviewRuntimeUnavailable(
                    reason="Runtime runner operations are unavailable."
                )
            )
        try:
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_source_path = normalize_session_workspace_path(
                source_project_path,
                workspace_root=workspace_root,
            )
        except ValueError as exc:
            return Failure(
                InvalidProjectPath(path=source_project_path, reason=str(exc))
            )
        try:
            result = await self.runner_operations.list_git_refs(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=None,
                source_project_path=normalized_source_path,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            return Failure(
                GitRefPreviewRuntimeUnavailable(reason="Runtime runner is not ready.")
            )
        except RuntimeRunnerOperationFailedError as exc:
            return Failure(GitRefPreviewRuntimeUnavailable(reason=str(exc)))
        return Success(
            GitRefPreview(
                refs=result.refs,
                default_branch=result.default_branch,
                head_commit=result.head_commit,
                repository_anchor_path=result.repository_anchor_path,
            )
        )

    async def _create_and_link_workspace_project(
        self,
        session: AsyncSession,
        *,
        allocation: SessionGitWorktree,
        worktree_path: str,
    ) -> SessionWorkspaceProject:
        """Register the worktree Project and link it to the allocation."""
        project = await self.session_workspace_project_repository.create_project(
            session,
            SessionWorkspaceProjectCreate(
                session_id=allocation.session_id,
                path=worktree_path,
            ),
        )
        await self.session_git_worktree_repository.link_workspace_project(
            session,
            worktree_id=allocation.id,
            session_workspace_project_id=project.id,
        )
        return project

    async def run_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one worker-owned create_git_worktree TurnAction."""
        try:
            return await self._execute_git_worktree_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                action=action,
                owner_generation=owner_generation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=None,
                )
            )
            raise

    async def run_agent_create_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentCreateGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one admitted Agent create bridge through the shared lifecycle."""
        try:
            return await self._execute_agent_create_git_worktree_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                action=action,
                owner_generation=owner_generation,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=predecessor_run_id,
                )
            )
            raise

    async def run_agent_remove_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentRemoveGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one admitted Agent removal while preserving its Git branch."""
        try:
            return await self._execute_agent_remove_git_worktree_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                action=action,
                owner_generation=owner_generation,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self._release_nonremoving_agent_removal_claims(
                    action_execution_id=execution.id,
                )
            )
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=predecessor_run_id,
                )
            )
            raise

    async def run_cleanup_orphan_git_worktrees_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CleanupOrphanGitWorktreesAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one manual orphan-worktree cleanup TurnAction."""
        del action
        try:
            return await self._execute_cleanup_orphan_git_worktrees_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                owner_generation=owner_generation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self._release_nonremoving_cleanup_claims(
                    action_execution_id=execution.id
                )
            )
            await asyncio.shield(
                self._persist_cleanup_cancellation(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_projection_updated=on_projection_updated,
                )
            )
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=None,
                )
            )
            raise

    async def run_create_session_working_folder_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateSessionWorkingFolderAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None = None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None = None,
    ) -> GitWorktreeActionExecutionResult:
        """Materialize the stored Session working folder through the Runner."""
        del action
        try:
            return await self._execute_create_session_working_folder_action(
                agent_id=agent_id,
                session_id=session_id,
                execution=execution,
                owner_generation=owner_generation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        except asyncio.CancelledError as exc:
            await asyncio.shield(
                self.cancel_action_execution(
                    execution=execution,
                    reason=_action_cancellation_reason(exc),
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=None,
                )
            )
            raise

    async def _execute_create_session_working_folder_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Run one current-binding folder setup action."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if agent_session is None or agent_session.agent_id != agent_id:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code="session_not_found",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        async with self.session_manager() as session:
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="create_session_working_folder",
            command_argv=None,
            content="Preparing Session working folder.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
            binding = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
        except RuntimeStorageError:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code="runtime_unavailable",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        except SessionWorkingFolderBindingError as error:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code=(
                    "invalid_stored_path"
                    if error.reason_code == "binding_stale"
                    else "binding_unavailable"
                ),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        working_folder_path = binding.working_folder_path
        if self.runner_operations is None:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code="runner_operations_unavailable",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        try:
            await self.runner_operations.mkdir_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                path=working_folder_path,
                parents=True,
                deadline_at=_git_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code="runtime_unavailable",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        except RuntimeRunnerOperationCanceledError:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code="runner_operation_canceled",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        except RuntimeRunnerOperationFailedError as exc:
            await self._mark_session_working_folder_action_failed(
                execution=execution,
                reason_code=exc.code or "runner_operation_failed",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )

        execution = await self._update_session_working_folder_result(
            execution=execution,
            result={
                "phase": "completed",
                "outcome": "ready",
                "reason_code": None,
            },
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.COMPLETED,
            step_key="create_session_working_folder",
            command_argv=None,
            content="Session working folder is ready.",
            exit_code=0,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            on_history_event_appended=on_history_event_appended,
        )
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=False,
            complete_run=False,
        )

    async def _update_session_working_folder_result(
        self,
        *,
        execution: ActionExecution,
        result: dict[str, JSONValue],
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecution:
        """Persist and project one bounded Session-folder setup result."""
        async with self.session_manager() as session:
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result,
            )
        await self._publish_action_execution_projection(
            execution=updated,
            on_projection_updated=on_projection_updated,
        )
        return updated

    async def _mark_session_working_folder_action_failed(
        self,
        *,
        execution: ActionExecution,
        reason_code: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Record bounded failure evidence and terminalize folder setup."""
        execution = await self._update_session_working_folder_result(
            execution=execution,
            result={
                "phase": "failed",
                "outcome": "failed",
                "reason_code": reason_code,
            },
            on_projection_updated=on_projection_updated,
        )
        reason = "Session working-folder setup failed."
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key="create_session_working_folder",
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            on_history_event_appended=on_history_event_appended,
        )

    async def _execute_cleanup_orphan_git_worktrees_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Discover and force-remove orphan worktrees from the current Runtime."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            project_repository = self.session_workspace_project_repository
            context_runtime_id = await project_repository.get_runtime_id_by_session_id(
                session,
                session_id=session_id,
            )
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
            execution = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=_cleanup_result(phase="discovering", candidates=[]),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        L = bind_extra(
            logger,
            {
                "operation": "cleanup_orphan_git_worktrees",
                "action_execution_id": execution.id,
                "agent_id": agent_id,
                "session_id": session_id,
                "runtime_id": context_runtime_id,
            },
        )
        L.info(
            "Manual orphan Git worktree cleanup started",
            extra={"stage": "initializing"},
        )

        if (
            agent_session is None
            or agent_session.agent_id != agent_id
            or agent_session.session_kind is not AgentSessionKind.ROOT
            or agent_session.status is not AgentSessionStatus.ACTIVE
        ):
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code="session_invalid",
                    candidates=[],
                ),
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason="Session not found.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as error:
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code=(
                        "binding_unavailable"
                        if isinstance(error, SessionWorkingFolderBindingError)
                        else "runtime_unavailable"
                    ),
                    candidates=[],
                ),
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason=str(error),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        if runtime.id != context_runtime_id:
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra={
                    **_cleanup_log_summary(
                        stage="terminal",
                        reason_code="runtime_changed",
                        candidates=[],
                    ),
                    "current_runtime_id": runtime.id,
                },
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason="Runtime changed before cleanup could start.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        if self.runner_operations is None:
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code="runner_operations_unavailable",
                    candidates=[],
                ),
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason="Runtime runner operations are unavailable.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )

        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="discover_orphan_git_worktrees",
            command_argv=None,
            content="Discovering managed Git worktrees.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            discovery = await self.runner_operations.discover_managed_git_worktrees(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                deadline_at=_git_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            L.warning(
                "Manual orphan Git worktree discovery failed",
                exc_info=True,
                extra={
                    "stage": "discovery",
                    "reason_code": "runtime_unavailable",
                    "runner_error_code": type(exc).__name__,
                },
            )
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code="runtime_unavailable",
                    candidates=[],
                ),
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason="Runtime runner is not ready.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        except RuntimeRunnerOperationFailedError as exc:
            L.warning(
                "Manual orphan Git worktree discovery failed",
                exc_info=True,
                extra={
                    "stage": "discovery",
                    "reason_code": "runner_operation_failed",
                    "runner_error_code": exc.code or "runner_operation_failed",
                },
            )
            L.warning(
                "Manual orphan Git worktree cleanup failed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code="runner_operation_failed",
                    candidates=[],
                ),
            )
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=_cleanup_result(phase="failed", candidates=[]),
                reason="Managed Git worktree discovery failed.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )

        L.info(
            "Managed Git worktree discovery completed",
            extra={
                "stage": "discovery",
                "candidate_count": len(discovery.entries),
                "registered_candidate_count": sum(
                    entry.registered for entry in discovery.entries
                ),
                "unidentified_candidate_count": sum(
                    not entry.registered
                    or entry.repository_anchor_path is None
                    or entry.failure_code is not None
                    for entry in discovery.entries
                ),
            },
        )
        candidates = [
            _cleanup_candidate(
                path=entry.worktree_path,
                outcome="unresolved",
                reason_code=None,
                summary=None,
            )
            for entry in sorted(
                discovery.entries, key=lambda entry: entry.worktree_path
            )
        ]
        result = _cleanup_result(phase="processing", candidates=candidates)
        execution = await self._update_cleanup_result(
            execution=execution,
            result=result,
            on_projection_updated=on_projection_updated,
        )

        for index, discovered in enumerate(
            sorted(discovery.entries, key=lambda entry: entry.worktree_path)
        ):
            if (
                not discovered.registered
                or discovered.repository_anchor_path is None
                or discovered.failure_code is not None
            ):
                candidates[index] = _cleanup_candidate(
                    path=discovered.worktree_path,
                    outcome="failed",
                    reason_code=discovered.failure_code
                    or "worktree_ownership_ambiguous",
                    summary="Git worktree identity could not be established.",
                )
                result = _cleanup_result(phase="processing", candidates=candidates)
                execution = await self._update_cleanup_result(
                    execution=execution,
                    result=result,
                    on_projection_updated=on_projection_updated,
                )
                L.warning(
                    "Manual orphan Git worktree cleanup candidate failed",
                    extra={
                        "stage": "candidate_validation",
                        "worktree_path": discovered.worktree_path,
                        "reason_code": discovered.failure_code
                        or "worktree_ownership_ambiguous",
                    },
                )
                await self._append_action_execution_event(
                    execution=execution,
                    kind=ActionExecutionEventKind.FAILED,
                    step_key="orphan_git_worktree_failed",
                    command_argv=None,
                    content="A managed worktree could not be safely identified.",
                    exit_code=None,
                    on_projection_updated=on_projection_updated,
                )
                continue

            claim_outcome = await self._claim_cleanup_candidate(
                runtime_id=runtime.id,
                action_execution_id=execution.id,
                owner_generation=execution.owner_generation,
                worktree_path=discovered.worktree_path,
                discovery_fingerprint=discovered.fingerprint,
            )
            if claim_outcome != "claimed":
                candidates[index] = _cleanup_candidate(
                    path=discovered.worktree_path,
                    outcome=(
                        "protected"
                        if claim_outcome == "active_connection"
                        else "failed"
                    ),
                    reason_code=claim_outcome,
                    summary=(
                        "Connected to active Session work."
                        if claim_outcome == "active_connection"
                        else "Another manual cleanup currently owns this path."
                    ),
                )
                result = _cleanup_result(phase="processing", candidates=candidates)
                execution = await self._update_cleanup_result(
                    execution=execution,
                    result=result,
                    on_projection_updated=on_projection_updated,
                )
                if claim_outcome == "active_connection":
                    L.info(
                        "Manual orphan Git worktree cleanup candidate protected",
                        extra={
                            "stage": "claim",
                            "worktree_path": discovered.worktree_path,
                            "reason_code": claim_outcome,
                        },
                    )
                else:
                    L.warning(
                        "Manual orphan Git worktree cleanup candidate failed",
                        extra={
                            "stage": "claim",
                            "worktree_path": discovered.worktree_path,
                            "reason_code": claim_outcome,
                        },
                    )
                await self._append_action_execution_event(
                    execution=execution,
                    kind=(
                        ActionExecutionEventKind.STEP_STARTED
                        if claim_outcome == "active_connection"
                        else ActionExecutionEventKind.FAILED
                    ),
                    step_key=(
                        "protect_active_worktree"
                        if claim_outcome == "active_connection"
                        else "orphan_git_worktree_failed"
                    ),
                    command_argv=None,
                    content=(
                        "Protected a worktree connected to active Session work."
                        if claim_outcome == "active_connection"
                        else "Skipped a worktree owned by another manual cleanup."
                    ),
                    exit_code=None,
                    on_projection_updated=on_projection_updated,
                )
                continue

            claim_state = GitWorktreePathClaimState.UNRESOLVED
            try:
                await self._mark_cleanup_claim_removing(
                    action_execution_id=execution.id,
                    worktree_path=discovered.worktree_path,
                )
                await self._append_action_execution_event(
                    execution=execution,
                    kind=ActionExecutionEventKind.STEP_STARTED,
                    step_key="remove_orphan_git_worktree",
                    command_argv=None,
                    content="Removing an orphaned Git worktree.",
                    exit_code=None,
                    on_projection_updated=on_projection_updated,
                )
                try:
                    removal = (
                        await self.runner_operations.remove_discovered_git_worktree(
                            runtime_id=runtime.id,
                            runner_generation=runtime.runner_generation,
                            owner_session_id=session_id,
                            discovered=discovered,
                            deadline_at=_git_operation_deadline(),
                        )
                    )
                except (
                    RuntimeRunnerOperationUnavailable,
                    RuntimeRunnerOperationGenerationError,
                ) as exc:
                    outcome = "failed"
                    reason_code = "runtime_unavailable"
                    summary = "Runtime runner is not ready."
                    claim_state = GitWorktreePathClaimState.FAILED
                    L.warning(
                        "Manual orphan Git worktree removal failed",
                        exc_info=True,
                        extra={
                            "stage": "removal",
                            "worktree_path": discovered.worktree_path,
                            "reason_code": reason_code,
                            "runner_error_code": type(exc).__name__,
                        },
                    )
                except RuntimeRunnerOperationFailedError as exc:
                    outcome = "failed"
                    reason_code = exc.code or "runner_operation_failed"
                    summary = "Git worktree removal failed."
                    claim_state = GitWorktreePathClaimState.FAILED
                    L.warning(
                        "Manual orphan Git worktree removal failed",
                        exc_info=True,
                        extra={
                            "stage": "removal",
                            "worktree_path": discovered.worktree_path,
                            "reason_code": reason_code,
                            "runner_error_code": reason_code,
                        },
                    )
                else:
                    outcome = removal.outcome
                    reason_code = None
                    summary = None
                    claim_state = (
                        GitWorktreePathClaimState.REMOVED
                        if outcome == "removed"
                        else GitWorktreePathClaimState.ALREADY_ABSENT
                    )
            finally:
                await self._release_cleanup_claim(
                    action_execution_id=execution.id,
                    worktree_path=discovered.worktree_path,
                    state=claim_state,
                )
            candidates[index] = _cleanup_candidate(
                path=discovered.worktree_path,
                outcome=outcome,
                reason_code=reason_code,
                summary=summary,
            )
            result = _cleanup_result(phase="processing", candidates=candidates)
            execution = await self._update_cleanup_result(
                execution=execution,
                result=result,
                on_projection_updated=on_projection_updated,
            )
            await self._append_action_execution_event(
                execution=execution,
                kind=(
                    ActionExecutionEventKind.COMMAND_COMPLETED
                    if outcome in {"removed", "already_absent"}
                    else ActionExecutionEventKind.FAILED
                ),
                step_key=(
                    "orphan_git_worktree_removed"
                    if outcome in {"removed", "already_absent"}
                    else "orphan_git_worktree_failed"
                ),
                command_argv=None,
                content=(
                    "Orphaned Git worktree removal completed."
                    if outcome in {"removed", "already_absent"}
                    else "Orphaned Git worktree removal failed."
                ),
                exit_code=0 if outcome in {"removed", "already_absent"} else None,
                on_projection_updated=on_projection_updated,
            )

        failed_count = _cleanup_candidate_count(candidates, "failed")
        if failed_count:
            L.warning(
                "Manual orphan Git worktree cleanup completed with failures",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code="candidate_failures",
                    candidates=candidates,
                ),
            )
            result = _cleanup_result(phase="failed", candidates=candidates)
            await self._release_cleanup_claims(action_execution_id=execution.id)
            await self._mark_cleanup_action_failed(
                execution=execution,
                result=result,
                reason="One or more managed worktrees could not be removed.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
        else:
            L.info(
                "Manual orphan Git worktree cleanup completed",
                extra=_cleanup_log_summary(
                    stage="terminal",
                    reason_code=None,
                    candidates=candidates,
                ),
            )
            result = _cleanup_result(phase="completed", candidates=candidates)
            execution = await self._update_cleanup_result(
                execution=execution,
                result=result,
                on_projection_updated=on_projection_updated,
            )
            await self._release_cleanup_claims(action_execution_id=execution.id)
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMPLETED,
                step_key=None,
                command_argv=None,
                content="Orphan Git worktree cleanup completed.",
                exit_code=0,
                on_projection_updated=on_projection_updated,
            )
            await self._commit_action_execution_history_event(
                execution=execution,
                status=ActionExecutionStatus.COMPLETED,
                failure_summary=None,
                cancellation_summary=None,
                on_history_event_appended=on_history_event_appended,
            )
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=False,
            complete_run=False,
        )

    async def _claim_cleanup_candidate(
        self,
        *,
        runtime_id: str,
        action_execution_id: str,
        owner_generation: int,
        worktree_path: str,
        discovery_fingerprint: str,
    ) -> Literal["claimed", "active_connection", "cleanup_in_progress"]:
        """Atomically check protection and claim one path before Runner I/O."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            result = await project_repository.try_claim_orphan_git_worktree(
                session,
                runtime_id=runtime_id,
                action_execution_id=action_execution_id,
                owner_generation=owner_generation,
                worktree_path=worktree_path,
                discovery_fingerprint=discovery_fingerprint,
            )
            await session.commit()
        return result

    async def _mark_cleanup_claim_removing(
        self,
        *,
        action_execution_id: str,
        worktree_path: str,
    ) -> None:
        """Mark one claimed target as undergoing Runner removal."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.mark_orphan_git_worktree_claim_removing(
                session,
                action_execution_id=action_execution_id,
                worktree_path=worktree_path,
            )
            await session.commit()

    async def _release_cleanup_claim(
        self,
        *,
        action_execution_id: str,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Release one cleanup claim after its Runner operation terminalizes."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_orphan_git_worktree_claim(
                session,
                action_execution_id=action_execution_id,
                worktree_path=worktree_path,
                state=state,
            )
            await session.commit()

    async def _release_cleanup_claims(self, *, action_execution_id: str) -> None:
        """Release every cleanup claim after a settled terminal action."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_orphan_git_worktree_claims(
                session,
                action_execution_id=action_execution_id,
            )
            await session.commit()

    async def _release_nonremoving_cleanup_claims(
        self,
        *,
        action_execution_id: str,
    ) -> None:
        """Retain in-flight removal claims through their bounded cancellation lease."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_nonremoving_orphan_git_worktree_claims(
                session,
                action_execution_id=action_execution_id,
            )
            await session.commit()

    async def _release_agent_removal_claim(
        self,
        *,
        action_execution_id: str,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Release one Agent removal claim after a settled outcome."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_agent_git_worktree_claim(
                session,
                action_execution_id=action_execution_id,
                worktree_path=worktree_path,
                state=state,
            )
            await session.commit()

    async def _release_nonremoving_agent_removal_claims(
        self,
        *,
        action_execution_id: str,
    ) -> None:
        """Release Agent claims that cannot still own Runner removal."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_nonremoving_agent_git_worktree_claims(
                session,
                action_execution_id=action_execution_id,
            )
            await session.commit()

    async def _claim_archive_cleanup_path(
        self,
        *,
        runtime_id: str,
        root_session_id: str,
        worktree_path: str,
    ) -> bool:
        """Claim one archive cleanup target before the Runner operation."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            claimed = await project_repository.try_claim_archive_git_worktree(
                session,
                runtime_id=runtime_id,
                root_session_id=root_session_id,
                worktree_path=worktree_path,
            )
            await session.commit()
        return claimed

    async def _release_archive_cleanup_path(
        self,
        *,
        runtime_id: str,
        root_session_id: str,
        worktree_path: str,
    ) -> None:
        """Release one archive cleanup target after the Runner operation."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_archive_git_worktree_claim(
                session,
                runtime_id=runtime_id,
                root_session_id=root_session_id,
                worktree_path=worktree_path,
            )
            await session.commit()

    async def _update_cleanup_result(
        self,
        *,
        execution: ActionExecution,
        result: dict[str, JSONValue],
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecution:
        """Persist and project one cleanup result snapshot."""
        async with self.session_manager() as session:
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result,
            )
        await self._publish_action_execution_projection(
            execution=updated,
            on_projection_updated=on_projection_updated,
        )
        return updated

    async def _mark_cleanup_action_failed(
        self,
        *,
        execution: ActionExecution,
        result: dict[str, JSONValue],
        reason: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Persist a cleanup result before terminalizing its failed action."""
        execution = await self._update_cleanup_result(
            execution=execution,
            result=result,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key="orphan_git_worktree_failed",
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            on_history_event_appended=on_history_event_appended,
        )

    async def _persist_cleanup_cancellation(
        self,
        *,
        execution: ActionExecution,
        reason: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> None:
        """Record unresolved cleanup candidates before cancellation terminalization."""
        async with self.session_manager() as session:
            current = await self.action_execution_repository.get_by_id(
                session,
                action_execution_id=execution.id,
            )
            if current is None:
                return
            current_result = current.result
            if current_result is None:
                result = _cleanup_result(phase="cancelled", candidates=[])
            else:
                candidates_value = current_result.get("candidates")
                candidates = (
                    [
                        candidate
                        for candidate in candidates_value
                        if isinstance(candidate, dict)
                    ]
                    if isinstance(candidates_value, list)
                    else []
                )
                for candidate in candidates:
                    if candidate.get("outcome") == "unresolved":
                        candidate["reason_code"] = "cancelled"
                        candidate["summary"] = reason
                result = _cleanup_result(phase="cancelled", candidates=candidates)
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result,
            )
        await self._publish_action_execution_projection(
            execution=updated,
            on_projection_updated=on_projection_updated,
        )

    async def _execute_agent_remove_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentRemoveGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one exact managed-worktree removal without deleting its branch."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            session_agent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
        if (
            agent_session is None
            or agent_session.agent_id != agent_id
            or agent_session.status is not AgentSessionStatus.ACTIVE
            or agent is None
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
            or session_agent is None
            or action.originating_agent_session_id != session_id
            or session_agent.context_id != action.session_agent_context_id
        ):
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=None,
                action=action,
                reason_code="target_context_changed",
                reason="The admitted managed worktree context is no longer available.",
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()
        if self.skill_store is None:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=None,
                action=action,
                reason_code="skill_projection_unavailable",
                reason="Skill projection storage is unavailable.",
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()
        runner_operations = self.runner_operations
        if runner_operations is None:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=None,
                action=action,
                reason_code="runner_operations_unavailable",
                reason="Runtime runner operations are unavailable.",
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()

        async with self.session_manager() as session:
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="resolve_managed_worktree",
            command_argv=None,
            content="Resolving the admitted Agent-managed worktree.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )

        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_worktree_path = normalize_session_workspace_path(
                action.worktree_path,
                workspace_root=workspace_root,
            )
        except (
            RuntimeStorageError,
            SessionWorkingFolderBindingError,
            ValueError,
        ) as error:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=None,
                action=action,
                reason_code="runtime_authority_changed",
                reason=str(error),
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()
        if (
            runtime.runtime_capability_version != agent.runtime_capability_version
            or normalized_worktree_path != action.worktree_path
        ):
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=None,
                action=action,
                reason_code="runtime_authority_changed",
                reason="Agent Runtime authority changed after admission.",
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()

        allocation: SessionGitWorktree | None = None
        project: SessionWorkspaceProject | None = None
        try:
            async with self.session_manager() as session:
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    runtime_target=runtime,
                )
                allocation = (
                    await self.session_git_worktree_repository.lock_by_id_for_session(
                        session,
                        worktree_id=action.worktree_allocation_id,
                        session_id=session_id,
                    )
                )
                project = (
                    await self.session_workspace_project_repository.lock_project_by_id(
                        session,
                        project_id=action.worktree_project_id,
                        context_id=action.session_agent_context_id,
                        session_id=session_id,
                    )
                )
                if (
                    allocation is None
                    or project is None
                    or allocation.session_agent_context_id
                    != action.session_agent_context_id
                    or allocation.session_workspace_project_id != project.id
                    or allocation.worktree_path != action.worktree_path
                    or project.path != action.worktree_path
                    or allocation.status is not SessionGitWorktreeStatus.READY
                ):
                    raise ValueError(
                        "The admitted managed worktree changed before removal."
                    )
                _, ownership_error = _cleanup_classification(
                    allocation=allocation,
                    session_id=allocation.session_id,
                    workspace_root=workspace_root,
                    working_folder_path=binding.working_folder_path,
                )
                if ownership_error is not None:
                    raise ValueError(ownership_error)
                normalized_source_path = normalize_session_workspace_path(
                    allocation.source_project_path,
                    workspace_root=workspace_root,
                )
                if normalized_source_path != allocation.source_project_path:
                    raise ValueError("Recorded source Project path changed.")
                project_repository = self.session_workspace_project_repository
                claimed = await project_repository.try_claim_agent_git_worktree(
                    session,
                    runtime_id=runtime.id,
                    action_execution_id=execution.id,
                    owner_generation=owner_generation,
                    worktree_path=action.worktree_path,
                )
                if not claimed:
                    raise _AgentWorktreeRemovalClaimConflict
        except _AgentWorktreeRemovalClaimConflict:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=allocation,
                action=action,
                reason_code="removal_in_progress",
                reason="Another destructive operation currently owns this path.",
                retry_guidance="Retry after the other worktree operation completes.",
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()
        except (SessionWorkingFolderBindingError, ValueError) as error:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=allocation,
                action=action,
                reason_code="target_context_changed",
                reason=str(error),
                retry_guidance=None,
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()
        if allocation is None or project is None:
            raise RuntimeError("Managed worktree removal authority is missing")

        claim_state = GitWorktreePathClaimState.UNRESOLVED
        try:
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.STEP_STARTED,
                step_key="inspect_git_worktree",
                command_argv=None,
                content="Inspecting the managed Git worktree.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            inspection = await runner_operations.inspect_git_worktree(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                source_project_path=allocation.source_project_path,
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
            inspection_error = _agent_removal_inspection_error(
                allocation=allocation,
                inspection_worktree_path=inspection.worktree_path,
                registered=inspection.registered,
                registered_branch_name=inspection.registered_branch_name,
                target_kind=inspection.target_kind,
                dirty=inspection.dirty,
            )
            if inspection_error is not None:
                claim_state = GitWorktreePathClaimState.UNRESOLVED
                await self._fail_agent_remove_git_worktree(
                    execution=execution,
                    allocation=allocation,
                    action=action,
                    reason_code="worktree_ownership_ambiguous",
                    reason=inspection_error,
                    retry_guidance=(
                        "Inspect the recorded worktree and retry only after its "
                        "identity is unambiguous."
                    ),
                    dirty_content_discarded=False,
                    predecessor_run_id=predecessor_run_id,
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return _bridge_remove_terminal_result()
            if inspection.dirty is True and not action.force:
                claim_state = GitWorktreePathClaimState.FAILED
                await self._fail_agent_remove_git_worktree(
                    execution=execution,
                    allocation=allocation,
                    action=action,
                    reason_code="dirty_worktree",
                    reason=(
                        "The managed worktree has dirty or untracked content and "
                        "was not removed."
                    ),
                    retry_guidance=(
                        "Retry with force=true only when discarding all dirty and "
                        "untracked worktree content is intended."
                    ),
                    dirty_content_discarded=False,
                    predecessor_run_id=predecessor_run_id,
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return _bridge_remove_terminal_result()

            expected_authority = RuntimeOperationAuthority(
                configuration_sequence=runtime.configuration_sequence,
                configuration_digest=runtime.configuration_digest,
                desired_generation=runtime.desired_generation,
            )
            current_runtime = (
                await self.runtime_target_resolver.resolve_operation_target(
                    agent_id,
                    expected_authority=expected_authority,
                    start_if_stopped=False,
                )
            )
            async with self.session_manager() as session:
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    runtime_target=current_runtime,
                )
                current_allocation = (
                    await self.session_git_worktree_repository.lock_by_id_for_session(
                        session,
                        worktree_id=action.worktree_allocation_id,
                        session_id=session_id,
                    )
                )
                current_project = (
                    await self.session_workspace_project_repository.lock_project_by_id(
                        session,
                        project_id=action.worktree_project_id,
                        context_id=action.session_agent_context_id,
                        session_id=session_id,
                    )
                )
                if (
                    current_allocation is None
                    or current_project is None
                    or current_allocation.status is not SessionGitWorktreeStatus.READY
                    or current_allocation.session_workspace_project_id
                    != current_project.id
                    or current_allocation.worktree_path != action.worktree_path
                    or current_project.path != action.worktree_path
                    or current_allocation.source_project_path
                    != allocation.source_project_path
                    or current_allocation.branch_name != allocation.branch_name
                ):
                    raise ValueError("The managed worktree changed before Git removal.")
                project_repository = self.session_workspace_project_repository
                await project_repository.mark_agent_git_worktree_claim_removing(
                    session,
                    action_execution_id=execution.id,
                    worktree_path=action.worktree_path,
                )
            claim_state = GitWorktreePathClaimState.REMOVING
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="remove_git_worktree",
                command_argv=_remove_worktree_command_argv(
                    worktree_path=allocation.worktree_path,
                    force=action.force,
                ),
                content="Removing the Agent-managed Git worktree checkout.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            removal = await runner_operations.remove_git_worktree(
                runtime_id=current_runtime.id,
                runner_generation=current_runtime.runner_generation,
                owner_session_id=session_id,
                source_project_path=allocation.source_project_path,
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                force=action.force,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
            if removal.worktree_path != allocation.worktree_path:
                raise ValueError("Runner returned a different worktree path.")
            claim_state = (
                GitWorktreePathClaimState.REMOVED
                if removal.outcome == "removed"
                else GitWorktreePathClaimState.ALREADY_ABSENT
            )
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_COMPLETED,
                step_key="remove_git_worktree",
                command_argv=None,
                content="Agent-managed Git worktree checkout removal completed.",
                exit_code=0,
                on_projection_updated=on_projection_updated,
            )
        except asyncio.CancelledError:
            raise
        except (
            RuntimeStorageError,
            SessionWorkingFolderBindingError,
            RuntimeRunnerOperationCanceledError,
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
            ValueError,
        ) as error:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=allocation,
                action=action,
                reason_code=(
                    error.code
                    if isinstance(error, RuntimeRunnerOperationFailedError)
                    and error.code
                    else "removal_outcome_ambiguous"
                ),
                reason=str(error) or type(error).__name__,
                retry_guidance=(
                    "Inspect the recorded worktree state before an explicit retry."
                ),
                dirty_content_discarded=False,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_remove_terminal_result()

        cleaned_at = datetime.now(UTC)
        try:
            async with self.session_manager() as session:
                current_allocation = (
                    await self.session_git_worktree_repository.lock_by_id_for_session(
                        session,
                        worktree_id=allocation.id,
                        session_id=session_id,
                    )
                )
                current_project = (
                    await self.session_workspace_project_repository.lock_project_by_id(
                        session,
                        project_id=project.id,
                        context_id=action.session_agent_context_id,
                        session_id=session_id,
                    )
                )
                if (
                    current_allocation is None
                    or current_project is None
                    or current_allocation.status is not SessionGitWorktreeStatus.READY
                    or current_allocation.session_workspace_project_id
                    != current_project.id
                    or current_allocation.worktree_path != action.worktree_path
                    or current_project.path != action.worktree_path
                ):
                    raise RuntimeError(
                        "Managed worktree ownership changed after confirmed removal."
                    )
                await self.agent_project_catalog_repository.delete_entry_by_path(
                    session,
                    agent_id=agent_id,
                    path=action.worktree_path,
                )
                deleted = (
                    await self.session_workspace_project_repository.delete_project(
                        session,
                        project.id,
                        session_id=session_id,
                    )
                )
                if not deleted:
                    raise RuntimeError(
                        "Managed worktree Project removal was not confirmed."
                    )
                cleaned = await self.session_git_worktree_repository.mark_cleaned(
                    session,
                    worktree_id=allocation.id,
                    cleanup_summary=_agent_removal_terminal_summary(
                        removal_outcome=removal.outcome,
                        force=action.force,
                    ),
                    cleaned_at=cleaned_at,
                )
                project_repository = self.session_workspace_project_repository
                await project_repository.release_agent_git_worktree_claim(
                    session,
                    action_execution_id=execution.id,
                    worktree_path=action.worktree_path,
                    state=claim_state,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._record_agent_removal_projection_failure(
                execution=execution,
                allocation=allocation,
                worktree_path=action.worktree_path,
                claim_state=claim_state,
                reason=(
                    "Agent-managed checkout removal was confirmed, but Session "
                    "Project cleanup requires recovery."
                ),
            )
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=allocation,
                action=action,
                reason_code="project_state_update_failed",
                reason=str(error) or type(error).__name__,
                retry_guidance=(
                    "The checkout removal was confirmed; inspect Session Project "
                    "state before further work."
                ),
                dirty_content_discarded=(action.force and inspection.dirty is True),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
                release_nonremoving_claim=False,
            )
            return _bridge_remove_terminal_result()

        skill_store = self.skill_store
        if skill_store is None:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=cleaned,
                action=action,
                reason_code="skill_projection_failed",
                reason="Skill projection storage became unavailable.",
                retry_guidance=(
                    "The checkout was removed and its branch was preserved, but "
                    "the Skill projection could not be refreshed."
                ),
                dirty_content_discarded=(action.force and inspection.dirty is True),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
                release_nonremoving_claim=False,
            )
            return _bridge_remove_terminal_result()
        try:
            await skill_store.invalidate_project(
                agent_id,
                session_id,
                project_id=project.id,
                project_path=project.path,
                session_run_state=agent_session.run_state,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            await self._fail_agent_remove_git_worktree(
                execution=execution,
                allocation=cleaned,
                action=action,
                reason_code="skill_projection_failed",
                reason=str(error) or type(error).__name__,
                retry_guidance=(
                    "The checkout was removed and its branch was preserved, but "
                    "the Skill projection could not be refreshed."
                ),
                dirty_content_discarded=(action.force and inspection.dirty is True),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
                release_nonremoving_claim=False,
            )
            return _bridge_remove_terminal_result()

        execution = await self._update_action_result(
            execution=execution,
            result={
                "worktree_project_id": project.id,
                "worktree_allocation_id": allocation.id,
                "worktree_path": allocation.worktree_path,
                "branch_name": allocation.branch_name,
                "force": action.force,
                "dirty_content_discarded": (action.force and inspection.dirty is True),
                "removal_outcome": removal.outcome,
                "retry_guidance": (
                    f"The branch {allocation.branch_name} was preserved. Delete "
                    "it separately when it is no longer needed."
                ),
                "reason_code": None,
            },
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.COMPLETED,
            step_key=None,
            command_argv=None,
            content=(
                "Agent-managed Git worktree removal completed. The Git branch "
                "was preserved."
            ),
            exit_code=0,
            on_projection_updated=on_projection_updated,
        )
        await self.commit_bridge_action_execution_terminal_handoff(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            predecessor_run_id=predecessor_run_id,
            allocation=None,
            on_history_event_appended=on_history_event_appended,
        )
        return _bridge_remove_terminal_result()

    async def _execute_agent_create_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: AgentCreateGitWorktreeAction,
        owner_generation: int,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Execute one pinned Agent create request and end its predecessor Run."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            agent = await self.agent_repository.get_by_id(session, agent_id)
            session_agent = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session,
                    session_id,
                )
            )
            source_project = (
                await self.session_workspace_project_repository.get_project_by_id(
                    session,
                    action.source_project_id,
                )
            )
        if (
            agent_session is None
            or agent_session.agent_id != agent_id
            or agent_session.status is not AgentSessionStatus.ACTIVE
            or agent is None
            or agent.runtime_capability is not AgentRuntimeCapability.MANAGED
            or session_agent is None
            or action.originating_agent_session_id != session_id
            or session_agent.context_id != action.session_agent_context_id
            or source_project is None
            or source_project.session_agent_context_id
            != action.session_agent_context_id
            or source_project.path != action.source_project_path
        ):
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="source_context_changed",
                reason="The admitted source Project context is no longer available.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        if self.skill_store is None:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="skill_projection_unavailable",
                reason="Skill projection storage is unavailable.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        async with self.session_manager() as session:
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="resolve_source",
            command_argv=None,
            content="Resolving the admitted Git Project.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )

        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
            binding = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_source_path = normalize_session_workspace_path(
                action.source_project_path,
                workspace_root=workspace_root,
            )
        except (
            RuntimeStorageError,
            SessionWorkingFolderBindingError,
            ValueError,
        ) as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="runtime_authority_changed",
                reason=str(error),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()
        if (
            runtime.runtime_capability_version != agent.runtime_capability_version
            or normalized_source_path != action.source_project_path
        ):
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="runtime_authority_changed",
                reason="Agent Runtime authority changed after admission.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        runner_operations = self.runner_operations
        if runner_operations is None:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="runner_operations_unavailable",
                reason="Runtime runner operations are unavailable.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()
        try:
            refs = await runner_operations.list_git_refs(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                source_project_path=normalized_source_path,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
        except (
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="runtime_unavailable",
                reason="Runtime runner is not ready.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()
        except RuntimeRunnerOperationFailedError as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code=error.code or "source_not_git",
                reason=str(error),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        starting_ref = action.starting_ref or refs.head_commit
        if starting_ref is None:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="head_unavailable",
                reason="The selected Project has no current HEAD commit.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        try:
            async with self.session_manager() as session:
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    runtime_target=runtime,
                )
                current_project = (
                    await self.session_workspace_project_repository.get_project_by_id(
                        session,
                        action.source_project_id,
                    )
                )
                if (
                    current_project is None
                    or current_project.session_agent_context_id
                    != action.session_agent_context_id
                    or current_project.path != normalized_source_path
                ):
                    raise ValueError(
                        "The admitted source Project changed before Git execution."
                    )
                allocation = await self._ensure_agent_worktree_allocation(
                    session,
                    execution=execution,
                    session_id=session_id,
                    session_handle=agent_session.handle,
                    runtime_id=runtime.id,
                    working_folder_path=binding.working_folder_path,
                    source_project_path=refs.repository_anchor_path,
                    starting_ref=starting_ref,
                    requested_branch_name=action.branch_name,
                )
        except (SessionWorkingFolderBindingError, ValueError) as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=None,
                reason_code="source_context_changed",
                reason=str(error),
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        if allocation.status in {
            SessionGitWorktreeStatus.FAILED,
            SessionGitWorktreeStatus.CLEANUP_PENDING,
            SessionGitWorktreeStatus.CLEANED,
            SessionGitWorktreeStatus.CLEANUP_FAILED,
        }:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=allocation,
                reason_code="allocation_unavailable",
                reason=allocation.failure_summary or "Git worktree allocation failed.",
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()
        if allocation.status is SessionGitWorktreeStatus.READY:
            if allocation.base_commit is None:
                raise RuntimeError("Ready worktree allocation has no base commit")
            create_result = _CreateWorktreeSuccess(
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                base_commit=allocation.base_commit,
            )
        else:
            create_result = await self._run_agent_create_worktree_step(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                generated_branch=action.branch_name is None,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            if create_result is None:
                return _bridge_create_terminal_result()

        generated_project = await self._register_agent_created_project(
            agent_id=agent_id,
            runtime=runtime,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            predecessor_run_id=predecessor_run_id,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        if generated_project is None:
            return _bridge_create_terminal_result()
        if not await self._catalog_agent_created_project(
            agent_id=agent_id,
            runtime=runtime,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            predecessor_run_id=predecessor_run_id,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return _bridge_create_terminal_result()
        await self._run_action_refresh_project_status_step(
            agent_id=agent_id,
            execution=execution,
            path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
        )
        try:
            await self._sync_skill_projection_for_project_change(
                agent_id=agent_id,
                session_id=session_id,
                required=True,
            )
        except Exception as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=allocation,
                reason_code="skill_projection_failed",
                reason=str(error) or type(error).__name__,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return _bridge_create_terminal_result()

        execution = await self._update_action_result(
            execution=execution,
            result={
                "source_project_path": normalized_source_path,
                "source_project_id": action.source_project_id,
                "generated_project_id": generated_project.id,
                "worktree_path": create_result.worktree_path,
                "requested_starting_ref": action.starting_ref,
                "base_commit": create_result.base_commit,
                "branch_name": create_result.branch_name,
                "reason_code": None,
            },
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.COMPLETED,
            step_key=None,
            command_argv=None,
            content="Agent-managed Git worktree creation completed.",
            exit_code=0,
            on_projection_updated=on_projection_updated,
        )
        await self.commit_bridge_action_execution_terminal_handoff(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            predecessor_run_id=predecessor_run_id,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )
        return _bridge_create_terminal_result()

    async def _execute_git_worktree_action(
        self,
        *,
        agent_id: str,
        session_id: str,
        execution: ActionExecution,
        action: CreateGitWorktreeAction,
        owner_generation: int,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> GitWorktreeActionExecutionResult:
        """Run the operation after the current worker admitted it."""
        if execution.session_id != session_id:
            raise ValueError("ActionExecution belongs to another session")
        if execution.owner_generation != owner_generation:
            raise RuntimeError("ActionExecution belongs to another Session owner")
        if execution.status is not ActionExecutionStatus.PENDING:
            raise RuntimeError("Only newly admitted pending operations may execute")
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )

        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
        if agent_session is None or agent_session.agent_id != agent_id:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason="Session not found.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        async with self.session_manager() as session:
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="wait_for_runtime",
            command_argv=None,
            content="Waiting for Runtime readiness.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bindable_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id
            )
            binding = await binding_service.resolve_authority_for_target(
                agent_id=agent_id,
                session_id=session_id,
                runtime_target=runtime,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as error:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason=str(error),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        try:
            workspace_root = normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix()
            normalized_source_path = normalize_session_workspace_path(
                action.source_project_path,
                workspace_root=workspace_root,
            )
        except ValueError as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason=str(exc),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        working_folder_path = binding.working_folder_path
        try:
            async with self.session_manager() as session:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=session_id,
                    runtime_target=runtime,
                )
                allocation = await self._ensure_action_worktree_allocation(
                    session,
                    execution=execution,
                    session_id=session_id,
                    session_handle=agent_session.handle,
                    working_folder_path=working_folder_path,
                    source_project_path=normalized_source_path,
                    starting_ref=action.starting_ref.strip(),
                )
        except SessionWorkingFolderBindingError as error:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=None,
                reason=str(error),
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="create_git_worktree",
            command_argv=None,
            content="Starting Git worktree action.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )

        if self.runner_operations is None:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason="Runtime runner operations are unavailable.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )

        if allocation.status in {
            SessionGitWorktreeStatus.FAILED,
            SessionGitWorktreeStatus.CLEANUP_PENDING,
            SessionGitWorktreeStatus.CLEANED,
            SessionGitWorktreeStatus.CLEANUP_FAILED,
        }:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=allocation.failure_summary or "Git worktree allocation failed.",
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        if allocation.status is SessionGitWorktreeStatus.READY:
            if allocation.base_commit is None:
                raise RuntimeError("Ready worktree allocation has no base commit")
            create_result = _CreateWorktreeSuccess(
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                base_commit=allocation.base_commit,
            )
        else:
            create_result = await self._run_action_create_worktree_step(
                runtime=runtime,
                execution=execution,
                allocation=allocation,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            if create_result is None:
                return GitWorktreeActionExecutionResult(
                    completed=True,
                    context_invalidated=False,
                    complete_run=False,
                )
        if not await self._run_action_register_project_step(
            agent_id=agent_id,
            runtime=runtime,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        if not await self._run_action_catalog_step(
            agent_id=agent_id,
            runtime=runtime,
            execution=execution,
            allocation=allocation,
            worktree_path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        ):
            return GitWorktreeActionExecutionResult(
                completed=True,
                context_invalidated=False,
                complete_run=False,
            )
        await self._run_action_refresh_project_status_step(
            agent_id=agent_id,
            execution=execution,
            path=create_result.worktree_path,
            on_projection_updated=on_projection_updated,
        )
        await self._sync_skill_projection_for_project_change(
            agent_id=agent_id,
            session_id=session_id,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.COMPLETED,
            step_key=None,
            command_argv=None,
            content="Git worktree action completed.",
            exit_code=0,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.COMPLETED,
            failure_summary=None,
            cancellation_summary=None,
            on_history_event_appended=on_history_event_appended,
        )
        return GitWorktreeActionExecutionResult(
            completed=True,
            context_invalidated=True,
            complete_run=False,
        )

    async def _ensure_agent_worktree_allocation(
        self,
        session: AsyncSession,
        *,
        execution: ActionExecution,
        session_id: str,
        session_handle: str,
        runtime_id: str,
        working_folder_path: str,
        source_project_path: str,
        starting_ref: str,
        requested_branch_name: str | None,
    ) -> SessionGitWorktree:
        """Create or fetch one pinned Agent-requested worktree allocation."""
        existing = (
            await self.session_git_worktree_repository.get_by_action_execution_id(
                session,
                action_execution_id=execution.id,
            )
        )
        if existing is not None:
            if (
                existing.session_id != session_id
                or existing.source_project_path != source_project_path
                or existing.starting_ref != starting_ref
                or (
                    requested_branch_name is not None
                    and existing.branch_name != requested_branch_name
                )
            ):
                raise ValueError(
                    "The existing allocation does not match the admitted request."
                )
            return existing

        worktree_parent_path = (
            PurePosixPath(working_folder_path) / "worktrees"
        ).as_posix()
        path_suffix = 1
        branch_suffix = 1
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            worktree_path, generated_branch_name = _target_names(
                session_handle=session_handle,
                worktree_parent_path=worktree_parent_path,
                source_project_path=source_project_path,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
            )
            branch_name = requested_branch_name or generated_branch_name
            project_repository = self.session_workspace_project_repository
            await project_repository.acquire_runtime_path_coordination_lock(
                session,
                runtime_id=runtime_id,
            )
            await project_repository.acquire_runtime_worktree_path_lock(
                session,
                runtime_id=runtime_id,
                worktree_path=worktree_path,
            )
            path_exists = (
                await self.session_git_worktree_repository.worktree_path_exists(
                    session,
                    worktree_path=worktree_path,
                    excluding_id="",
                )
            )
            branch_exists = (
                await self.session_git_worktree_repository.branch_name_exists(
                    session,
                    branch_name=branch_name,
                    excluding_id="",
                )
            )
            claim_exists = await project_repository.has_blocking_git_worktree_claim(
                session,
                runtime_id=runtime_id,
                worktree_path=worktree_path,
            )
            if branch_exists and requested_branch_name is not None:
                raise ValueError(
                    f"Git branch already exists in a managed allocation: {branch_name}"
                )
            if not path_exists and not branch_exists and not claim_exists:
                return await self.session_git_worktree_repository.create(
                    session,
                    SessionGitWorktreeCreate(
                        id=uuid7().hex,
                        session_id=session_id,
                        action_execution_id=execution.id,
                        session_workspace_project_id=None,
                        source_project_path=source_project_path,
                        starting_ref=starting_ref,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                        branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                        status=SessionGitWorktreeStatus.PENDING,
                    ),
                )
            if path_exists or claim_exists:
                path_suffix += 1
            if branch_exists:
                branch_suffix += 1
        raise ValueError("Could not allocate a unique Git worktree path and branch.")

    async def _run_agent_create_worktree_step(
        self,
        *,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        generated_branch: bool,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> _CreateWorktreeSuccess | None:
        """Create an Agent-requested worktree with bounded generated collisions."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        current = allocation
        path_suffix = 1
        branch_suffix = 1
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            current = await self._choose_agent_available_target(
                current,
                runtime_id=runtime.id,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
                generated_branch=generated_branch,
            )
            command_argv = [
                "git",
                "worktree",
                "add",
                "-b",
                current.branch_name,
                current.worktree_path,
                current.starting_ref,
            ]
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="create_git_worktree",
                command_argv=command_argv,
                content="Starting Agent-managed Git worktree creation.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                current = await self.session_git_worktree_repository.mark_creating(
                    session,
                    worktree_id=current.id,
                )
            try:
                result = await runner_operations.create_git_worktree(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    owner_session_id=current.session_id,
                    source_project_path=current.source_project_path,
                    worktree_path=current.worktree_path,
                    branch_name=current.branch_name,
                    starting_ref=current.starting_ref,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=self._action_text_callback(
                        execution=execution,
                        on_projection_updated=on_projection_updated,
                    ),
                )
            except RuntimeRunnerOperationFailedError as error:
                collision = error.code or _collision_kind(str(error))
                if collision in {"branch", "branch_exists"} and generated_branch:
                    branch_suffix = _generated_branch_suffix(current.branch_name) + 1
                    continue
                if collision in {"path", "worktree_path_exists"}:
                    path_suffix = (
                        _worktree_path_suffix(
                            current.worktree_path,
                            source_project_path=current.source_project_path,
                        )
                        + 1
                    )
                    continue
                await self._fail_agent_create_git_worktree(
                    execution=execution,
                    allocation=current,
                    reason_code=error.code or "runner_operation_failed",
                    reason=str(error),
                    predecessor_run_id=predecessor_run_id,
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            except (
                RuntimeRunnerOperationUnavailable,
                RuntimeRunnerOperationGenerationError,
            ):
                await self._fail_agent_create_git_worktree(
                    execution=execution,
                    allocation=current,
                    reason_code="runtime_unavailable",
                    reason="Runtime runner is not ready.",
                    predecessor_run_id=predecessor_run_id,
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_COMPLETED,
                step_key="create_git_worktree",
                command_argv=None,
                content="Agent-managed Git worktree creation completed.",
                exit_code=0,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                await self.session_git_worktree_repository.mark_ready(
                    session,
                    worktree_id=current.id,
                    base_commit=result.base_commit,
                    worktree_path=result.worktree_path,
                    branch_name=result.branch_name,
                    ready_at=datetime.now(UTC),
                )
            return _CreateWorktreeSuccess(
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                base_commit=result.base_commit,
            )
        await self._fail_agent_create_git_worktree(
            execution=execution,
            allocation=current,
            reason_code="collision_exhausted",
            reason="Could not allocate a unique Git worktree path and branch.",
            predecessor_run_id=predecessor_run_id,
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        return None

    async def _choose_agent_available_target(
        self,
        allocation: SessionGitWorktree,
        *,
        runtime_id: str,
        path_suffix: int,
        branch_suffix: int,
        generated_branch: bool,
    ) -> SessionGitWorktree:
        """Choose the next Agent target while preserving an explicit branch."""
        session_handle = (
            _branch_session_handle(allocation.branch_name)
            if generated_branch
            else "explicit"
        )
        worktree_parent_path = PurePosixPath(allocation.worktree_path).parent.as_posix()
        current_path_suffix = path_suffix
        current_branch_suffix = branch_suffix
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            worktree_path, generated_branch_name = _target_names(
                session_handle=session_handle,
                worktree_parent_path=worktree_parent_path,
                source_project_path=allocation.source_project_path,
                path_suffix=current_path_suffix,
                branch_suffix=current_branch_suffix,
            )
            branch_name = (
                generated_branch_name if generated_branch else allocation.branch_name
            )
            async with self.session_manager() as session:
                project_repository = self.session_workspace_project_repository
                await project_repository.acquire_runtime_path_coordination_lock(
                    session,
                    runtime_id=runtime_id,
                )
                await project_repository.acquire_runtime_worktree_path_lock(
                    session,
                    runtime_id=runtime_id,
                    worktree_path=worktree_path,
                )
                path_exists = (
                    await self.session_git_worktree_repository.worktree_path_exists(
                        session,
                        worktree_path=worktree_path,
                        excluding_id=allocation.id,
                    )
                )
                branch_exists = (
                    await self.session_git_worktree_repository.branch_name_exists(
                        session,
                        branch_name=branch_name,
                        excluding_id=allocation.id,
                    )
                )
                claim_exists = await project_repository.has_blocking_git_worktree_claim(
                    session,
                    runtime_id=runtime_id,
                    worktree_path=worktree_path,
                )
                if branch_exists and not generated_branch:
                    raise ValueError(
                        f"Git branch already exists in a managed allocation: "
                        f"{branch_name}"
                    )
                if not path_exists and not branch_exists and not claim_exists:
                    return await self.session_git_worktree_repository.update_target(
                        session,
                        worktree_id=allocation.id,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                    )
            if path_exists or claim_exists:
                current_path_suffix += 1
            if branch_exists:
                current_branch_suffix += 1
        return allocation

    async def _ensure_action_worktree_allocation(
        self,
        session: AsyncSession,
        *,
        execution: ActionExecution,
        session_id: str,
        session_handle: str,
        working_folder_path: str,
        source_project_path: str,
        starting_ref: str,
    ) -> SessionGitWorktree:
        """Create or fetch the worktree allocation for an action execution."""
        existing = (
            await self.session_git_worktree_repository.get_by_action_execution_id(
                session,
                action_execution_id=execution.id,
            )
        )
        if existing is not None:
            return existing
        worktree_path, branch_name = _target_names(
            session_handle=session_handle,
            worktree_parent_path=(
                PurePosixPath(working_folder_path) / "worktrees"
            ).as_posix(),
            source_project_path=source_project_path,
            path_suffix=1,
            branch_suffix=1,
        )
        return await self.session_git_worktree_repository.create(
            session,
            SessionGitWorktreeCreate(
                id=uuid7().hex,
                session_id=session_id,
                action_execution_id=execution.id,
                session_workspace_project_id=None,
                source_project_path=source_project_path,
                starting_ref=starting_ref,
                worktree_path=worktree_path,
                branch_name=branch_name,
                branch_created_by=SessionGitWorktreeBranchCreatedBy.AZENTS,
                status=SessionGitWorktreeStatus.PENDING,
            ),
        )

    async def _run_action_create_worktree_step(
        self,
        *,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> _CreateWorktreeSuccess | None:
        """Run create_git_worktree for an action execution."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        path_suffix = 1
        branch_suffix = 1
        current = allocation
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            current = await self._choose_available_target(
                current,
                runtime_id=runtime.id,
                path_suffix=path_suffix,
                branch_suffix=branch_suffix,
            )
            command_argv = [
                "git",
                "worktree",
                "add",
                "-b",
                current.branch_name,
                current.worktree_path,
                current.starting_ref,
            ]
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_STARTED,
                step_key="create_git_worktree",
                command_argv=command_argv,
                content="Starting Git worktree creation.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                await self.session_git_worktree_repository.mark_creating(
                    session,
                    worktree_id=current.id,
                )
            try:
                result = await runner_operations.create_git_worktree(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    owner_session_id=current.session_id,
                    source_project_path=current.source_project_path,
                    worktree_path=current.worktree_path,
                    branch_name=current.branch_name,
                    starting_ref=current.starting_ref,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=self._action_text_callback(
                        execution=execution,
                        on_projection_updated=on_projection_updated,
                    ),
                )
            except RuntimeRunnerOperationFailedError as exc:
                collision = _collision_kind(str(exc))
                if collision == "branch":
                    branch_suffix = _generated_branch_suffix(current.branch_name) + 1
                    continue
                if collision == "path":
                    path_suffix = (
                        _worktree_path_suffix(
                            current.worktree_path,
                            source_project_path=current.source_project_path,
                        )
                        + 1
                    )
                    continue
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=current,
                    reason=str(exc),
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            except (
                RuntimeRunnerOperationUnavailable,
                RuntimeRunnerOperationGenerationError,
            ):
                await self._mark_action_execution_failed(
                    execution=execution,
                    allocation=current,
                    reason="Runtime runner is not ready.",
                    on_projection_updated=on_projection_updated,
                    on_history_event_appended=on_history_event_appended,
                )
                return None
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.COMMAND_COMPLETED,
                step_key="create_git_worktree",
                command_argv=None,
                content="Git worktree creation completed.",
                exit_code=0,
                on_projection_updated=on_projection_updated,
            )
            async with self.session_manager() as session:
                await self.session_git_worktree_repository.mark_ready(
                    session,
                    worktree_id=current.id,
                    base_commit=result.base_commit,
                    worktree_path=result.worktree_path,
                    branch_name=result.branch_name,
                    ready_at=datetime.now(UTC),
                )
            return _CreateWorktreeSuccess(
                worktree_path=result.worktree_path,
                branch_name=result.branch_name,
                base_commit=result.base_commit,
            )
        await self._mark_action_execution_failed(
            execution=execution,
            allocation=current,
            reason="Could not allocate a unique Git worktree path and branch.",
            on_projection_updated=on_projection_updated,
            on_history_event_appended=on_history_event_appended,
        )
        return None

    async def _run_action_register_project_step(
        self,
        *,
        agent_id: str,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Register the action-created worktree as a session Project."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="register_project",
            command_argv=None,
            content="Starting register_project.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            expected_authority = RuntimeOperationAuthority(
                configuration_sequence=runtime.configuration_sequence,
                configuration_digest=runtime.configuration_digest,
                desired_generation=runtime.desired_generation,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                expected_authority=expected_authority,
                start_if_stopped=False,
            )
            async with self.session_manager() as session:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=allocation.session_id,
                    runtime_target=runtime,
                )
                await self._create_and_link_workspace_project(
                    session,
                    allocation=allocation,
                    worktree_path=worktree_path,
                )
        except Exception as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=str(exc) or type(exc).__name__,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        return True

    async def _register_agent_created_project(
        self,
        *,
        agent_id: str,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> SessionWorkspaceProject | None:
        """Register or recover the Project linked to an Agent allocation."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="register_project",
            command_argv=None,
            content="Registering the Agent-managed worktree Project.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            expected_authority = RuntimeOperationAuthority(
                configuration_sequence=runtime.configuration_sequence,
                configuration_digest=runtime.configuration_digest,
                desired_generation=runtime.desired_generation,
            )
            current_runtime = (
                await self.runtime_target_resolver.resolve_operation_target(
                    agent_id,
                    expected_authority=expected_authority,
                    start_if_stopped=False,
                )
            )
            async with self.session_manager() as session:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=allocation.session_id,
                    runtime_target=current_runtime,
                )
                repository = self.session_git_worktree_repository
                current_allocation = await repository.get_by_action_execution_id(
                    session,
                    action_execution_id=execution.id,
                )
                if current_allocation is None:
                    raise RuntimeError("Git worktree allocation is missing")
                if current_allocation.session_workspace_project_id is not None:
                    project_repository = self.session_workspace_project_repository
                    project = await project_repository.get_project_by_id(
                        session,
                        current_allocation.session_workspace_project_id,
                    )
                    if project is None or project.path != worktree_path:
                        raise RuntimeError(
                            "Linked worktree Project does not match the allocation"
                        )
                    return project
                return await self._create_and_link_workspace_project(
                    session,
                    allocation=current_allocation,
                    worktree_path=worktree_path,
                )
        except Exception as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=allocation,
                reason_code="project_registration_failed",
                reason=str(error) or type(error).__name__,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return None

    async def _run_action_catalog_step(
        self,
        *,
        agent_id: str,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Upsert catalog state for the action-created Project."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="upsert_catalog",
            command_argv=None,
            content="Starting upsert_catalog.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            expected_authority = RuntimeOperationAuthority(
                configuration_sequence=runtime.configuration_sequence,
                configuration_digest=runtime.configuration_digest,
                desired_generation=runtime.desired_generation,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                expected_authority=expected_authority,
                start_if_stopped=False,
            )
            async with self.session_manager() as session:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=allocation.session_id,
                    runtime_target=runtime,
                )
                await self.agent_project_catalog_repository.upsert_entry(
                    session,
                    agent_id=agent_id,
                    path=worktree_path,
                )
        except Exception as exc:
            await self._mark_action_execution_failed(
                execution=execution,
                allocation=allocation,
                reason=str(exc) or type(exc).__name__,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        return True

    async def _catalog_agent_created_project(
        self,
        *,
        agent_id: str,
        runtime: RuntimeOperationTarget,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> bool:
        """Upsert Project Catalog state before the bridge terminal handoff."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="upsert_catalog",
            command_argv=None,
            content="Updating the Agent Project Catalog.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            expected_authority = RuntimeOperationAuthority(
                configuration_sequence=runtime.configuration_sequence,
                configuration_digest=runtime.configuration_digest,
                desired_generation=runtime.desired_generation,
            )
            current_runtime = (
                await self.runtime_target_resolver.resolve_operation_target(
                    agent_id,
                    expected_authority=expected_authority,
                    start_if_stopped=False,
                )
            )
            async with self.session_manager() as session:
                binding_service = self.session_working_folder_binding_service
                await binding_service.resolve_bound_authority_in_transaction(
                    session,
                    agent_id=agent_id,
                    session_id=allocation.session_id,
                    runtime_target=current_runtime,
                )
                await self.agent_project_catalog_repository.upsert_entry(
                    session,
                    agent_id=agent_id,
                    path=worktree_path,
                )
        except Exception as error:
            await self._fail_agent_create_git_worktree(
                execution=execution,
                allocation=allocation,
                reason_code="catalog_update_failed",
                reason=str(error) or type(error).__name__,
                predecessor_run_id=predecessor_run_id,
                on_projection_updated=on_projection_updated,
                on_history_event_appended=on_history_event_appended,
            )
            return False
        return True

    async def _run_action_refresh_project_status_step(
        self,
        *,
        agent_id: str,
        execution: ActionExecution,
        path: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> None:
        """Refresh catalog status and record a warning on non-blocking failure."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.STEP_STARTED,
            step_key="refresh_project_status",
            command_argv=None,
            content="Starting refresh_project_status.",
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        try:
            result = await self.agent_project_catalog_service.refresh_project_status(
                agent_id=agent_id,
                path=path,
            )
        except Exception as exc:
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.WARNING,
                step_key="refresh_project_status",
                command_argv=None,
                content=str(exc) or type(exc).__name__,
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
            return
        if result.success:
            entry = result.value
            if entry.status is AgentProjectCatalogStatus.AVAILABLE:
                return
            await self._append_action_execution_event(
                execution=execution,
                kind=ActionExecutionEventKind.WARNING,
                step_key="refresh_project_status",
                command_argv=None,
                content=entry.status_detail or f"Project status is {entry.status}.",
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )
        else:
            error = result.error
            match error:
                case InvalidProjectPath():
                    await self._append_action_execution_event(
                        execution=execution,
                        kind=ActionExecutionEventKind.WARNING,
                        step_key="refresh_project_status",
                        command_argv=None,
                        content=error.reason,
                        exit_code=None,
                        on_projection_updated=on_projection_updated,
                    )
                case _:
                    assert_never(error)

    def _action_text_callback(
        self,
        *,
        execution: ActionExecution,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> RuntimeOperationTextCallback:
        """Create a callback that persists streamed action stdout/stderr."""

        async def callback(delta: RuntimeOperationTextDelta) -> None:
            kind = (
                ActionExecutionEventKind.STDOUT
                if delta.stream == "stdout"
                else ActionExecutionEventKind.STDERR
            )
            await self._append_action_execution_event(
                execution=execution,
                kind=kind,
                step_key="create_git_worktree",
                command_argv=None,
                content=delta.text,
                exit_code=None,
                on_projection_updated=on_projection_updated,
            )

        return callback

    async def _append_action_execution_event(
        self,
        *,
        execution: ActionExecution,
        kind: ActionExecutionEventKind,
        step_key: str | None,
        command_argv: list[str] | None,
        content: str | None,
        exit_code: int | None,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecutionEvent:
        """Append one action execution event in a short transaction."""
        async with self.session_manager() as session:
            event = await self.action_execution_repository.append_event(
                session,
                ActionExecutionEventCreate(
                    action_execution_id=execution.id,
                    session_id=execution.session_id,
                    kind=kind,
                    step_key=step_key,
                    command_argv=command_argv,
                    content=content,
                    exit_code=exit_code,
                ),
            )
        await self._publish_action_execution_projection(
            execution=execution,
            on_projection_updated=on_projection_updated,
        )
        return event

    async def _publish_action_execution_projection(
        self,
        *,
        execution: ActionExecution,
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecutionProjection:
        """Publish the current action execution projection when requested."""
        async with self.session_manager() as session:
            repository = self.action_execution_repository
            projection = await repository.get_projection_by_mailbox_item_id(
                session,
                mailbox_item_id=execution.mailbox_item_id,
            )
            if projection is None:
                raise RuntimeError("ActionExecution projection is missing")
        if on_projection_updated is not None:
            await on_projection_updated(projection)
        return projection

    async def _commit_action_execution_history_event(
        self,
        *,
        execution: ActionExecution,
        status: ActionExecutionStatus,
        failure_summary: str | None,
        cancellation_summary: str | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        allocation: SessionGitWorktree | None = None,
    ) -> Event:
        """Atomically append one terminal snapshot and delete its live row."""
        return await self._commit_action_execution_terminal_handoff(
            execution=execution,
            status=status,
            failure_summary=failure_summary,
            cancellation_summary=cancellation_summary,
            on_history_event_appended=on_history_event_appended,
            allocation=allocation,
            predecessor_run_id=None,
        )

    async def commit_bridge_action_execution_terminal_handoff(
        self,
        *,
        execution: ActionExecution,
        status: ActionExecutionStatus,
        failure_summary: str | None,
        cancellation_summary: str | None,
        predecessor_run_id: str,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        allocation: SessionGitWorktree | None = None,
    ) -> Event:
        """Atomically terminalize a registered bridge and enqueue continuation."""
        return await self._commit_action_execution_terminal_handoff(
            execution=execution,
            status=status,
            failure_summary=failure_summary,
            cancellation_summary=cancellation_summary,
            on_history_event_appended=on_history_event_appended,
            allocation=allocation,
            predecessor_run_id=predecessor_run_id,
        )

    async def _commit_action_execution_terminal_handoff(
        self,
        *,
        execution: ActionExecution,
        status: ActionExecutionStatus,
        failure_summary: str | None,
        cancellation_summary: str | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        allocation: SessionGitWorktree | None,
        predecessor_run_id: str | None,
    ) -> Event:
        """Commit terminal history, optional continuation, and live-state removal."""
        if status not in {
            ActionExecutionStatus.COMPLETED,
            ActionExecutionStatus.FAILED,
            ActionExecutionStatus.CANCELLED,
        }:
            raise ValueError("ActionExecution terminal status is required")
        external_id = f"action_execution_result:{execution.id}"
        continuation_idempotency_key = f"turn_action_continuation:{execution.id}"
        terminal_at = datetime.now(UTC)
        async with self.session_manager() as session:
            projection = await self.action_execution_repository.lock_projection_by_id(
                session,
                action_execution_id=execution.id,
                session_id=execution.session_id,
            )
            if projection is None:
                existing = await self.event_transcript_repository.get_by_external_id(
                    session,
                    execution.session_id,
                    external_id,
                )
                if existing is None:
                    raise RuntimeError("ActionExecution terminal state is missing")
                event = existing
                if _is_agent_worktree_bridge_action(execution.action_type):
                    pending_continuation = (
                        await self.mailbox_item_repository.get_by_idempotency_key(
                            session,
                            session_id=execution.session_id,
                            kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
                            idempotency_key=continuation_idempotency_key,
                        )
                    )
                    promoted_continuation = (
                        await self.event_transcript_repository.get_by_external_id(
                            session,
                            execution.session_id,
                            continuation_idempotency_key,
                        )
                    )
                    if pending_continuation is None and promoted_continuation is None:
                        raise RuntimeError(
                            "Bridge terminal continuation state is missing"
                        )
            else:
                terminal_execution = projection.execution.model_copy(
                    update={
                        "status": status,
                        "failure_summary": failure_summary,
                        "cancellation_summary": cancellation_summary,
                        "completed_at": (
                            terminal_at
                            if status is ActionExecutionStatus.COMPLETED
                            else None
                        ),
                        "failed_at": (
                            terminal_at
                            if status is ActionExecutionStatus.FAILED
                            else None
                        ),
                        "cancelled_at": (
                            terminal_at
                            if status is ActionExecutionStatus.CANCELLED
                            else None
                        ),
                        "updated_at": terminal_at,
                    }
                )
                terminal_projection = projection.model_copy(
                    update={"execution": terminal_execution}
                )
                if (
                    allocation is not None
                    and status is not ActionExecutionStatus.COMPLETED
                ):
                    summary = failure_summary or cancellation_summary
                    if summary is None:
                        raise RuntimeError("Terminal allocation summary is missing")
                    await self.session_git_worktree_repository.mark_failed(
                        session,
                        worktree_id=allocation.id,
                        failure_summary=summary,
                        failed_at=terminal_at,
                    )
                event = await self.event_transcript_repository.append(
                    session,
                    EventCreate(
                        session_id=execution.session_id,
                        kind=EventKind.ACTION_EXECUTION_RESULT,
                        payload={
                            "action_execution": terminal_projection.model_dump(
                                mode="json", exclude_none=True
                            )
                        },
                        external_id=external_id,
                    ),
                )
                if _is_agent_worktree_bridge_action(execution.action_type):
                    if predecessor_run_id is None:
                        raise RuntimeError(
                            "Bridge terminal handoff requires predecessor Run"
                        )
                    continuation_payload = _bridge_continuation_payload(
                        terminal_projection,
                        predecessor_run_id=predecessor_run_id,
                    )
                    await self.mailbox_item_repository.create_idempotent(
                        session,
                        MailboxItemCreate(
                            session_id=execution.session_id,
                            kind=MailboxItemKind.TURN_ACTION_CONTINUATION,
                            scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                            requested_model_target_label=None,
                            requested_reasoning_effort=None,
                            sender_user_id=None,
                            order_group=None,
                            order_sequence=0,
                            content="",
                            idempotency_key=continuation_idempotency_key,
                            metadata={},
                            action=None,
                            attachments=[],
                            file_parts=[],
                            payload=continuation_payload,
                        ),
                        idempotency_key=continuation_idempotency_key,
                    )
                    await self.agent_session_repository.mark_running_for_input_wakeup(
                        session,
                        execution.session_id,
                    )
                await self.action_execution_repository.delete_by_id(
                    session,
                    action_execution_id=execution.id,
                )
        if on_history_event_appended is not None:
            await on_history_event_appended(event)
        return event

    async def cancel_action_execution(
        self,
        *,
        execution: ActionExecution,
        reason: str,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        predecessor_run_id: str | None,
    ) -> Event:
        """Cancel one active operation without re-executing its side effect."""
        if execution.action_type == "cleanup_orphan_git_worktrees":
            await self._persist_cleanup_cancellation(
                execution=execution,
                reason=reason,
                on_projection_updated=None,
            )
            await self._release_nonremoving_cleanup_claims(
                action_execution_id=execution.id
            )
        if execution.action_type == "agent_remove_git_worktree":
            await self._release_nonremoving_agent_removal_claims(
                action_execution_id=execution.id
            )
        async with self.session_manager() as session:
            allocation = (
                await self.session_git_worktree_repository.get_by_action_execution_id(
                    session,
                    action_execution_id=execution.id,
                )
            )
        if _is_agent_worktree_bridge_action(execution.action_type):
            if execution.action_type == "agent_create_git_worktree":
                action = AgentCreateGitWorktreeAction.model_validate(execution.action)
                await self._compensate_agent_created_project(
                    execution=execution,
                    allocation=allocation,
                )
                terminal_allocation = allocation
            else:
                action = AgentRemoveGitWorktreeAction.model_validate(execution.action)
                terminal_allocation = None
            resolved_predecessor_run_id = (
                predecessor_run_id or action.originating_run_id
            )
            return await self.commit_bridge_action_execution_terminal_handoff(
                execution=execution,
                status=ActionExecutionStatus.CANCELLED,
                failure_summary=None,
                cancellation_summary=reason,
                predecessor_run_id=resolved_predecessor_run_id,
                allocation=terminal_allocation,
                on_history_event_appended=on_history_event_appended,
            )
        return await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.CANCELLED,
            failure_summary=None,
            cancellation_summary=reason,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )

    async def cancel_live_action_executions(
        self,
        *,
        session_id: str,
        reason: str,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        on_action_execution_removed: ActionExecutionRemovedCallback | None,
        predecessor_run_id: str | None,
    ) -> list[Event]:
        """Cancel leftover live executions before a processing boundary starts."""
        async with self.session_manager() as session:
            executions = await self.action_execution_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        events: list[Event] = []
        for execution in executions:
            if execution.status in {
                ActionExecutionStatus.PENDING,
                ActionExecutionStatus.RUNNING,
            }:
                event = await self.cancel_action_execution(
                    execution=execution,
                    reason=reason,
                    on_history_event_appended=on_history_event_appended,
                    predecessor_run_id=predecessor_run_id,
                )
            else:
                event = await self._commit_action_execution_history_event(
                    execution=execution,
                    status=execution.status,
                    failure_summary=execution.failure_summary,
                    cancellation_summary=execution.cancellation_summary,
                    on_history_event_appended=on_history_event_appended,
                )
            events.append(event)
            if on_action_execution_removed is not None:
                await on_action_execution_removed(execution.id)
        return events

    async def _mark_action_execution_failed(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree | None,
        reason: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Persist one final failure log and hand it to durable history."""
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key=None,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self._commit_action_execution_history_event(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )

    async def _update_action_result(
        self,
        *,
        execution: ActionExecution,
        result: dict[str, JSONValue],
        on_projection_updated: ActionExecutionProjectionCallback | None,
    ) -> ActionExecution:
        """Persist and project one bounded worktree action result."""
        async with self.session_manager() as session:
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result,
            )
        await self._publish_action_execution_projection(
            execution=updated,
            on_projection_updated=on_projection_updated,
        )
        return updated

    async def _fail_agent_create_git_worktree(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree | None,
        reason_code: str,
        reason: str,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
    ) -> None:
        """Persist a bounded Agent create failure and enqueue its continuation."""
        await self._compensate_agent_created_project(
            execution=execution,
            allocation=allocation,
        )
        execution = await self._update_action_result(
            execution=execution,
            result={
                "reason_code": reason_code,
                "worktree_path": (
                    allocation.worktree_path if allocation is not None else None
                ),
                "base_commit": (
                    allocation.base_commit if allocation is not None else None
                ),
                "branch_name": (
                    allocation.branch_name if allocation is not None else None
                ),
            },
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key=None,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self.commit_bridge_action_execution_terminal_handoff(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            predecessor_run_id=predecessor_run_id,
            allocation=allocation,
            on_history_event_appended=on_history_event_appended,
        )

    async def _fail_agent_remove_git_worktree(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree | None,
        action: AgentRemoveGitWorktreeAction,
        reason_code: str,
        reason: str,
        retry_guidance: str | None,
        dirty_content_discarded: bool,
        predecessor_run_id: str,
        on_projection_updated: ActionExecutionProjectionCallback | None,
        on_history_event_appended: ActionExecutionHistoryEventCallback | None,
        release_nonremoving_claim: bool = True,
    ) -> None:
        """Persist a removal failure without changing allocation ownership."""
        if release_nonremoving_claim:
            await self._release_nonremoving_agent_removal_claims(
                action_execution_id=execution.id,
            )
        execution = await self._update_action_result(
            execution=execution,
            result={
                "reason_code": reason_code,
                "worktree_project_id": action.worktree_project_id,
                "worktree_allocation_id": action.worktree_allocation_id,
                "worktree_path": action.worktree_path,
                "branch_name": (
                    allocation.branch_name if allocation is not None else None
                ),
                "force": action.force,
                "dirty_content_discarded": dirty_content_discarded,
                "retry_guidance": retry_guidance,
            },
            on_projection_updated=on_projection_updated,
        )
        await self._append_action_execution_event(
            execution=execution,
            kind=ActionExecutionEventKind.FAILED,
            step_key=None,
            command_argv=None,
            content=reason,
            exit_code=None,
            on_projection_updated=on_projection_updated,
        )
        await self.commit_bridge_action_execution_terminal_handoff(
            execution=execution,
            status=ActionExecutionStatus.FAILED,
            failure_summary=reason,
            cancellation_summary=None,
            predecessor_run_id=predecessor_run_id,
            allocation=None,
            on_history_event_appended=on_history_event_appended,
        )

    async def _record_agent_removal_projection_failure(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        worktree_path: str,
        claim_state: GitWorktreePathClaimState,
        reason: str,
    ) -> None:
        """Record confirmed checkout removal when later Project cleanup fails."""
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_cleanup_failed(
                session,
                worktree_id=allocation.id,
                cleanup_summary=reason,
                failed_at=datetime.now(UTC),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_agent_git_worktree_claim(
                session,
                action_execution_id=execution.id,
                worktree_path=worktree_path,
                state=claim_state,
            )

    async def _compensate_agent_created_project(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree | None,
    ) -> None:
        """Remove generated Project state when Agent creation does not complete."""
        if allocation is None:
            return
        async with self.session_manager() as session:
            current_allocation = (
                await self.session_git_worktree_repository.get_by_action_execution_id(
                    session,
                    action_execution_id=execution.id,
                )
            )
            if (
                current_allocation is None
                or current_allocation.session_workspace_project_id is None
            ):
                return
            project = await self.session_workspace_project_repository.get_project_by_id(
                session,
                current_allocation.session_workspace_project_id,
            )
            if project is None:
                return
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                execution.session_id,
            )
            if agent_session is None:
                raise RuntimeError(
                    "AgentSession is missing during Project compensation"
                )
            await self.agent_project_catalog_repository.delete_entry_by_path(
                session,
                agent_id=agent_session.agent_id,
                path=project.path,
            )
            deleted = await self.session_workspace_project_repository.delete_project(
                session,
                project.id,
                session_id=execution.session_id,
            )
            if not deleted:
                raise RuntimeError("Generated worktree Project compensation failed")

        if self.skill_store is None:
            return
        await self.skill_store.invalidate_project(
            agent_session.agent_id,
            execution.session_id,
            project_id=project.id,
            project_path=project.path,
            session_run_state=agent_session.run_state,
        )

    async def _sync_skill_projection_for_project_change(
        self,
        *,
        agent_id: str,
        session_id: str,
        required: bool = False,
    ) -> None:
        """Refresh latest Skill projection after adding a Project source."""
        if self.skill_store is None or self.runner_operations is None:
            if required:
                raise RuntimeError("Skill projection dependencies are unavailable")
            return
        projection_service = SkillProjectionService(
            store=self.skill_store,
            session_manager=self.session_manager,
            runtime_target_resolver=self.runtime_target_resolver,
            session_working_folder_binding_service=(
                self.session_working_folder_binding_service
            ),
            runner_operations=adapt_runtime_runner_operations(self.runner_operations),
            project_repository=self.session_workspace_project_repository,
        )
        await projection_service.sync_latest(
            agent_id=agent_id,
            session_id=session_id,
            reason="project_change",
        )

    async def mark_cleanup_pending_for_session(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> GitWorktreeCleanupRequest:
        """Request cleanup for session-owned Git worktree allocations."""
        allocations = await self.session_git_worktree_repository.list_by_session_id(
            session,
            session_id=session_id,
        )
        cleanup_targets = [
            allocation
            for allocation in allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if not cleanup_targets:
            return GitWorktreeCleanupRequest(cleanup_requested=False)
        for allocation in cleanup_targets:
            await self.session_git_worktree_repository.mark_cleanup_pending(
                session,
                worktree_id=allocation.id,
            )
        return GitWorktreeCleanupRequest(cleanup_requested=True)

    async def list_action_execution_projections(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> list[ActionExecutionProjection]:
        """List live action execution projections for a session."""
        return await self.action_execution_repository.list_projections_by_session_id(
            session,
            session_id=session_id,
        )

    async def request_manual_cleanup(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        session_workspace_project_id: str | None,
    ) -> Result[GitWorktreeCleanupRequest, GitWorktreeCleanupRequestError]:
        """Validate access and request manual worktree cleanup retry."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return Failure(GitWorktreeCleanupSessionNotFound())
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return Failure(GitWorktreeCleanupSubagentReadOnly())
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return Failure(GitWorktreeCleanupAccessDenied())
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if not allocations:
                return Failure(GitWorktreeCleanupNotFound())
            if session_workspace_project_id is not None:
                allocations = [
                    allocation
                    for allocation in allocations
                    if allocation.session_workspace_project_id
                    == session_workspace_project_id
                ]
                if not allocations:
                    return Failure(GitWorktreeCleanupNotFound())
            cleanup_targets = [
                allocation
                for allocation in allocations
                if allocation.status is not SessionGitWorktreeStatus.CLEANED
            ]
            if not cleanup_targets:
                return Success(GitWorktreeCleanupRequest(cleanup_requested=False))
            for allocation in cleanup_targets:
                await self.session_git_worktree_repository.mark_cleanup_pending(
                    session,
                    worktree_id=allocation.id,
                )
            return Success(GitWorktreeCleanupRequest(cleanup_requested=True))

    async def run_cleanup_for_session(
        self,
        *,
        agent_id: str,
        session_id: str,
        session_workspace_project_id: str | None,
    ) -> None:
        """Run best-effort cleanup for session-owned Git worktrees."""
        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
        if session_workspace_project_id is not None:
            allocations = [
                allocation
                for allocation in allocations
                if allocation.session_workspace_project_id
                == session_workspace_project_id
            ]
        cleanup_targets = [
            allocation
            for allocation in allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if not cleanup_targets:
            return
        try:
            binding_service = self.session_working_folder_binding_service
            await binding_service.require_bound_context(
                agent_id=agent_id,
                session_id=session_id,
            )
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                start_if_stopped=False,
            )
        except (RuntimeStorageError, SessionWorkingFolderBindingError) as error:
            await self._mark_cleanup_targets_failed(
                allocations=cleanup_targets,
                reason=str(error),
            )
            return
        if self.runner_operations is None:
            await self._mark_cleanup_targets_failed(
                allocations=cleanup_targets,
                reason="Runtime runner operations are unavailable.",
            )
            return

        last_cleaned: SessionGitWorktree | None = None
        for allocation in cleanup_targets:
            cleaned = await self._run_cleanup_for_allocation(
                agent_id=agent_id,
                session_id=session_id,
                claim_owner_session_id=session_id,
                runtime=runtime,
                allocation=allocation,
                force=False,
            )
            if cleaned is not None:
                last_cleaned = cleaned

        if last_cleaned is None:
            return

    async def run_archive_cleanup_for_root_tree(
        self,
        *,
        agent_id: str,
        root_session_id: str,
        subtree_session_ids: Sequence[str],
    ) -> int:
        """Attempt forced cleanup for one newly archived root SessionAgent tree."""
        allowed_session_ids = set(subtree_session_ids)
        if root_session_id not in allowed_session_ids:
            raise ValueError("Root session must belong to its archive subtree")

        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=root_session_id,
            )
            eligible_allocations: list[SessionGitWorktree] = []
            for allocation in allocations:
                creator_session_id = allocation.created_by_agent_session_id
                if creator_session_id not in allowed_session_ids:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="allocation_outside_root_tree",
                    )
                    await self.session_git_worktree_repository.mark_cleanup_failed(
                        session,
                        worktree_id=allocation.id,
                        cleanup_summary=(
                            "Git worktree allocation belongs outside the archive "
                            "subtree."
                        ),
                        failed_at=datetime.now(UTC),
                    )
                    continue
                eligible_allocations.append(allocation)
                if allocation.status is not SessionGitWorktreeStatus.CLEANED:
                    await self.session_git_worktree_repository.mark_cleanup_pending(
                        session,
                        worktree_id=allocation.id,
                    )

        cleanup_targets = [
            allocation
            for allocation in eligible_allocations
            if allocation.status is not SessionGitWorktreeStatus.CLEANED
        ]
        if cleanup_targets:
            if self.runner_operations is None:
                for allocation in cleanup_targets:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="runner_operations_unavailable",
                    )
                await self._mark_cleanup_targets_failed(
                    allocations=cleanup_targets,
                    reason="Runtime runner operations are unavailable.",
                )
                return len(allocations)

            for allocation in cleanup_targets:
                creator_session_id = allocation.created_by_agent_session_id
                if creator_session_id is None:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code="creator_session_missing",
                    )
                    await self._mark_cleanup_failed(
                        worktree_id=allocation.id,
                        reason=(
                            "Git worktree allocation creator AgentSession is missing."
                        ),
                    )
                    continue
                try:
                    binding_service = self.session_working_folder_binding_service
                    await binding_service.require_bound_context(
                        agent_id=agent_id,
                        session_id=allocation.session_id,
                    )
                    runtime = (
                        await self.runtime_target_resolver.resolve_operation_target(
                            agent_id,
                            start_if_stopped=False,
                        )
                    )
                except (
                    RuntimeStorageError,
                    SessionWorkingFolderBindingError,
                ) as error:
                    _log_archive_cleanup_failure(
                        agent_id=agent_id,
                        root_session_id=root_session_id,
                        allocation=allocation,
                        reason_code=(
                            "binding_unavailable"
                            if isinstance(error, SessionWorkingFolderBindingError)
                            else "runtime_unavailable"
                        ),
                    )
                    await self._mark_cleanup_failed(
                        worktree_id=allocation.id,
                        reason=str(error),
                    )
                    continue
                try:
                    await self._run_cleanup_for_allocation(
                        agent_id=agent_id,
                        session_id=creator_session_id,
                        claim_owner_session_id=root_session_id,
                        runtime=runtime,
                        allocation=allocation,
                        force=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception(
                        "Archived Session Git worktree cleanup failed unexpectedly",
                        extra={
                            "agent_id": agent_id,
                            "root_session_id": root_session_id,
                            "session_id": creator_session_id,
                            "worktree_id": allocation.id,
                            "reason_code": "unexpected_cleanup_failure",
                        },
                    )
                    try:
                        await self._mark_cleanup_failed(
                            worktree_id=allocation.id,
                            reason=("Git worktree cleanup failed: unexpected_error."),
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception(
                            "Archived Session Git worktree cleanup failure state "
                            "could not be recorded",
                            extra={
                                "agent_id": agent_id,
                                "root_session_id": root_session_id,
                                "session_id": creator_session_id,
                                "worktree_id": allocation.id,
                            },
                        )
        return len(allocations)

    async def _run_cleanup_for_allocation(
        self,
        *,
        agent_id: str,
        session_id: str,
        claim_owner_session_id: str,
        runtime: RuntimeOperationTarget,
        allocation: SessionGitWorktree,
        force: bool,
    ) -> SessionGitWorktree | None:
        """Run cleanup for one session-owned Git worktree allocation."""
        expected_authority = RuntimeOperationAuthority(
            configuration_sequence=runtime.configuration_sequence,
            configuration_digest=runtime.configuration_digest,
            desired_generation=runtime.desired_generation,
        )
        try:
            runtime = await self.runtime_target_resolver.resolve_operation_target(
                agent_id,
                expected_authority=expected_authority,
                start_if_stopped=False,
            )
            binding_service = self.session_working_folder_binding_service
            binding = await binding_service.resolve_bound_authority_for_target(
                agent_id=agent_id,
                session_id=allocation.session_id,
                runtime_target=runtime,
            )
        except RuntimeStorageError:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason="Git worktree cleanup blocked: runtime_unavailable.",
            )
            return None
        except SessionWorkingFolderBindingError:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason="Git worktree cleanup blocked: session_binding_unavailable.",
            )
            return None
        cleanup_classification, ownership_error = _cleanup_classification(
            allocation=allocation,
            session_id=session_id,
            workspace_root=normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix(),
            working_folder_path=binding.working_folder_path,
        )
        if ownership_error is not None:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=ownership_error,
            )
            return None
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        claimed = await self._claim_archive_cleanup_path(
            runtime_id=runtime.id,
            root_session_id=claim_owner_session_id,
            worktree_path=allocation.worktree_path,
        )
        if not claimed:
            logger.info(
                "Skipped archived Git worktree cleanup owned by another operation",
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "worktree_id": allocation.id,
                },
            )
            return None
        try:
            removal = await runner_operations.remove_git_worktree(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=session_id,
                source_project_path=allocation.source_project_path,
                worktree_path=allocation.worktree_path,
                branch_name=allocation.branch_name,
                force=force,
                deadline_at=_git_operation_deadline(),
                text_output_callback=None,
            )
            if allocation.branch_created_by is SessionGitWorktreeBranchCreatedBy.AZENTS:
                await runner_operations.delete_git_branch(
                    runtime_id=runtime.id,
                    runner_generation=runtime.runner_generation,
                    owner_session_id=session_id,
                    source_project_path=allocation.source_project_path,
                    branch_name=allocation.branch_name,
                    deadline_at=_git_operation_deadline(),
                    text_output_callback=None,
                )
            if cleanup_classification == "legacy":
                await self._cleanup_empty_session_worktree_parent(
                    runtime=runtime,
                    allocation=allocation,
                )
            cleaned_at = datetime.now(UTC)
            async with self.session_manager() as session:
                await self.agent_project_catalog_repository.delete_entry_by_path(
                    session,
                    agent_id=agent_id,
                    path=allocation.worktree_path,
                )
                cleaned = await self.session_git_worktree_repository.mark_cleaned(
                    session,
                    worktree_id=allocation.id,
                    cleanup_summary=_cleanup_terminal_summary(
                        removal_outcome=removal.outcome,
                        force=force,
                    ),
                    cleaned_at=cleaned_at,
                )
                if allocation.session_workspace_project_id is not None:
                    await self.session_workspace_project_repository.delete_project(
                        session,
                        allocation.session_workspace_project_id,
                        session_id=allocation.session_id,
                    )
            return cleaned
        except (
            RuntimeRunnerOperationCanceledError,
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ) as exc:
            logger.warning(
                "Git worktree cleanup Runner operation failed",
                exc_info=True,
                extra={
                    "agent_id": agent_id,
                    "session_id": session_id,
                    "worktree_id": allocation.id,
                    "runner_error_code": (
                        exc.code
                        if isinstance(exc, RuntimeRunnerOperationFailedError)
                        else type(exc).__name__
                    ),
                },
            )
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=_cleanup_operation_failure_summary(exc),
            )
            return None
        finally:
            await self._release_archive_cleanup_path(
                runtime_id=runtime.id,
                root_session_id=claim_owner_session_id,
                worktree_path=allocation.worktree_path,
            )

    async def _cleanup_empty_session_worktree_parent(
        self,
        *,
        runtime: RuntimeOperationTarget,
        allocation: SessionGitWorktree,
    ) -> None:
        """Delete the session worktree directory after its last child is removed."""
        runner_operations = self.runner_operations
        if runner_operations is None:
            raise RuntimeError("Runtime runner operations are unavailable")
        parent_path = _session_worktree_parent_path(
            allocation.worktree_path,
            workspace_root=normalize_agent_workspace_root(
                runtime.workspace_path
            ).as_posix(),
        )
        if parent_path is None:
            return
        try:
            listed = await runner_operations.list_files(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=allocation.session_id,
                path=parent_path,
                recursive=False,
                deadline_at=_git_operation_deadline(),
            )
            if listed.entries:
                return
            await runner_operations.delete_file(
                runtime_id=runtime.id,
                runner_generation=runtime.runner_generation,
                owner_session_id=allocation.session_id,
                path=parent_path,
                recursive=False,
                deadline_at=_git_operation_deadline(),
            )
        except (
            RuntimeRunnerOperationCanceledError,
            RuntimeRunnerOperationFailedError,
            RuntimeRunnerOperationUnavailable,
            RuntimeRunnerOperationGenerationError,
        ):
            logger.info(
                "Skipped empty session worktree directory cleanup",
                extra={
                    "session_id": allocation.session_id,
                    "worktree_id": allocation.id,
                },
            )

    async def _mark_cleanup_targets_failed(
        self,
        *,
        allocations: list[SessionGitWorktree],
        reason: str,
    ) -> None:
        """Mark multiple cleanup targets failed with the same reason."""
        for allocation in allocations:
            await self._mark_cleanup_failed(
                worktree_id=allocation.id,
                reason=reason,
            )

    async def _mark_cleanup_failed(
        self,
        *,
        worktree_id: str,
        reason: str,
    ) -> None:
        """Persist a user-safe cleanup failure summary."""
        failed_at = datetime.now(UTC)
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_cleanup_failed(
                session,
                worktree_id=worktree_id,
                cleanup_summary=reason,
                failed_at=failed_at,
            )

    async def _choose_available_target(
        self,
        allocation: SessionGitWorktree,
        *,
        runtime_id: str,
        path_suffix: int,
        branch_suffix: int,
    ) -> SessionGitWorktree:
        """Apply DB-visible target suffixing before a runner attempt."""
        current_path_suffix = path_suffix
        current_branch_suffix = branch_suffix
        for _ in range(_MAX_COLLISION_ATTEMPTS):
            worktree_path, branch_name = _target_names(
                session_handle=_branch_session_handle(allocation.branch_name),
                worktree_parent_path=PurePosixPath(
                    allocation.worktree_path
                ).parent.as_posix(),
                source_project_path=allocation.source_project_path,
                path_suffix=current_path_suffix,
                branch_suffix=current_branch_suffix,
            )
            async with self.session_manager() as session:
                project_repository = self.session_workspace_project_repository
                await project_repository.acquire_runtime_path_coordination_lock(
                    session,
                    runtime_id=runtime_id,
                )
                await project_repository.acquire_runtime_worktree_path_lock(
                    session,
                    runtime_id=runtime_id,
                    worktree_path=worktree_path,
                )
                path_exists = (
                    await self.session_git_worktree_repository.worktree_path_exists(
                        session,
                        worktree_path=worktree_path,
                        excluding_id=allocation.id,
                    )
                )
                branch_exists = (
                    await self.session_git_worktree_repository.branch_name_exists(
                        session,
                        branch_name=branch_name,
                        excluding_id=allocation.id,
                    )
                )
                claim_exists = await project_repository.has_blocking_git_worktree_claim(
                    session,
                    runtime_id=runtime_id,
                    worktree_path=worktree_path,
                )
                if not path_exists and not branch_exists and not claim_exists:
                    return await self.session_git_worktree_repository.update_target(
                        session,
                        worktree_id=allocation.id,
                        worktree_path=worktree_path,
                        branch_name=branch_name,
                    )
            if path_exists or claim_exists:
                current_path_suffix += 1
            if branch_exists:
                current_branch_suffix += 1
        return allocation


def _action_cancellation_reason(exc: asyncio.CancelledError) -> str:
    """Return the durable operation cancellation reason."""
    reason = str(exc.args[0]) if exc.args else ""
    if reason == USER_STOP_CANCEL_MESSAGE:
        return "Operation cancelled by user stop."
    if reason == SHUTDOWN_CANCEL_MESSAGE:
        return "Operation cancelled after the worker shutdown wait expired."
    return "Operation cancelled during Session ownership handover."


@dataclasses.dataclass(frozen=True)
class _CreateWorktreeSuccess:
    """Successful create_git_worktree result."""

    worktree_path: str
    branch_name: str
    base_commit: str


class _AgentWorktreeRemovalClaimConflict(RuntimeError):
    """Another destructive operation currently owns the requested path."""


def _bridge_create_terminal_result() -> GitWorktreeActionExecutionResult:
    """Return the terminal fresh-Run outcome for an Agent create bridge."""
    return GitWorktreeActionExecutionResult(
        completed=True,
        context_invalidated=False,
        complete_run=True,
    )


def _bridge_remove_terminal_result() -> GitWorktreeActionExecutionResult:
    """Return the terminal fresh-Run outcome for an Agent removal bridge."""
    return GitWorktreeActionExecutionResult(
        completed=True,
        context_invalidated=False,
        complete_run=True,
    )


def _agent_removal_inspection_error(
    *,
    allocation: SessionGitWorktree,
    inspection_worktree_path: str,
    registered: bool,
    registered_branch_name: str | None,
    target_kind: Literal["directory", "missing", "other"],
    dirty: bool | None,
) -> str | None:
    """Return why Runner inspection cannot authorize exact removal."""
    if inspection_worktree_path != allocation.worktree_path:
        return "Runner inspected a different worktree path."
    if target_kind == "missing":
        if registered or registered_branch_name is not None or dirty is not None:
            return "Runner returned inconsistent missing-worktree evidence."
        return None
    if target_kind != "directory":
        return "The recorded worktree path is not a removable directory."
    if not registered:
        return "The recorded checkout is not registered as a Git worktree."
    if registered_branch_name != allocation.branch_name:
        return "The registered Git worktree branch does not match the allocation."
    if dirty is None:
        return "Runner could not determine the worktree dirty state."
    return None


def _remove_worktree_command_argv(
    *,
    worktree_path: str,
    force: bool,
) -> list[str]:
    """Build a content-free progress argv for checkout-only removal."""
    argv = ["git", "worktree", "remove"]
    if force:
        argv.append("--force")
    argv.append(worktree_path)
    return argv


def _agent_removal_terminal_summary(
    *,
    removal_outcome: Literal["removed", "already_absent"],
    force: bool,
) -> str:
    """Return durable evidence that Agent removal preserved the branch."""
    if removal_outcome == "already_absent":
        return "Agent removal completed: checkout_confirmed_absent; branch_preserved."
    if force:
        return "Agent removal completed: checkout_removed_force; branch_preserved."
    return "Agent removal completed: checkout_removed; branch_preserved."


def _git_operation_deadline() -> datetime:
    """Return a deadline for one Git runner operation."""
    return datetime.now(UTC) + timedelta(seconds=_GIT_OPERATION_TIMEOUT_SECONDS)


def _normalized_optional_tool_argument(
    value: str | None,
    *,
    field_name: str,
) -> str | None:
    """Normalize an optional tool string while rejecting explicit empty values."""
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty when provided.")
    return normalized


def _worktree_bridge_identity(
    *,
    session_id: str,
    run_id: str,
    tool_name: str,
    client_tool_call_id: str,
) -> str:
    """Build one bounded stable bridge idempotency identity."""
    canonical = "\0".join((session_id, run_id, tool_name, client_tool_call_id))
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"agent-worktree:{tool_name}:{digest}"


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


def _worktree_path_suffix(
    worktree_path: str,
    *,
    source_project_path: str,
) -> int:
    """Recover the numeric suffix from one generated worktree path."""
    path_leaf = PurePosixPath(worktree_path).name
    repo_leaf = _repo_leaf(source_project_path)
    if path_leaf == repo_leaf:
        return 1
    suffix = path_leaf.removeprefix(f"{repo_leaf}-")
    if path_leaf == f"{repo_leaf}-{suffix}" and suffix.isdigit():
        value = int(suffix)
        if value >= 2:
            return value
    raise ValueError("Recorded worktree path is not Azents-generated")


def _generated_branch_suffix(branch_name: str) -> int:
    """Recover the numeric suffix from one generated worktree branch."""
    session_handle = _branch_session_handle(branch_name)
    branch_base = f"azents/{session_handle}"
    if branch_name == branch_base:
        return 1
    suffix = branch_name.removeprefix(f"{branch_base}-")
    if branch_name == f"{branch_base}-{suffix}" and suffix.isdigit():
        value = int(suffix)
        if value >= 2:
            return value
    raise ValueError("Recorded worktree branch is not Azents-generated")


def _branch_session_handle(branch_name: str) -> str:
    """Recover the stable session-handle prefix from an Azents branch name."""
    prefix = "azents/"
    if not branch_name.startswith(prefix):
        raise ValueError("Recorded worktree branch is not Azents-managed")
    return re.sub(r"-\d+$", "", branch_name.removeprefix(prefix))


def _session_worktree_parent_path(
    worktree_path: str,
    *,
    workspace_root: str,
) -> str | None:
    """Return the session-scoped worktree parent directory for an allocated path."""
    worktree_root = PurePosixPath(workspace_root) / ".azents" / "worktrees"
    try:
        relative = PurePosixPath(worktree_path).relative_to(worktree_root)
    except ValueError:
        return None
    if len(relative.parts) < 2:
        return None
    return (worktree_root / relative.parts[0]).as_posix()


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


def _log_archive_cleanup_failure(
    *,
    agent_id: str,
    root_session_id: str,
    allocation: SessionGitWorktree,
    reason_code: str,
) -> None:
    """Log one bounded expected failure from archive-owned worktree cleanup."""
    logger.warning(
        "Archived Session Git worktree cleanup did not complete",
        extra={
            "agent_id": agent_id,
            "root_session_id": root_session_id,
            "session_id": allocation.created_by_agent_session_id,
            "worktree_id": allocation.id,
            "reason_code": reason_code,
        },
    )


def _cleanup_terminal_summary(
    *,
    removal_outcome: Literal["removed", "already_absent"],
    force: bool,
) -> str:
    """Return a stable durable cleanup terminal classification."""
    if removal_outcome == "already_absent":
        return "Git worktree cleanup completed: confirmed_absent."
    if force:
        return "Git worktree cleanup completed: removed_force."
    return "Git worktree cleanup completed: removed."


def _cleanup_operation_failure_summary(
    error: (
        RuntimeRunnerOperationCanceledError
        | RuntimeRunnerOperationFailedError
        | RuntimeRunnerOperationUnavailable
        | RuntimeRunnerOperationGenerationError
    ),
) -> str:
    """Return a bounded cleanup failure without Runner path diagnostics."""
    if isinstance(error, RuntimeRunnerOperationFailedError):
        if error.code == "worktree_ownership_ambiguous":
            return "Git worktree cleanup blocked: ambiguous_target_ownership."
        return "Git worktree cleanup failed: runner_operation_failed."
    if isinstance(error, RuntimeRunnerOperationCanceledError):
        return "Git worktree cleanup failed: runner_operation_failed."
    return "Git worktree cleanup failed: runtime_unavailable."


def _cleanup_candidate(
    *,
    path: str,
    outcome: Literal[
        "unresolved",
        "protected",
        "removed",
        "already_absent",
        "failed",
    ],
    reason_code: str | None,
    summary: str | None,
) -> dict[str, JSONValue]:
    """Build one content-free durable cleanup candidate result."""
    return {
        "path": path,
        "outcome": outcome,
        "reason_code": reason_code,
        "summary": summary,
    }


def _cleanup_result(
    *,
    phase: str,
    candidates: list[dict[str, JSONValue]],
) -> dict[str, JSONValue]:
    """Build the versioned durable result for one cleanup action."""
    candidate_values: list[JSONValue] = [candidate for candidate in candidates]
    return {
        "schema_version": 1,
        "phase": phase,
        "examined_count": len(candidates),
        "protected_count": _cleanup_candidate_count(candidates, "protected"),
        "removed_count": _cleanup_candidate_count(candidates, "removed"),
        "already_absent_count": _cleanup_candidate_count(
            candidates,
            "already_absent",
        ),
        "failed_count": _cleanup_candidate_count(candidates, "failed"),
        "unresolved_count": _cleanup_candidate_count(candidates, "unresolved"),
        "candidates": candidate_values,
    }


def _cleanup_candidate_count(
    candidates: list[dict[str, JSONValue]],
    outcome: str,
) -> int:
    """Count one candidate outcome without exposing candidate contents."""
    return sum(1 for candidate in candidates if candidate.get("outcome") == outcome)


def _cleanup_log_summary(
    *,
    stage: str,
    reason_code: str | None,
    candidates: list[dict[str, JSONValue]],
) -> dict[str, str | int | None]:
    """Return structured cleanup summary fields for operational logs."""
    return {
        "stage": stage,
        "reason_code": reason_code,
        "candidate_count": len(candidates),
        "failed_count": _cleanup_candidate_count(candidates, "failed"),
        "protected_count": _cleanup_candidate_count(candidates, "protected"),
        "removed_count": _cleanup_candidate_count(candidates, "removed"),
        "already_absent_count": _cleanup_candidate_count(
            candidates,
            "already_absent",
        ),
    }


def _collision_kind(message: str) -> Literal["branch", "path"] | None:
    """Infer retryable target collision kind from runner failure text."""
    lowered = message.lower()
    if "branch_exists" in lowered or "branch exists" in lowered:
        return "branch"
    if "worktree_path_exists" in lowered or "worktree path exists" in lowered:
        return "path"
    return None
