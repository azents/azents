"""Specific repository-owned Session worktree atomic operations."""

import dataclasses
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Literal

from azcommon.uuid import uuid7
from fastapi import Depends

from azents.core.action_execution_data import (
    ActionExecution,
    ActionExecutionEvent,
    ActionExecutionEventCreate,
    ActionExecutionProjection,
)
from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    ActionExecutionEventKind,
    ActionExecutionStatus,
    AgentSessionKind,
    AgentSessionStatus,
    EventKind,
    GitWorktreePathClaimState,
    MailboxItemKind,
    MailboxSchedulingMode,
    SessionGitWorktreeBranchCreatedBy,
    SessionGitWorktreeStatus,
)
from azents.core.json_value import JSONValue
from azents.core.mailbox_data import MailboxItemCreate
from azents.core.session_git_worktree_results import (
    _bridge_continuation_payload,
    _cleanup_classification,
    _cleanup_result,
    _decode_cleanup_candidates,
    _is_agent_worktree_bridge_action,
    _target_names,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.core.session_workspace_paths import normalize_session_workspace_path
from azents.core.session_workspace_project import (
    SessionWorkspaceProject,
    SessionWorkspaceProjectCreate,
)
from azents.engine.events.action_messages import (
    AgentCreateGitWorktreeAction,
    AgentRemoveGitWorktreeAction,
)
from azents.engine.events.types import Event
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import EventTranscriptRepository
from azents.repos.agent_execution.data import EventCreate
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.mailbox import MailboxRepository
from azents.repos.session_execution.ownership import (
    fence_owned_session_mutation,
    validate_session_execution_owner,
)
from azents.repos.session_git_worktree import SessionGitWorktreeRepository
from azents.repos.session_git_worktree.data import (
    SessionGitWorktree,
    SessionGitWorktreeCreate,
)
from azents.repos.session_git_worktree.operation_data import (
    ArchiveCleanupPreparation,
    CleanupDecision,
    CompensatedProject,
    PreviewAccess,
    RemovalAuthorityChanged,
    RemovalClaimConflict,
    RemovalIntent,
    StartedCleanup,
    TargetChoice,
    WorktreeContext,
)
from azents.repos.session_working_folder_binding import (
    SessionWorkingFolderBindingRepository,
)
from azents.repos.session_working_folder_binding.data import SessionWorkingFolderTarget
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace_user import WorkspaceUserRepository

_MAX_COLLISION_ATTEMPTS = 20


@dataclasses.dataclass
class SessionGitWorktreeOperationsRepository:
    """Own worktree database lifetimes and compose the original atomic groups."""

    agent_repository: Annotated[AgentRepository, Depends()]
    agent_session_repository: Annotated[AgentSessionRepository, Depends()]
    workspace_user_repository: Annotated[WorkspaceUserRepository, Depends()]
    agent_runtime_repository: Annotated[AgentRuntimeRepository, Depends()]
    session_git_worktree_repository: Annotated[SessionGitWorktreeRepository, Depends()]
    session_workspace_project_repository: Annotated[
        SessionWorkspaceProjectRepository, Depends()
    ]
    agent_project_catalog_repository: Annotated[
        AgentProjectCatalogRepository, Depends()
    ]
    action_execution_repository: Annotated[ActionExecutionRepository, Depends()]
    mailbox_item_repository: Annotated[MailboxRepository, Depends()]
    event_transcript_repository: Annotated[EventTranscriptRepository, Depends()]
    binding_repository: Annotated[SessionWorkingFolderBindingRepository, Depends()]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def assert_actor_current(
        self, *, execution: ActionExecution, actor_generation: int
    ) -> None:
        """Complete an owner observation before admitting external execution."""
        async with self.read_session_manager() as session:
            await validate_session_execution_owner(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id, owner_generation=actor_generation
                ),
            )

    async def list_active_session_allocations(
        self, *, agent_id: str, session_id: str
    ) -> list[SessionGitWorktree] | None:
        """Complete the list active session allocations database operation."""
        async with self.read_session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if (
                agent_session is None
                or agent_session.agent_id != agent_id
                or agent_session.status is not AgentSessionStatus.ACTIVE
            ):
                return None
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            return allocations

    async def admit_create(
        self,
        *,
        agent_id: str,
        context_id: str,
        bridge_identity: str,
        client_tool_call_id: str,
        originating_run_id: str,
        owner_generation: int,
        session_id: str,
        normalized_branch_name: str | None,
        normalized_source_path: str,
        normalized_starting_ref: str | None,
    ) -> str:
        """Complete the admit create database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=session_id, owner_generation=owner_generation
                ),
            )
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
                or session_agent.context_id != context_id
            ):
                raise ValueError("The current Session context is unavailable.")
            if project is None or project.session_agent_context_id != context_id:
                raise ValueError(
                    "source_project_path must identify a current Session Project."
                )
            action = AgentCreateGitWorktreeAction(
                bridge_identity=bridge_identity,
                originating_run_id=originating_run_id,
                client_tool_call_id=client_tool_call_id,
                session_agent_context_id=context_id,
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
                        requested_enabled_execution_options=[],
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
            return admission.id

    async def admit_remove(
        self,
        *,
        agent_id: str,
        context_id: str,
        bridge_identity: str,
        client_tool_call_id: str,
        originating_run_id: str,
        owner_generation: int,
        session_id: str,
        normalized_worktree_path: str,
        force: bool,
    ) -> str:
        """Complete the admit remove database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=session_id, owner_generation=owner_generation
                ),
            )
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
                or session_agent.context_id != context_id
            ):
                raise ValueError("The current Session context is unavailable.")
            if (
                project is None
                or project.session_agent_context_id != context_id
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
                session_agent_context_id=context_id,
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
                        requested_enabled_execution_options=[],
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
            return admission.id

    async def preview_access(self, *, agent_id: str, user_id: str) -> PreviewAccess:
        """Complete the preview access database operation."""
        async with self.read_session_manager() as session:
            agent = await self.agent_repository.get_by_id(session, agent_id)
            if agent is None:
                return PreviewAccess.AGENT_NOT_FOUND
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return PreviewAccess.ACCESS_DENIED
            return PreviewAccess.ALLOWED

    async def read_session(self, *, session_id: str) -> AgentSession | None:
        """Complete the read session database operation."""
        async with self.read_session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            return agent_session

    async def mark_running(self, *, execution: ActionExecution) -> ActionExecution:
        """Complete the mark running database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            execution = await self.action_execution_repository.mark_running(
                session,
                action_execution_id=execution.id,
                started_at=datetime.now(UTC),
            )
            return execution

    async def update_result(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        result: dict[str, JSONValue],
    ) -> ActionExecution:
        """Complete the update result database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result,
            )
            return updated

    async def start_orphan_cleanup(
        self,
        *,
        execution: ActionExecution,
        session_id: str,
        initial_result: dict[str, JSONValue],
    ) -> StartedCleanup:
        """Complete the start orphan cleanup database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
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
                result=initial_result,
            )
            return StartedCleanup(
                agent_session=agent_session,
                context_runtime_id=context_runtime_id,
                execution=execution,
            )

    async def claim_orphan_path(
        self,
        *,
        execution: ActionExecution,
        owner_generation: int,
        runtime_id: str,
        worktree_path: str,
        discovery_fingerprint: str,
    ) -> Literal["claimed", "active_connection", "cleanup_in_progress"]:
        """Complete the claim orphan path database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id, owner_generation=owner_generation
                ),
            )
            project_repository = self.session_workspace_project_repository
            result = await project_repository.try_claim_orphan_git_worktree(
                session,
                runtime_id=runtime_id,
                action_execution_id=execution.id,
                owner_generation=owner_generation,
                worktree_path=worktree_path,
                discovery_fingerprint=discovery_fingerprint,
            )

            return result

    async def mark_orphan_removing(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        worktree_path: str,
    ) -> None:
        """Complete the mark orphan removing database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.mark_orphan_git_worktree_claim_removing(
                session,
                action_execution_id=execution.id,
                worktree_path=worktree_path,
            )

    async def release_orphan_claim(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Complete the release orphan claim database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_orphan_git_worktree_claim(
                session,
                action_execution_id=execution.id,
                worktree_path=worktree_path,
                state=state,
            )

    async def release_orphan_claims(
        self, *, execution: ActionExecution, actor_generation: int | None
    ) -> None:
        """Complete the release orphan claims database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_orphan_git_worktree_claims(
                session,
                action_execution_id=execution.id,
            )

    async def release_nonremoving_orphan_claims(
        self, *, execution: ActionExecution, actor_generation: int | None
    ) -> None:
        """Complete the release nonremoving orphan claims database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_nonremoving_orphan_git_worktree_claims(
                session,
                action_execution_id=execution.id,
            )

    async def release_agent_claim(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        worktree_path: str,
        state: GitWorktreePathClaimState,
    ) -> None:
        """Complete the release agent claim database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_agent_git_worktree_claim(
                session,
                action_execution_id=execution.id,
                worktree_path=worktree_path,
                state=state,
            )

    async def release_nonremoving_agent_claims(
        self, *, execution: ActionExecution, actor_generation: int | None
    ) -> None:
        """Complete the release nonremoving agent claims database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_nonremoving_agent_git_worktree_claims(
                session,
                action_execution_id=execution.id,
            )

    async def claim_archive_path(
        self, *, runtime_id: str, root_session_id: str, worktree_path: str
    ) -> bool:
        """Complete the claim archive path database operation."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            claimed = await project_repository.try_claim_archive_git_worktree(
                session,
                runtime_id=runtime_id,
                root_session_id=root_session_id,
                worktree_path=worktree_path,
            )

            return claimed

    async def release_archive_claim(
        self, *, runtime_id: str, root_session_id: str, worktree_path: str
    ) -> None:
        """Complete the release archive claim database operation."""
        async with self.session_manager() as session:
            project_repository = self.session_workspace_project_repository
            await project_repository.release_archive_git_worktree_claim(
                session,
                runtime_id=runtime_id,
                root_session_id=root_session_id,
                worktree_path=worktree_path,
            )

    async def cancel_cleanup_result(
        self, *, execution: ActionExecution, actor_generation: int | None, reason: str
    ) -> ActionExecution | None:
        """Complete the cancel cleanup result database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
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
                candidates = tuple(
                    candidate.with_cancellation(reason)
                    for candidate in _decode_cleanup_candidates(current_result)
                )
                result = _cleanup_result(phase="cancelled", candidates=candidates)
            updated = await self.action_execution_repository.update_result(
                session,
                action_execution_id=execution.id,
                result=result.to_json(),
            )
            return updated

    async def read_removal_context(
        self, *, agent_id: str, session_id: str
    ) -> WorktreeContext:
        """Complete the read removal context database operation."""
        async with self.read_session_manager() as session:
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
            return WorktreeContext(
                agent=agent,
                agent_session=agent_session,
                session_agent=session_agent,
                source_project=None,
            )

    async def claim_agent_removal(
        self,
        *,
        execution: ActionExecution,
        owner_generation: int,
        action: AgentRemoveGitWorktreeAction,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        working_folder_path: str,
        workspace_root: str,
    ) -> RemovalIntent:
        """Complete the claim agent removal database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id, owner_generation=owner_generation
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                target=target,
                bind_pending=False,
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
            try:
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
                    working_folder_path=working_folder_path,
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
                    runtime_id=target.id,
                    action_execution_id=execution.id,
                    owner_generation=owner_generation,
                    worktree_path=action.worktree_path,
                )
                if not claimed:
                    raise RemovalClaimConflict(allocation=allocation)
                return RemovalIntent(allocation=allocation, project=project)
            except ValueError as error:
                raise RemovalAuthorityChanged(
                    reason=str(error), allocation=allocation
                ) from error

    async def revalidate_agent_removal(
        self,
        *,
        execution: ActionExecution,
        action: AgentRemoveGitWorktreeAction,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        allocation: SessionGitWorktree,
    ) -> None:
        """Complete the revalidate agent removal database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                target=target,
                bind_pending=False,
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
                or current_allocation.session_workspace_project_id != current_project.id
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

    async def finish_agent_removal(
        self,
        *,
        execution: ActionExecution,
        action: AgentRemoveGitWorktreeAction,
        agent_id: str,
        session_id: str,
        allocation: SessionGitWorktree,
        project: SessionWorkspaceProject,
        claim_state: GitWorktreePathClaimState,
        cleaned_at: datetime,
        cleanup_summary: str,
    ) -> SessionGitWorktree:
        """Complete the finish agent removal database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
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
                or current_allocation.session_workspace_project_id != current_project.id
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
            deleted = await self.session_workspace_project_repository.delete_project(
                session,
                project.id,
                session_id=session_id,
            )
            if not deleted:
                raise RuntimeError(
                    "Managed worktree Project removal was not confirmed."
                )
            cleaned = await self.session_git_worktree_repository.mark_cleaned(
                session,
                worktree_id=allocation.id,
                cleanup_summary=cleanup_summary,
                cleaned_at=cleaned_at,
            )
            project_repository = self.session_workspace_project_repository
            await project_repository.release_agent_git_worktree_claim(
                session,
                action_execution_id=execution.id,
                worktree_path=action.worktree_path,
                state=claim_state,
            )
            return cleaned

    async def read_create_context(
        self, *, agent_id: str, session_id: str, source_project_id: str
    ) -> WorktreeContext:
        """Complete the read create context database operation."""
        async with self.read_session_manager() as session:
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
                    source_project_id,
                )
            )
            return WorktreeContext(
                agent=agent,
                agent_session=agent_session,
                session_agent=session_agent,
                source_project=source_project,
            )

    async def allocate_agent_worktree(
        self,
        *,
        execution: ActionExecution,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        source_project_id: str,
        context_id: str,
        normalized_source_path: str,
        session_handle: str,
        runtime_id: str,
        working_folder_path: str,
        source_project_path: str,
        starting_ref: str,
        requested_branch_name: str | None,
    ) -> SessionGitWorktree:
        """Complete the allocate agent worktree database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                target=target,
                bind_pending=False,
            )
            current_project = (
                await self.session_workspace_project_repository.get_project_by_id(
                    session,
                    source_project_id,
                )
            )
            if (
                current_project is None
                or current_project.session_agent_context_id != context_id
                or current_project.path != normalized_source_path
            ):
                raise ValueError(
                    "The admitted source Project changed before Git execution."
                )
            allocation = await self._ensure_agent_worktree_allocation(
                session,
                execution=execution,
                session_id=session_id,
                session_handle=session_handle,
                runtime_id=runtime_id,
                working_folder_path=working_folder_path,
                source_project_path=source_project_path,
                starting_ref=starting_ref,
                requested_branch_name=requested_branch_name,
            )
            return allocation

    async def allocate_action_worktree(
        self,
        *,
        execution: ActionExecution,
        agent_id: str,
        session_id: str,
        target: SessionWorkingFolderTarget,
        session_handle: str,
        working_folder_path: str,
        source_project_path: str,
        starting_ref: str,
    ) -> SessionGitWorktree:
        """Complete the allocate action worktree database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=session_id,
                target=target,
                bind_pending=False,
            )
            allocation = await self._ensure_action_worktree_allocation(
                session,
                execution=execution,
                session_id=session_id,
                session_handle=session_handle,
                working_folder_path=working_folder_path,
                source_project_path=source_project_path,
                starting_ref=starting_ref,
            )
            return allocation

    async def mark_creating(
        self, *, execution: ActionExecution, current: SessionGitWorktree
    ) -> SessionGitWorktree:
        """Complete the mark creating database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            current = await self.session_git_worktree_repository.mark_creating(
                session,
                worktree_id=current.id,
            )
            return current

    async def mark_ready(
        self,
        *,
        execution: ActionExecution,
        current: SessionGitWorktree,
        base_commit: str,
        worktree_path: str,
        branch_name: str,
    ) -> None:
        """Complete the mark ready database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.session_git_worktree_repository.mark_ready(
                session,
                worktree_id=current.id,
                base_commit=base_commit,
                worktree_path=worktree_path,
                branch_name=branch_name,
                ready_at=datetime.now(UTC),
            )

    async def try_choose_target(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        runtime_id: str,
        worktree_path: str,
        branch_name: str,
        generated_branch: bool,
    ) -> TargetChoice:
        """Complete the try choose target database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
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
                    f"Git branch already exists in a managed allocation: {branch_name}"
                )
            if not path_exists and not branch_exists and not claim_exists:
                chosen = await self.session_git_worktree_repository.update_target(
                    session,
                    worktree_id=allocation.id,
                    worktree_path=worktree_path,
                    branch_name=branch_name,
                )
                return TargetChoice(
                    allocation=chosen,
                    path_exists=path_exists,
                    branch_exists=branch_exists,
                    claim_exists=claim_exists,
                )

            return TargetChoice(
                allocation=None,
                path_exists=path_exists,
                branch_exists=branch_exists,
                claim_exists=claim_exists,
            )

    async def register_project(
        self,
        *,
        execution: ActionExecution,
        agent_id: str,
        allocation: SessionGitWorktree,
        target: SessionWorkingFolderTarget,
        worktree_path: str,
    ) -> SessionWorkspaceProject:
        """Complete the register project database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=allocation.session_id,
                target=target,
                bind_pending=False,
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

    async def catalog_project(
        self,
        *,
        execution: ActionExecution,
        agent_id: str,
        allocation: SessionGitWorktree,
        target: SessionWorkingFolderTarget,
        worktree_path: str,
    ) -> None:
        """Complete the catalog project database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
            await self.binding_repository.resolve_authority_in_session(
                session,
                agent_id=agent_id,
                session_id=allocation.session_id,
                target=target,
                bind_pending=False,
            )
            await self.agent_project_catalog_repository.upsert_entry(
                session,
                agent_id=agent_id,
                path=worktree_path,
            )

    async def append_action_event(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        kind: ActionExecutionEventKind,
        step_key: str | None,
        command_argv: list[str] | None,
        content: str | None,
        exit_code: int | None,
    ) -> ActionExecutionEvent:
        """Complete the append action event database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
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
            return event

    async def read_action_projection(
        self, *, execution: ActionExecution
    ) -> ActionExecutionProjection:
        """Complete the read action projection database operation."""
        async with self.read_session_manager() as session:
            repository = self.action_execution_repository
            projection = await repository.get_projection_by_mailbox_item_id(
                session,
                mailbox_item_id=execution.mailbox_item_id,
            )
            if projection is None:
                raise RuntimeError("ActionExecution projection is missing")
            return projection

    async def commit_terminal_handoff(
        self,
        *,
        execution: ActionExecution,
        actor_generation: int | None,
        allocation: SessionGitWorktree | None,
        external_id: str,
        continuation_idempotency_key: str,
        status: ActionExecutionStatus,
        failure_summary: str | None,
        cancellation_summary: str | None,
        predecessor_run_id: str | None,
        terminal_at: datetime,
    ) -> Event:
        """Complete the commit terminal handoff database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
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
                            requested_enabled_execution_options=[],
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
            return event

    async def read_action_allocation(
        self, *, execution: ActionExecution
    ) -> SessionGitWorktree | None:
        """Complete the read action allocation database operation."""
        async with self.read_session_manager() as session:
            allocation = (
                await self.session_git_worktree_repository.get_by_action_execution_id(
                    session,
                    action_execution_id=execution.id,
                )
            )
            return allocation

    async def list_live_actions(self, *, session_id: str) -> list[ActionExecution]:
        """Complete the list live actions database operation."""
        async with self.read_session_manager() as session:
            executions = await self.action_execution_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            return executions

    async def record_removal_projection_failure(
        self,
        *,
        execution: ActionExecution,
        allocation: SessionGitWorktree,
        claim_state: GitWorktreePathClaimState,
        reason: str,
        worktree_path: str,
    ) -> None:
        """Complete the record removal projection failure database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation,
                ),
            )
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

    async def compensate_created_project(
        self, *, execution: ActionExecution, actor_generation: int | None
    ) -> CompensatedProject | None:
        """Complete the compensate created project database operation."""
        async with self.session_manager() as session:
            await fence_owned_session_mutation(
                session,
                SessionExecutionOwner(
                    session_id=execution.session_id,
                    owner_generation=execution.owner_generation
                    if actor_generation is None
                    else actor_generation,
                ),
            )
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
            return CompensatedProject(agent_session=agent_session, project=project)

    async def request_manual_cleanup(
        self,
        *,
        agent_id: str,
        session_id: str,
        user_id: str,
        session_workspace_project_id: str | None,
    ) -> CleanupDecision:
        """Complete the request manual cleanup database operation."""
        async with self.session_manager() as session:
            agent_session = await self.agent_session_repository.get_by_id(
                session,
                session_id,
            )
            if agent_session is None or agent_session.agent_id != agent_id:
                return CleanupDecision.SESSION_NOT_FOUND
            if agent_session.session_kind is AgentSessionKind.SUBAGENT:
                return CleanupDecision.SUBAGENT_READ_ONLY
            workspace_user = (
                await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=agent_session.workspace_id,
                    user_id=user_id,
                )
            )
            if workspace_user is None:
                return CleanupDecision.ACCESS_DENIED
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            if not allocations:
                return CleanupDecision.NOT_FOUND
            if session_workspace_project_id is not None:
                allocations = [
                    allocation
                    for allocation in allocations
                    if allocation.session_workspace_project_id
                    == session_workspace_project_id
                ]
                if not allocations:
                    return CleanupDecision.NOT_FOUND
            cleanup_targets = [
                allocation
                for allocation in allocations
                if allocation.status is not SessionGitWorktreeStatus.CLEANED
            ]
            if not cleanup_targets:
                return CleanupDecision.NO_CLEANUP
            for allocation in cleanup_targets:
                await self.session_git_worktree_repository.mark_cleanup_pending(
                    session,
                    worktree_id=allocation.id,
                )
            return CleanupDecision.CLEANUP_PENDING

    async def list_allocations(self, *, session_id: str) -> list[SessionGitWorktree]:
        """Complete the list allocations database operation."""
        async with self.read_session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=session_id,
            )
            return allocations

    async def prepare_archive_cleanup(
        self, *, root_session_id: str, allowed_session_ids: set[str]
    ) -> ArchiveCleanupPreparation:
        """Complete the prepare archive cleanup database operation."""
        async with self.session_manager() as session:
            allocations = await self.session_git_worktree_repository.list_by_session_id(
                session,
                session_id=root_session_id,
            )
            eligible_allocations: list[SessionGitWorktree] = []
            rejected_allocations: list[SessionGitWorktree] = []
            for allocation in allocations:
                creator_session_id = allocation.created_by_agent_session_id
                if creator_session_id not in allowed_session_ids:
                    rejected_allocations.append(allocation)
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
            return ArchiveCleanupPreparation(
                allocations=allocations,
                eligible_allocations=eligible_allocations,
                rejected_allocations=rejected_allocations,
            )

    async def finish_archive_removal(
        self,
        *,
        agent_id: str,
        allocation: SessionGitWorktree,
        cleaned_at: datetime,
        cleanup_summary: str,
    ) -> SessionGitWorktree:
        """Complete the finish archive removal database operation."""
        async with self.session_manager() as session:
            await self.agent_project_catalog_repository.delete_entry_by_path(
                session,
                agent_id=agent_id,
                path=allocation.worktree_path,
            )
            cleaned = await self.session_git_worktree_repository.mark_cleaned(
                session,
                worktree_id=allocation.id,
                cleanup_summary=cleanup_summary,
                cleaned_at=cleaned_at,
            )
            if allocation.session_workspace_project_id is not None:
                await self.session_workspace_project_repository.delete_project(
                    session,
                    allocation.session_workspace_project_id,
                    session_id=allocation.session_id,
                )
            return cleaned

    async def mark_cleanup_failed(
        self, *, worktree_id: str, reason: str, failed_at: datetime
    ) -> None:
        """Complete the mark cleanup failed database operation."""
        async with self.session_manager() as session:
            await self.session_git_worktree_repository.mark_cleanup_failed(
                session,
                worktree_id=worktree_id,
                cleanup_summary=reason,
                failed_at=failed_at,
            )

    async def _create_and_link_workspace_project(
        self,
        session: WriteSession,
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

    async def _ensure_agent_worktree_allocation(
        self,
        session: WriteSession,
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

    async def _ensure_action_worktree_allocation(
        self,
        session: WriteSession,
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

    async def mark_cleanup_pending(self, *, session_id: str) -> bool:
        """Commit pending cleanup flags for a Session as a completed operation."""
        async with self.session_manager() as session:
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
                return False
            for allocation in cleanup_targets:
                await self.session_git_worktree_repository.mark_cleanup_pending(
                    session,
                    worktree_id=allocation.id,
                )
            return True
