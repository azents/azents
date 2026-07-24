"""Agent automatic Project policy repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.agent_automatic_project_item import (
    RDBAgentAutomaticProjectItem,
)
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)

from .data import (
    AgentAutomaticProjectPolicy,
    AgentAutomaticProjectPolicyRevisionConflict,
)


class AgentAutomaticProjectRepository:
    """Persist revisioned ordered Project policies for automatic root Sessions."""

    async def get_policy(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentAutomaticProjectPolicy | None:
        """Fetch one policy from a single statement-level database snapshot."""
        result = await session.execute(
            sa.select(
                RDBAgentAutomaticProjectSetting,
                RDBAgentAutomaticProjectItem.path,
            )
            .outerjoin(
                RDBAgentAutomaticProjectItem,
                RDBAgentAutomaticProjectItem.agent_id
                == RDBAgentAutomaticProjectSetting.agent_id,
            )
            .where(RDBAgentAutomaticProjectSetting.agent_id == agent_id)
            .order_by(RDBAgentAutomaticProjectItem.position.asc())
            .execution_options(populate_existing=True)
        )
        rows = result.all()
        if not rows:
            return None
        setting = rows[0][0]
        return AgentAutomaticProjectPolicy(
            agent_id=setting.agent_id,
            revision=setting.revision,
            project_paths=tuple(path for _, path in rows if path is not None),
            updated_by_workspace_user_id=setting.updated_by_workspace_user_id,
            created_at=setting.created_at,
            updated_at=setting.updated_at,
        )

    async def lock_policy(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
    ) -> AgentAutomaticProjectPolicy | None:
        """Lock and fetch one Agent automatic Project policy."""
        result = await session.execute(
            sa.select(RDBAgentAutomaticProjectSetting)
            .where(RDBAgentAutomaticProjectSetting.agent_id == agent_id)
            .with_for_update()
        )
        setting = result.scalar_one_or_none()
        if setting is None:
            return None
        return await self._build_policy(session, setting)

    async def replace_policy(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        expected_revision: int,
        paths: list[str],
        updated_by_workspace_user_id: str,
    ) -> Result[
        AgentAutomaticProjectPolicy,
        AgentAutomaticProjectPolicyRevisionConflict,
    ]:
        """Atomically replace a policy when its revision precondition matches."""
        setting_result = await session.execute(
            sa.update(RDBAgentAutomaticProjectSetting)
            .where(
                RDBAgentAutomaticProjectSetting.agent_id == agent_id,
                RDBAgentAutomaticProjectSetting.revision == expected_revision,
            )
            .values(
                revision=RDBAgentAutomaticProjectSetting.revision + 1,
                updated_by_workspace_user_id=updated_by_workspace_user_id,
                updated_at=sa.func.now(),
            )
            .returning(RDBAgentAutomaticProjectSetting)
        )
        setting = setting_result.scalar_one_or_none()
        if setting is None:
            return Failure(
                AgentAutomaticProjectPolicyRevisionConflict(
                    agent_id=agent_id,
                    expected_revision=expected_revision,
                )
            )

        await session.execute(
            sa.delete(RDBAgentAutomaticProjectItem).where(
                RDBAgentAutomaticProjectItem.agent_id == agent_id,
            )
        )
        session.add_all(
            [
                RDBAgentAutomaticProjectItem(
                    agent_id=agent_id,
                    path=path,
                    position=position,
                )
                for position, path in enumerate(paths)
            ]
        )
        await session.flush()
        return Success(
            AgentAutomaticProjectPolicy(
                agent_id=setting.agent_id,
                revision=setting.revision,
                project_paths=tuple(paths),
                updated_by_workspace_user_id=setting.updated_by_workspace_user_id,
                created_at=setting.created_at,
                updated_at=setting.updated_at,
            )
        )

    async def _build_policy(
        self,
        session: AsyncSession,
        setting: RDBAgentAutomaticProjectSetting,
    ) -> AgentAutomaticProjectPolicy:
        """Build one policy snapshot from a settings row and ordered items."""
        item_result = await session.execute(
            sa.select(RDBAgentAutomaticProjectItem.path)
            .where(RDBAgentAutomaticProjectItem.agent_id == setting.agent_id)
            .order_by(RDBAgentAutomaticProjectItem.position.asc())
        )
        return AgentAutomaticProjectPolicy(
            agent_id=setting.agent_id,
            revision=setting.revision,
            project_paths=tuple(item_result.scalars()),
            updated_by_workspace_user_id=setting.updated_by_workspace_user_id,
            created_at=setting.created_at,
            updated_at=setting.updated_at,
        )
