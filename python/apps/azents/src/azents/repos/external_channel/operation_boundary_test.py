"""Real PostgreSQL proof for Channel Work state and exact ingress claims."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    ExternalChannelActionMode,
    ExternalChannelAppMode,
    ExternalChannelDeliveryOperation,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelResponseMode,
    ExternalChannelTransport,
    ExternalChannelWorkTaskStatus,
)
from azents.core.external_channel_progress import ExternalChannelWorkTask
from azents.core.external_channel_provider_effect import ProviderMutationOutcome
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelInteraction,
    RDBExternalChannelResource,
)
from azents.rdb.models.external_channel_ingress import RDBExternalChannelIngressOwner
from azents.rdb.session_capabilities import (
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.external_channel.data import ExternalChannelBinding
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressLeaseClaim,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.external_channel.work_data import ChannelActionEffectPlan
from azents.repos.external_channel.work_state import (
    ChannelWorkStateMutation,
    ExternalChannelWorkStateStore,
)
from azents.repos.external_channel.work_state_test import (
    _cleanup_binding,
    _seed_binding,
    _work,
)
from azents.testing.external_channel import make_provider_effect_plan


@pytest.mark.parametrize("held", ["connection", "route"])
async def test_multi_disconnect_impact_is_plain_under_held_owner(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    held: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    lifecycle = ExternalChannelLifecycleRepository()
    try:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelConnection)
                .where(RDBExternalChannelConnection.id == seeded.connection_id)
                .values(app_mode=ExternalChannelAppMode.MULTI)
            )
            await session.write_session.execute(
                sa.update(RDBExternalChannelAgentRoute)
                .where(RDBExternalChannelAgentRoute.id == seeded.route_id)
                .values(connection_app_mode=ExternalChannelAppMode.MULTI)
            )
        async with AsyncSession(rdb_engine) as holder:
            query = (
                sa.select(RDBExternalChannelConnection)
                .where(RDBExternalChannelConnection.id == seeded.connection_id)
                .with_for_update()
                if held == "connection"
                else sa.select(RDBExternalChannelAgentRoute)
                .where(RDBExternalChannelAgentRoute.id == seeded.route_id)
                .with_for_update()
            )
            assert await holder.scalar(query) is not None
            async with reads() as session:
                impact = await asyncio.wait_for(
                    lifecycle.project_multi_connection_impact(
                        session, connection_id=seeded.connection_id
                    ),
                    timeout=2,
                )
                assert impact is not None
                assert impact.active_route_count == 1
                assert impact.active_binding_count == 1
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_private_interaction_projection_updates_without_read_gate(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = ExternalChannelRepository()
    interaction_id = None
    now = datetime.now(UTC)
    try:
        async with writes() as session:
            interaction = RDBExternalChannelInteraction(
                connection_id=seeded.connection_id,
                transport=ExternalChannelTransport.HTTP,
                provider_interaction_key=uuid4().hex,
                interaction_type=ExternalChannelInteractionType.SHORTCUT,
                callback_id=None,
                action_id=None,
                principal_id=None,
                setup_claim_id=None,
                resource_correlation_key=None,
                projection={"source": "opaque"},
                status=ExternalChannelInteractionStatus.ACCEPTED,
                expires_at=now + timedelta(minutes=10),
                error_kind=None,
                error_summary=None,
            )
            session.write_session.add(interaction)
            await session.write_session.flush()
            interaction_id = interaction.id
            await session.write_session.execute(
                sa.update(RDBExternalChannelInteraction)
                .where(RDBExternalChannelInteraction.id == interaction_id)
                .values(updated_at=now - timedelta(days=1))
            )
        async with writes() as session:
            async with AsyncSession(rdb_engine) as holder:
                assert (
                    await holder.scalar(
                        sa.select(RDBExternalChannelInteraction)
                        .where(RDBExternalChannelInteraction.id == interaction_id)
                        .with_for_update()
                    )
                    is not None
                )
                observed = await asyncio.wait_for(
                    repository.get_interaction(session, interaction_id=interaction_id),
                    timeout=2,
                )
                assert observed is not None
                assert observed.projection == {"source": "opaque"}
            unchanged = await repository.replace_interaction_projection(
                session,
                interaction_id=interaction_id,
                projection={"source": "opaque"},
            )
            assert unchanged is not None
            assert unchanged.updated_at == now - timedelta(days=1)
        async with writes() as session:
            changed = await repository.replace_interaction_projection(
                session,
                interaction_id=interaction_id,
                projection={"source": "current"},
            )
            assert changed is not None
            assert changed.projection == {"source": "current"}
            assert changed.updated_at > unchanged.updated_at
    finally:
        if interaction_id is not None:
            async with writes() as session:
                await session.write_session.execute(
                    sa.delete(RDBExternalChannelInteraction).where(
                        RDBExternalChannelInteraction.id == interaction_id
                    )
                )
        await _cleanup_binding(rdb_engine, seeded)


async def test_binding_response_mode_update_retains_expected_mode_timestamp_predicates(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = ExternalChannelRepository()
    barrier = asyncio.Barrier(2)
    try:
        async with writes() as session:
            expected_updated_at = await session.read_session.scalar(
                sa.select(RDBExternalChannelBinding.updated_at).where(
                    RDBExternalChannelBinding.id == seeded.binding_id
                )
            )
        assert expected_updated_at is not None
        async with writes() as session:
            same = await repository.update_connected_binding_response_mode(
                session,
                binding_id=seeded.binding_id,
                expected_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                expected_updated_at=expected_updated_at,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            )
            assert same is not None
            assert same.updated_at == expected_updated_at

        async def update() -> ExternalChannelBinding | None:
            async with writes() as session:
                await barrier.wait()
                return await repository.update_connected_binding_response_mode(
                    session,
                    binding_id=seeded.binding_id,
                    expected_response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                    expected_updated_at=expected_updated_at,
                    response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                )

        outcomes = await asyncio.wait_for(asyncio.gather(update(), update()), timeout=3)
        assert sum(outcome is not None for outcome in outcomes) == 1
        winner = next(outcome for outcome in outcomes if outcome is not None)
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelBinding)
                .where(RDBExternalChannelBinding.id == seeded.binding_id)
                .values(disconnected_at=datetime.now(UTC), updated_at=winner.updated_at)
            )
        async with writes() as session:
            assert (
                await repository.update_connected_binding_response_mode(
                    session,
                    binding_id=seeded.binding_id,
                    expected_response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                    expected_updated_at=winner.updated_at,
                    response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                )
                is None
            )
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_direct_work_commits_under_held_session_owner_row(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    repository = ExternalChannelWorkRepository()
    try:
        async with writes() as session:
            await session.write_session.execute(
                sa.update(RDBExternalChannelResource)
                .where(RDBExternalChannelResource.id == seeded.resource_id)
                .values(labels={"channel_id": "C1", "thread_ts": "1.0"})
            )
            await repository.work_state_store.update(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: _work(seeded.binding_id),
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current, result=None
                ),
            )
        async with AsyncSession(rdb_engine) as holder:
            assert (
                await holder.scalar(
                    sa.select(RDBAgentSession)
                    .where(RDBAgentSession.id == seeded.owner_session_id)
                    .with_for_update(key_share=True)
                )
                is not None
            )
            async with writes() as session:
                observed = await asyncio.wait_for(
                    repository.list_active_work(
                        session,
                        session_id=seeded.owner_session_id,
                        agent_id=seeded.owner_agent_id,
                    ),
                    timeout=2,
                )
                assert len(observed) == 1
                transition = await asyncio.wait_for(
                    repository.commit_direct_action(
                        session,
                        session_id=seeded.owner_session_id,
                        agent_id=seeded.owner_agent_id,
                        run_id=None,
                        client_tool_call_id="metadata-update",
                        binding_id=seeded.binding_id,
                        mode=ExternalChannelActionMode.CONTINUE,
                        message=None,
                        title="Current work...",
                        tasks=[
                            ExternalChannelWorkTask(
                                id="current-task",
                                title="Current task",
                                status=ExternalChannelWorkTaskStatus.IN_PROGRESS,
                                details=None,
                                output=None,
                                sources=[],
                            )
                        ],
                        files=[],
                        now=datetime.now(UTC),
                    ),
                    timeout=2,
                )
                assert transition.work_id
    finally:
        await _cleanup_binding(rdb_engine, seeded)


@pytest.mark.parametrize("change", ["cycle", "revision"])
async def test_delayed_tracker_outcome_cannot_overwrite_new_work(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
    change: str,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    store = ExternalChannelWorkStateStore()
    initial = _work(seeded.binding_id)
    provider = make_provider_effect_plan("delayed-outcome")
    provider = replace(
        provider,
        target=replace(
            provider.target,
            agent_id=seeded.owner_agent_id,
            agent_session_id=seeded.owner_session_id,
            binding_id=seeded.binding_id,
            resource_id=seeded.resource_id,
            operation=ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
        ),
    )
    effect = ChannelActionEffectPlan(
        provider=provider,
        part=0,
        work_cycle_id=initial.work_cycle_id,
        expected_desired_progress_revision=0,
        dependencies=(),
        projection_host_kind="standalone",
    )
    try:
        async with writes() as session:
            await store.update(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                default_factory=lambda: initial,
                mutator=lambda current: ChannelWorkStateMutation(
                    state=current, result=None
                ),
            )
        changed = initial.model_copy(
            update={
                "work_cycle_id": "replacement-cycle"
                if change == "cycle"
                else initial.work_cycle_id,
                "desired_progress_revision": 1 if change == "revision" else 0,
                "title": "Replacement",
                "state_revision": 2,
            }
        )
        async with writes() as session:
            await store.update_existing(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
                mutator=lambda current: ChannelWorkStateMutation(
                    state=changed, result=None
                ),
            )
        async with writes() as session:
            assert (
                not await ExternalChannelWorkRepository().apply_direct_effect_outcome(
                    session,
                    effect=effect,
                    outcome=ProviderMutationOutcome(
                        status="delivered",
                        provider_message_key="obsolete-message",
                        error_kind=None,
                        error_summary=None,
                    ),
                )
            )
            current = await store.load(
                session,
                agent_id=seeded.owner_agent_id,
                session_id=seeded.owner_session_id,
                binding_id=seeded.binding_id,
            )
            assert current == changed
    finally:
        await _cleanup_binding(rdb_engine, seeded)


async def test_ingress_claim_has_one_winner_and_reclaimed_owner_rejects_late_worker(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    writes = create_read_write_session_manager(rdb_engine)
    reads = create_read_only_session_manager(rdb_engine)
    seeded = await _seed_binding(rdb_engine, suffix=uuid4().hex[:10])
    queue = ExternalChannelIngressQueueRepository()
    now = datetime.now(UTC)
    barrier = asyncio.Barrier(2)
    async with writes() as session:
        owner = RDBExternalChannelIngressOwner(
            connection_id=seeded.connection_id,
            target_resource_id=seeded.resource_id,
            route_id=seeded.route_id,
            participation_setting_id=None,
            participation_settings_generation=None,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            binding_id=seeded.binding_id,
            session_id=seeded.owner_session_id,
        )
        session.write_session.add(owner)
        await session.write_session.flush()
        owner_id = owner.id

    async def claim(worker: str) -> ExternalChannelIngressLeaseClaim | None:
        async with writes() as session:
            await barrier.wait()
            return await queue.claim_lease(
                session,
                owner_id=owner_id,
                lease_owner=worker,
                now=now,
                lease_expires_at=now + timedelta(minutes=1),
            )

    try:
        candidates = await asyncio.wait_for(
            asyncio.gather(claim("first"), claim("second")), timeout=3
        )
        winners = [candidate for candidate in candidates if candidate is not None]
        assert len(winners) == 1
        old = winners[0]
        assert old.owner.lease_owner is not None
        async with AsyncSession(rdb_engine) as holder:
            assert (
                await holder.scalar(
                    sa.select(RDBExternalChannelIngressOwner)
                    .where(RDBExternalChannelIngressOwner.id == owner_id)
                    .with_for_update()
                )
                is not None
            )
            async with reads() as session:
                observed = await asyncio.wait_for(
                    queue.get_active_owner(session, owner_id=owner_id), timeout=2
                )
                assert observed is not None
                assert observed.lease_generation == old.owner.lease_generation
                await asyncio.wait_for(
                    queue.inspect_active(session, now=now, limit=10), timeout=2
                )
        async with writes() as session:
            next_claim = await queue.claim_lease(
                session,
                owner_id=owner_id,
                lease_owner="replacement",
                now=now + timedelta(minutes=2),
                lease_expires_at=now + timedelta(minutes=3),
            )
            assert next_claim is not None
            assert next_claim.owner.lease_generation == old.owner.lease_generation + 1
        async with writes() as session:
            assert (
                await queue.lock_leased_owner(
                    session,
                    owner_id=owner_id,
                    lease_owner=old.owner.lease_owner,
                    lease_generation=old.owner.lease_generation,
                    now=now + timedelta(minutes=2),
                )
                is None
            )
    finally:
        async with writes() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelIngressOwner).where(
                    RDBExternalChannelIngressOwner.id == owner_id
                )
            )
        await _cleanup_binding(rdb_engine, seeded)
