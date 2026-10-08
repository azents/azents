"""Read-only due-unit discovery for routing common Memory execution Sessions."""

import dataclasses
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends

from azents.core.enums import AgentLifecycleStatus
from azents.core.historical_memory_consolidation import ConsolidationUnitKey
from azents.rdb.deps import get_read_only_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.historical_memory_execution import RDBMemoryUnit, RDBMemoryWork
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession


@dataclasses.dataclass(frozen=True)
class ConsolidationDiscoveryRepository:
    """Observe pending domain work without claiming an independent owner lease."""

    session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]

    async def list_due(
        self, *, agent_id: str | None, limit: int
    ) -> tuple[ConsolidationUnitKey, ...]:
        async with self.session_manager() as session:
            pending = sa.exists(
                sa.select(RDBMemoryWork.id).where(
                    RDBMemoryWork.unit_id == RDBMemoryUnit.id
                )
            )
            membership = sa.exists(
                sa.select(RDBWorkspaceUser.id).where(
                    RDBWorkspaceUser.workspace_id == RDBMemoryUnit.workspace_id,
                    RDBWorkspaceUser.user_id == RDBMemoryUnit.associated_user_id,
                )
            )
            query = (
                sa.select(
                    RDBMemoryUnit.workspace_id,
                    RDBMemoryUnit.agent_id,
                    RDBMemoryUnit.scope,
                    RDBMemoryUnit.associated_user_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBMemoryUnit.agent_id)
                .where(
                    pending,
                    RDBAgent.workspace_id == RDBMemoryUnit.workspace_id,
                    RDBAgent.lifecycle_status == AgentLifecycleStatus.ACTIVE,
                    RDBAgent.enabled.is_(True),
                    RDBAgent.memory_enabled.is_(True),
                    sa.or_(RDBMemoryUnit.associated_user_id.is_(None), membership),
                    sa.or_(
                        RDBMemoryUnit.retry_at.is_(None),
                        RDBMemoryUnit.retry_at <= sa.func.clock_timestamp(),
                    ),
                )
                .order_by(
                    RDBMemoryUnit.workspace_id,
                    RDBMemoryUnit.agent_id,
                    RDBMemoryUnit.scope,
                    RDBMemoryUnit.associated_user_id,
                )
                .limit(limit)
            )
            if agent_id is not None:
                query = query.where(RDBMemoryUnit.agent_id == agent_id)
            return tuple(
                ConsolidationUnitKey(
                    workspace_id=workspace_id,
                    agent_id=current_agent_id,
                    scope=scope,
                    associated_user_id=user_id,
                )
                for workspace_id, current_agent_id, scope, user_id in (
                    await session.read_session.execute(query)
                ).all()
            )
