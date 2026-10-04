"""Toolkit namespace allocation repository tests."""

import asyncio

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session_capabilities import (
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.toolkit_namespace import ToolkitNamespaceRepository
from azents.repos.toolkit_namespace_data import AgentToolkitNamespaceReservation


async def _seed_namespace_fixture(session: WriteSession) -> None:
    await session.write_session.execute(
        sa.text(
            """
            INSERT INTO workspaces (id, name, handle)
            VALUES ('workspace-namespace', 'Namespace', 'namespace')
            """
        )
    )
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
                'agent-namespace',
                'workspace-namespace',
                'Namespace Agent',
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
        )
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
                    'toolkit-namespace-a',
                    'workspace-namespace',
                    NULL,
                    'mcp',
                    'stored_a',
                    'A',
                    '{}'::jsonb,
                    TRUE
                ),
                (
                    'toolkit-namespace-b',
                    'workspace-namespace',
                    NULL,
                    'mcp',
                    'stored_b',
                    'B',
                    '{}'::jsonb,
                    TRUE
                ),
                (
                    'toolkit-namespace-c',
                    'workspace-namespace',
                    NULL,
                    'mcp',
                    'stored_c',
                    'C',
                    '{}'::jsonb,
                    TRUE
                )
            """
        )
    )
    await session.write_session.flush()


async def test_allocation_skips_cross_base_namespace_collision(
    rdb_session: WriteSession,
) -> None:
    """Consume another base's exact namespace instead of overwriting it."""
    await _seed_namespace_fixture(rdb_session)
    repository = ToolkitNamespaceRepository()

    first = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="mcp",
    )
    explicit_suffix = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-b",
        base_slug="mcp_2",
    )
    second = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-c",
        base_slug="mcp",
    )

    assert (first.namespace, first.ordinal) == ("mcp", 1)
    assert (explicit_suffix.namespace, explicit_suffix.ordinal) == ("mcp_2", 1)
    assert (second.namespace, second.ordinal) == ("mcp_3", 3)


async def test_retired_namespace_is_not_reused(rdb_session: WriteSession) -> None:
    """Keep the old final name reserved after a Toolkit changes base Slug."""
    await _seed_namespace_fixture(rdb_session)
    repository = ToolkitNamespaceRepository()

    original = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="mcp",
    )
    replacement = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="other",
    )
    next_toolkit = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-b",
        base_slug="mcp",
    )

    assert original.namespace == "mcp"
    assert replacement.namespace == "other"
    assert next_toolkit.namespace == "mcp_2"
    retired_toolkit_id = await rdb_session.read_session.scalar(
        sa.text(
            """
            SELECT toolkit_id
            FROM agent_toolkit_namespace_reservations
            WHERE agent_id = 'agent-namespace' AND namespace = 'mcp'
            """
        )
    )
    assert retired_toolkit_id is None


async def test_matching_active_reservation_is_reused(
    rdb_session: WriteSession,
) -> None:
    """Return the same reservation for detach/reattach-style reconciliation."""
    await _seed_namespace_fixture(rdb_session)
    repository = ToolkitNamespaceRepository()

    first = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="mcp",
    )
    reused = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="mcp",
    )

    assert reused == first
    count = await rdb_session.read_session.scalar(
        sa.text(
            """
            SELECT COUNT(*)
            FROM agent_toolkit_namespace_reservations
            WHERE agent_id = 'agent-namespace'
            """
        )
    )
    assert count == 1


async def test_toolkit_delete_retires_reservation_via_foreign_key(
    rdb_session: WriteSession,
) -> None:
    """Clear the active mapping while retaining the reserved namespace."""
    await _seed_namespace_fixture(rdb_session)
    repository = ToolkitNamespaceRepository()
    reservation = await repository.ensure_active(
        rdb_session,
        agent_id="agent-namespace",
        toolkit_id="toolkit-namespace-a",
        base_slug="mcp",
    )

    await rdb_session.write_session.execute(
        sa.text("DELETE FROM toolkit_configs WHERE id = 'toolkit-namespace-a'")
    )
    await rdb_session.write_session.flush()

    row = (
        await rdb_session.write_session.execute(
            sa.text(
                """
                SELECT toolkit_id, namespace
                FROM agent_toolkit_namespace_reservations
                WHERE id = :reservation_id
                """
            ),
            {"reservation_id": reservation.id},
        )
    ).one()
    assert row == (None, "mcp")


async def test_distinct_toolkits_claim_unique_namespace_and_reuse_without_agent_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Competing identities serialize only allocation; a matching reuse is a read."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    repository = ToolkitNamespaceRepository()
    async with manager() as session:
        await _seed_namespace_fixture(session)
    try:

        async def allocate(toolkit_id: str) -> AgentToolkitNamespaceReservation:
            async with manager() as session:
                return await repository.ensure_active(
                    session,
                    agent_id="agent-namespace",
                    toolkit_id=toolkit_id,
                    base_slug="duplicate",
                )

        first, second = await asyncio.gather(
            allocate("toolkit-namespace-a"), allocate("toolkit-namespace-b")
        )
        assert {first.namespace, second.namespace} == {"duplicate", "duplicate_2"}
        async with manager() as holder:
            await holder.write_session.execute(
                sa.select(RDBAgent.id)
                .where(RDBAgent.id == "agent-namespace")
                .with_for_update()
            )
            async with asyncio.timeout(5):
                reused = await allocate("toolkit-namespace-a")
            assert reused.id == first.id
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBAgent).where(RDBAgent.id == "agent-namespace")
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == "workspace-namespace")
            )
