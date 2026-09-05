"""Binding ownership and concurrency tests for External Channel Work state."""

import datetime
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import ExternalChannelWorkStatus
from azents.repos.external_channel.work_state import (
    ChannelWorkState,
    ChannelWorkStateMutation,
    ExternalChannelWorkStateStore,
)


@dataclass(frozen=True)
class _SeededBinding:
    """Committed relational identities for one binding ownership test."""

    workspace_id: str
    owner_agent_id: str
    other_agent_id: str
    owner_session_id: str
    other_session_id: str
    connection_id: str
    route_id: str
    resource_id: str
    binding_id: str


def _work(binding_id: str, *, title: str | None = None) -> ChannelWorkState:
    """Build one active Work payload."""
    return ChannelWorkState(
        schema_version=5,
        binding_id=binding_id,
        work_cycle_id=f"cycle-{binding_id}",
        status=ExternalChannelWorkStatus.ACTIVE,
        tracker_visibility="visible",
        slack_presence_thread_ts=None,
        slack_presence_initiator_user_id=None,
        title=title,
        tasks=[],
        state_revision=1,
        desired_progress_revision=0,
        desired_progress=None,
        awaiting_input_run_id=None,
        finished_at=None,
        projection_parts=[],
    )


async def _seed_binding(engine: AsyncEngine, *, suffix: str) -> _SeededBinding:
    """Commit one binding plus another valid AgentSession for isolation tests."""
    seeded = _SeededBinding(
        workspace_id=f"ws-{suffix}",
        owner_agent_id=f"agent-{suffix}-owner",
        other_agent_id=f"agent-{suffix}-other",
        owner_session_id=f"session-{suffix}-owner",
        other_session_id=f"session-{suffix}-other",
        connection_id=f"conn-{suffix}",
        route_id=f"route-{suffix}",
        resource_id=f"resource-{suffix}",
        binding_id=f"binding-{suffix}",
    )
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES (:id, :name, :handle)
                """
            ),
            {
                "id": seeded.workspace_id,
                "name": f"Work state {suffix}",
                "handle": f"work-state-{suffix}",
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label
                )
                VALUES
                    (
                        :owner_agent_id, :workspace_id, 'Owner Agent',
                        '{}'::jsonb, '{}'::jsonb,
                        '[
                            {"label": "main", "model_selection": {}},
                            {"label": "light", "model_selection": {}}
                        ]'::jsonb,
                        'main', 'light'
                    ),
                    (
                        :other_agent_id, :workspace_id, 'Other Agent',
                        '{}'::jsonb, '{}'::jsonb,
                        '[
                            {"label": "main", "model_selection": {}},
                            {"label": "light", "model_selection": {}}
                        ]'::jsonb,
                        'main', 'light'
                    )
                """
            ),
            {
                "owner_agent_id": seeded.owner_agent_id,
                "other_agent_id": seeded.other_agent_id,
                "workspace_id": seeded.workspace_id,
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO agent_sessions (
                    id, workspace_id, agent_id, handle, status, start_reason,
                    session_kind, product_mode
                )
                VALUES
                    (
                        :owner_session_id, :workspace_id, :owner_agent_id,
                        :owner_session_id, 'active', 'external_channel', 'root', 'team'
                    ),
                    (
                        :other_session_id, :workspace_id, :other_agent_id,
                        :other_session_id, 'active', 'external_channel', 'root', 'team'
                    )
                """
            ),
            {
                "owner_session_id": seeded.owner_session_id,
                "other_session_id": seeded.other_session_id,
                "workspace_id": seeded.workspace_id,
                "owner_agent_id": seeded.owner_agent_id,
                "other_agent_id": seeded.other_agent_id,
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_connections (
                    id, workspace_id, provider, transport, ingress_profile, status,
                    app_mode, provider_app_id, provider_tenant_id,
                    encrypted_credentials
                )
                VALUES (
                    :connection_id, :workspace_id, 'slack', 'http',
                    'slack_http', 'active', 'single', :provider_app_id,
                    :provider_tenant_id, 'ciphertext'
                )
                """
            ),
            {
                "connection_id": seeded.connection_id,
                "workspace_id": seeded.workspace_id,
                "provider_app_id": f"app-{suffix}",
                "provider_tenant_id": f"tenant-{suffix}",
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_agent_routes (
                    id, connection_id, agent_id, agent_id_snapshot, route_mode,
                    connection_app_mode, catalog_status
                )
                VALUES (
                    :route_id, :connection_id, :owner_agent_id, :owner_agent_id,
                    'dedicated', 'single', 'available'
                )
                """
            ),
            {
                "route_id": seeded.route_id,
                "connection_id": seeded.connection_id,
                "owner_agent_id": seeded.owner_agent_id,
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_resources (
                    id, connection_id, resource_type, provider_resource_key,
                    labels, status
                )
                VALUES (
                    :resource_id, :connection_id, 'thread', :provider_resource_key,
                    '{}'::jsonb,
                    'active'
                )
                """
            ),
            {
                "resource_id": seeded.resource_id,
                "connection_id": seeded.connection_id,
                "provider_resource_key": f"thread-{suffix}",
            },
        )
        await connection.execute(
            sa.text(
                """
                INSERT INTO external_channel_bindings (
                    id, resource_id, route_id, agent_session_id, response_mode
                )
                VALUES (
                    :binding_id, :resource_id, :route_id, :owner_session_id,
                    'all_messages'
                )
                """
            ),
            {
                "binding_id": seeded.binding_id,
                "resource_id": seeded.resource_id,
                "route_id": seeded.route_id,
                "owner_session_id": seeded.owner_session_id,
            },
        )
    return seeded


