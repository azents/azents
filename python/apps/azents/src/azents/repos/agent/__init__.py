"""Agent repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, ModelParameters
from azents.core.enums import AgentType
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.services.uploads.schema import StoredImage

from .data import (
    Agent,
    AgentCreate,
    AgentList,
    AgentUpdate,
    NotFound,
)

_params_adapter = TypeAdapter[ModelParameters](ModelParameters)
_model_selection_adapter = TypeAdapter[AgentModelSelection](AgentModelSelection)


class AgentRepository:
    """Agent CRUD repository."""

    async def create(
        self,
        session: AsyncSession,
        create: AgentCreate,
    ) -> Agent:
        """Create Agent."""
        params_dict = (
            create.model_parameters.model_dump(mode="json", exclude_none=True)
            if create.model_parameters is not None
            else None
        )
        rdb_agent = RDBAgent(
            workspace_id=create.workspace_id,
            name=create.name,
            model_selection=create.model_selection.model_dump(mode="json"),
            lightweight_model_selection=(
                create.lightweight_model_selection.model_dump(mode="json")
            ),
            description=create.description,
            model_parameters=params_dict,
            system_prompt=create.system_prompt,
            enabled=create.enabled,
            type=create.type,
            runtime_provider_id=create.runtime_provider_id,
            shell_enabled=create.shell_enabled,
            memory_enabled=create.memory_enabled,
            max_turns=create.max_turns,
        )
        session.add(rdb_agent)
        await session.flush()
        return self._build_row(rdb_agent)

    async def get_by_id(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Fetch Agent by ID."""
        rdb_agent = await session.get(RDBAgent, agent_id)
        if rdb_agent is None:
            return None
        return self._build_row(rdb_agent)

    async def list_by_workspace(
        self, session: AsyncSession, workspace_id: str
    ) -> AgentList:
        """Fetch all Agents in workspace."""
        result = await session.execute(
            sa.select(RDBAgent)
            .where(RDBAgent.workspace_id == workspace_id)
            .order_by(RDBAgent.created_at.desc())
        )
        rows = result.scalars().all()
        return AgentList(items=[self._build_row(r) for r in rows])

    async def list_visible_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: str,
        workspace_user_id: str,
    ) -> AgentList:
        """Fetch Agents queryable in workspace."""
        admin_exists = (
            sa.select(sa.literal(1))
            .select_from(RDBAgentAdmin)
            .where(
                RDBAgentAdmin.agent_id == RDBAgent.id,
                RDBAgentAdmin.workspace_user_id == workspace_user_id,
            )
            .correlate(RDBAgent)
            .exists()
        )
        result = await session.execute(
            sa.select(RDBAgent)
            .where(
                RDBAgent.workspace_id == workspace_id,
                sa.or_(
                    RDBAgent.type == AgentType.PUBLIC,
                    admin_exists,
                ),
            )
            .order_by(RDBAgent.created_at.desc())
        )
        rows = result.scalars().all()
        return AgentList(items=[self._build_row(r) for r in rows])

    async def update_by_id(
        self,
        session: AsyncSession,
        agent_id: str,
        update: AgentUpdate,
    ) -> Result[Agent, NotFound]:
        """Update Agent by ID."""
        if not update:
            agent = await self.get_by_id(session, agent_id)
            if agent is None:
                return Failure(NotFound(agent_id=agent_id))
            return Success(agent)

        db_values: dict[str, object] = {}
        if "name" in update:
            db_values["name"] = update["name"]
        if "description" in update:
            db_values["description"] = update["description"]
        if "model_selection" in update:
            db_values["model_selection"] = update["model_selection"].model_dump(
                mode="json"
            )
        if "lightweight_model_selection" in update:
            db_values["lightweight_model_selection"] = update[
                "lightweight_model_selection"
            ].model_dump(mode="json")
        if "model_parameters" in update:
            params = update["model_parameters"]
            db_values["model_parameters"] = (
                params.model_dump(mode="json", exclude_none=True)
                if params is not None
                else None
            )
        if "system_prompt" in update:
            db_values["system_prompt"] = update["system_prompt"]
        if "enabled" in update:
            db_values["enabled"] = update["enabled"]
        if "type" in update:
            db_values["type"] = update["type"]
        if "runtime_provider_id" in update:
            db_values["runtime_provider_id"] = update["runtime_provider_id"]
        if "shell_enabled" in update:
            db_values["shell_enabled"] = update["shell_enabled"]
        if "memory_enabled" in update:
            db_values["memory_enabled"] = update["memory_enabled"]
        if "max_turns" in update:
            db_values["max_turns"] = update["max_turns"]

        await session.execute(
            sa.update(RDBAgent).where(RDBAgent.id == agent_id).values(**db_values)
        )
        rdb_agent = await session.get(RDBAgent, agent_id)
        if rdb_agent is None:
            return Failure(NotFound(agent_id=agent_id))
        return Success(self._build_row(rdb_agent))

    async def delete_by_id(self, session: AsyncSession, agent_id: str) -> None:
        """Delete Agent by ID."""
        await session.execute(sa.delete(RDBAgent).where(RDBAgent.id == agent_id))

    def _build_row(self, rdb: RDBAgent) -> Agent:
        """Convert RDB row to domain model."""
        model_parameters = (
            _params_adapter.validate_python(rdb.model_parameters)
            if rdb.model_parameters is not None
            else None
        )
        model_selection = _model_selection_adapter.validate_python(rdb.model_selection)
        lightweight_model_selection = _model_selection_adapter.validate_python(
            rdb.lightweight_model_selection
        )
        avatar = (
            StoredImage.model_validate(rdb.avatar) if rdb.avatar is not None else None
        )
        return Agent(
            id=rdb.id,
            workspace_id=rdb.workspace_id,
            name=rdb.name,
            description=rdb.description,
            model_selection=model_selection,
            lightweight_model_selection=lightweight_model_selection,
            model_parameters=model_parameters,
            system_prompt=rdb.system_prompt,
            enabled=rdb.enabled,
            type=rdb.type,
            runtime_provider_id=rdb.runtime_provider_id,
            shell_enabled=rdb.shell_enabled,
            memory_enabled=rdb.memory_enabled,
            max_turns=rdb.max_turns,
            avatar=avatar,
            created_at=rdb.created_at,
            updated_at=rdb.updated_at,
        )

    async def update_avatar(
        self,
        session: AsyncSession,
        agent_id: str,
        avatar: StoredImage | None,
    ) -> Result[Agent, NotFound]:
        """Update only Agent avatar field."""
        avatar_dict = avatar.model_dump(mode="json") if avatar is not None else None
        stmt = (
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(avatar=avatar_dict)
            .returning(RDBAgent.id)
        )
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            return Failure(NotFound(agent_id=agent_id))

        rdb_agent = await session.get(RDBAgent, agent_id)
        if rdb_agent is None:
            return Failure(NotFound(agent_id=agent_id))
        return Success(self._build_row(rdb_agent))
