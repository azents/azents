"""Composable source-change enrollment without consolidation-owner row locks."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from uuid6 import uuid7

from azents.core.enums import AgentSessionProductMode
from azents.core.historical_memory_consolidation import (
    ConsolidationScope,
    ConsolidationWorkKind,
)
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.historical_memory_consolidation import RDBConsolidationWork
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session_capabilities import WriteSession


async def enroll_source_in_session(
    session: WriteSession,
    *,
    source: RDBHistoricalMemorySource,
    root: RDBAgentSession,
    kind: ConsolidationWorkKind,
) -> str | None:
    """Insert exact source work in the caller's source/lifecycle transaction.

    The caller owns source authorization/locking. This operation neither
    creates nor locks a consolidation unit. A null return means the same
    evidence/change identity was already enrolled, not a swallowed failure.
    """
    conversation = root.conversation
    if conversation is None:
        raise ValueError("Historical source has no Conversation.")
    membership_id: str | None = None
    match conversation.product_mode:
        case AgentSessionProductMode.TEAM:
            scope = ConsolidationScope.TEAM
            user_id = None
        case AgentSessionProductMode.USER:
            scope = ConsolidationScope.USER
            user_id = conversation.associated_user_id
            if user_id is None:
                raise ValueError("Personal source has no associated User.")
            membership_id = await session.write_session.scalar(
                sa.select(RDBWorkspaceUser.memory_grant_identity).where(
                    RDBWorkspaceUser.workspace_id == root.workspace_id,
                    RDBWorkspaceUser.user_id == user_id,
                )
            )
            if membership_id is None:
                if kind is ConsolidationWorkKind.RESTORED:
                    return None
                if kind is not ConsolidationWorkKind.REMOVED:
                    raise PermissionError("Source membership is unavailable.")
        case None:
            raise ValueError("Historical source is not a product root.")
    if root.agent_id is None:
        raise ValueError("Historical source has no Agent.")
    work_id = uuid7().hex
    statement = (
        insert(RDBConsolidationWork)
        .values(
            id=work_id,
            agent_id=root.agent_id,
            workspace_id=root.workspace_id,
            scope=scope,
            associated_user_id=user_id,
            source_session_id=source.source_session_id,
            summary_generation=source.summary_generation,
            availability_generation=source.availability_generation,
            evidence_hash=source.evidence_hash,
            membership_grant_id=membership_id,
            kind=kind,
        )
        .on_conflict_do_nothing(constraint="uq_historical_consolidation_work_version")
        .returning(RDBConsolidationWork.id)
    )
    return await session.write_session.scalar(statement)
