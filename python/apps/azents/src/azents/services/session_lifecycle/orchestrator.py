"""Session lifecycle orchestration boundaries."""

import dataclasses
import datetime
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ArchivedSessionPurgeParticipantPhase
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
    SessionLifecycleRegistry,
    SessionLifecycleTransitionContext,
)
from azents.rdb.session import SessionManager
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantSnapshot,
)

PurgeParticipantOperation = Callable[
    [SessionLifecycleParticipantDefinition],
    Awaitable[dict[str, object] | None],
]
TransitionOperation = Callable[[], Awaitable[None]]

_PURGE_PHASE_ORDER = {
    ArchivedSessionPurgeParticipantPhase.PENDING: 0,
    ArchivedSessionPurgeParticipantPhase.PREPARED: 1,
    ArchivedSessionPurgeParticipantPhase.CLEANUP_COMPLETED: 2,
    ArchivedSessionPurgeParticipantPhase.VERIFIED: 3,
}


class SessionLifecyclePurgeParticipantFailure(RuntimeError):
    """A participant operation failed after durable failure attribution."""

    def __init__(
        self,
        *,
        participant_key: str,
        phase: ArchivedSessionPurgeParticipantPhase,
        error: Exception,
    ) -> None:
        """Initialize a failure with its responsible participant checkpoint."""
        self.participant_key = participant_key
        self.phase = phase
        self.error_kind = type(error).__name__
        self.error_summary = str(error) or self.error_kind
        super().__init__(self.error_summary)


@dataclasses.dataclass(frozen=True)
class SessionLifecycleOrchestrator:
    """Own cross-domain lifecycle checkpoints without owning domain cleanup."""

    registry: SessionLifecycleRegistry

    async def materialize_claimed_purge_participants(
        self,
        session: AsyncSession,
        *,
        retention_repository: ArchivedSessionRetentionRepository,
        purge_job_id: str,
        lease_owner: str,
    ) -> None:
        """Persist the active participant/version set in the claim transaction."""
        await retention_repository.materialize_purge_participant_executions(
            session,
            job_id=purge_job_id,
            lease_owner=lease_owner,
            participants=tuple(
                ArchivedSessionPurgeParticipantSnapshot(
                    participant_key=participant.key,
                    policy_version=participant.policy_version,
                )
                for participant in self.registry.participants
            ),
        )

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        transition: TransitionOperation,
    ) -> None:
        """Run the archive transition after validating its participant registry."""
        self._require_transition_context(context)
        await transition()

    async def restore(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        transition: TransitionOperation,
    ) -> None:
        """Run the restore transition after validating its participant registry."""
        self._require_transition_context(context)
        await transition()

    async def run_purge_phase(
        self,
        *,
        session_manager: SessionManager[AsyncSession],
        retention_repository: ArchivedSessionRetentionRepository,
        context: SessionLifecyclePurgeContext,
        phase: ArchivedSessionPurgeParticipantPhase,
        operation: PurgeParticipantOperation,
    ) -> None:
        """Run one durable purge phase in dependency order.

        Each participant checkpoint is persisted only after its idempotent operation
        completes. Failures are attributed to both the participant and purge job
        before this method raises for the scheduler retry policy.
        """
        async with session_manager() as session:
            executions = await retention_repository.list_purge_participant_executions(
                session,
                job_id=context.purge_job_id,
            )
        executions_by_key = {
            execution.participant_key: execution for execution in executions
        }
        if len(executions_by_key) != len(self.registry.participants):
            raise RuntimeError("Purge participant snapshot is incomplete.")

        for participant in self.registry.participants:
            execution = executions_by_key.get(participant.key)
            if execution is None:
                raise RuntimeError(
                    f"Purge participant snapshot is missing {participant.key}."
                )
            self.registry.require_policy_version(
                key=participant.key,
                policy_version=execution.policy_version,
            )
            if _PURGE_PHASE_ORDER[execution.phase] >= _PURGE_PHASE_ORDER[phase]:
                continue

            dependency = next(
                (
                    dependency_key
                    for dependency_key in participant.dependencies
                    if _PURGE_PHASE_ORDER[executions_by_key[dependency_key].phase]
                    < _PURGE_PHASE_ORDER[phase]
                ),
                None,
            )
            if dependency is not None:
                async with session_manager() as session:
                    blocked = await retention_repository.mark_purge_participant_blocked(
                        session,
                        job_id=context.purge_job_id,
                        lease_owner=context.lease_owner,
                        participant_key=participant.key,
                        blocked_by_participant_key=dependency,
                        now=datetime.datetime.now(datetime.UTC),
                    )
                if not blocked:
                    raise RuntimeError("Archived-session purge lease was lost.")
                raise RuntimeError(
                    f"Purge participant {participant.key} is blocked by {dependency}."
                )

            async with session_manager() as session:
                started = await retention_repository.start_purge_participant_attempt(
                    session,
                    job_id=context.purge_job_id,
                    lease_owner=context.lease_owner,
                    participant_key=participant.key,
                    now=datetime.datetime.now(datetime.UTC),
                )
            if not started:
                raise RuntimeError("Archived-session purge lease was lost.")

            try:
                operational_summary = await operation(participant)
            except Exception as error:
                async with session_manager() as session:
                    recorded = (
                        await retention_repository.record_purge_participant_failure(
                            session,
                            job_id=context.purge_job_id,
                            lease_owner=context.lease_owner,
                            participant_key=participant.key,
                            phase=phase,
                            error_kind=type(error).__name__,
                            error_summary=str(error) or type(error).__name__,
                            now=datetime.datetime.now(datetime.UTC),
                        )
                    )
                if not recorded:
                    raise RuntimeError(
                        "Archived-session purge lease was lost while recording "
                        "participant failure."
                    ) from error
                raise SessionLifecyclePurgeParticipantFailure(
                    participant_key=participant.key,
                    phase=phase,
                    error=error,
                ) from error

            async with session_manager() as session:
                checkpointed = await retention_repository.checkpoint_purge_participant(
                    session,
                    job_id=context.purge_job_id,
                    lease_owner=context.lease_owner,
                    participant_key=participant.key,
                    phase=phase,
                    operational_summary=operational_summary,
                    now=datetime.datetime.now(datetime.UTC),
                )
            if not checkpointed:
                raise RuntimeError("Archived-session purge lease was lost.")
            executions_by_key[participant.key] = execution.model_copy(
                update={"phase": phase}
            )

    def _require_transition_context(
        self,
        context: SessionLifecycleTransitionContext,
    ) -> None:
        """Validate a locked transition context before mutating its root tree."""
        if not context.root_session_id:
            raise ValueError("Session lifecycle transition requires a root session.")
        if not context.subtree_session_ids:
            raise ValueError("Session lifecycle transition requires a nonempty tree.")
        if context.root_session_id not in context.subtree_session_ids:
            raise ValueError(
                "Session lifecycle transition root must belong to its subtree."
            )
