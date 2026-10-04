"""Exact immutable-revision reads under independent foreground authority."""

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
)
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationUnitKey,
)
from azents.core.historical_memory_publication import validate_consolidation_overview
from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemorySnapshotConsumer,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationRevision,
    RDBConsolidationRevisionDependency,
    RDBConsolidationUnit,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import ReadSession
from azents.repos.historical_memory_consolidation.authority import unit_predicate
from azents.repos.historical_memory_consolidation.sources import source_predicate


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


def denied_revision_manifest(key: ConsolidationUnitKey) -> sa.ColumnElement[bool]:
    """Correlate denial to this exact revision's full independent manifest."""
    dependency = RDBConsolidationRevisionDependency
    source = RDBHistoricalMemorySource
    root = RDBAgentSession
    grant = (
        sa.select(RDBWorkspaceUser.memory_grant_identity)
        .where(
            RDBWorkspaceUser.workspace_id == key.workspace_id,
            RDBWorkspaceUser.user_id == key.associated_user_id,
        )
        .scalar_subquery()
    )
    allowed = sa.and_(
        root.id.is_not(None),
        source.source_session_id.is_not(None),
        source_predicate(key),
        source.availability_generation == dependency.availability_generation,
        dependency.membership_grant_id.is_not_distinct_from(
            grant if key.scope is ConsolidationScope.USER else sa.null()
        ),
        source.summary_generation >= dependency.summary_generation,
        sa.or_(
            source.summary_generation > dependency.summary_generation,
            source.evidence_hash.is_not_distinct_from(dependency.evidence_hash),
        ),
    )
    return (
        sa.select(dependency.id)
        .outerjoin(root, root.id == dependency.source_session_id)
        .outerjoin(source, source.source_session_id == dependency.source_session_id)
        .where(
            dependency.revision_id == RDBConsolidationRevision.id,
            allowed.is_not(True),
        )
        .correlate(RDBConsolidationRevision)
        .exists()
    )


async def read_foreground_revision(
    session: ReadSession,
    *,
    consumer: MemorySnapshotConsumer,
    scope: ConsolidationScope,
    selected: ConsolidatedMemorySnapshotEntry | None,
) -> ConsolidatedMemorySnapshotEntry | None:
    """Observe permitted exact bytes and their own manifest without read fencing."""
    key = foreground_unit(consumer, scope)
    if key is None or (selected is not None and selected.unit != key):
        return None
    unit = RDBConsolidationUnit
    revision = RDBConsolidationRevision
    agent = RDBAgent
    personal_grant = (
        sa.select(RDBWorkspaceUser.id)
        .where(
            RDBWorkspaceUser.workspace_id == key.workspace_id,
            RDBWorkspaceUser.user_id == key.associated_user_id,
        )
        .exists()
    )
    consumer_root = aliased(RDBAgentSession)
    consumer_allowed = (
        sa.select(consumer_root.id)
        .where(
            consumer_root.id == consumer.session_id,
            consumer_root.agent_id == consumer.agent_id,
            consumer_root.workspace_id == consumer.workspace_id,
            consumer_root.session_kind == AgentSessionKind.ROOT,
            consumer_root.status == AgentSessionStatus.ACTIVE,
            consumer_root.product_mode == consumer.product_mode,
            consumer_root.associated_user_id.is_not_distinct_from(
                consumer.associated_user_id
            ),
        )
        .exists()
    )
    query = (
        sa.select(revision)
        .join(unit, unit.id == revision.unit_id)
        .join(agent, agent.id == unit.agent_id)
        .where(
            unit_predicate(key),
            agent.workspace_id == key.workspace_id,
            agent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
            agent.memory_enabled.is_(True),
            consumer_allowed,
            ~denied_revision_manifest(key),
        )
        .execution_options(populate_existing=True)
    )
    if key.scope is ConsolidationScope.USER:
        query = query.where(personal_grant)
    if selected is None:
        query = query.where(revision.id == unit.published_revision_id)
    else:
        query = query.where(
            unit.id == selected.unit_id, revision.id == selected.revision_id
        )
    observed = await session.read_session.scalar(query)
    if observed is None or not observed.rendered_block:
        return None
    validated = validate_consolidation_overview(key=key, markdown=observed.markdown)
    if validated.rendered_block != observed.rendered_block:
        raise ValueError("Consolidated Memory publication bytes are inconsistent.")
    result = ConsolidatedMemorySnapshotEntry(
        unit=key,
        unit_id=observed.unit_id,
        revision_id=observed.id,
        rendered_block=observed.rendered_block,
        published_at=observed.published_at,
    )
    if selected is not None and selected != result:
        return None
    return result
