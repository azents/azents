"""Real database ownership checks for independent semantic destinations."""

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.external_channel.action_operations import (
    ExternalChannelActionOperations,
)
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
)


async def test_navigation_is_bound_to_current_session_and_agent_owned_service(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    suffix = uuid4().hex[:10]
    seeded = await _seed_binding(rdb_engine, suffix=suffix)
    service_id = uuid4().hex
    foreign_id = uuid4().hex
    operations = ExternalChannelActionOperations(
        session_manager=create_read_write_session_manager(rdb_engine),
        read_only_session_manager=create_read_only_session_manager(rdb_engine),
        repository=ExternalChannelWorkRepository(),
        execution_owner=None,
    )
    try:
        async with rdb_engine.begin() as connection:
            await connection.execute(
                sa.text("""
                INSERT INTO runtime_web_services
                    (id, workspace_id, agent_id, port, hostname_key)
                VALUES (:id, :workspace, :agent, :port, :host)
            """),
                [
                    {
                        "id": service_id,
                        "workspace": seeded.workspace_id,
                        "agent": seeded.owner_agent_id,
                        "port": 3000,
                        "host": suffix + "a",
                    },
                    {
                        "id": foreign_id,
                        "workspace": seeded.workspace_id,
                        "agent": seeded.other_agent_id,
                        "port": 3000,
                        "host": suffix + "b",
                    },
                ],
            )
        context = await operations.navigation_context(
            session_id=seeded.owner_session_id,
            agent_id=seeded.owner_agent_id,
            binding_id=seeded.binding_id,
            service_ids=[service_id],
        )
        assert context.service_hosts == {service_id: suffix + "a"}
        assert context.workspace_handle == f"work-state-{suffix}"
        for target in [foreign_id, uuid4().hex]:
            with pytest.raises(ValueError, match="target is unavailable"):
                await operations.navigation_context(
                    session_id=seeded.owner_session_id,
                    agent_id=seeded.owner_agent_id,
                    binding_id=seeded.binding_id,
                    service_ids=[target],
                )
        with pytest.raises(ValueError, match="scope is unavailable"):
            await operations.navigation_context(
                session_id=seeded.other_session_id,
                agent_id=seeded.other_agent_id,
                binding_id=seeded.binding_id,
                service_ids=[],
            )
        async with rdb_engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE external_channel_bindings "
                    "SET disconnected_at = now() WHERE id = :id"
                ),
                {"id": seeded.binding_id},
            )
        with pytest.raises(ValueError, match="scope is unavailable"):
            await operations.navigation_context(
                session_id=seeded.owner_session_id,
                agent_id=seeded.owner_agent_id,
                binding_id=seeded.binding_id,
                service_ids=[],
            )
    finally:
        async with rdb_engine.begin() as connection:
            await connection.execute(
                sa.text("DELETE FROM runtime_web_services WHERE id IN (:a, :b)"),
                {"a": service_id, "b": foreign_id},
            )
        await _cleanup_binding(rdb_engine, seeded)
