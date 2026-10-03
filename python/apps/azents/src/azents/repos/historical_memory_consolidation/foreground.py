"""Exact immutable-revision reads under independent foreground authority."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import AgentSessionProductMode
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_publication import validate_consolidation_overview
from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemorySnapshotConsumer,
)
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
)
from azents.repos.historical_memory_consolidation.authority import (
    ConsolidationAuthorityBusyError,
    ConsolidationAuthorityError,
    ConsolidationDeadlineError,
    lock_unit_authority,
    unit_predicate,
)
from azents.repos.historical_memory_consolidation.drafts import (
    check_dependency_manifest,
)


def foreground_unit(
    consumer: MemorySnapshotConsumer, scope: ConsolidationScope
) -> ConsolidationUnitKey | None:
    """A personal alias can only select the root's durable associated User."""
    if scope is ConsolidationScope.USER and (
        consumer.product_mode is not AgentSessionProductMode.USER
        or consumer.associated_user_id is None
    ):
        return None
    return ConsolidationUnitKey(
        workspace_id=consumer.workspace_id,
        agent_id=consumer.agent_id,
        scope=scope,
        associated_user_id=(
            consumer.associated_user_id if scope is ConsolidationScope.USER else None
        ),
    )


async def read_foreground_revision(
    session: AsyncSession,
    *,
    consumer: MemorySnapshotConsumer,
    scope: ConsolidationScope,
    selected: ConsolidatedMemorySnapshotEntry | None,
) -> ConsolidatedMemorySnapshotEntry | None:
    """Use the selected revision's own manifest, never the new current pointer."""
    key = foreground_unit(consumer, scope)
    if key is None or (selected is not None and selected.unit != key):
        return None
    await session.execute(
        sa.select(sa.func.set_config("statement_timeout", "2000", True))
    )
    try:
        grant = await lock_unit_authority(session, key)
        unit = await session.scalar(
            sa.select(RDBConsolidationUnit).where(unit_predicate(key))
        )
        if unit is None or (selected is not None and selected.unit_id != unit.id):
            return None
        revision_id = (
            unit.published_revision_id if selected is None else selected.revision_id
        )
        if revision_id is None:
            return None
        # Collection uses SKIP LOCKED; a snapshot holds these immutable bytes
        # until its reference commits in the same database transaction.
        revision = await session.scalar(
            sa.select(RDBConsolidationRevision)
            .where(
                RDBConsolidationRevision.id == revision_id,
                RDBConsolidationRevision.unit_id == unit.id,
            )
            .with_for_update(read=True, nowait=True)
        )
        if revision is None or not revision.rendered_block:
            return None
        manifest = (
            sa.select(
                RDBConsolidationRevisionDependency.source_session_id,
                RDBConsolidationRevisionDependency.summary_generation,
                RDBConsolidationRevisionDependency.evidence_hash,
                RDBConsolidationRevisionDependency.availability_generation,
                RDBConsolidationRevisionDependency.membership_grant_id,
            )
            .where(RDBConsolidationRevisionDependency.revision_id == revision.id)
            .subquery("foreground_revision_manifest")
        )
        await check_dependency_manifest(
            session, key=key, membership_grant_id=grant, influence=manifest
        )
    except ConsolidationAuthorityBusyError, ConsolidationDeadlineError:
        raise
    except ConsolidationAuthorityError:
        return None
    validated = validate_consolidation_overview(key=key, markdown=revision.markdown)
    if validated.rendered_block != revision.rendered_block:
        raise ValueError("Consolidated Memory publication bytes are inconsistent.")
    result = ConsolidatedMemorySnapshotEntry(
        unit=key,
        unit_id=unit.id,
        revision_id=revision.id,
        rendered_block=revision.rendered_block,
        published_at=revision.published_at,
    )
    if selected is not None and selected != result:
        return None
    return result
