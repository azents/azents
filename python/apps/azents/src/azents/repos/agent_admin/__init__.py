"""AgentAdmin repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from azcommon.sqlalchemy.postgres import is_constrained_by
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_admin import RDBAgentAdmin

from .data import AgentAdmin, AgentAdminCreate, AgentAdminList, DuplicateAdmin


class AgentAdminRepository:
    """AgentAdmin CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentAdminCreate,
    ) -> Result[AgentAdmin, DuplicateAdmin]:
        """Create AgentAdmin.

        :param session: Database session
        :param create: Create data
        :return: Created AgentAdmin or error
        """
        try:
            rdb = RDBAgentAdmin(
                agent_id=create.agent_id,
                workspace_user_id=create.workspace_user_id,
            )
            session.add(rdb)
            await session.flush()
            return Success(self._build(rdb))
        except IntegrityError as e:
            await session.rollback()
            if is_constrained_by(e, RDBAgentAdmin.UQ_AGENT_WORKSPACE_USER):
                return Failure(
                    DuplicateAdmin(
                        agent_id=create.agent_id,
                        workspace_user_id=create.workspace_user_id,
                    )
                )
            raise

    async def list_by_agent(
        self, session: AsyncSession, agent_id: str
    ) -> AgentAdminList:
        """Fetch admin list for Agent.

        :param session: Database session
        :param agent_id: Agent ID
        :return: AgentAdmin list
        """
        result = await session.execute(
            sa.select(RDBAgentAdmin)
            .where(RDBAgentAdmin.agent_id == agent_id)
            .order_by(RDBAgentAdmin.created_at.asc())
        )
        rdbs = result.scalars().all()
        return AgentAdminList(items=[self._build(r) for r in rdbs])

    async def is_admin(
        self, session: AsyncSession, agent_id: str, workspace_user_id: str
    ) -> bool:
        """Check whether specific WorkspaceUser is admin of Agent.

        :param session: Database session
        :param agent_id: Agent ID
        :param workspace_user_id: WorkspaceUser ID
        :return: True when admin
        """
        result = await session.execute(
            sa.select(sa.func.count())
            .select_from(RDBAgentAdmin)
            .where(
                RDBAgentAdmin.agent_id == agent_id,
                RDBAgentAdmin.workspace_user_id == workspace_user_id,
            )
        )
        return result.scalar_one() > 0

    async def count_by_agent(self, session: AsyncSession, agent_id: str) -> int:
        """Count Agent admins.

        :param session: Database session
        :param agent_id: Agent ID
        :return: Admin count
        """
        result = await session.execute(
            sa.select(sa.func.count())
            .select_from(RDBAgentAdmin)
            .where(RDBAgentAdmin.agent_id == agent_id)
        )
        return result.scalar_one()

    async def delete(
        self,
        session: AsyncSession,
        agent_id: str,
        workspace_user_id: str,
    ) -> bool:
        """Delete AgentAdmin.

        :param session: Database session
        :param agent_id: Agent ID
        :param workspace_user_id: WorkspaceUser ID
        :return: True when a row was deleted
        """
        result = await session.execute(
            sa.delete(RDBAgentAdmin).where(
                RDBAgentAdmin.agent_id == agent_id,
                RDBAgentAdmin.workspace_user_id == workspace_user_id,
            )
        )
        return result.rowcount > 0  # type: ignore[union-attr]  # CursorResult has rowcount

    def _build(self, rdb: RDBAgentAdmin) -> AgentAdmin:
        """Convert RDB model to domain model."""
        return AgentAdmin(
            id=rdb.id,
            agent_id=rdb.agent_id,
            workspace_user_id=rdb.workspace_user_id,
            created_at=rdb.created_at,
        )
