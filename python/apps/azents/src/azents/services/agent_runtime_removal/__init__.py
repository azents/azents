"""Durable Agent Runtime removal confirmation and coordinator."""

import asyncio
import dataclasses
import datetime
import logging
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.broker.deps import get_broker
from azents.broker.types import SessionStopSignal
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentRuntimeRemovalStage,
    AgentRuntimeRemovalStatus,
    RuntimeTerminalDeleteAcknowledgementKind,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent.data import Agent
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.agent_runtime_removal import AgentRuntimeRemovalRepository
from azents.repos.agent_runtime_removal.data import AgentRuntimeRemovalOperation
from azents.repos.agent_runtime_removal_finalizer import (
    AgentRuntimeRemovalFinalizerRepository,
)
from azents.repos.agent_runtime_removal_scope import (
    AgentRuntimeRemovalScopeRepository,
)
from azents.repos.agent_runtime_removal_scope.data import AgentRuntimeRemovalImpact

from .data import (
    AgentRuntimeRemovalConfirmationRequest,
    AgentRuntimeRemovalConfirmationResult,
    AgentRuntimeRemovalUnavailable,
)

_DESTRUCTIVE_SCOPE_VERSION = 1
_CLEANUP_BATCH_SIZE = 100
_LEASE_DURATION = datetime.timedelta(minutes=15)
_RETRY_DELAY = datetime.timedelta(seconds=5)
_MAX_RETRY_DELAY = datetime.timedelta(minutes=30)
_OPERATION_LIMIT = 100
_DEADLINE_SAFETY_MARGIN = datetime.timedelta(seconds=30)

logger = logging.getLogger(__name__)


class AgentRuntimeRemovalBroker(Protocol):
    """Best-effort Session stop wake-up transport."""

    async def send_message(self, signal: SessionStopSignal) -> None:
        """Send one Session stop wake-up."""
        ...


@dataclasses.dataclass(frozen=True)
class AgentRuntimeRemovalCoordinatorSummary:
    """Result of one bounded Runtime removal scheduler pass."""

    claimed_count: int
    completed_count: int
    retry_scheduled_count: int
    deadline_reached: bool
    limit_reached: bool


@dataclasses.dataclass(frozen=True)
class _CleanupProgress:
    """Reloaded operation and completion state after one cleanup page."""

    operation: AgentRuntimeRemovalOperation
    completed: bool


