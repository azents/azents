"""Completed database operations for Worker Session lifecycle authority."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.agent_session_data import AgentSession
from azents.core.enums import (
    AgentRunParentResultDeliveryState,
    AgentRunPhase,
    AgentRunStatus,
    MailboxSchedulingMode,
)
from azents.core.inference_profile import RequestedInferenceProfile
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import AgentRunState
from azents.engine.run.failure import FailedRunRetryState
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.hierarchy_contention import retry_hierarchy_operation
from azents.repos.mailbox import MailboxRepository
from azents.repos.session_execution.data import PendingCommandSnapshot
from azents.repos.session_execution.ownership import (
    fence_owned_session_mutation,
    validate_session_execution_owner,
)
from azents.repos.terminal_finalization import TerminalRunFinalizationRepository
from azents.repos.worker_session_data import (
    CanonicalExecutionWorkDriftError,
    WorkerIdleDisposition,
    WorkerIdleTransition,
)


@dataclasses.dataclass(frozen=True)
class WorkerSessionOperationRepository:
    """Own Worker descriptions and exact Session critical mutation fences."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    agent_run_repository: Annotated[AgentRunRepository, Depends(AgentRunRepository)]
    mailbox_item_repository: Annotated[MailboxRepository, Depends(MailboxRepository)]
    terminal_finalization_repository: Annotated[
        TerminalRunFinalizationRepository, Depends(TerminalRunFinalizationRepository)
    ]

    async def _lock_owned_session(
        self,
        session: WriteSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> AgentSession:
        """Fence critical writes with the existing missing/stale errors."""
        return await fence_owned_session_mutation(
            session, SessionExecutionOwner(session_id, owner_generation)
        )

    async def assert_owner_generation_in_session(
        self,
        session: WriteSession,
        *,
        session_id: str,
        owner_generation: int,
    ) -> None:
        """Guard one composing transaction without nesting a completed operation."""
        await self._lock_owned_session(
            session,
            session_id=session_id,
            owner_generation=owner_generation,
        )

    async def assert_current_owner_generation(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> None:
        """Complete the owner check before any application external side effect."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )

    async def claim_owner_generation(self, session_id: str) -> int:
        """Claim the next generation with the existing explicit commit boundary."""
        async with self.session_manager() as session:
            generation = await self.agent_session_repository.claim_owner_generation(
                session, session_id
            )
            await session.write_session.commit()
            return generation

    async def parent_result_activity_session_id(self, run_id: str) -> str | None:
        """Resolve an enqueued result's parent routing ID in one completed read."""
        async with self.session_manager() as session:
            run = await self.agent_run_repository.get_by_id(session, run_id)
            if (
                run is None
                or run.parent_result_delivery_state
                is not AgentRunParentResultDeliveryState.ENQUEUED
            ):
                return None
            source = (
                await self.agent_session_repository.get_session_agent_by_session_id(
                    session, run.session_id
                )
            )
            if source is None or source.parent_session_agent_id is None:
                return None
            parent = await self.agent_session_repository.get_session_agent_by_id(
                session, source.parent_session_agent_id
            )
            return parent.agent_session_id if parent is not None else None

    async def mark_session_running(self, session_id: str) -> None:
        """Apply the existing recovery running/heartbeat transition atomically."""
        async with self.session_manager() as session:
            await self.agent_session_repository.mark_running(session, session_id)

    async def mark_session_idle(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> WorkerIdleTransition:
        """Keep command, wake-producing input, active Run and idle mutation atomic."""
        async with self.session_manager() as session:
            current = await self._lock_owned_session(
                session,
                session_id=session_id,
                owner_generation=owner_generation,
            )
            if current.pending_command_id is not None:
                return WorkerIdleTransition(
                    disposition=WorkerIdleDisposition.COMMAND_PENDING,
                    command_id=current.pending_command_id,
                    run_id=None,
                )
            mailbox = self.mailbox_item_repository
            pending_wake = await mailbox.has_by_session_id_and_scheduling_mode(
                session,
                session_id=session_id,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
            )
            if pending_wake:
                return WorkerIdleTransition(
                    disposition=WorkerIdleDisposition.WAKE_INPUT_PENDING,
                    command_id=None,
                    run_id=None,
                )
            active_run = await self.agent_run_repository.get_active_by_session_id(
                session, session_id=session_id
            )
            if active_run is not None:
                return WorkerIdleTransition(
                    disposition=WorkerIdleDisposition.RUN_ACTIVE,
                    command_id=None,
                    run_id=active_run.id,
                )
            await self.agent_session_repository.mark_idle(session, session_id)
            return WorkerIdleTransition(
                disposition=WorkerIdleDisposition.IDLE,
                command_id=None,
                run_id=None,
            )

    async def validate_pending_command(
        self,
        session_id: str,
        *,
        owner_generation: int,
        command: PendingCommandSnapshot,
    ) -> None:
        """Compare the same five command fields against the observed current owner."""
        async with self.session_manager() as session:
            current_session = await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )
            current = (
                current_session.pending_command_id,
                current_session.pending_command_name,
                current_session.pending_command_payload,
                current_session.pending_command_requester_user_id,
                current_session.pending_command_created_at,
            )
            expected = (
                command.id,
                command.name,
                command.payload,
                command.requester_user_id,
                command.created_at,
            )
            if current != expected:
                raise CanonicalExecutionWorkDriftError(
                    "Canonical pending command changed before execution"
                )

    async def clear_pending_command(
        self,
        session_id: str,
        *,
        owner_generation: int,
        command_id: str,
    ) -> None:
        """Clear only the exact command identity while the Worker remains current."""
        async with self.session_manager() as session:
            current = await self._lock_owned_session(
                session,
                session_id=session_id,
                owner_generation=owner_generation,
            )
            if current.pending_command_id != command_id:
                raise CanonicalExecutionWorkDriftError(
                    "Canonical pending command changed before cleanup"
                )
            await self.agent_session_repository.clear_pending_command(
                session,
                session_id=session_id,
                command_id=command_id,
            )

    async def has_pending_command(self, session_id: str) -> bool:
        """Return the existing runner pending-command predicate after DB closure."""
        async with self.session_manager() as session:
            command = (
                await self.agent_session_repository.get_pending_command_by_session_id(
                    session, session_id
                )
            )
            return command is not None

    async def has_active_agent_run(self, session_id: str) -> bool:
        """Read the existing pending-or-running Run predicate without claiming it."""
        async with self.session_manager() as session:
            return (
                await self.agent_run_repository.get_active_by_session_id(
                    session, session_id=session_id
                )
                is not None
            )

    async def get_pending_idle_continuation_run_id(self, session_id: str) -> str | None:
        """Read the durable idle continuation ID with the existing missing error."""
        async with self.session_manager() as session:
            current = await self.agent_session_repository.get_by_id(session, session_id)
        if current is None:
            raise ValueError("AgentSession not found")
        return current.pending_idle_continuation_run_id

    async def heartbeat_session(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Commit harmless heartbeat metadata before broker renewal."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )
            await self.agent_session_repository.heartbeat_running(session, session_id)

    async def has_stop_request(self, session_id: str) -> bool:
        """Read the existing durable Stop intent without new authority policy."""
        async with self.session_manager() as session:
            return await self.agent_session_repository.has_stop_request(
                session, session_id
            )

    async def get_running_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> AgentRunState | None:
        """Read only the current activated Run under the Worker guard."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )
            return await self.agent_run_repository.get_running_by_session_id(
                session, session_id=session_id
            )

    async def get_active_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> AgentRunState | None:
        """Read the newest pending/running Run without claiming it."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )
            return await self.agent_run_repository.get_active_by_session_id(
                session, session_id=session_id
            )

    async def claim_recoverable_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
    ) -> AgentRunState | None:
        """Prefer running work, otherwise retain the pending claim/commit group."""
        async with self.session_manager() as session:
            await validate_session_execution_owner(
                session, SessionExecutionOwner(session_id, owner_generation)
            )
            running = await self.agent_run_repository.get_running_by_session_id(
                session, session_id=session_id
            )
            if running is not None:
                return running
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            running = await self.agent_run_repository.get_running_by_session_id(
                session, session_id=session_id
            )
            if running is not None:
                return running
            pending = await self.agent_run_repository.claim_pending_by_session_id(
                session, session_id=session_id
            )
            await session.write_session.commit()
            return pending

    async def create_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        input_event_ids: Sequence[str],
    ) -> AgentRunState:
        """Reject work drift and atomically commit pending Run/input association."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            running = await self.agent_run_repository.get_running_by_session_id(
                session, session_id=session_id
            )
            pending = await self.agent_run_repository.claim_pending_by_session_id(
                session, session_id=session_id
            )
            if running is not None or pending is not None:
                raise CanonicalExecutionWorkDriftError(
                    "Recoverable AgentRun appeared after canonical snapshot"
                )
            pending = await self.agent_run_repository.create_pending(
                session,
                session_id=session_id,
                parent_agent_run_id=None,
                scheduled_task_cycle_id=None,
            )
            await self.agent_run_repository.associate_input_events(
                session, run_id=pending.id, event_ids=input_event_ids
            )
            await session.write_session.commit()
            return pending

    async def claim_lifecycle_start(
        self,
        session_id: str,
        *,
        owner_generation: int,
        now: datetime.datetime,
    ) -> bool:
        """Claim Session-start hooks under the same generation guard."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            return await self.agent_session_repository.claim_lifecycle_start(
                session, session_id, now=now
            )

    @retry_hierarchy_operation
    async def cancel_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> AgentRunState:
        """Cancel only a Session-bound PENDING Run with parent finalization atomic."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.get_by_id(session, run_id)
            if (
                run is None
                or run.session_id != session_id
                or run.status != AgentRunStatus.PENDING
            ):
                raise ValueError("Pending AgentRun not found in session")
            cancelled = await self.agent_run_repository.mark_terminal(
                session,
                run_id,
                AgentRunStatus.CANCELLED,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await self.terminal_finalization_repository.finalize_run_in_session(
                session, run_id=run_id
            )
            await session.write_session.commit()
            return cancelled

    async def complete_bridge_predecessor_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> AgentRunStatus:
        """Preserve PENDING/RUNNING bridge terminal status and parent suppression."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.lock_by_id(session, run_id)
            if run is None or run.session_id != session_id:
                raise ValueError("AgentRun not found in session")
            match run.status:
                case AgentRunStatus.PENDING:
                    terminal_status = AgentRunStatus.CANCELLED
                case AgentRunStatus.RUNNING:
                    terminal_status = AgentRunStatus.COMPLETED
                case _:
                    raise ValueError("Bridge predecessor AgentRun is not active")
            terminal_at = datetime.datetime.now(datetime.UTC)
            await self.agent_run_repository.mark_terminal(
                session, run_id, terminal_status, ended_at=terminal_at
            )
            await self.agent_run_repository.mark_parent_result_suppressed(
                session, run_id=run_id, finalized_at=terminal_at
            )
            await session.write_session.commit()
            return terminal_status

    async def activate_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        initial_phase: AgentRunPhase,
        requested_profile: RequestedInferenceProfile,
    ) -> AgentRunState:
        """Commit selected profile, Session mismatch validation and phase together."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.activate_pending(
                session,
                run_id=run_id,
                activated_at=datetime.datetime.now(datetime.UTC),
                requested_model_target_label=requested_profile.model_target_label,
                requested_reasoning_effort=requested_profile.reasoning_effort,
                requested_enabled_execution_options=requested_profile.enabled_execution_options,
            )
            if run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            run = await self.agent_run_repository.update_phase(
                session, run_id, initial_phase
            )
            await session.write_session.commit()
            return run

    @retry_hierarchy_operation
    async def mark_session_agent_runs_terminal(
        self,
        session_id: str,
        *,
        owner_generation: int,
        status: AgentRunStatus,
    ) -> list[str]:
        """Keep bulk terminal mutation and parent finalization in one transaction."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            runs = await self.agent_run_repository.mark_session_running_terminal(
                session,
                session_id=session_id,
                status=status,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            transitioned = [run.id for run in runs]
            await self.terminal_finalization_repository.finalize_runs_in_session(
                session, run_ids=transitioned
            )
            return transitioned

    @retry_hierarchy_operation
    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Retain conditional transition and mismatched Session rejection atomically."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.get_by_id(session, run_id)
            if run is not None and run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            await self.agent_run_repository.mark_terminal_if_running(
                session,
                run_id,
                status,
                ended_at=datetime.datetime.now(datetime.UTC),
            )
            await self.terminal_finalization_repository.finalize_run_in_session(
                session, run_id=run_id
            )

    @retry_hierarchy_operation
    async def mark_agent_run_stopped_for_user_stop(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
    ) -> None:
        """Converge interruption to User Stop and finalize parent authority together."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.get_by_id(session, run_id)
            if run is not None and run.session_id != session_id:
                raise ValueError("AgentRun session mismatch")
            await self.agent_run_repository.mark_stopped_for_user_stop(
                session, run_id, ended_at=datetime.datetime.now(datetime.UTC)
            )
            await self.terminal_finalization_repository.finalize_run_in_session(
                session, run_id=run_id
            )

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Validate exact Run existence and Session before the retry-state write."""
        async with self.session_manager() as session:
            await self.assert_owner_generation_in_session(
                session, session_id=session_id, owner_generation=owner_generation
            )
            run = await self.agent_run_repository.get_by_id(session, run_id)
            if run is None or run.session_id != session_id:
                raise ValueError("AgentRun not found in session")
            await self.agent_run_repository.update_retry_state(
                session, run_id, retry_state
            )
