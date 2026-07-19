"""Agent repository tests."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    SelectableModelOption,
)
from azents.rdb.models.agent import RDBAgent
from azents.testing.model_selection import (
    make_test_model_selection,
    make_test_model_settings,
)

from . import AgentRepository
from .data import AgentCreate, AgentUpdate


class _StopAfterWrite(Exception):
    """Stop a repository write after its mapped statement is observable."""


def _agent_create(*, tool_search_enabled: bool) -> AgentCreate:
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


async def test_create_maps_tool_search_enabled_to_rdb_agent() -> None:
    """Map the explicit create value instead of relying on the DB default."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().create(
            session,
            _agent_create(tool_search_enabled=True),
        )

    rdb_agent = session.add.call_args.args[0]
    assert isinstance(rdb_agent, RDBAgent)
    assert rdb_agent.tool_search_enabled is True


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
