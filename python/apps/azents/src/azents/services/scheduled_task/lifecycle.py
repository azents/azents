"""Transaction-bound Scheduled Task lifecycle participant operations."""

from collections.abc import Sequence
from dataclasses import asdict
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.session_lifecycle import (
    SessionLifecycleParticipantDefinition,
    SessionLifecyclePurgeContext,
    SessionLifecycleTransitionContext,
)
from azents.repos.scheduled_task.lifecycle import (
    ScheduledTaskLifecycleCleanup,
    ScheduledTaskLifecycleRepository,
    ScheduledTaskLifecycleVerification,
)

_PARTICIPANT_KEY = "session.scheduled-task"


class ScheduledTaskLifecycleService:
    """Run Scheduled Task lifecycle work inside caller-owned transactions."""

    def __init__(
        self,
        repository: Annotated[
            ScheduledTaskLifecycleRepository,
            Depends(ScheduledTaskLifecycleRepository.create),
        ],
    ) -> None:
        self.repository = repository

    async def archive_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ScheduledTaskLifecycleCleanup | None:
        """Remove pre-start Session-tree Scheduled authority."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.terminate_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def archive_allows_active_runs(
        self,
        session: AsyncSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Return whether archive can preserve every active execution."""
        return await self.repository.archive_allows_active_runs(
            session,
            session_ids=session_ids,
            running_session_ids=running_session_ids,
        )

    async def restore_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecycleTransitionContext,
    ) -> ScheduledTaskLifecycleVerification | None:
        """Validate restore without recreating removed Scheduled authority."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.validate_restore_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def prepare_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ScheduledTaskLifecycleVerification | None:
        """Wait for every preserved started cycle before permanent purge."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.require_purge_ready(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def cleanup_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ScheduledTaskLifecycleCleanup | None:
        """Delete residual Task and admitted-cycle state before finalization."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        return await self.repository.purge_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )

    async def verify_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ScheduledTaskLifecycleVerification | None:
        """Require no Scheduled Task or cycle state to remain."""
        if definition.key != _PARTICIPANT_KEY:
            return None
        verification = await self.repository.verify_session_tree(
            session,
            session_ids=context.subtree_session_ids,
        )
        if (
            verification.task_count
            or verification.trigger_count
            or verification.admitted_cycle_count
            or verification.started_cycle_count
        ):
            raise RuntimeError("Scheduled Task purge cleanup is incomplete.")
        return verification

    async def finalize_purge_participant(
        self,
        session: AsyncSession,
        definition: SessionLifecycleParticipantDefinition,
        context: SessionLifecyclePurgeContext,
    ) -> ScheduledTaskLifecycleVerification | None:
        """Recheck absence immediately before root-tree finalization."""
        return await self.verify_purge_participant(session, definition, context)

    @staticmethod
    def summary_dict(
        summary: ScheduledTaskLifecycleCleanup | ScheduledTaskLifecycleVerification,
    ) -> dict[str, object]:
        """Return a cleanup-plan-free durable participant summary."""
        values = asdict(summary)
        values.pop("cleanup_plans", None)
        return values
