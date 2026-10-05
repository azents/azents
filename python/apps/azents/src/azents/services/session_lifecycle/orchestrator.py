"""Session lifecycle orchestration through completed purge checkpoints."""

import asyncio
import dataclasses
import datetime
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends

from azents.core.enums import ArchivedSessionPurgeParticipantPhase
from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
    SessionLifecycleRegistry,
    SessionLifecycleTransitionContext,
    SessionLifecycleTransitionPolicy,
)
from azents.core.session_lifecycle_purge import (
    SessionLifecyclePurgeParticipantFailure,
    SessionLifecyclePurgePolicy,
)
from azents.repos.session_lifecycle_purge_operations import (
    SessionLifecyclePurgeOperations,
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


@dataclasses.dataclass(frozen=True)
class SessionLifecycleOrchestrator:
    """Sequence external participants between completed durable checkpoints."""

    registry: SessionLifecycleRegistry
    operations: Annotated[
        SessionLifecyclePurgeOperations, Depends(SessionLifecyclePurgeOperations)
    ]

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
        SessionLifecyclePurgePolicy(self.registry)._require_transition_context(context)
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
        SessionLifecyclePurgePolicy(self.registry)._require_transition_context(context)
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
        context: SessionLifecyclePurgeContext,
        phase: ArchivedSessionPurgeParticipantPhase,
        operation: PurgeParticipantOperation,
    ) -> None:
        """Run one durable purge phase in dependency order.

        Each participant checkpoint is persisted only after its idempotent operation
        completes. Failures are attributed to both the participant and purge job
        before this method raises for the scheduler retry policy.
        """
        executions = await self.operations.list_executions(
            job_id=context.purge_job_id,
        )
        snapshot_participants = SessionLifecyclePurgePolicy(
            self.registry
        )._require_purge_snapshot_participants(executions)
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
                blocked = await self.operations.block(
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

            started = await self.operations.start(
                job_id=context.purge_job_id,
                lease_owner=context.lease_owner,
                participant_key=participant.key,
                now=datetime.datetime.now(datetime.UTC),
            )
            if not started:
                raise RuntimeError("Archived-session purge lease was lost.")

            try:
                operational_summary = await operation(participant)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                recorded = await self.operations.fail(
                    job_id=context.purge_job_id,
                    lease_owner=context.lease_owner,
                    participant_key=participant.key,
                    phase=phase,
                    error_kind=type(error).__name__,
                    error_summary=str(error) or type(error).__name__,
                    now=datetime.datetime.now(datetime.UTC),
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

            checkpointed = await self.operations.checkpoint(
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
