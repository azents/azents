"""Final database deletion boundary for a retention-purged Session tree."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextGitWorktree,
    RDBSessionAgentContextProject,
)


class SessionLifecycleFinalizerRepository:
    """Delete a fenced root tree only after participant cleanup is verified."""

    async def finalize_purged_root_tree(
        self,
        session: AsyncSession,
        *,
        root_session_id: str,
        session_ids: list[str],
    ) -> None:
        """Delete lifecycle-root rows in their restrictive ownership order."""
        root_session_agent_id = await session.scalar(
            sa.select(RDBSessionAgent.id).where(
                RDBSessionAgent.agent_session_id == root_session_id
            )
        )
        if root_session_agent_id is not None:
            context_ids = list(
                (
                    await session.scalars(
                        sa.select(RDBSessionAgent.context_id).where(
                            RDBSessionAgent.root_session_agent_id
                            == root_session_agent_id
                        )
                    )
                ).all()
            )
            if context_ids:
                await session.execute(
                    sa.delete(RDBSessionAgentContextGitWorktree).where(
                        RDBSessionAgentContextGitWorktree.session_agent_context_id.in_(
                            context_ids
                        )
                    )
                )
                await session.execute(
                    sa.delete(RDBSessionAgentContextProject).where(
                        RDBSessionAgentContextProject.session_agent_context_id.in_(
                            context_ids
                        )
                    )
                )
                await session.execute(
                    sa.update(RDBSessionAgentContext)
                    .where(RDBSessionAgentContext.id.in_(context_ids))
                    .values(root_session_agent_id=None)
                )
            await session.execute(
                sa.update(RDBSessionAgent)
                .where(
                    RDBSessionAgent.root_session_agent_id == root_session_agent_id,
                    RDBSessionAgent.parent_session_agent_id.is_not(None),
                )
                .values(parent_session_agent_id=None)
            )
            await session.execute(
                sa.delete(RDBSessionAgent).where(
                    RDBSessionAgent.id == root_session_agent_id
                )
            )
            if context_ids:
                await session.execute(
                    sa.delete(RDBSessionAgentContext).where(
                        RDBSessionAgentContext.id.in_(context_ids)
                    )
                )
        await session.execute(
            sa.delete(RDBAgentSession).where(RDBAgentSession.id.in_(session_ids))
        )
        await session.flush()
