"""Server-owned exact pending changes and Memory domain identity."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from azents.core.historical_memory_consolidation import (
    ConsolidationUnitKey,
    ConsolidationWorkKind,
    MemoryExecutionAuthorityError,
)
from azents.rdb.models.historical_memory_execution import RDBMemoryUnit, RDBMemoryWork
from azents.rdb.session_capabilities import WriteSession


def memory_unit_predicate(key: ConsolidationUnitKey) -> sa.ColumnElement[bool]:
    return sa.and_(
        RDBMemoryUnit.agent_id == key.agent_id,
        RDBMemoryUnit.workspace_id == key.workspace_id,
        RDBMemoryUnit.scope == key.scope,
        RDBMemoryUnit.associated_user_id.is_not_distinct_from(key.associated_user_id),
    )


async def ensure_memory_unit(session: WriteSession, key: ConsolidationUnitKey) -> str:
    """Create the domain identity without taking execution ownership."""
    await session.write_session.execute(
        insert(RDBMemoryUnit)
        .values(
            id=uuid7().hex,
            workspace_id=key.workspace_id,
            agent_id=key.agent_id,
            scope=key.scope,
            associated_user_id=key.associated_user_id,
            active_session_id=None,
            markdown=None,
            rendered_block=None,
            accepted_at=None,
            retry_at=None,
        )
        .on_conflict_do_nothing(constraint="uq_memory_units_scope")
    )
    result = await session.write_session.scalar(
        sa.select(RDBMemoryUnit.id).where(memory_unit_predicate(key))
    )
    if result is None:
        raise MemoryExecutionAuthorityError("Memory unit is unavailable.")
    return result


async def enroll_memory_work(
    session: WriteSession,
    key: ConsolidationUnitKey,
    *,
    source_session_id: str,
    kind: ConsolidationWorkKind,
) -> str:
    """Register one change; only server execution association can settle it."""
    unit_id = await ensure_memory_unit(session, key)
    work_id = uuid7().hex
    await session.write_session.execute(
        insert(RDBMemoryWork).values(
            id=work_id,
            unit_id=unit_id,
            source_session_id=source_session_id,
            kind=kind,
            admitted_session_id=None,
        )
    )
    return work_id
