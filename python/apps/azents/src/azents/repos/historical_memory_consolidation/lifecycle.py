"""Source availability transitions composed into existing lifecycle transactions."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionProductMode, AgentSessionStatus
from azents.core.historical_memory_consolidation import ConsolidationWorkKind
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.repos.historical_memory_consolidation.enrollment import (
    enroll_source_in_session,
)


async def source_availability_in_session(
    session: AsyncSession,
    *,
    source_session_id: str,
    denied: bool,
) -> None:
    """Advance denial continuity and enroll the exact changed or restored source.

    Call after locking/mutating the root, in the same transaction. Restore leaves
    the monotonic availability identity unchanged and cannot revive old evidence.
    An unprepared source still records continuity but needs no consolidation work.
    """
    root = await session.get(RDBAgentSession, source_session_id)
    if root is None:
        return
    source = await session.scalar(
        sa.select(RDBHistoricalMemorySource)
        .where(RDBHistoricalMemorySource.source_session_id == source_session_id)
        .with_for_update(nowait=True)
    )
    if source is None:
        return
    if denied:
        source.availability_generation += 1
    if source.prepared_at is not None:
        await enroll_source_in_session(
            session,
            source=source,
            root=root,
            kind=(
                ConsolidationWorkKind.REMOVED
                if denied
                else ConsolidationWorkKind.RESTORED
            ),
        )
    await session.flush()


async def membership_work_in_session(
    session: AsyncSession,
    *,
    workspace_id: str,
    user_id: str,
    denied: bool,
) -> None:
    """Enroll body-free personal source deltas in the membership transaction.

    Removal runs before deleting the old grant, restoration after inserting the
    fresh grant. Pages do not acquire consolidation ownership locks. All existing
    source summaries remain canonical; old attempts/manifests stay grant-fenced.
    """
    after: str | None = None
    while True:
        query = (
            sa.select(RDBHistoricalMemorySource, RDBAgentSession)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .where(
                RDBAgentSession.workspace_id == workspace_id,
                RDBAgentSession.associated_user_id == user_id,
                RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                RDBHistoricalMemorySource.prepared_at.is_not(None),
            )
            .order_by(RDBHistoricalMemorySource.source_session_id)
            .limit(50)
        )
        if not denied:
            query = query.where(RDBAgentSession.status == AgentSessionStatus.ACTIVE)
        if after is not None:
            query = query.where(RDBHistoricalMemorySource.source_session_id > after)
        rows = (await session.execute(query)).all()
        if not rows:
            return
        for source, root in rows:
            await enroll_source_in_session(
                session,
                source=source,
                root=root,
                kind=(
                    ConsolidationWorkKind.REMOVED
                    if denied
                    else ConsolidationWorkKind.RESTORED
                ),
            )
        after = rows[-1][0].source_session_id


async def agent_memory_availability_in_session(
    session: AsyncSession, *, agent_id: str, denied: bool
) -> None:
    """Record Memory disable continuity across all source roots before commit."""
    after: str | None = None
    while True:
        query = (
            sa.select(RDBHistoricalMemorySource.source_session_id)
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .where(RDBAgentSession.agent_id == agent_id)
            .order_by(RDBHistoricalMemorySource.source_session_id)
            .limit(50)
        )
        if not denied:
            query = query.where(RDBAgentSession.status == AgentSessionStatus.ACTIVE)
        if after is not None:
            query = query.where(RDBHistoricalMemorySource.source_session_id > after)
        ids = list(await session.scalars(query))
        if not ids:
            return
        for source_id in ids:
            await source_availability_in_session(
                session, source_session_id=source_id, denied=denied
            )
        after = ids[-1]
