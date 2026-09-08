"""Toolkit repository tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)

from . import AgentToolkitRepository, ToolkitRepository
from .data import (
    EffectiveToolkitSlugConflict,
    EffectiveToolkitSource,
    ToolkitCreate,
    ToolkitUpdate,
)


class _StopAfterWrite(Exception):
    """Stop a repository write after its mapped statement is observable."""


class _Credentials(BaseModel):
    """Test toolkit credentials."""

    token: str


def _toolkit_create() -> ToolkitCreate:
    """Build a complete Toolkit repository create input."""
    return ToolkitCreate(
        workspace_id="workspace-1",
        owner_agent_id=None,
        toolkit_type="mcp",
        slug="toolkit",
        name="Toolkit",
        config={},
        always_expose_tools=False,
    )


async def test_create_initializes_revision_to_one() -> None:
    """Map the initial persisted source revision on creation."""
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().create(session, _toolkit_create())

    toolkit = session.add.call_args.args[0]
    assert isinstance(toolkit, RDBToolkitConfig)
    assert toolkit.revision == 1
    assert toolkit.always_expose_tools is False


async def test_update_increments_revision_once() -> None:
    """Increment persisted source revision once for a config update."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().update_by_id(
            session,
            "toolkit-1",
            ToolkitUpdate(config={"url": "https://example.test"}),
        )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["config"] == {"url": "https://example.test"}


async def test_update_persists_always_expose_tools() -> None:
    """Persist the Toolkit-wide direct exposure policy."""
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().update_by_id(
            session,
            "toolkit-1",
            ToolkitUpdate(always_expose_tools=True),
        )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["always_expose_tools"] is True
    assert compiled.params["revision_1"] == 1


async def test_update_credentials_increments_revision_once() -> None:
    """Increment persisted source revision once for a credential update."""
    session = AsyncMock(spec=AsyncSession)
    cipher = MagicMock()
    cipher.encrypt.return_value = "encrypted"

    await ToolkitRepository(cipher=cipher).update_credentials(
        session,
        "toolkit-1",
        _Credentials(token="secret"),
    )

    statement = session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["encrypted_credentials"] == "encrypted"


async def _seed_effective_toolkits(session: AsyncSession) -> None:
    """Seed shared, owned, disabled, and corrupted attachment cases."""
    await session.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-effective', 'Effective', 'effective')
            """
        )
    )
    for agent_id in ("agent-effective-1", "agent-effective-2"):
        await session.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label
                )
                VALUES (
                    :agent_id,
                    'workspace-effective',
                    :agent_id,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{"label":"default","model_selection":{}}]'::jsonb,
                    'default',
                    'default'
                )
                """
            ),
            {"agent_id": agent_id},
        )
    await session.execute(
        sa.text(
            """
            INSERT INTO toolkit_configs (
                id, workspace_id, owner_agent_id, toolkit_type, slug, name, config,
                enabled
            )
            VALUES
                (
                    'toolkit-effective-shared',
                    'workspace-effective',
                    NULL,
                    'mcp',
                    'shared',
                    'Shared',
                    '{}'::jsonb,
                    true
                ),
                (
                    'toolkit-effective-owned-1',
                    'workspace-effective',
                    'agent-effective-1',
                    'mcp',
                    'private',
                    'Owned 1',
                    '{}'::jsonb,
                    true
                ),
                (
                    'toolkit-effective-owned-2',
                    'workspace-effective',
                    'agent-effective-2',
                    'mcp',
                    'private',
                    'Owned 2',
                    '{}'::jsonb,
                    true
                ),
                (
                    'toolkit-effective-disabled',
                    'workspace-effective',
                    'agent-effective-1',
                    'mcp',
                    'disabled',
                    'Disabled',
                    '{}'::jsonb,
                    false
                )
            """
        )
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO agent_toolkits (
                id, agent_id, toolkit_id, toolkit_type
            )
            VALUES
                (
                    'attachment-effective-shared',
                    'agent-effective-1',
                    'toolkit-effective-shared',
                    'mcp'
                ),
                (
                    'attachment-corrupt-owned',
                    'agent-effective-2',
                    'toolkit-effective-owned-1',
                    'mcp'
                )
            """
        )
    )
    await session.flush()


async def test_effective_relation_unions_shared_and_owned_without_projection_leak(
    rdb_session: AsyncSession,
) -> None:
    """Return direct owners and shared attachments while ignoring invalid projection."""
    await _seed_effective_toolkits(rdb_session)
    repository = ToolkitRepository()

    agent_one = await repository.list_effective_for_agent(
        rdb_session,
        "agent-effective-1",
        workspace_id="workspace-effective",
    )
    assert [
        (item.toolkit.id, item.source, item.agent_toolkit_id) for item in agent_one
    ] == [
        (
            "toolkit-effective-shared",
            EffectiveToolkitSource.SHARED_ATTACHMENT,
            "attachment-effective-shared",
        ),
        (
            "toolkit-effective-owned-1",
            EffectiveToolkitSource.AGENT_OWNED,
            None,
        ),
    ]

    agent_two = await repository.list_effective_for_agent(
        rdb_session,
        "agent-effective-2",
        workspace_id="workspace-effective",
    )
    assert [item.toolkit.id for item in agent_two] == ["toolkit-effective-owned-2"]
    attachments = await AgentToolkitRepository().list_by_agent(
        rdb_session,
        "agent-effective-2",
    )
    assert attachments == []
    assert (
        await AgentToolkitRepository().get_by_id(
            rdb_session,
            "attachment-corrupt-owned",
        )
        is None
    )

    shared = await repository.list_by_workspace(
        rdb_session,
        "workspace-effective",
    )
    assert [toolkit.id for toolkit in shared] == ["toolkit-effective-shared"]


async def test_effective_relation_fails_closed_on_duplicate_slug(
    rdb_session: AsyncSession,
) -> None:
    """Reject cross-source duplicate slugs before a consumer sees partial state."""
    await _seed_effective_toolkits(rdb_session)
    await rdb_session.execute(
        sa.text(
            """
            UPDATE toolkit_configs
            SET slug = 'private'
            WHERE id = 'toolkit-effective-shared'
            """
        )
    )

    with pytest.raises(EffectiveToolkitSlugConflict) as exc_info:
        await ToolkitRepository().list_effective_for_agent(
            rdb_session,
            "agent-effective-1",
            workspace_id="workspace-effective",
        )

    assert exc_info.value.agent_id == "agent-effective-1"
    assert exc_info.value.slug == "private"
    assert exc_info.value.toolkit_ids == (
        "toolkit-effective-owned-1",
        "toolkit-effective-shared",
    )


async def test_platform_impact_counts_shared_and_direct_owner_agents(
    rdb_session: AsyncSession,
) -> None:
    """Count the canonical enabled effective relation for Platform impact."""
    await _seed_effective_toolkits(rdb_session)

    count = await PlatformGitHubAppSystemSettingRepository().count_agents_for_toolkits(
        rdb_session,
        toolkit_ids={
            "toolkit-effective-shared",
            "toolkit-effective-owned-1",
            "toolkit-effective-owned-2",
            "toolkit-effective-disabled",
        },
    )

    assert count == 2