class AgentRuntimeRemovalService:
    """Confirm and advance irreversible Agent Runtime removal."""

    def __init__(
        self,
        session_manager: Annotated[
            SessionManager[AsyncSession], Depends(get_session_manager)
        ],
        agent_repository: Annotated[AgentRepository, Depends(AgentRepository)],
        runtime_repository: Annotated[
            AgentRuntimeRepository, Depends(AgentRuntimeRepository)
        ],
        removal_repository: Annotated[
            AgentRuntimeRemovalRepository,
            Depends(AgentRuntimeRemovalRepository),
        ],
        scope_repository: Annotated[
            AgentRuntimeRemovalScopeRepository,
            Depends(AgentRuntimeRemovalScopeRepository),
        ],
        finalizer_repository: Annotated[
            AgentRuntimeRemovalFinalizerRepository,
            Depends(AgentRuntimeRemovalFinalizerRepository),
        ],
        broker: Annotated[AgentRuntimeRemovalBroker, Depends(get_broker)],
    ) -> None:
        """Initialize Runtime removal dependencies."""
        self.session_manager = session_manager
        self.agent_repository = agent_repository
        self.runtime_repository = runtime_repository
        self.removal_repository = removal_repository
        self.scope_repository = scope_repository
        self.finalizer_repository = finalizer_repository
        self.broker = broker

    async def confirm(
        self,
        request: AgentRuntimeRemovalConfirmationRequest,
    ) -> AgentRuntimeRemovalConfirmationResult:
        """Commit the irreversible Agent work fence and durable operation."""
        async with self.session_manager() as session:
            agent = await self.agent_repository.lock_by_id(session, request.agent_id)
            if agent is None or agent.workspace_id != request.workspace_id:
                raise AgentRuntimeRemovalUnavailable(
                    code="agent_not_found",
                    message="Agent is unavailable for Runtime removal.",
                )
            active = await self.removal_repository.get_active_by_agent_id(
                session,
                request.agent_id,
            )
            if active is not None:
                self._require_replay(
                    request=request,
                    operation=active,
                    agent=agent,
                )
                return AgentRuntimeRemovalConfirmationResult(
                    operation=active,
                    impact=self._impact_from_operation(active),
                    replayed=True,
                )
            if agent.runtime_capability is not AgentRuntimeCapability.MANAGED:
                raise AgentRuntimeRemovalUnavailable(
                    code="runtime_remove_not_available",
                    message="Runtime removal is available only for managed Agents.",
                )
            if (
                agent.runtime_capability_version != request.expected_capability_version
                or agent.runtime_profile_selection_version
                != request.expected_runtime_profile_selection_version
            ):
                raise AgentRuntimeRemovalUnavailable(
                    code="runtime_capability_version_conflict",
                    message="Agent Runtime capability changed concurrently.",
                )
            historical = await self.removal_repository.get_by_agent_idempotency_key(
                session,
                agent_id=request.agent_id,
                idempotency_key=request.idempotency_key,
            )
            if historical is not None:
                raise AgentRuntimeRemovalUnavailable(
                    code="runtime_remove_conflict",
                    message="Runtime removal idempotency key was already used.",
                )

            impact = await self.scope_repository.get_impact(
                session,
                agent_id=agent.id,
            )
            runtime = await self.runtime_repository.get_by_agent_id_for_update(
                session,
                agent.id,
            )
            updated_agent = (
                await self.agent_repository.compare_and_set_runtime_capability(
                    session,
                    agent_id=agent.id,
                    expected_capability=AgentRuntimeCapability.MANAGED,
                    expected_capability_version=request.expected_capability_version,
                    expected_runtime_profile_selection_version=(
                        request.expected_runtime_profile_selection_version
                    ),
                    capability=AgentRuntimeCapability.REMOVING,
                    runtime_profile_id=None,
                    shell_enabled=False,
                )
            )
            if updated_agent is None:
                raise AgentRuntimeRemovalUnavailable(
                    code="runtime_capability_version_conflict",
                    message="Agent Runtime capability changed concurrently.",
                )
            created = await self.removal_repository.create_or_get_active(
                session,
                agent_id=agent.id,
                workspace_id=agent.workspace_id,
                requested_by_workspace_user_id=(request.requested_by_workspace_user_id),
                idempotency_key=request.idempotency_key,
                expected_capability_version=request.expected_capability_version,
                committed_capability_version=(updated_agent.runtime_capability_version),
                agent_runtime_id=None if runtime is None else runtime.id,
                confirmed_at=datetime.datetime.now(datetime.UTC),
                destructive_scope_version=_DESTRUCTIVE_SCOPE_VERSION,
                active_root_session_count=impact.active_root_session_count,
                active_subagent_count=impact.active_subagent_count,
                active_run_count=impact.active_run_count,
                queued_runtime_action_count=impact.queued_runtime_action_count,
            )
            if not created.idempotency_match:
                raise AgentRuntimeRemovalUnavailable(
                    code="runtime_remove_conflict",
                    message="Another Runtime removal operation is already active.",
                )
            return AgentRuntimeRemovalConfirmationResult(
                operation=created.operation,
                impact=impact,
                replayed=False,
            )

    async def coordinate_once(
        self,
        *,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> AgentRuntimeRemovalCoordinatorSummary:
        """Claim and advance a bounded set of durable removal operations."""
        claimed_count = 0
        completed_count = 0
        retry_scheduled_count = 0
        deadline_reached = False
        for _ in range(_OPERATION_LIMIT):
            now = datetime.datetime.now(datetime.UTC)
            if now + _DEADLINE_SAFETY_MARGIN >= deadline:
                deadline_reached = True
                break
            async with self.session_manager() as session:
                operation = await self.removal_repository.claim_due(
                    session,
                    now=now,
                    lease_owner=lease_owner,
                    lease_until=now + _LEASE_DURATION,
                )
            if operation is None:
                break
            claimed_count += 1
            try:
                completed = await self._advance(
                    operation=operation,
                    lease_owner=lease_owner,
                    deadline=deadline,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._retry(
                    operation=operation,
                    lease_owner=lease_owner,
                    error_kind=type(exc).__name__,
                    error_summary=str(exc) or type(exc).__name__,
                )
                retry_scheduled_count += 1
                logger.exception(
                    "Agent Runtime removal failed; retry scheduled",
                    extra={
                        "agent_runtime_removal_operation_id": operation.id,
                        "agent_id": operation.agent_id,
                        "stage": operation.stage.value,
                        "attempt_count": operation.attempt_count,
                    },
                )
                continue
            completed_count += int(completed)
            retry_scheduled_count += int(not completed)
        return AgentRuntimeRemovalCoordinatorSummary(
            claimed_count=claimed_count,
            completed_count=completed_count,
            retry_scheduled_count=retry_scheduled_count,
            deadline_reached=deadline_reached,
            limit_reached=claimed_count == _OPERATION_LIMIT,
        )

    async def _advance(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
        deadline: datetime.datetime,
    ) -> bool:
        """Advance one operation until completion or an external wait."""
        current = operation
        while datetime.datetime.now(datetime.UTC) + _DEADLINE_SAFETY_MARGIN < deadline:
            match current.stage:
                case AgentRuntimeRemovalStage.FENCING:
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        stage=AgentRuntimeRemovalStage.INTERRUPTING_WORK,
                    )
                case AgentRuntimeRemovalStage.INTERRUPTING_WORK:
                    if await self._interrupt_work(
                        operation=current,
                        lease_owner=lease_owner,
                    ):
                        current = await self._set_stage(
                            operation_id=current.id,
                            lease_owner=lease_owner,
                            stage=AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE,
                        )
                    else:
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="active_work_pending",
                            error_summary="Agent work is still stopping.",
                        )
                        return False
                case AgentRuntimeRemovalStage.CLEANING_PRODUCT_STATE:
                    progress = await self._cleanup_product_state(
                        operation=current,
                        lease_owner=lease_owner,
                    )
                    current = progress.operation
                    if not progress.completed:
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="product_cleanup_pending",
                            error_summary=(
                                "Runtime-owned product cleanup is continuing."
                            ),
                        )
                        return False
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        stage=AgentRuntimeRemovalStage.DELETING_RUNTIME,
                    )
                case AgentRuntimeRemovalStage.DELETING_RUNTIME:
                    if not await self._delete_runtime(
                        operation=current,
                        lease_owner=lease_owner,
                    ):
                        await self._retry(
                            operation=current,
                            lease_owner=lease_owner,
                            error_kind="physical_deletion_pending",
                            error_summary=(
                                "Authoritative Runtime deletion acknowledgement "
                                "is pending."
                            ),
                        )
                        return False
                    current = await self._set_stage(
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        stage=AgentRuntimeRemovalStage.FINALIZING,
                    )
                case AgentRuntimeRemovalStage.FINALIZING:
                    async with self.session_manager() as session:
                        completed = await self.finalizer_repository.finalize(
                            session,
                            operation_id=current.id,
                            lease_owner=lease_owner,
                            now=datetime.datetime.now(datetime.UTC),
                        )
                    if not completed:
                        raise RuntimeError(
                            "Agent Runtime removal lease was lost before finalization"
                        )
                    return True
                case AgentRuntimeRemovalStage.COMPLETED:
                    return True
        await self._retry(
            operation=current,
            lease_owner=lease_owner,
            error_kind="scheduler_deadline",
            error_summary="Runtime removal yielded before the scheduler deadline.",
        )
        return False

    async def _interrupt_work(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> bool:
        """Record durable stop fences and send best-effort wake signals."""
        async with self.session_manager() as session:
            await self._require_owned(
                session,
                operation_id=operation.id,
                lease_owner=lease_owner,
            )
            interrupted = await self.scope_repository.interrupt_work(
                session,
                agent_id=operation.agent_id,
                operation_id=operation.id,
                now=datetime.datetime.now(datetime.UTC),
            )
        for session_id in interrupted.stop_session_ids:
            try:
                await self.broker.send_message(SessionStopSignal(session_id=session_id))
            except Exception:
                logger.exception(
                    "Agent Runtime removal stop wake-up failed",
                    extra={
                        "agent_runtime_removal_operation_id": operation.id,
                        "agent_id": operation.agent_id,
                    },
                )
        return not interrupted.active_work_remaining

    async def _cleanup_product_state(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> _CleanupProgress:
        """Process and checkpoint one root-context cleanup page."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            current = await self._require_owned(
                session,
                operation_id=operation.id,
                lease_owner=lease_owner,
            )
            batch = await self.scope_repository.cleanup_batch(
                session,
                agent_id=current.agent_id,
                agent_runtime_id=current.agent_runtime_id,
                operation_id=current.id,
                after_context_id=current.cleanup_cursor_context_id,
                limit=_CLEANUP_BATCH_SIZE,
                now=now,
            )
            recorded = await self.removal_repository.record_cleanup_progress(
                session,
                operation_id=current.id,
                lease_owner=lease_owner,
                expected_cursor_context_id=current.cleanup_cursor_context_id,
                cursor_context_id=batch.cursor_context_id,
                scanned_count=batch.scanned_count,
                invalidated_count=batch.invalidated_count,
                completed=batch.completed,
                now=now,
            )
            if not recorded:
                raise RuntimeError("Agent Runtime removal cleanup lease was lost")
            refreshed = await self.removal_repository.get_by_id(session, current.id)
            if refreshed is None:
                raise RuntimeError("Agent Runtime removal operation is missing")
            return _CleanupProgress(
                operation=refreshed,
                completed=batch.completed,
            )

    async def _delete_runtime(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
    ) -> bool:
        """Request and verify exact terminal Runtime deletion."""
        now = datetime.datetime.now(datetime.UTC)
        async with self.session_manager() as session:
            current = await self._require_owned(
                session,
                operation_id=operation.id,
                lease_owner=lease_owner,
            )
            runtime = await self._lock_operation_runtime(session, current)
            if current.physical_deletion_required is None:
                current = await self._record_delete_target(
                    session,
                    operation=current,
                    lease_owner=lease_owner,
                    runtime=runtime,
                    now=now,
                )
                runtime = await self._lock_operation_runtime(session, current)
            if current.physical_deletion_required is False:
                return True
            if runtime is None:
                raise RuntimeError("Removal target AgentRuntime is missing")
            target_generation = current.target_terminal_delete_generation
            if target_generation is None:
                raise RuntimeError("Runtime deletion target generation is missing")
            if (
                runtime.terminal_delete_requested_generation != target_generation
                or runtime.terminal_delete_acknowledged_generation != target_generation
                or runtime.terminal_delete_acknowledgement_kind is None
                or runtime.terminal_delete_acknowledged_at is None
            ):
                return False
            if current.physical_delete_acknowledged_at is None:
                removal_repository = self.removal_repository
                recorded = (
                    await removal_repository.record_physical_delete_acknowledgement(
                        session,
                        operation_id=current.id,
                        lease_owner=lease_owner,
                        acknowledgement_kind=(
                            runtime.terminal_delete_acknowledgement_kind
                        ),
                        acknowledged_at=runtime.terminal_delete_acknowledged_at,
                    )
                )
                if not recorded:
                    raise RuntimeError(
                        "Runtime deletion acknowledgement lease was lost"
                    )
            return True

    async def _record_delete_target(
        self,
        session: AsyncSession,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
        runtime: AgentRuntime | None,
        now: datetime.datetime,
    ) -> AgentRuntimeRemovalOperation:
        """Persist immutable physical-deletion requirement and generation."""
        if runtime is None:
            required = False
            target_generation = None
            requested_at = None
        elif (
            runtime.terminal_delete_acknowledgement_kind
            is RuntimeTerminalDeleteAcknowledgementKind.NO_PHYSICAL_BINDING
            and runtime.terminal_delete_acknowledged_generation
            == runtime.desired_generation
        ):
            required = False
            target_generation = None
            requested_at = None
        elif runtime.terminal_delete_requested_generation is not None:
            required = True
            target_generation = runtime.terminal_delete_requested_generation
            requested_at = now
        elif runtime.runtime_provider_resource_id is None:
            runtime_repository = self.runtime_repository
            runtime = await (
                runtime_repository.request_terminal_delete_without_physical_binding(
                    session, runtime.id
                )
            )
            if runtime is None:
                raise RuntimeError(
                    "AgentRuntime cannot prove absence of a physical binding"
                )
            required = False
            target_generation = None
            requested_at = None
        else:
            runtime = await self.runtime_repository.request_terminal_delete(
                session,
                runtime.id,
            )
            if runtime is None or runtime.terminal_delete_requested_generation is None:
                raise RuntimeError("AgentRuntime terminal deletion request failed")
            required = True
            target_generation = runtime.terminal_delete_requested_generation
            requested_at = now
        recorded = await self.removal_repository.record_physical_delete_target(
            session,
            operation_id=operation.id,
            lease_owner=lease_owner,
            required=required,
            target_generation=target_generation,
            requested_at=requested_at,
            now=now,
        )
        if not recorded:
            raise RuntimeError("Runtime deletion target lease was lost")
        refreshed = await self.removal_repository.get_by_id(session, operation.id)
        if refreshed is None:
            raise RuntimeError("Agent Runtime removal operation is missing")
        return refreshed

    async def _lock_operation_runtime(
        self,
        session: AsyncSession,
        operation: AgentRuntimeRemovalOperation,
    ) -> AgentRuntime | None:
        """Lock and validate the operation's exact logical Runtime."""
        runtime = await self.runtime_repository.get_by_agent_id_for_update(
            session,
            operation.agent_id,
        )
        if operation.agent_runtime_id is None:
            if runtime is not None:
                raise RuntimeError(
                    "AgentRuntime appeared after Runtime removal confirmation"
                )
            return None
        if runtime is None or runtime.id != operation.agent_runtime_id:
            raise RuntimeError("Removal target AgentRuntime changed")
        return runtime

    async def _set_stage(
        self,
        *,
        operation_id: str,
        lease_owner: str,
        stage: AgentRuntimeRemovalStage,
    ) -> AgentRuntimeRemovalOperation:
        """Advance one owned stage and reload its durable evidence."""
        async with self.session_manager() as session:
            now = datetime.datetime.now(datetime.UTC)
            await self._require_owned(
                session,
                operation_id=operation_id,
                lease_owner=lease_owner,
            )
            updated = await self.removal_repository.set_stage(
                session,
                operation_id=operation_id,
                lease_owner=lease_owner,
                stage=stage,
                now=now,
            )
            if not updated:
                raise RuntimeError("Agent Runtime removal lease was lost")
            operation = await self.removal_repository.get_by_id(
                session,
                operation_id,
            )
            if operation is None:
                raise RuntimeError("Agent Runtime removal operation is missing")
            return operation

    async def _require_owned(
        self,
        session: AsyncSession,
        *,
        operation_id: str,
        lease_owner: str,
    ) -> AgentRuntimeRemovalOperation:
        """Lock one running operation and validate lease ownership."""
        operation = await self.removal_repository.lock_by_id(session, operation_id)
        if (
            operation is None
            or operation.status is not AgentRuntimeRemovalStatus.RUNNING
            or operation.lease_owner != lease_owner
        ):
            raise RuntimeError("Agent Runtime removal lease was lost")
        return operation

    async def _retry(
        self,
        *,
        operation: AgentRuntimeRemovalOperation,
        lease_owner: str,
        error_kind: str,
        error_summary: str,
    ) -> None:
        """Release one operation into bounded retry wait."""
        now = datetime.datetime.now(datetime.UTC)
        exponent = min(max(operation.attempt_count - 1, 0), 8)
        delay = min(_RETRY_DELAY * (2**exponent), _MAX_RETRY_DELAY)
        async with self.session_manager() as session:
            await self.removal_repository.mark_retry(
                session,
                operation_id=operation.id,
                lease_owner=lease_owner,
                next_attempt_at=now + delay,
                error_kind=error_kind,
                error_summary=error_summary,
                now=now,
            )

    def _require_replay(
        self,
        *,
        request: AgentRuntimeRemovalConfirmationRequest,
        operation: AgentRuntimeRemovalOperation,
        agent: Agent,
    ) -> None:
        """Reject idempotency reuse or a competing active operation."""
        if (
            operation.idempotency_key != request.idempotency_key
            or operation.workspace_id != request.workspace_id
            or operation.requested_by_workspace_user_id
            != request.requested_by_workspace_user_id
            or operation.expected_capability_version
            != request.expected_capability_version
            or operation.committed_capability_version
            != agent.runtime_capability_version
            or agent.runtime_capability is not AgentRuntimeCapability.REMOVING
            or agent.runtime_profile_selection_version
            != request.expected_runtime_profile_selection_version + 1
            or agent.runtime_profile_id is not None
            or agent.shell_enabled
        ):
            raise AgentRuntimeRemovalUnavailable(
                code="runtime_remove_conflict",
                message="Another Runtime removal operation is already active.",
            )

    @staticmethod
    def _impact_from_operation(
        operation: AgentRuntimeRemovalOperation,
    ) -> AgentRuntimeRemovalImpact:
        """Rebuild the privacy-safe impact stored with an operation."""
        return AgentRuntimeRemovalImpact(
            active_root_session_count=operation.active_root_session_count,
            active_subagent_count=operation.active_subagent_count,
            active_run_count=operation.active_run_count,
            queued_runtime_action_count=operation.queued_runtime_action_count,
        )
