"""Completed persistence operations for compacted-event retention."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.orm import aliased

from azents.core.archived_session_retention_data import RetentionRevisionConflict
from azents.core.enums import AgentRunStatus, EventKind
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent_run import RDBAgentRun
from azents.rdb.models.agent_run_input_event import RDBAgentRunInputEvent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.archived_session_retention import RDBSystemFileLifecycleSetting
from azents.rdb.models.event import RDBEvent
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.archived_session_retention import ArchivedSessionRetentionRepository
from azents.repos.archived_session_retention.data import SystemFileLifecycleSettings


async def record_compaction_displacement(
    session: WriteSession, *, session_id: str, head_event_id: str
) -> None:
    """Record first displacement in the same transaction as a summary head move."""
    compacted_at = await session.write_session.scalar(
        sa.select(RDBEvent.created_at).where(
            RDBEvent.session_id == session_id,
            RDBEvent.id == head_event_id,
            RDBEvent.kind == EventKind.COMPACTION_SUMMARY,
        )
    )
    if compacted_at is None:
        return
    previous_head = (
        sa.select(RDBAgentSession.model_input_head_event_id)
        .where(RDBAgentSession.id == session_id)
        .scalar_subquery()
    )
    await session.write_session.execute(
        sa.update(RDBEvent)
        .where(
            RDBEvent.session_id == session_id,
            RDBEvent.id < head_event_id,
            RDBEvent.compacted_at.is_(None),
            sa.or_(previous_head.is_(None), RDBEvent.id >= previous_head),
        )
        .values(compacted_at=compacted_at)
    )


@dataclasses.dataclass(frozen=True)
class CompactedEventCleanupSummary:
    """Result of one bounded cleanup pass."""

    deleted_count: int
    limit_reached: bool
    unlimited: bool


@dataclasses.dataclass
class CompactedEventRetentionOperations:
    """Own settings CAS and bounded, atomic event cleanup transactions."""

    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]
    settings_repository: Annotated[
        ArchivedSessionRetentionRepository, Depends(ArchivedSessionRetentionRepository)
    ]

    async def update_settings(
        self, *, expected_revision: int, retention_days: int | None, user_id: str
    ) -> SystemFileLifecycleSettings:
        """Update only compacted-event policy using existing settings revision CAS."""
        async with self.session_manager() as session:
            changed = await session.write_session.scalar(
                sa.update(RDBSystemFileLifecycleSetting)
                .where(
                    RDBSystemFileLifecycleSetting.id == 1,
                    RDBSystemFileLifecycleSetting.revision == expected_revision,
                )
                .values(
                    compacted_event_retention_days=retention_days,
                    revision=RDBSystemFileLifecycleSetting.revision + 1,
                    updated_by_user_id=user_id,
                    updated_at=sa.func.now(),
                )
                .returning(RDBSystemFileLifecycleSetting.id)
            )
            if changed is None:
                raise RetentionRevisionConflict
            return await self.settings_repository.get_settings(session)

    async def cleanup_once(
        self, *, now: datetime.datetime, limit: int
    ) -> CompactedEventCleanupSummary:
        """Delete expired history only after file-GC and active-input protection."""
        async with self.session_manager() as session:
            settings = await session.write_session.scalar(
                sa.select(RDBSystemFileLifecycleSetting)
                .where(RDBSystemFileLifecycleSetting.id == 1)
                .with_for_update(read=True)
            )
            if settings is None:
                raise RuntimeError("System file lifecycle settings are not initialized")
            days = settings.compacted_event_retention_days
            if days is None:
                return CompactedEventCleanupSummary(0, False, True)
            # Avoid datetime underflow for a valid, very large integer policy.
            earliest = datetime.datetime.min.replace(tzinfo=datetime.UTC)
            if days > (now - earliest).days:
                return CompactedEventCleanupSummary(0, False, False)
            cutoff = now - datetime.timedelta(days=days)
            active_input = (
                sa.select(RDBAgentRunInputEvent.event_id)
                .join(
                    RDBAgentRun,
                    RDBAgentRun.id == RDBAgentRunInputEvent.agent_run_id,
                )
                .where(
                    RDBAgentRunInputEvent.event_id == RDBEvent.id,
                    RDBAgentRun.status.in_(
                        (AgentRunStatus.PENDING, AgentRunStatus.RUNNING)
                    ),
                )
                .exists()
            )
            head_event = aliased(RDBEvent)
            valid_head = (
                sa.select(head_event.id)
                .where(
                    head_event.session_id == RDBAgentSession.id,
                    head_event.id == RDBAgentSession.model_input_head_event_id,
                    head_event.kind == EventKind.COMPACTION_SUMMARY,
                )
                .exists()
            )
            ids = list(
                await session.write_session.scalars(
                    sa.select(RDBEvent.id)
                    .join(RDBAgentSession, RDBAgentSession.id == RDBEvent.session_id)
                    .where(
                        RDBEvent.compacted_at <= cutoff,
                        RDBEvent.id < RDBAgentSession.model_input_head_event_id,
                        RDBEvent.id <= RDBAgentSession.model_file_gc_cursor_event_id,
                        ~active_input,
                        valid_head,
                    )
                    .order_by(RDBEvent.compacted_at, RDBEvent.id)
                    .limit(limit)
                    .with_for_update(of=RDBEvent, skip_locked=True)
                )
            )
            if ids:
                await session.write_session.execute(
                    sa.delete(RDBEvent).where(RDBEvent.id.in_(ids))
                )
            return CompactedEventCleanupSummary(
                deleted_count=len(ids),
                limit_reached=len(ids) == limit,
                unlimited=False,
            )
