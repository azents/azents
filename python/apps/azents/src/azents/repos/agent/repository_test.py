"""Agent repository tests."""

import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    SelectableModelOption,
)
from azents.core.enums import AgentRuntimeCapability, ExternalChannelResponseMode
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_avatar_cleanup import RDBAgentAvatarCleanupJob
from azents.services.uploads.schema import (
    StoredImage,
    StoredImageFile,
    StoredImageThumbnails,
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
        runtime_profile_id=None,
        runtime_capability=AgentRuntimeCapability.MANAGED,
        external_channel_default_response_mode=(
            ExternalChannelResponseMode.ALL_MESSAGES
        ),
        tool_search_enabled=tool_search_enabled,
    )


def _avatar(key: str) -> StoredImage:
    """Build one stored avatar snapshot."""
    file = StoredImageFile(
        key=key,
        content_type="image/webp",
        size_bytes=1,
        width=512,
        height=512,
    )
    return StoredImage(
        filename="avatar.webp",
        default=file,
        thumbnails=StoredImageThumbnails(large=file),
        original=None,
        uploaded_at=datetime.datetime.now(datetime.UTC),
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


async def test_create_does_not_add_legacy_execution_setting() -> None:
    """Do not reactivate the legacy execution-policy selection path."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = [None, _StopAfterWrite]

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().create(
            session,
            _agent_create(),
        )

    assert len(session.add.call_args_list) == 2


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


async def test_runtime_capability_compare_and_set_maps_version_fence() -> None:
    """Map the capability transition and optimistic version into SQL."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().compare_and_set_runtime_capability(
            session,
            agent_id="agent-1",
            expected_capability=AgentRuntimeCapability.MANAGED,
            expected_capability_version=3,
            expected_runtime_profile_selection_version=7,
            capability=AgentRuntimeCapability.REMOVING,
            runtime_profile_id=None,
        )

    statement = session.execute.call_args.args[0]
    params = statement.compile().params
    assert params["runtime_capability_1"] is AgentRuntimeCapability.MANAGED
    assert params["runtime_capability_version_1"] == 1
    assert params["runtime_capability_version_2"] == 3
    assert params["runtime_capability"] is AgentRuntimeCapability.REMOVING
    assert params["runtime_profile_selection_version_1"] == 1
    assert params["runtime_profile_selection_version_2"] == 7
    assert params["runtime_profile_id"] is None


async def test_update_avatar_locks_agent_and_enqueues_prior_snapshot() -> None:
    """Avatar mutation takes an exclusive row lock before snapshotting state."""
    session = AsyncMock(spec=AsyncSession)
    old_avatar = _avatar("public/avatar/agent-1/large/old.webp")
    new_avatar = _avatar("public/avatar/agent-1/large/new.webp")
    row = RDBAgent(
        workspace_id="workspace-1",
        name="Avatar Agent",
        model_selection=make_test_model_selection().model_dump(mode="json"),
        lightweight_model_selection=make_test_model_selection().model_dump(mode="json"),
        avatar=old_avatar.model_dump(mode="json"),
    )
    result = Mock()
    result.scalar_one_or_none.return_value = row
    session.execute.return_value = result
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await AgentRepository().update_avatar(session, row.id, new_avatar)

    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in sql
    cleanup_job = session.add.call_args.args[0]
    assert isinstance(cleanup_job, RDBAgentAvatarCleanupJob)
    assert cleanup_job.agent_id == row.id
    assert cleanup_job.avatar == old_avatar.model_dump(mode="json")