async def _cleanup_binding(engine: AsyncEngine, seeded: _SeededBinding) -> None:
    """Remove committed rows created outside the rollback fixture."""
    async with engine.begin() as connection:
        await connection.execute(
            sa.text(
                """
                DELETE FROM toolkit_states
                WHERE session_id IN (:owner_session_id, :other_session_id)
                """
            ),
            {
                "owner_session_id": seeded.owner_session_id,
                "other_session_id": seeded.other_session_id,
            },
        )
        await connection.execute(
            sa.text("DELETE FROM external_channel_bindings WHERE id = :id"),
            {"id": seeded.binding_id},
        )
        await connection.execute(
            sa.text("DELETE FROM external_channel_resources WHERE id = :id"),
            {"id": seeded.resource_id},
        )
        await connection.execute(
            sa.text("DELETE FROM external_channel_agent_routes WHERE id = :id"),
            {"id": seeded.route_id},
        )
        await connection.execute(
            sa.text("DELETE FROM external_channel_connections WHERE id = :id"),
            {"id": seeded.connection_id},
        )
        await connection.execute(
            sa.text(
                """
                DELETE FROM agent_sessions
                WHERE id IN (:owner_session_id, :other_session_id)
                """
            ),
            {
                "owner_session_id": seeded.owner_session_id,
                "other_session_id": seeded.other_session_id,
            },
        )
        await connection.execute(
            sa.text(
                """
                DELETE FROM agents
                WHERE id IN (:owner_agent_id, :other_agent_id)
                """
            ),
            {
                "owner_agent_id": seeded.owner_agent_id,
                "other_agent_id": seeded.other_agent_id,
            },
        )
        await connection.execute(
            sa.text("DELETE FROM workspaces WHERE id = :id"),
            {"id": seeded.workspace_id},
        )


