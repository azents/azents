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
    SessionLifecycleTransitionPolicy,
)
from azents.rdb.session import SessionManager
from azents.repos.archived_session_retention import (
    ArchivedSessionPurgeParticipantSnapshotInvalid,
    ArchivedSessionRetentionRepository,
)
from azents.repos.archived_session_retention.data import (
    ArchivedSessionPurgeParticipantExecution,
    ArchivedSessionPurgeParticipantSnapshot,
)

PurgeParticipantOperation = Callable[
    [SessionLifecycleParticipantDefinition],
    Awaitable[dict[str, object] | None],
]
TransitionParticipantOperation = Callable[
    [
        SessionLifecycleParticipantDefinition,
        SessionLifecycleTransitionContext,
    ],
    Awaitable[None],
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


class SessionLifecyclePurgeSnapshotValidationFailure(RuntimeError):
    """A participant snapshot failed validation before lifecycle side effects."""

    def __init__(
        self,
        *,
        participant_key: str | None,
        error: Exception,
    ) -> None:
        """Initialize a structured snapshot validation failure."""
        self.participant_key = participant_key
        self.phase = ArchivedSessionPurgeParticipantPhase.PENDING
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
        """Materialize once or validate the existing immutable participant snapshot."""
        try:
            executions = (
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
            )
        except ArchivedSessionPurgeParticipantSnapshotInvalid as error:
            raise SessionLifecyclePurgeSnapshotValidationFailure(
                participant_key=error.participant_key,
                error=error,
            ) from error
        self._require_purge_snapshot_participants(executions)

    def _snapshot_validation_failure(
        self,
        *,
        participant_key: str | None,
        message: str,
        error: Exception | None = None,
    ) -> SessionLifecyclePurgeSnapshotValidationFailure:
        """Build one structured immutable snapshot validation failure."""
        return SessionLifecyclePurgeSnapshotValidationFailure(
            participant_key=participant_key,
            error=error or RuntimeError(message),
        )

    def _require_purge_snapshot_participants(
        self,
        executions: list[ArchivedSessionPurgeParticipantExecution],
    ) -> tuple[SessionLifecycleParticipantDefinition, ...]:
        """Resolve one complete, supported immutable participant snapshot."""
        executions_by_key = {
            execution.participant_key: execution for execution in executions
        }
        if not executions or len(executions_by_key) != len(executions):
            raise self._snapshot_validation_failure(
                participant_key=None,
                message="Purge participant snapshot is incomplete.",
            )

        snapshot_participant_keys = set(executions_by_key)
        for execution in executions:
            try:
                self.registry.require_policy_version(
                    key=execution.participant_key,
                    policy_version=execution.policy_version,
                )
            except ValueError as error:
                raise self._snapshot_validation_failure(
                    participant_key=execution.participant_key,
                    message=str(error),
                    error=error,
                ) from error
        snapshot_participants = tuple(
            participant
            for participant in self.registry.participants
            if participant.key in snapshot_participant_keys
        )
        for participant in snapshot_participants:
            missing_dependencies = tuple(
                dependency
                for dependency in participant.dependencies
                if dependency not in executions_by_key
            )
            if missing_dependencies:
                raise self._snapshot_validation_failure(
                    participant_key=participant.key,
                    message=(
                        "Purge participant snapshot is missing dependencies for "
                        f"{participant.key}: {', '.join(missing_dependencies)}."
                    ),
                )
        return snapshot_participants

    async def archive(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: TransitionParticipantOperation,
        transition: TransitionOperation,
    ) -> None:
        """Run participant archive operations before the locked root transition.

        The caller owns the surrounding database transaction. Participant failures
        propagate directly so the caller rolls back participant and root state
        together.
        """
        self._require_transition_context(context)
        for participant in self.registry.participants:
            if participant.archive_policy is SessionLifecycleTransitionPolicy.PRESERVE:
                continue
            await participant_operation(participant, context)
        await transition()

    async def restore(
        self,
        *,
        context: SessionLifecycleTransitionContext,
        participant_operation: TransitionParticipantOperation,
        transition: TransitionOperation,
    ) -> None:
        """Run restore validation or mutation before the locked root transition.

        A terminal-on-archive participant has no inverse mutation, but is dispatched
        for validation that its terminal state remains preserved. Ordinary
        preserve-only participants require no restore operation.
        """
        self._require_transition_context(context)
        for participant in reversed(self.registry.participants):
            if (
                participant.restore_policy is SessionLifecycleTransitionPolicy.PRESERVE
                and participant.archive_policy
                is not SessionLifecycleTransitionPolicy.TERMINATE
            ):
                continue
            await participant_operation(participant, context)
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
        snapshot_participants = self._require_purge_snapshot_participants(executions)
        executions_by_key = {
            execution.participant_key: execution for execution in executions
        }

        for participant in snapshot_participants:
            execution = executions_by_key[participant.key]
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
