"""Agent repository tests."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    SelectableModelOption,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)

from . import AgentRepository
from .data import AgentCreate, AgentUpdate


class _StopAfterWrite(Exception):
    """Stop a repository write after its mapped statement is observable."""


def _agent_create(*, tool_search_enabled: bool = True) -> AgentCreate:
    """Build one complete Agent repository create input."""
    selection = make_test_model_selection()
    option = SelectableModelOption(
        label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        model_selection=selection,
        settings=make_test_model_settings(),
    )
    return AgentCreate(
        workspace_id="workspace-1",
        name="Tool Search Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
        selectable_model_options=[option],
        main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
        tool_search_enabled=tool_search_enabled,
    )


async def test_create_uses_enabled_tool_search_default() -> None:
    """Map the repository create default instead of relying on the DB default."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().create(
            session,
            _agent_create(),
        )

    rdb_agent = session.add.call_args.args[0]
    assert isinstance(rdb_agent, RDBAgent)
    assert rdb_agent.tool_search_enabled is True


async def test_create_maps_explicit_tool_search_opt_out_to_rdb_agent() -> None:
    """Map an explicit Tool Search opt-out to the persisted Agent row."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().create(
            session,
            _agent_create(tool_search_enabled=False),
        )

    rdb_agent = session.add.call_args.args[0]
    assert isinstance(rdb_agent, RDBAgent)
    assert rdb_agent.tool_search_enabled is False


async def test_create_adds_initial_empty_automatic_project_policy() -> None:
    """Persist revision-one policy settings after inserting the Agent row."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = [None, _StopAfterWrite]

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().create(
            session,
            _agent_create(),
        )

    policy_setting = session.add.call_args_list[1].args[0]
    assert isinstance(policy_setting, RDBAgentAutomaticProjectSetting)
    assert policy_setting.agent_id == session.add.call_args_list[0].args[0].id
    assert policy_setting.revision == 1
    assert policy_setting.updated_by_workspace_user_id is None


async def test_update_maps_tool_search_enabled_to_update_statement() -> None:
    """Map an explicit update value into the persisted Agent row."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().update_by_id(
            session,
            "agent-1",
            AgentUpdate(tool_search_enabled=False),
        )

    statement = session.execute.call_args.args[0]
    assert statement.compile().params["tool_search_enabled"] is False