async def test_work_state_rejects_non_owner_identity(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A valid unrelated AgentSession cannot host another binding's Work state."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix="ownership")
    store = ExternalChannelWorkStateStore()
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            for agent_id, session_id in (
                (seeded.other_agent_id, seeded.other_session_id),
                (seeded.owner_agent_id, seeded.other_session_id),
            ):
                with pytest.raises(ValueError, match="binding ownership"):
                    await store.update(
                        session,
                        agent_id=agent_id,
                        session_id=session_id,
                        binding_id=seeded.binding_id,
                        default_factory=lambda: _work(seeded.binding_id),
                        mutator=lambda current: ChannelWorkStateMutation(
                            state=current,
                            result=None,
                        ),
                    )
            await session.rollback()

        async with rdb_engine.connect() as connection:
            state_count = await connection.scalar(
                sa.text(
                    """
                    SELECT count(*)
                    FROM toolkit_states
                    WHERE state_name = :state_name
                    """
                ),
                {"state_name": f"channel_work:{seeded.binding_id}"},
            )
        assert state_count == 0
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_update_persists_absent_default_without_rewriting_existing_noop(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A no-op mutator creates its absent default but preserves an existing row."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix="default-noop")
    store = ExternalChannelWorkStateStore()
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            created = await store.update(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: _work(seeded.binding_id),
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current,
                    result=current,
                    changed=False,
                ),
            )
            await session.commit()

        assert created.result.work_cycle_id == f"cycle-{seeded.binding_id}"
        async with rdb_engine.connect() as connection:
            initial_version = await connection.scalar(
                sa.text(
                    """
                    SELECT version
                    FROM toolkit_states
                    WHERE state_name = :state_name
                    """
                ),
                {"state_name": f"channel_work:{seeded.binding_id}"},
            )
        assert initial_version == 1

        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            repeated = await store.update(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: _work(seeded.binding_id),
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current,
                    result=current,
                    changed=False,
                ),
            )
            await session.commit()

        assert repeated.result.work_cycle_id == f"cycle-{seeded.binding_id}"
        async with rdb_engine.connect() as connection:
            repeated_version = await connection.scalar(
                sa.text(
                    """
                    SELECT version
                    FROM toolkit_states
                    WHERE state_name = :state_name
                    """
                ),
                {"state_name": f"channel_work:{seeded.binding_id}"},
            )
        assert repeated_version == 1
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_work_state_cas_retry_refreshes_after_concurrent_writer(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A CAS retry reruns its mutator from another Session's committed state."""
    del latest_db_schema
    seeded = await _seed_binding(rdb_engine, suffix="concurrency")
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup_session:
            await ExternalChannelWorkStateStore().update(
                setup_session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: _work(seeded.binding_id),
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current,
                    result=None,
                ),
            )
            await setup_session.commit()

        async with (
            AsyncSession(rdb_engine, expire_on_commit=False) as first_session,
            AsyncSession(rdb_engine, expire_on_commit=False) as second_session,
        ):
            first_store = ExternalChannelWorkStateStore()
            second_store = ExternalChannelWorkStateStore()
            assert (
                await first_store.load(
                    first_session,
                    agent_id=seeded.owner_agent_id,
                    session_id=seeded.owner_session_id,
                    binding_id=seeded.binding_id,
                )
                is not None
            )

            def second_writer(
                current: ChannelWorkState,
            ) -> ChannelWorkStateMutation[None]:
                updated = current.model_copy(deep=True)
                updated.title = "second"
                updated.state_revision += 1
                return ChannelWorkStateMutation(state=updated, result=None)

            await second_store.update_existing(
                second_session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                mutator=second_writer,
            )
            await second_session.commit()

            def first_writer(
                current: ChannelWorkState,
            ) -> ChannelWorkStateMutation[None]:
                updated = current.model_copy(deep=True)
                updated.title = f"{current.title}+first"
                updated.state_revision += 1
                return ChannelWorkStateMutation(state=updated, result=None)

            await first_store.update_existing(
                first_session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                mutator=first_writer,
            )
            await first_session.commit()

        async with AsyncSession(rdb_engine, expire_on_commit=False) as verify_session:
            final = await ExternalChannelWorkStateStore().load(
                verify_session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
            )
            assert final is not None
            assert final.title == "second+first"
            assert final.state_revision == 3
    finally:
        await _cleanup_binding(rdb_engine, seeded)


def test_work_state_requires_schema_version_five_and_tracker_fields() -> None:
    """Payload validation fails closed for unsupported schema versions."""
    with pytest.raises(ValidationError):
        ChannelWorkState.model_validate(
            {
                **_work("binding-schema").model_dump(mode="json"),
                "schema_version": 1,
            }
        )
    with pytest.raises(ValidationError):
        ChannelWorkState.model_validate(
            {
                key: value
                for key, value in _work("binding-missing-schema")
                .model_dump(mode="json")
                .items()
                if key != "schema_version"
            }
        )
    with pytest.raises(ValidationError):
        ChannelWorkState.model_validate(
            {
                **_work("binding-visibility").model_dump(mode="json"),
                "tracker_visibility": "unknown",
            }
        )
    with pytest.raises(ValidationError):
        ChannelWorkState.model_validate(
            {
                key: value
                for key, value in _work("binding-missing-visibility")
                .model_dump(mode="json")
                .items()
                if key != "tracker_visibility"
            }
        )
    projected = _work("binding-host-kind").model_dump(mode="json")
    projected["projection_parts"] = [
        {
            "part_ordinal": 0,
            "desired_progress_revision": 1,
            "status": "present",
            "provider_message_key": "discord:111:555",
            "host_kind": "unknown",
        }
    ]
    with pytest.raises(ValidationError):
        ChannelWorkState.model_validate(projected)


def test_finished_work_cannot_await_participant_input() -> None:
    """Awaiting input remains orthogonal only while Work is active."""
    work = _work("binding-finished-awaiting").model_copy(deep=True)
    work.status = ExternalChannelWorkStatus.FINISHED
    work.finished_at = datetime.datetime(2026, 8, 31, tzinfo=datetime.UTC)
    work.awaiting_input_run_id = "run-1"

    with pytest.raises(
        ValidationError,
        match="Finished Channel Work cannot await participant input",
    ):
        ChannelWorkState.model_validate(work.model_dump(mode="json"))


def test_awaiting_input_requires_nonempty_run_identity() -> None:
    """An established awaiting marker always identifies its requesting Run."""
    with pytest.raises(ValidationError, match="at least 1 character"):
        ChannelWorkState.model_validate(
            {
                **_work("binding-empty-awaiting").model_dump(mode="json"),
                "awaiting_input_run_id": "",
            }
        )
