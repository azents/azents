"""Session lifecycle orchestration over completed Worker database operations."""

import dataclasses
import datetime
import logging
from collections.abc import Sequence
from typing import Annotated, assert_never

from azcommon.logging import bind_extra
from fastapi import Depends

from azents.broker.types import SessionBroker, SessionWakeUp
from azents.core.enums import AgentRunPhase, AgentRunStatus
from azents.core.inference_profile import RequestedInferenceProfile
from azents.engine.events.types import AgentRunState
from azents.engine.run.failure import FailedRunRetryState
from azents.repos.session_execution.data import PendingCommandSnapshot
from azents.repos.worker_session import WorkerSessionOperationRepository
from azents.repos.worker_session_data import WorkerIdleDisposition
from azents.worker.deps import get_worker_broker

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SessionLifecycleService:
    """Sequence completed Session operations and existing broker effects."""

    broker: Annotated[SessionBroker, Depends(get_worker_broker)]
    repository: Annotated[
        WorkerSessionOperationRepository, Depends(WorkerSessionOperationRepository)
    ]

    async def claim_owner_generation(self, session_id: str) -> int:
        """Claim the next durable generation after broker ownership acquisition."""
        return await self.repository.claim_owner_generation(session_id)

    async def release_session_lock(self, session_id: str) -> None:
        """Release the existing broker lock."""
        await self.broker.release_session_lock(session_id)

    async def assert_current_owner_generation(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Complete durable ownership validation before an external side effect."""
        await self.repository.assert_current_owner_generation(
            session_id, owner_generation=owner_generation
        )

    async def release_owned_session_lock(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Release broker ownership only after a completed current-owner check."""
        await self.assert_current_owner_generation(
            session_id, owner_generation=owner_generation
        )
        await self.broker.release_session_lock(session_id)

    async def clear_owned_session_activity(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Clear live activity only after durable ownership validation completes."""
        await self.assert_current_owner_generation(
            session_id, owner_generation=owner_generation
        )
        await self.broker.clear_session_activity(
            session_id, owner_generation=owner_generation
        )

    async def send_session_wake_up(self, message: SessionWakeUp) -> None:
        """Send through the existing Session broker path."""
        await self.broker.send_message(message)

    async def notify_parent_result_activity(self, run_id: str) -> None:
        """Publish activity only after resolving committed parent-result routing."""
        parent_session_id = await self.repository.parent_result_activity_session_id(
            run_id
        )
        if parent_session_id is not None:
            await self.broker.notify_mailbox_activity(parent_session_id)

    async def set_session_activity(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        phase: AgentRunPhase | None = None,
    ) -> None:
        """Record existing live activity only after a completed owner check."""
        await self.assert_current_owner_generation(
            session_id, owner_generation=owner_generation
        )
        await self.broker.set_session_activity(
            session_id, owner_generation=owner_generation, run_id=run_id, phase=phase
        )

    async def renew_session_owner_heartbeat(self, session_id: str) -> None:
        """Refresh the existing broker owner heartbeat without database work."""
        await self.broker.renew_session_owner_heartbeat(session_id)

    async def mark_session_running(self, session_id: str) -> None:
        """Complete the durable running/heartbeat transition."""
        await self.repository.mark_session_running(session_id)

    async def mark_session_idle(
        self, session_id: str, *, owner_generation: int
    ) -> bool:
        """Apply true-idle predicates atomically and log their detached decision."""
        transition = await self.repository.mark_session_idle(
            session_id, owner_generation=owner_generation
        )
        operation_logger = bind_extra(logger, {"session_id": session_id})
        match transition.disposition:
            case WorkerIdleDisposition.IDLE:
                return True
            case WorkerIdleDisposition.COMMAND_PENDING:
                operation_logger.info(
                    "Skipped session idle transition because a command is pending",
                    extra={"command_id": transition.command_id},
                )
            case WorkerIdleDisposition.WAKE_INPUT_PENDING:
                operation_logger.info(
                    "Skipped session idle transition because "
                    "wake-producing input is pending",
                )
            case WorkerIdleDisposition.RUN_ACTIVE:
                operation_logger.info(
                    "Skipped session idle transition because an AgentRun is active",
                    extra={"run_id": transition.run_id},
                )
            case _ as unreachable:
                assert_never(unreachable)
        return False

    async def validate_pending_command(
        self, session_id: str, *, owner_generation: int, command: PendingCommandSnapshot
    ) -> None:
        """Revalidate the exact canonical command through a completed operation."""
        await self.repository.validate_pending_command(
            session_id, owner_generation=owner_generation, command=command
        )

    async def clear_pending_command(
        self, session_id: str, *, owner_generation: int, command_id: str
    ) -> None:
        """Complete exact command cleanup under the durable Worker fence."""
        await self.repository.clear_pending_command(
            session_id, owner_generation=owner_generation, command_id=command_id
        )

    async def has_active_agent_run(self, session_id: str) -> bool:
        """Read the existing active Run predicate without retaining a session."""
        return await self.repository.has_active_agent_run(session_id)

    async def get_pending_idle_continuation_run_id(self, session_id: str) -> str | None:
        """Return the detached completed Run awaiting true-idle evaluation."""
        return await self.repository.get_pending_idle_continuation_run_id(session_id)

    async def has_pending_idle_continuation(self, session_id: str) -> bool:
        """Return the existing pending idle-continuation predicate."""
        return (await self.get_pending_idle_continuation_run_id(session_id)) is not None

    async def heartbeat_session(
        self, session_id: str, *, owner_generation: int
    ) -> None:
        """Commit the DB heartbeat before renewing the broker owner lease."""
        await self.repository.heartbeat_session(
            session_id, owner_generation=owner_generation
        )
        await self.broker.renew_session_ttl(session_id)

    async def has_stop_request(self, session_id: str) -> bool:
        """Return the completed durable Stop-intent read."""
        return await self.repository.has_stop_request(session_id)

    async def get_running_agent_run(
        self, session_id: str, *, owner_generation: int
    ) -> AgentRunState | None:
        """Read activated work without claiming pending work."""
        return await self.repository.get_running_agent_run(
            session_id, owner_generation=owner_generation
        )

    async def get_active_agent_run(
        self, session_id: str, *, owner_generation: int
    ) -> AgentRunState | None:
        """Read the newest pending/running Run under the current Worker fence."""
        return await self.repository.get_active_agent_run(
            session_id, owner_generation=owner_generation
        )

    async def claim_recoverable_agent_run(
        self, session_id: str, *, owner_generation: int
    ) -> AgentRunState | None:
        """Complete existing running selection or pending claim before dispatch."""
        return await self.repository.claim_recoverable_agent_run(
            session_id, owner_generation=owner_generation
        )

    async def create_pending_agent_run(
        self, session_id: str, *, owner_generation: int, input_event_ids: Sequence[str]
    ) -> AgentRunState:
        """Complete pending Run creation/input association after drift validation."""
        return await self.repository.create_pending_agent_run(
            session_id,
            owner_generation=owner_generation,
            input_event_ids=input_event_ids,
        )

    async def claim_lifecycle_start(
        self, session_id: str, *, owner_generation: int, now: datetime.datetime
    ) -> bool:
        """Claim Session-start hooks in a completed guarded operation."""
        return await self.repository.claim_lifecycle_start(
            session_id, owner_generation=owner_generation, now=now
        )

    async def cancel_pending_agent_run(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> AgentRunState:
        """Complete pending cancellation and direct-parent finalization."""
        return await self.repository.cancel_pending_agent_run(
            session_id, owner_generation=owner_generation, run_id=run_id
        )

    async def complete_bridge_predecessor_run(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> AgentRunStatus:
        """Terminalize a bridge predecessor without ordinary foreground settlement."""
        return await self.repository.complete_bridge_predecessor_run(
            session_id, owner_generation=owner_generation, run_id=run_id
        )

    async def activate_pending_agent_run(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        initial_phase: AgentRunPhase,
        requested_profile: RequestedInferenceProfile,
    ) -> AgentRunState:
        """Complete profile/Session/phase activation before model preparation."""
        return await self.repository.activate_pending_agent_run(
            session_id,
            owner_generation=owner_generation,
            run_id=run_id,
            initial_phase=initial_phase,
            requested_profile=requested_profile,
        )

    async def mark_session_agent_runs_terminal(
        self, session_id: str, *, owner_generation: int, status: AgentRunStatus
    ) -> list[str]:
        """Complete bulk terminal mutation and parent-result admission together."""
        return await self.repository.mark_session_agent_runs_terminal(
            session_id, owner_generation=owner_generation, status=status
        )

    async def mark_agent_run_terminal_if_running(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        status: AgentRunStatus,
    ) -> None:
        """Complete conditional terminal mutation and parent admission together."""
        await self.repository.mark_agent_run_terminal_if_running(
            session_id, owner_generation=owner_generation, run_id=run_id, status=status
        )

    async def mark_agent_run_stopped_for_user_stop(
        self, session_id: str, *, owner_generation: int, run_id: str
    ) -> None:
        """Complete User Stop convergence and direct-parent finalization together."""
        await self.repository.mark_agent_run_stopped_for_user_stop(
            session_id, owner_generation=owner_generation, run_id=run_id
        )

    async def update_agent_run_retry_state(
        self,
        session_id: str,
        *,
        owner_generation: int,
        run_id: str,
        retry_state: FailedRunRetryState | None,
    ) -> None:
        """Complete the exact Session-bound Run retry-state mutation."""
        await self.repository.update_agent_run_retry_state(
            session_id,
            owner_generation=owner_generation,
            run_id=run_id,
            retry_state=retry_state,
        )
