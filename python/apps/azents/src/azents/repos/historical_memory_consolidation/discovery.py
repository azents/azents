"""Bounded metadata-only due-unit reconciliation, independent of Redis and Runtime."""

from dataclasses import dataclass

import sqlalchemy as sa

from azents.core.enums import AgentLifecycleStatus
from azents.core.historical_memory_consolidation import (
    ConsolidationUnitKey,
    ConsolidationWorkState,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_consolidation import (
    RDBConsolidationUnit,
    RDBConsolidationWork,
)
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.historical_memory_consolidation.authority import (
    consolidation_session,
    database_now,
)


@dataclass(frozen=True)
class ConsolidationDiscoveryRepository:
    """Eligibility before dispatch; claim and every later operation reauthorize."""

    session_manager: SessionManager[WriteSession]

    async def list_due(
        self, *, agent_id: str | None, limit: int
    ) -> tuple[ConsolidationUnitKey, ...]:
        if not 1 <= limit <= 100:
            raise ValueError("Consolidation discovery page bounds are invalid.")
        async with consolidation_session(self.session_manager) as session:
            now = await database_now(session)
            query = (
                sa.select(
                    RDBConsolidationWork.workspace_id,
                    RDBConsolidationWork.agent_id,
                    RDBConsolidationWork.scope,
                    RDBConsolidationWork.associated_user_id,
                )
                .join(
                    RDBAgent,
                    sa.and_(
                        RDBAgent.id == RDBConsolidationWork.agent_id,
                        RDBAgent.workspace_id == RDBConsolidationWork.workspace_id,
                    ),
                )
                .outerjoin(
                    RDBConsolidationUnit,
                    sa.and_(
                        RDBConsolidationUnit.workspace_id
                        == RDBConsolidationWork.workspace_id,
                        RDBConsolidationUnit.agent_id == RDBConsolidationWork.agent_id,
                        RDBConsolidationUnit.scope == RDBConsolidationWork.scope,
                        RDBConsolidationUnit.associated_user_id.is_not_distinct_from(
                            RDBConsolidationWork.associated_user_id
                        ),
                    ),
                )
                .where(
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBAgent.memory_enabled.is_(True),
                    RDBConsolidationWork.state.in_(
                        [
                            ConsolidationWorkState.PENDING,
                            ConsolidationWorkState.CONSIDERED,
                        ]
                    ),
                    sa.or_(
                        RDBConsolidationUnit.lease_until.is_(None),
                        RDBConsolidationUnit.lease_until <= now,
                    ),
                    sa.or_(
                        RDBConsolidationUnit.retry_at.is_(None),
                        RDBConsolidationUnit.retry_at <= now,
                    ),
                    sa.or_(
                        RDBConsolidationWork.associated_user_id.is_(None),
                        sa.select(RDBWorkspaceUser.user_id)
                        .where(
                            RDBWorkspaceUser.workspace_id
                            == RDBConsolidationWork.workspace_id,
                            RDBWorkspaceUser.user_id
                            == RDBConsolidationWork.associated_user_id,
                        )
                        .exists(),
                    ),
                )
                .distinct()
                .order_by(
                    RDBConsolidationWork.workspace_id,
                    RDBConsolidationWork.agent_id,
                    RDBConsolidationWork.scope,
                    RDBConsolidationWork.associated_user_id,
                )
                .limit(limit)
            )
            if agent_id is not None:
                query = query.where(RDBConsolidationWork.agent_id == agent_id)
            rows = (await session.write_session.execute(query)).all()
            result = tuple(
                ConsolidationUnitKey(
                    workspace_id=workspace,
                    agent_id=agent,
                    scope=scope,
                    associated_user_id=user,
                )
                for workspace, agent, scope, user in rows
            )
        return result
