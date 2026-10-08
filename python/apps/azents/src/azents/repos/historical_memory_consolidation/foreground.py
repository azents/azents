"""Scope-only current results and independently authorized boundary-selected bytes."""

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
from azents.core.historical_memory_snapshot import (
    ConsolidatedMemorySnapshotEntry,
    MemorySnapshotConsumer,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.historical_memory_execution import RDBMemoryUnit
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import ReadSession


def foreground_unit(
    consumer: MemorySnapshotConsumer, scope: ConsolidationScope
) -> ConsolidationUnitKey | None:
    """Personal scope comes only from this public root's durable associated User."""
    if scope is ConsolidationScope.USER and (
        consumer.product_mode is not AgentSessionProductMode.USER
        or consumer.associated_user_id is None
    ):
        return None
    return ConsolidationUnitKey(
        workspace_id=consumer.workspace_id,
        agent_id=consumer.agent_id,
        scope=scope,
        associated_user_id=consumer.associated_user_id
        if scope is ConsolidationScope.USER
        else None,
    )


async def read_current_result(
    session: ReadSession,
    *,
    consumer: MemorySnapshotConsumer,
    scope: ConsolidationScope,
    selected: ConsolidatedMemorySnapshotEntry | None,
) -> ConsolidatedMemorySnapshotEntry | None:
    """Authorize a scope; retain selected boundary bytes without source inheritance."""
    key = foreground_unit(consumer, scope)
    if key is None or (selected is not None and selected.unit != key):
        return None
    root = aliased(RDBAgentSession)
    conversation = aliased(RDBConversation)
    allowed = (
        sa.select(root.id)
        .join(conversation, conversation.session_id == root.id)
        .where(
            root.id == consumer.session_id,
            root.agent_id == consumer.agent_id,
            root.workspace_id == consumer.workspace_id,
            root.status == AgentSessionStatus.ACTIVE,
            conversation.session_kind == AgentSessionKind.ROOT,
            conversation.product_mode == consumer.product_mode,
            conversation.associated_user_id.is_not_distinct_from(
                consumer.associated_user_id
            ),
        )
        .exists()
    )
    authority = sa.select(RDBAgent.id).where(
        RDBAgent.id == key.agent_id,
        RDBAgent.workspace_id == key.workspace_id,
        RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
        RDBAgent.memory_enabled.is_(True),
        allowed,
    )
    if key.scope is ConsolidationScope.USER:
        authority = authority.where(
            sa.select(RDBWorkspaceUser.id)
            .where(
                RDBWorkspaceUser.workspace_id == key.workspace_id,
                RDBWorkspaceUser.user_id == key.associated_user_id,
            )
            .exists()
        )
    if selected is not None:
        authorized = await session.read_session.scalar(authority)
        return selected if authorized is not None else None
    row = await session.read_session.scalar(
        sa.select(RDBMemoryUnit).where(
            RDBMemoryUnit.agent_id == key.agent_id,
            RDBMemoryUnit.workspace_id == key.workspace_id,
            RDBMemoryUnit.scope == key.scope,
            RDBMemoryUnit.associated_user_id.is_not_distinct_from(
                key.associated_user_id
            ),
            authority.exists(),
        )
    )
    if row is None or not row.rendered_block or row.accepted_at is None:
        return None
    return ConsolidatedMemorySnapshotEntry(
        unit=key,
        rendered_block=row.rendered_block,
        published_at=row.accepted_at,
    )
