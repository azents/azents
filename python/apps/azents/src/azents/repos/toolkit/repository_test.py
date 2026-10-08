"""Toolkit repository tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.models.toolkit import RDBToolkitConfig
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.github_platform_system_setting.repository import (
    PlatformGitHubAppSystemSettingRepository,
)

from . import AgentToolkitRepository, ToolkitRepository
from .data import (
    EffectiveToolkitNamespaceMismatch,
    EffectiveToolkitNamespaceMissing,
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
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    _raw_session.flush.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().create(session, _toolkit_create())

    toolkit = _raw_session.add.call_args.args[0]
    assert isinstance(toolkit, RDBToolkitConfig)
    assert toolkit.revision == 1
    assert toolkit.always_expose_tools is False


async def test_update_increments_revision_once() -> None:
    """Increment persisted source revision once for a config update."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    _raw_session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().update_by_id(
            session,
            "toolkit-1",
            ToolkitUpdate(config={"url": "https://example.test"}),
        )

    statement = _raw_session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["config"] == {"url": "https://example.test"}


async def test_update_persists_always_expose_tools() -> None:
    """Persist the Toolkit-wide direct exposure policy."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    _raw_session.execute.side_effect = _StopAfterWrite

    with pytest.raises(_StopAfterWrite):
        await ToolkitRepository().update_by_id(
            session,
            "toolkit-1",
            ToolkitUpdate(always_expose_tools=True),
        )

    statement = _raw_session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["always_expose_tools"] is True
    assert compiled.params["revision_1"] == 1


async def test_update_credentials_increments_revision_once() -> None:
    """Increment persisted source revision once for a credential update."""
    _raw_session = AsyncMock(spec=AsyncSession)
    session = ReadWriteSession(_raw_session)
    cipher = MagicMock()
    cipher.encrypt.return_value = "encrypted"

    await ToolkitRepository(cipher=cipher).update_credentials(
        session,
        "toolkit-1",
        _Credentials(token="secret"),
    )

    statement = _raw_session.execute.call_args.args[0]
    compiled = statement.compile()
    assert compiled.params["revision_1"] == 1
    assert compiled.params["encrypted_credentials"] == "encrypted"


async def _seed_effective_toolkits(session: WriteSession) -> None:
    """Seed shared, owned, disabled, and corrupted attachment cases."""
    await session.write_session.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-effective', 'Effective', 'effective')
            """
        )
    )
    for agent_id in ("agent-effective-1", "agent-effective-2"):
        await session.write_session.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label, enabled, type,
                    memory_enabled
                )
                VALUES (
                    :agent_id,
                    'workspace-effective',
                    :agent_id,
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{
                        "label": "default",
                        "candidates": [{
                            "model_selection": {},
                            "settings": {
                                "context_window_tokens": null,
                                "max_output_tokens": null,
                                "builtin_tools": []
                            }
                        }],
                        "subagent_enabled": true,
                        "subagent_guidance": null
                    }]'::jsonb,
                    'default',
                    'default',
                    TRUE,
                    'public',
                    TRUE
                )
                """
            ),
            {"agent_id": agent_id},
        )
    await session.write_session.execute(
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
    await session.write_session.execute(
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
    await session.write_session.execute(
        sa.text(
            """
            INSERT INTO agent_toolkit_namespace_reservations (
                id, agent_id, toolkit_id, base_slug, ordinal, namespace
            )
            VALUES
                (
                    'namespace-effective-shared',
                    'agent-effective-1',
                    'toolkit-effective-shared',
                    'shared',
                    1,
                    'shared'
                ),
                (
                    'namespace-effective-owned-1',
                    'agent-effective-1',
                    'toolkit-effective-owned-1',
                    'private',
                    1,
                    'private'
                ),
                (
                    'namespace-effective-owned-2',
                    'agent-effective-2',
                    'toolkit-effective-owned-2',
                    'private',
                    1,
                    'private'
                ),
                (
                    'namespace-effective-disabled',
                    'agent-effective-1',
                    'toolkit-effective-disabled',
                    'disabled',
                    1,
                    'disabled'
                )
            """
        )
    )
    await session.write_session.flush()


async def test_effective_relation_unions_shared_and_owned_without_projection_leak(
    rdb_session: WriteSession,
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


async def test_effective_relation_allows_duplicate_slug_with_distinct_namespaces(
    rdb_session: WriteSession,
) -> None:
    """Return duplicate base Slugs through the durable namespace authority."""
    await _seed_effective_toolkits(rdb_session)
    await rdb_session.write_session.execute(
        sa.text(
            """
            UPDATE toolkit_configs
            SET slug = 'private'
            WHERE id = 'toolkit-effective-shared';

            UPDATE agent_toolkit_namespace_reservations
            SET base_slug = 'private', ordinal = 2, namespace = 'private_2'
            WHERE toolkit_id = 'toolkit-effective-shared'
            """
        )
    )

    effective = await ToolkitRepository().list_effective_for_agent(
        rdb_session,
        "agent-effective-1",
        workspace_id="workspace-effective",
    )

    assert [
        (item.toolkit.id, item.toolkit.slug, item.namespace) for item in effective
    ] == [
        ("toolkit-effective-shared", "private", "private_2"),
        ("toolkit-effective-owned-1", "private", "private"),
    ]


async def test_effective_relation_fails_closed_on_missing_namespace(
    rdb_session: WriteSession,
) -> None:
    """Reject an effective Toolkit whose Foundation authority is missing."""
    await _seed_effective_toolkits(rdb_session)
    await rdb_session.write_session.execute(
        sa.text(
            """
            DELETE FROM agent_toolkit_namespace_reservations
            WHERE toolkit_id = 'toolkit-effective-shared'
            """
        )
    )

    with pytest.raises(EffectiveToolkitNamespaceMissing) as exc_info:
        await ToolkitRepository().list_effective_for_agent(
            rdb_session,
            "agent-effective-1",
            workspace_id="workspace-effective",
        )

    assert exc_info.value.agent_id == "agent-effective-1"
    assert exc_info.value.toolkit_id == "toolkit-effective-shared"


async def test_effective_relation_fails_closed_on_stale_base_slug(
    rdb_session: WriteSession,
) -> None:
    """Reject a namespace mapping left stale by an older rolling writer."""
    await _seed_effective_toolkits(rdb_session)
    await rdb_session.write_session.execute(
        sa.text(
            """
            UPDATE toolkit_configs
            SET slug = 'renamed'
            WHERE id = 'toolkit-effective-shared'
            """
        )
    )

    with pytest.raises(EffectiveToolkitNamespaceMismatch) as exc_info:
        await ToolkitRepository().list_effective_for_agent(
            rdb_session,
            "agent-effective-1",
            workspace_id="workspace-effective",
        )

    assert exc_info.value.agent_id == "agent-effective-1"
    assert exc_info.value.toolkit_id == "toolkit-effective-shared"
    assert exc_info.value.toolkit_slug == "renamed"
    assert exc_info.value.reservation_base_slug == "shared"


async def test_platform_impact_counts_shared_and_direct_owner_agents(
    rdb_session: WriteSession,
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
