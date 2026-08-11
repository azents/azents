"""Agent repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    AgentModelSelection,
    ModelParameters,
    SelectableModelOption,
    SubagentSettings,
)
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentRuntimeCapability,
    AgentType,
    ExternalChannelResponseMode,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_admin import RDBAgentAdmin
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.services.uploads.schema import StoredImage

from .data import (
    Agent,
    AgentCreate,
    AgentList,
    AgentUpdate,
    NotFound,
)

_params_adapter = TypeAdapter[ModelParameters](ModelParameters)
_subagent_settings_adapter = TypeAdapter[SubagentSettings](SubagentSettings)
_model_selection_adapter = TypeAdapter[AgentModelSelection](AgentModelSelection)
_selectable_model_options_adapter = TypeAdapter[list[SelectableModelOption]](
    list[SelectableModelOption]
)


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
            selectable_model_options=[
                option.model_dump(mode="json")
                for option in create.selectable_model_options
            ],
            main_model_label=create.main_model_label,
            lightweight_model_label=create.lightweight_model_label,
            description=create.description,
            model_parameters=params_dict,
            system_prompt=create.system_prompt,
            enabled=create.enabled,
            external_channel_default_response_mode=(
                create.external_channel_default_response_mode
            ),
            type=create.type,
            runtime_profile_id=create.runtime_profile_id,
            runtime_capability=create.runtime_capability,
            shell_enabled=create.shell_enabled,
            memory_enabled=create.memory_enabled,
            tool_search_enabled=create.tool_search_enabled,
            max_turns=create.max_turns,
            auto_archive_ttl_days=create.auto_archive_ttl_days,
            subagent_settings=create.subagent_settings.model_dump(mode="json"),
        )
        session.add(rdb_agent)
        await session.flush()
        session.add(RDBAgentAutomaticProjectSetting(agent_id=rdb_agent.id))
        await session.flush()
        return self._build_row(rdb_agent)

    async def get_by_id(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Fetch Agent by ID."""
        rdb_agent = await session.get(RDBAgent, agent_id)
        if rdb_agent is None:
            return None
        return self._build_row(rdb_agent)

    async def lock_by_id(self, session: AsyncSession, agent_id: str) -> Agent | None:
        """Lock one Agent for transactional lifecycle validation."""
        result = await session.execute(
            sa.select(RDBAgent)
            .where(RDBAgent.id == agent_id)
            # Admission and write reauthorization only validate lifecycle and
            # ownership columns, so FOR NO KEY UPDATE is sufficient.
            .with_for_update(key_share=True)
        )
        rdb_agent = result.scalar_one_or_none()
        if rdb_agent is None:
            return None
        return self._build_row(rdb_agent)

    async def get_runtime_selection_input_for_update(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        """Fetch one Agent while serializing Runtime Profile selection."""
        result = await session.execute(
            sa.select(RDBAgent)
            .where(RDBAgent.id == agent_id)
            # SQLAlchemy renders key_share=True as PostgreSQL
            # ``FOR NO KEY UPDATE`` unless read=True is also supplied. This
            # blocks selection-column updates while allowing FK KEY SHARE
            # locks taken by independent Runtime-state writes.
            .with_for_update(key_share=True)
        )
        rdb_agent = result.scalar_one_or_none()
        if rdb_agent is None:
            return None
        return self._build_row(rdb_agent)

    async def compare_and_set_runtime_capability(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        expected_capability: AgentRuntimeCapability,
        expected_capability_version: int,
        expected_runtime_profile_selection_version: int,
        capability: AgentRuntimeCapability,
        runtime_profile_id: str | None,
        shell_enabled: bool,
    ) -> Agent | None:
        """Replace Runtime authority and Profile selection under both fences."""
        result = await session.execute(
            sa.update(RDBAgent)
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.runtime_capability == expected_capability,
                RDBAgent.runtime_capability_version == expected_capability_version,
                RDBAgent.runtime_profile_selection_version
                == expected_runtime_profile_selection_version,
            )
            .values(
                runtime_capability=capability,
                runtime_capability_version=RDBAgent.runtime_capability_version + 1,
                runtime_profile_id=runtime_profile_id,
                runtime_profile_selection_version=(
                    RDBAgent.runtime_profile_selection_version + 1
                ),
                shell_enabled=shell_enabled,
                updated_at=sa.func.now(),
            )
            .returning(RDBAgent)
        )
        rdb_agent = result.scalar_one_or_none()
        await session.flush()
        return self._build_row(rdb_agent) if rdb_agent is not None else None

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
        if "selectable_model_options" in update:
            db_values["selectable_model_options"] = [
                option.model_dump(mode="json")
                for option in update["selectable_model_options"]
            ]
        if "main_model_label" in update:
            db_values["main_model_label"] = update["main_model_label"]
        if "lightweight_model_label" in update:
            db_values["lightweight_model_label"] = update["lightweight_model_label"]
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
        if "shell_enabled" in update:
            db_values["shell_enabled"] = update["shell_enabled"]
        if "memory_enabled" in update:
            db_values["memory_enabled"] = update["memory_enabled"]
        if "tool_search_enabled" in update:
            db_values["tool_search_enabled"] = update["tool_search_enabled"]
        if "max_turns" in update:
            db_values["max_turns"] = update["max_turns"]
        if "auto_archive_ttl_days" in update:
            db_values["auto_archive_ttl_days"] = update["auto_archive_ttl_days"]
        if "subagent_settings" in update:
            db_values["subagent_settings"] = update["subagent_settings"].model_dump(
                mode="json"
            )

        await session.execute(
            sa.update(RDBAgent).where(RDBAgent.id == agent_id).values(**db_values)
        )
        rdb_agent = await session.get(RDBAgent, agent_id)
        if rdb_agent is None:
            return Failure(NotFound(agent_id=agent_id))
        return Success(self._build_row(rdb_agent))

    async def replace_runtime_profile_selection(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        expected_version: int,
        runtime_profile_id: str | None,
    ) -> Agent | None:
        """Replace one Agent selection with optimistic version fencing."""
        result = await session.execute(
            sa.update(RDBAgent)
            .where(
                RDBAgent.id == agent_id,
                RDBAgent.runtime_profile_selection_version == expected_version,
            )
            .values(
                runtime_profile_id=runtime_profile_id,
                runtime_profile_selection_version=(
                    RDBAgent.runtime_profile_selection_version + 1
                ),
                updated_at=sa.func.now(),
            )
            .returning(RDBAgent)
        )
        rdb_agent = result.scalar_one_or_none()
        await session.flush()
        return self._build_row(rdb_agent) if rdb_agent is not None else None

    async def update_external_channel_default_response_mode(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        response_mode: ExternalChannelResponseMode,
    ) -> Agent | None:
        """Replace the default copied to subsequently created channel bindings."""
        result = await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(external_channel_default_response_mode=response_mode)
            .returning(RDBAgent)
        )
        rdb_agent = result.scalar_one_or_none()
        await session.flush()
        return self._build_row(rdb_agent) if rdb_agent is not None else None

    async def mark_decommissioning(
        self,
        session: AsyncSession,
        agent_id: str,
    ) -> Agent | None:
        """Fence an Agent from new work for durable decommission."""
        result = await session.execute(
            sa.update(RDBAgent)
            .where(RDBAgent.id == agent_id)
            .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
            .returning(RDBAgent)
        )
        rdb = result.scalar_one_or_none()
        if rdb is None:
            return None
        await session.flush()
        return self._build_row(rdb)

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
        selectable_model_options = _selectable_model_options_adapter.validate_python(
            rdb.selectable_model_options
        )
        if rdb.main_model_label is None or rdb.lightweight_model_label is None:
            msg = "Agent selectable model labels are missing"
            raise ValueError(msg)
        subagent_settings = _subagent_settings_adapter.validate_python(
            rdb.subagent_settings
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
            selectable_model_options=selectable_model_options,
            main_model_label=rdb.main_model_label,
            lightweight_model_label=rdb.lightweight_model_label,
            model_parameters=model_parameters,
            system_prompt=rdb.system_prompt,
            enabled=rdb.enabled,
            external_channel_default_response_mode=(
                rdb.external_channel_default_response_mode
            ),
            lifecycle_status=rdb.lifecycle_status,
            type=rdb.type,
            runtime_profile_id=rdb.runtime_profile_id,
            runtime_profile_selection_version=(rdb.runtime_profile_selection_version),
            runtime_capability=rdb.runtime_capability,
            runtime_capability_version=rdb.runtime_capability_version,
            shell_enabled=rdb.shell_enabled,
            memory_enabled=rdb.memory_enabled,
            tool_search_enabled=rdb.tool_search_enabled,
            max_turns=rdb.max_turns,
            auto_archive_ttl_days=rdb.auto_archive_ttl_days,
            subagent_settings=subagent_settings,
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
