"""Concrete database-only archive/restore participant composition."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated

from fastapi import Depends

from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.core.session_lifecycle import (
    SessionArchiveMutation,
    SessionLifecycleRegistry,
    SessionLifecycleTransitionContext,
    SessionLifecycleTransitionPolicy,
)
from azents.core.session_lifecycle_registry import get_session_lifecycle_registry
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.lifecycle_target import LifecycleTargetRepository
from azents.repos.scheduled_task.lifecycle import ScheduledTaskLifecycleRepository


@dataclasses.dataclass
class SessionLifecycleOperationsRepository:
    """Preserve registry order inside the enclosing repository transaction."""

    registry: Annotated[
        SessionLifecycleRegistry, Depends(get_session_lifecycle_registry)
    ]
    agent_session_repository: Annotated[
        AgentSessionRepository, Depends(AgentSessionRepository)
    ]
    lifecycle_target_repository: Annotated[
        LifecycleTargetRepository, Depends(LifecycleTargetRepository)
    ]
    retention_repository: Annotated[
        ArchivedSessionRetentionRepository, Depends(ArchivedSessionRetentionRepository)
    ]
    external_channel_repository: Annotated[
        ExternalChannelLifecycleRepository,
        Depends(ExternalChannelLifecycleRepository.create),
    ]
    scheduled_task_repository: Annotated[
        ScheduledTaskLifecycleRepository,
        Depends(ScheduledTaskLifecycleRepository.create),
    ]

    @staticmethod
    def require_context(context: SessionLifecycleTransitionContext) -> None:
        """Validate the exact existing root-tree transition identity."""
        if not context.root_session_id:
            raise ValueError("Session lifecycle transition requires a root session.")
        if not context.subtree_session_ids:
            raise ValueError("Session lifecycle transition requires a nonempty tree.")
        if context.root_session_id not in context.subtree_session_ids:
            raise ValueError(
                "Session lifecycle transition root must belong to its subtree."
            )

    async def archive_allows_active_runs(
        self,
        session: ReadSession,
        *,
        session_ids: Sequence[str],
        running_session_ids: Sequence[str],
    ) -> bool:
        """Retain Scheduled active-cycle archive eligibility."""
        return await self.scheduled_task_repository.archive_allows_active_runs(
            session, session_ids=session_ids, running_session_ids=running_session_ids
        )

    async def archive(
        self,
        session: WriteSession,
        command: SessionArchiveMutation,
    ) -> tuple[ProviderEffectPlan, ...]:
        """Commit participant and root mutations in the caller's DB-only composition."""
        context = command.context
        self.require_context(context)
        retention = await self.lifecycle_target_repository.resolve_retention(
            session,
            retention_repository=self.retention_repository,
            archived_at=command.archived_at,
        )
        plans: tuple[ProviderEffectPlan, ...] = ()
        for participant in self.registry.participants:
            if participant.archive_policy is SessionLifecycleTransitionPolicy.PRESERVE:
                continue
            if participant.key == "session.scheduled-task":
                result = await self.scheduled_task_repository.terminate_session_tree(
                    session, session_ids=context.subtree_session_ids
                )
                plans += result.cleanup_plans
            if participant.key == "session.external-channel":
                result = await self.external_channel_repository.terminate_session_tree(
                    session,
                    session_ids=context.subtree_session_ids,
                    now=datetime.datetime.now(datetime.UTC),
                )
                plans += result.cleanup_plans
        await self.agent_session_repository.archive_conversation_resources(
            session,
            root_session_id=context.root_session_id,
            session_ids=list(context.subtree_session_ids),
        )
        await self.lifecycle_target_repository.archive_status(
            session,
            root_session_id=context.root_session_id,
            session_ids=context.subtree_session_ids,
            retention=retention,
            end_reason=None,
        )
        await self.lifecycle_target_repository.schedule_archive_purge(
            session,
            root_session_id=context.root_session_id,
            retention_repository=self.retention_repository,
            retention=retention,
            scheduled_at=command.archived_at,
        )
        return plans

    async def accelerate_account_purge(
        self,
        session: WriteSession,
        *,
        root_session_id: str,
        session_ids: Sequence[str],
        archived_at: datetime.datetime,
        now: datetime.datetime,
    ) -> None:
        """Apply existing account-removal urgency without a separate delete pipeline."""
        await self.lifecycle_target_repository.accelerate_account_purge(
            session,
            root_session_id=root_session_id,
            session_ids=session_ids,
            archived_at=archived_at,
            now=now,
            retention_repository=self.retention_repository,
        )

    async def restore(
        self, session: WriteSession, context: SessionLifecycleTransitionContext
    ) -> None:
        """Validate participant state in reverse registry order before root restore."""
        self.require_context(context)
        for participant in reversed(self.registry.participants):
            if (
                participant.restore_policy is SessionLifecycleTransitionPolicy.PRESERVE
                and participant.archive_policy
                is not SessionLifecycleTransitionPolicy.TERMINATE
            ):
                continue
            if participant.key == "session.scheduled-task":
                await self.scheduled_task_repository.validate_restore_session_tree(
                    session, session_ids=context.subtree_session_ids
                )
            if participant.key == "session.external-channel":
                await self.external_channel_repository.validate_restore_session_tree(
                    session, session_ids=context.subtree_session_ids
                )
        await self.agent_session_repository.restore_tree(
            session,
            root_session_id=context.root_session_id,
            session_ids=list(context.subtree_session_ids),
        )
