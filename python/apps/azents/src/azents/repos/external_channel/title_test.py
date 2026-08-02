"""External Channel automatic title repository tests."""

import asyncio
import datetime
from collections.abc import Sequence
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    EventKind,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelDiscordThreadTitleProofKind,
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSessionTitleCandidateStatus,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelDiscordThreadTitleProjection,
    RDBExternalChannelIngressLease,
    RDBExternalChannelResource,
    RDBExternalChannelSessionTitleCandidate,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.runtime_profile import RDBWorkspaceRuntimeProfile
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelDiscordThreadTitleProjection,
    ExternalChannelDiscordThreadTitleProjectionCreate,
    ExternalChannelResourceCreate,
    ExternalChannelSessionTitleCandidateCreate,
)
from azents.repos.external_channel.lifecycle import ExternalChannelLifecycleRepository
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.title import ExternalChannelTitleRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


@dataclass(frozen=True)
class _TitleFixture:
    """Identifiers for one persisted External Channel automatic-title state."""

    connection_id: str
    resource_id: str
    binding_id: str
    agent_session_id: str
    candidate_id: str
    projection_id: str


def _at(minute: int) -> datetime.datetime:
    """Return a stable timezone-aware test timestamp."""
    return datetime.datetime(2026, 8, 2, 0, minute, tzinfo=datetime.UTC)


async def _create_title_fixture(
    session: AsyncSession,
    *,
    suffix: str,
    app_mode: ExternalChannelAppMode = ExternalChannelAppMode.SINGLE,
) -> _TitleFixture:
    """Create the real foreign-key graph needed by one title projection."""
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name=f"Title repository test {suffix}",
            handle=f"title-repository-{suffix}",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        f"title-repository-{suffix}",
    )
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"title-repository-integration-{suffix}",
        encrypted_credentials="encrypted",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"title-repository-model-{suffix}",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name=f"Title repository agent {suffix}",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    session.add(agent)
    await session.flush()
    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )

    external_channel_repository = ExternalChannelRepository()
    connection = await external_channel_repository.create_connection(
        session,
        ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.DISCORD,
            transport=ExternalChannelTransport.HTTP,
            app_mode=app_mode,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_app_id=f"title-app-{suffix}",
            provider_tenant_id=f"title-guild-{suffix}",
            provider_bot_user_id=f"title-bot-{suffix}",
            http_callback_selector_hash=f"title-selector-{suffix}",
            encrypted_credentials="ciphertext",
            capabilities=None,
            provider_config=None,
            last_verified_at=_at(0),
            last_health_at=_at(0),
            disconnected_at=None,
            socket_lease_owner=None,
            socket_lease_until=None,
            socket_heartbeat_at=None,
            socket_gap_detected_at=None,
            socket_gap_reason=None,
        ),
    )
    route = await external_channel_repository.create_agent_route(
        session,
        ExternalChannelAgentRouteCreate(
            connection_id=connection.id,
            agent_id=agent.id,
            agent_id_snapshot=agent.id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
            connection_app_mode=app_mode,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
            catalog_removed_at=None,
            catalog_removed_by_user_id=None,
        ),
    )
    resource = await external_channel_repository.create_resource_idempotent(
        session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key=f"discord:title:{suffix}",
            labels={
                "guild_id": f"title-guild-{suffix}",
                "parent_channel_id": f"title-parent-{suffix}",
                "root_message_id": f"title-root-{suffix}",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(0),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    binding = await external_channel_repository.create_binding_idempotent(
        session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=route.id,
            agent_session_id=agent_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )

    title_repository = ExternalChannelTitleRepository()
    candidate = await title_repository.create_session_title_candidate(
        session,
        ExternalChannelSessionTitleCandidateCreate(
            agent_session_id=agent_session.id,
            binding_id=binding.id,
            trigger_provider_message_key=f"discord:title-trigger:{suffix}",
            admission_access_request_id=None,
            admission_provisional_title="New conversation",
            status=ExternalChannelSessionTitleCandidateStatus.PENDING,
            consumed_event_id=None,
            relinquished_reason=None,
        ),
    )
    projection = await title_repository.create_discord_thread_title_projection(
        session,
        ExternalChannelDiscordThreadTitleProjectionCreate(
            resource_id=resource.id,
            binding_id=binding.id,
            agent_session_id=agent_session.id,
            session_title_candidate_id=candidate.id,
            provisioning_protocol_version=1,
            requested_provisional_title="New conversation",
            admission_connection_id=connection.id,
            admission_guild_id=f"title-guild-{suffix}",
            admission_parent_channel_id=f"title-parent-{suffix}",
            admission_root_message_id=f"title-root-{suffix}",
            admission_trigger_provider_message_key=f"discord:title-trigger:{suffix}",
            admission_observation_status=(
                ExternalChannelDiscordThreadObservationStatus.UNKNOWN
            ),
            admission_root_has_thread=None,
            admission_observed_thread_channel_id=None,
            admission_observed_at=_at(0),
            provisioning_status=(
                ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
            ),
            preflight_absent_at=None,
            thread_channel_id=None,
            expected_provisional_title=None,
            provisioning_proof_kind=None,
            provision_attempt_count=0,
            provision_next_attempt_at=None,
            provision_claimed_at=None,
            provision_failure_kind=None,
            provision_failure_summary=None,
            provision_completed_at=None,
            desired_title=None,
            title_generation_event_id=None,
            title_status=ExternalChannelDiscordThreadTitleStatus.WAITING,
            title_attempt_count=0,
            title_next_attempt_at=None,
            title_claimed_at=None,
            title_failure_kind=None,
            title_failure_summary=None,
            title_completed_at=None,
        ),
    )
    return _TitleFixture(
        connection_id=connection.id,
        resource_id=resource.id,
        binding_id=binding.id,
        agent_session_id=agent_session.id,
        candidate_id=candidate.id,
        projection_id=projection.id,
    )


async def _create_event(
    session: AsyncSession,
    *,
    agent_session_id: str,
    model_order: int,
) -> str:
    """Persist a valid Event that can fence candidate consumption and title state."""
    event = RDBEvent(
        session_id=agent_session_id,
        kind=EventKind.ASSISTANT_MESSAGE,
        payload={},
        model_order=model_order,
    )
    session.add(event)
    await session.flush()
    return event.id


async def _claim_title_for_settlement(
    session: AsyncSession,
    *,
    suffix: str,
) -> tuple[
    ExternalChannelTitleRepository,
    _TitleFixture,
    ExternalChannelDiscordThreadTitleProjection,
]:
    """Create one fully-authorized final-title claim behind a current fence."""
    fixture = await _create_title_fixture(session, suffix=suffix)
    repository = ExternalChannelTitleRepository()
    event_id = await _create_event(
        session,
        agent_session_id=fixture.agent_session_id,
        model_order=1,
    )
    candidate = await session.get(
        RDBExternalChannelSessionTitleCandidate,
        fixture.candidate_id,
    )
    projection = await session.get(
        RDBExternalChannelDiscordThreadTitleProjection,
        fixture.projection_id,
    )
    resource = await session.get(RDBExternalChannelResource, fixture.resource_id)
    assert candidate is not None
    assert projection is not None
    assert resource is not None
    candidate.status = ExternalChannelSessionTitleCandidateStatus.CONSUMED
    candidate.consumed_event_id = event_id
    projection.provisioning_status = (
        ExternalChannelDiscordThreadTitleProvisioningStatus.READY
    )
    projection.thread_channel_id = f"title-thread-{suffix}"
    projection.expected_provisional_title = "New conversation"
    projection.provisioning_proof_kind = (
        ExternalChannelDiscordThreadTitleProofKind.DIRECT
    )
    projection.provision_completed_at = _at(1)
    projection.desired_title = "Investigate database latency"
    projection.title_generation_event_id = event_id
    projection.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
    projection.title_next_attempt_at = _at(2)
    resource.labels = {
        **(resource.labels or {}),
        "delivery_channel_id": projection.thread_channel_id,
    }
    await session.flush()

    claimed = await repository.claim_due_titles(
        session,
        now=_at(3),
        stale_before=_at(2),
        limit=10,
    )

    assert len(claimed) == 1
    assert claimed[0].title_claimed_at is not None
    return repository, fixture, claimed[0]


async def _cleanup_committed_title_fixture(
    session: AsyncSession,
    *,
    fixture: _TitleFixture,
) -> None:
    """Remove the committed rows that exercise multi-session title locking."""
    await session.execute(
        sa.delete(RDBExternalChannelDiscordThreadTitleProjection).where(
            RDBExternalChannelDiscordThreadTitleProjection.id == fixture.projection_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelSessionTitleCandidate).where(
            RDBExternalChannelSessionTitleCandidate.id == fixture.candidate_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelDeliveryAttempt).where(
            RDBExternalChannelDeliveryAttempt.binding_id == fixture.binding_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelBinding).where(
            RDBExternalChannelBinding.id == fixture.binding_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelResource).where(
            RDBExternalChannelResource.id == fixture.resource_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelAgentRoute).where(
            RDBExternalChannelAgentRoute.connection_id == fixture.connection_id
        )
    )
    await session.execute(
        sa.delete(RDBExternalChannelConnection).where(
            RDBExternalChannelConnection.id == fixture.connection_id
        )
    )
    await session.commit()


class TestExternalChannelTitleRepository:
    """Durable automatic-title repository contract tests."""

    async def test_create_is_idempotent_for_exact_candidate_and_projection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Retries return the existing title authority and projection identity."""
        fixture = await _create_title_fixture(rdb_session, suffix="idempotent")
        repository = ExternalChannelTitleRepository()

        candidate = await repository.create_session_title_candidate(
            rdb_session,
            ExternalChannelSessionTitleCandidateCreate(
                agent_session_id=fixture.agent_session_id,
                binding_id=fixture.binding_id,
                trigger_provider_message_key="discord:title-trigger:idempotent",
                admission_access_request_id=None,
                admission_provisional_title="New conversation",
                status=ExternalChannelSessionTitleCandidateStatus.PENDING,
                consumed_event_id=None,
                relinquished_reason=None,
            ),
        )
        projection = await repository.create_discord_thread_title_projection(
            rdb_session,
            ExternalChannelDiscordThreadTitleProjectionCreate(
                resource_id=fixture.resource_id,
                binding_id=fixture.binding_id,
                agent_session_id=fixture.agent_session_id,
                session_title_candidate_id=fixture.candidate_id,
                provisioning_protocol_version=1,
                requested_provisional_title="New conversation",
                admission_connection_id=fixture.connection_id,
                admission_guild_id="title-guild-idempotent",
                admission_parent_channel_id="title-parent-idempotent",
                admission_root_message_id="title-root-idempotent",
                admission_trigger_provider_message_key="discord:title-trigger:idempotent",
                admission_observation_status=(
                    ExternalChannelDiscordThreadObservationStatus.UNKNOWN
                ),
                admission_root_has_thread=None,
                admission_observed_thread_channel_id=None,
                admission_observed_at=_at(0),
                provisioning_status=(
                    ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
                ),
                preflight_absent_at=None,
                thread_channel_id=None,
                expected_provisional_title=None,
                provisioning_proof_kind=None,
                provision_attempt_count=0,
                provision_next_attempt_at=None,
                provision_claimed_at=None,
                provision_failure_kind=None,
                provision_failure_summary=None,
                provision_completed_at=None,
                desired_title=None,
                title_generation_event_id=None,
                title_status=ExternalChannelDiscordThreadTitleStatus.WAITING,
                title_attempt_count=0,
                title_next_attempt_at=None,
                title_claimed_at=None,
                title_failure_kind=None,
                title_failure_summary=None,
                title_completed_at=None,
            ),
        )

        assert candidate.id == fixture.candidate_id
        assert projection.id == fixture.projection_id

    async def test_exact_consume_and_relinquish_are_terminal_and_fenced(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only the exact pending candidate can be consumed or relinquished once."""
        consumed_fixture = await _create_title_fixture(rdb_session, suffix="consume")
        relinquished_fixture = await _create_title_fixture(
            rdb_session,
            suffix="relinquish",
        )
        repository = ExternalChannelTitleRepository()
        event_id = await _create_event(
            rdb_session,
            agent_session_id=consumed_fixture.agent_session_id,
            model_order=1,
        )

        stale = await repository.consume_pending_candidate(
            rdb_session,
            candidate_id=consumed_fixture.candidate_id,
            agent_session_id=consumed_fixture.agent_session_id,
            binding_id=consumed_fixture.binding_id,
            trigger_provider_message_key="wrong-trigger",
            consumed_event_id=event_id,
        )
        consumed = await repository.consume_pending_candidate(
            rdb_session,
            candidate_id=consumed_fixture.candidate_id,
            agent_session_id=consumed_fixture.agent_session_id,
            binding_id=consumed_fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:consume",
            consumed_event_id=event_id,
        )
        cannot_relinquish_consumed = await repository.relinquish_pending_candidate(
            rdb_session,
            candidate_id=consumed_fixture.candidate_id,
            agent_session_id=consumed_fixture.agent_session_id,
            binding_id=consumed_fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:consume",
            reason="preexisting_title",
        )
        relinquished = await repository.relinquish_pending_candidate(
            rdb_session,
            candidate_id=relinquished_fixture.candidate_id,
            agent_session_id=relinquished_fixture.agent_session_id,
            binding_id=relinquished_fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:relinquish",
            reason="manual_title",
        )
        pending = await repository.get_pending_candidate_for_event(
            rdb_session,
            agent_session_id=relinquished_fixture.agent_session_id,
            binding_id=relinquished_fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:relinquish",
            for_update=False,
        )

        assert stale is None
        assert consumed is not None
        assert consumed.status is ExternalChannelSessionTitleCandidateStatus.CONSUMED
        assert consumed.consumed_event_id == event_id
        assert cannot_relinquish_consumed is None
        assert relinquished is not None
        assert (
            relinquished.status
            is ExternalChannelSessionTitleCandidateStatus.RELINQUISHED
        )
        assert relinquished.relinquished_reason == "manual_title"
        assert pending is None

    async def test_create_returns_terminal_candidate_for_same_provenance(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Same provenance retries retain terminal ownership without reopening it."""
        consumed_fixture = await _create_title_fixture(
            rdb_session,
            suffix="retry-consumed",
        )
        relinquished_fixture = await _create_title_fixture(
            rdb_session,
            suffix="retry-relinquished",
        )
        repository = ExternalChannelTitleRepository()
        event_id = await _create_event(
            rdb_session,
            agent_session_id=consumed_fixture.agent_session_id,
            model_order=1,
        )
        consumed = await repository.consume_pending_candidate(
            rdb_session,
            candidate_id=consumed_fixture.candidate_id,
            agent_session_id=consumed_fixture.agent_session_id,
            binding_id=consumed_fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:retry-consumed",
            consumed_event_id=event_id,
        )
        relinquished = await repository.relinquish_pending_candidate(
            rdb_session,
            candidate_id=relinquished_fixture.candidate_id,
            agent_session_id=relinquished_fixture.agent_session_id,
            binding_id=relinquished_fixture.binding_id,
            trigger_provider_message_key=("discord:title-trigger:retry-relinquished"),
            reason="manual_title",
        )
        assert consumed is not None
        assert relinquished is not None

        retried_consumed = await repository.create_session_title_candidate(
            rdb_session,
            ExternalChannelSessionTitleCandidateCreate(
                agent_session_id=consumed_fixture.agent_session_id,
                binding_id=consumed_fixture.binding_id,
                trigger_provider_message_key=("discord:title-trigger:retry-consumed"),
                admission_access_request_id=None,
                admission_provisional_title="New conversation",
                status=ExternalChannelSessionTitleCandidateStatus.PENDING,
                consumed_event_id=None,
                relinquished_reason=None,
            ),
        )
        retried_relinquished = await repository.create_session_title_candidate(
            rdb_session,
            ExternalChannelSessionTitleCandidateCreate(
                agent_session_id=relinquished_fixture.agent_session_id,
                binding_id=relinquished_fixture.binding_id,
                trigger_provider_message_key=(
                    "discord:title-trigger:retry-relinquished"
                ),
                admission_access_request_id=None,
                admission_provisional_title="New conversation",
                status=ExternalChannelSessionTitleCandidateStatus.PENDING,
                consumed_event_id=None,
                relinquished_reason=None,
            ),
        )

        assert retried_consumed.id == consumed_fixture.candidate_id
        assert (
            retried_consumed.status
            is ExternalChannelSessionTitleCandidateStatus.CONSUMED
        )
        assert retried_consumed.consumed_event_id == event_id
        assert retried_relinquished.id == relinquished_fixture.candidate_id
        assert (
            retried_relinquished.status
            is ExternalChannelSessionTitleCandidateStatus.RELINQUISHED
        )
        assert retried_relinquished.relinquished_reason == "manual_title"

    async def test_projection_rejects_mismatched_candidate_trigger(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """The projection FK requires the candidate's exact trigger provenance."""
        fixture = await _create_title_fixture(rdb_session, suffix="trigger-fence")
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None

        with pytest.raises(
            IntegrityError,
            match="fk_ec_discord_title_projection_candidate_owner",
        ):
            async with rdb_session.begin_nested():
                projection.admission_trigger_provider_message_key = (
                    "discord:title-trigger:other"
                )
                await rdb_session.flush()

    async def test_waiting_title_allows_snapshot_before_provider_readiness(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Waiting preserves a generated snapshot until provisioning becomes ready."""
        fixture = await _create_title_fixture(rdb_session, suffix="waiting-snapshot")
        event_id = await _create_event(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            model_order=1,
        )
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None
        projection.desired_title = "Title generated before thread creation"
        projection.title_generation_event_id = event_id
        await rdb_session.flush()

        assert (
            projection.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
        )
        assert (
            projection.title_status is ExternalChannelDiscordThreadTitleStatus.WAITING
        )

    async def test_runnable_title_state_rejects_missing_title_snapshot(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Runnable title states require the title and generation Event snapshot."""
        fixture = await _create_title_fixture(rdb_session, suffix="title-ready")
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None

        with pytest.raises(
            IntegrityError,
            match="ck_ec_discord_title_projection_title_ready",
        ):
            async with rdb_session.begin_nested():
                projection.provisioning_status = (
                    ExternalChannelDiscordThreadTitleProvisioningStatus.READY
                )
                projection.thread_channel_id = "title-thread-ready"
                projection.expected_provisional_title = "New conversation"
                projection.provisioning_proof_kind = (
                    ExternalChannelDiscordThreadTitleProofKind.DIRECT
                )
                projection.provision_completed_at = _at(1)
                projection.title_status = (
                    ExternalChannelDiscordThreadTitleStatus.PENDING
                )
                projection.title_next_attempt_at = _at(1)
                await rdb_session.flush()

    async def test_arm_snapshots_only_the_consumed_generation_event(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Generated title state is atomically bound to the exact consumed Event."""
        fixture = await _create_title_fixture(rdb_session, suffix="arm")
        repository = ExternalChannelTitleRepository()
        event_id = await _create_event(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            model_order=1,
        )
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.READY
        )
        projection.thread_channel_id = "title-thread-arm"
        projection.expected_provisional_title = "New conversation"
        projection.provisioning_proof_kind = (
            ExternalChannelDiscordThreadTitleProofKind.DIRECT
        )
        projection.provision_completed_at = _at(1)
        await rdb_session.flush()
        consumed = await repository.consume_pending_candidate(
            rdb_session,
            candidate_id=fixture.candidate_id,
            agent_session_id=fixture.agent_session_id,
            binding_id=fixture.binding_id,
            trigger_provider_message_key="discord:title-trigger:arm",
            consumed_event_id=event_id,
        )
        assert consumed is not None

        armed = await repository.arm_title_projections_for_generated_title(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            generation_event_id=event_id,
            desired_title="Investigate database latency",
            now=_at(2),
        )

        assert len(armed) == 1
        assert armed[0].id == fixture.projection_id
        assert armed[0].desired_title == "Investigate database latency"
        assert armed[0].title_generation_event_id == event_id
        assert armed[0].title_status is ExternalChannelDiscordThreadTitleStatus.PENDING
        assert armed[0].title_next_attempt_at == _at(2)

    async def test_due_claims_recover_stale_provisioning_and_title_attempts(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Due workers claim once and recover abandoned provisioning and title work."""
        fixture = await _create_title_fixture(rdb_session, suffix="claims")
        repository = ExternalChannelTitleRepository()

        first_provision = await repository.claim_due_provisioning(
            rdb_session,
            now=_at(1),
            stale_before=_at(0),
            limit=10,
        )
        second_provision = await repository.claim_due_provisioning(
            rdb_session,
            now=_at(1),
            stale_before=_at(0),
            limit=10,
        )
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None
        projection.provision_claimed_at = _at(0)
        await rdb_session.flush()
        recovered_provision = await repository.claim_due_provisioning(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )

        event_id = await _create_event(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            model_order=1,
        )
        candidate = await rdb_session.get(
            RDBExternalChannelSessionTitleCandidate,
            fixture.candidate_id,
        )
        assert candidate is not None
        candidate.status = ExternalChannelSessionTitleCandidateStatus.CONSUMED
        candidate.consumed_event_id = event_id
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.READY
        )
        projection.thread_channel_id = "title-thread-claims"
        projection.expected_provisional_title = "New conversation"
        projection.provisioning_proof_kind = (
            ExternalChannelDiscordThreadTitleProofKind.DIRECT
        )
        projection.provision_completed_at = _at(2)
        projection.desired_title = "Inspect retry behavior"
        projection.title_generation_event_id = event_id
        projection.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
        projection.title_next_attempt_at = _at(2)
        resource = await rdb_session.get(
            RDBExternalChannelResource,
            fixture.resource_id,
        )
        assert resource is not None
        resource.labels = {
            **(resource.labels or {}),
            "delivery_channel_id": "title-thread-claims",
        }
        await rdb_session.flush()
        first_title = await repository.claim_due_titles(
            rdb_session,
            now=_at(3),
            stale_before=_at(2),
            limit=10,
        )
        second_title = await repository.claim_due_titles(
            rdb_session,
            now=_at(3),
            stale_before=_at(2),
            limit=10,
        )
        projection.title_claimed_at = _at(0)
        await rdb_session.flush()
        recovered_title = await repository.claim_due_titles(
            rdb_session,
            now=_at(4),
            stale_before=_at(1),
            limit=10,
        )

        assert [item.id for item in first_provision] == [fixture.projection_id]
        assert first_provision[0].provision_attempt_count == 1
        assert second_provision == ()
        assert [item.id for item in recovered_provision] == [fixture.projection_id]
        assert recovered_provision[0].provision_attempt_count == 2
        assert [item.id for item in first_title] == [fixture.projection_id]
        assert first_title[0].title_attempt_count == 1
        assert second_title == ()
        assert [item.id for item in recovered_title] == [fixture.projection_id]
        assert recovered_title[0].title_attempt_count == 2

    async def test_provisioning_claim_requires_supported_protocol_and_candidate(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Current Workers skip unsupported protocols and terminal candidates."""
        unsupported = await _create_title_fixture(rdb_session, suffix="unsupported")
        relinquished = await _create_title_fixture(
            rdb_session,
            suffix="relinquished-claim",
        )
        unsupported_projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            unsupported.projection_id,
        )
        relinquished_candidate = await rdb_session.get(
            RDBExternalChannelSessionTitleCandidate,
            relinquished.candidate_id,
        )
        assert unsupported_projection is not None
        assert relinquished_candidate is not None
        unsupported_projection.provisioning_protocol_version = 2
        relinquished_candidate.status = (
            ExternalChannelSessionTitleCandidateStatus.RELINQUISHED
        )
        relinquished_candidate.relinquished_reason = "manual_title"
        await rdb_session.flush()

        claimed = await ExternalChannelTitleRepository().claim_due_provisioning(
            rdb_session,
            now=_at(1),
            stale_before=_at(0),
            limit=10,
        )

        assert claimed == ()

    async def test_title_claim_requires_supported_protocol_and_candidate_provenance(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Final-title Workers skip unsupported or mismatched title provenance."""
        unsupported = await _create_title_fixture(
            rdb_session,
            suffix="title-unsupported",
        )
        mismatched = await _create_title_fixture(
            rdb_session,
            suffix="title-mismatched",
        )
        for fixture in (unsupported, mismatched):
            event_id = await _create_event(
                rdb_session,
                agent_session_id=fixture.agent_session_id,
                model_order=1,
            )
            candidate = await rdb_session.get(
                RDBExternalChannelSessionTitleCandidate,
                fixture.candidate_id,
            )
            projection = await rdb_session.get(
                RDBExternalChannelDiscordThreadTitleProjection,
                fixture.projection_id,
            )
            assert candidate is not None
            assert projection is not None
            candidate.status = ExternalChannelSessionTitleCandidateStatus.CONSUMED
            candidate.consumed_event_id = event_id
            projection.provisioning_status = (
                ExternalChannelDiscordThreadTitleProvisioningStatus.READY
            )
            projection.thread_channel_id = f"title-thread-{fixture.projection_id}"
            projection.expected_provisional_title = "New conversation"
            projection.provisioning_proof_kind = (
                ExternalChannelDiscordThreadTitleProofKind.DIRECT
            )
            projection.provision_completed_at = _at(1)
            projection.desired_title = "Investigate title claim eligibility"
            projection.title_generation_event_id = event_id
            projection.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
            projection.title_next_attempt_at = _at(1)
        unsupported_projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            unsupported.projection_id,
        )
        mismatched_candidate = await rdb_session.get(
            RDBExternalChannelSessionTitleCandidate,
            mismatched.candidate_id,
        )
        assert unsupported_projection is not None
        assert mismatched_candidate is not None
        unsupported_projection.provisioning_protocol_version = 2
        mismatched_candidate.admission_provisional_title = "Different admission title"
        await rdb_session.flush()

        claimed = await ExternalChannelTitleRepository().claim_due_titles(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )

        assert claimed == ()

    async def test_title_claim_requires_canonical_resource_delivery_target(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A title claim never starts when Resource targets another thread."""
        fixture = await _create_title_fixture(rdb_session, suffix="title-target")
        repository = ExternalChannelTitleRepository()
        event_id = await _create_event(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            model_order=1,
        )
        other_event_id = await _create_event(
            rdb_session,
            agent_session_id=fixture.agent_session_id,
            model_order=2,
        )
        candidate = await rdb_session.get(
            RDBExternalChannelSessionTitleCandidate,
            fixture.candidate_id,
        )
        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        resource = await rdb_session.get(
            RDBExternalChannelResource,
            fixture.resource_id,
        )
        assert candidate is not None
        assert projection is not None
        assert resource is not None
        candidate.status = ExternalChannelSessionTitleCandidateStatus.CONSUMED
        candidate.consumed_event_id = event_id
        projection.provisioning_status = (
            ExternalChannelDiscordThreadTitleProvisioningStatus.READY
        )
        projection.thread_channel_id = "canonical-title-thread"
        projection.expected_provisional_title = "New conversation"
        projection.provisioning_proof_kind = (
            ExternalChannelDiscordThreadTitleProofKind.DIRECT
        )
        projection.provision_completed_at = _at(1)
        projection.desired_title = "Do not patch a stale thread"
        projection.title_generation_event_id = event_id
        projection.title_status = ExternalChannelDiscordThreadTitleStatus.PENDING
        projection.title_next_attempt_at = _at(1)
        resource.labels = {
            **(resource.labels or {}),
            "delivery_channel_id": "obsolete-title-thread",
        }
        await rdb_session.flush()

        rejected = await repository.claim_due_titles(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )
        resource.labels = {
            **(resource.labels or {}),
            "delivery_channel_id": "canonical-title-thread",
        }
        candidate.status = ExternalChannelSessionTitleCandidateStatus.PENDING
        candidate.consumed_event_id = None
        await rdb_session.flush()
        rejected_pending = await repository.claim_due_titles(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )
        candidate.status = ExternalChannelSessionTitleCandidateStatus.CONSUMED
        candidate.consumed_event_id = other_event_id
        await rdb_session.flush()
        rejected_wrong_event = await repository.claim_due_titles(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )
        candidate.consumed_event_id = event_id
        await rdb_session.flush()
        claimed = await repository.claim_due_titles(
            rdb_session,
            now=_at(2),
            stale_before=_at(1),
            limit=10,
        )

        assert rejected == ()
        assert rejected_pending == ()
        assert rejected_wrong_event == ()
        assert [item.id for item in claimed] == [fixture.projection_id]

    async def test_title_settlement_requires_exact_claim_and_current_authority(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A successful final rename settles only its exact current authority."""
        repository, fixture, claim = await _claim_title_for_settlement(
            rdb_session,
            suffix="settle-applied",
        )
        assert claim.title_claimed_at is not None

        stale = await repository.settle_title_applied(
            rdb_session,
            projection_id=fixture.projection_id,
            expected_title_attempt_count=claim.title_attempt_count + 1,
            expected_title_claimed_at=claim.title_claimed_at,
            now=_at(4),
        )
        settled = await repository.settle_title_applied(
            rdb_session,
            projection_id=fixture.projection_id,
            expected_title_attempt_count=claim.title_attempt_count,
            expected_title_claimed_at=claim.title_claimed_at,
            now=_at(4),
        )

        assert stale is None
        assert settled is not None
        assert settled.title_status is ExternalChannelDiscordThreadTitleStatus.APPLIED
        assert settled.title_claimed_at is None
        assert settled.title_failure_kind is None
        assert settled.title_failure_summary is None
        assert settled.title_completed_at == _at(4)

    async def test_title_settlement_terminalizes_target_conflict(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A changed canonical delivery target rejects an otherwise valid rename."""
        repository, fixture, claim = await _claim_title_for_settlement(
            rdb_session,
            suffix="settle-conflict",
        )
        assert claim.title_claimed_at is not None
        resource = await rdb_session.get(
            RDBExternalChannelResource,
            fixture.resource_id,
        )
        assert resource is not None
        resource.labels = {
            **(resource.labels or {}),
            "delivery_channel_id": "different-title-thread",
        }
        await rdb_session.flush()

        settled = await repository.settle_title_relinquished(
            rdb_session,
            projection_id=fixture.projection_id,
            expected_title_attempt_count=claim.title_attempt_count,
            expected_title_claimed_at=claim.title_claimed_at,
            reason="already_renamed",
            now=_at(4),
        )

        assert settled is not None
        assert (
            settled.title_status is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )
        assert settled.title_failure_kind == "delivery_channel_conflict"
        assert settled.title_failure_summary == "delivery_channel_conflict"

    async def test_title_retry_and_failure_are_exactly_fenced(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Transient and permanent results mutate only their current title claim."""
        repository, retry_fixture, retry_claim = await _claim_title_for_settlement(
            rdb_session,
            suffix="retry",
        )
        assert retry_claim.title_claimed_at is not None
        retry = await repository.retry_title(
            rdb_session,
            projection_id=retry_fixture.projection_id,
            expected_title_attempt_count=retry_claim.title_attempt_count,
            expected_title_claimed_at=retry_claim.title_claimed_at,
            next_attempt_at=_at(5),
            failure_kind="transport_error",
            failure_summary="Discord title delivery timed out.",
        )
        _, failure_fixture, failure_claim = await _claim_title_for_settlement(
            rdb_session,
            suffix="failure",
        )
        assert failure_claim.title_claimed_at is not None
        failed = await repository.fail_title(
            rdb_session,
            projection_id=failure_fixture.projection_id,
            expected_title_attempt_count=failure_claim.title_attempt_count,
            expected_title_claimed_at=failure_claim.title_claimed_at,
            failure_kind="permission_denied",
            failure_summary="Discord denied title updates.",
            now=_at(4),
        )

        assert retry is not None
        assert retry.title_status is ExternalChannelDiscordThreadTitleStatus.RETRY_WAIT
        assert retry.title_next_attempt_at == _at(5)
        assert retry.title_claimed_at is None
        assert retry.title_failure_kind == "transport_error"
        assert failed is not None
        assert failed.title_status is ExternalChannelDiscordThreadTitleStatus.FAILED
        assert failed.title_next_attempt_at is None
        assert failed.title_claimed_at is None
        assert failed.title_failure_kind == "permission_denied"
        assert failed.title_completed_at == _at(4)

    async def test_lifecycle_terminalization_stops_both_title_phases(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Lifecycle terminalization performs only durable title-state mutations."""
        fixture = await _create_title_fixture(rdb_session, suffix="lifecycle-stop")
        repository = ExternalChannelTitleRepository()

        await repository.terminalize_lifecycle_projections(
            rdb_session,
            session_ids=(fixture.agent_session_id,),
            binding_ids=(),
            resource_ids=(),
            reason="session_archived",
            now=_at(2),
        )

        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert projection is not None
        assert (
            projection.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
        )
        assert projection.provision_failure_kind == "session_archived"
        assert (
            projection.title_status
            is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )
        assert projection.title_failure_kind == "session_archived"
        await repository.validate_lifecycle_projections_terminal(
            rdb_session,
            session_ids=(fixture.agent_session_id,),
        )

    async def test_resource_loss_terminalizes_title_work(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A direct Resource loss fences title work without provider operations."""
        fixture = await _create_title_fixture(rdb_session, suffix="resource-loss")

        marked = await ExternalChannelRepository().mark_resource_unavailable(
            rdb_session,
            resource_id=fixture.resource_id,
            now=_at(2),
        )

        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        assert marked is True
        assert projection is not None
        assert (
            projection.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
        )
        assert (
            projection.title_status
            is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )

    async def test_lifecycle_purge_deletes_projection_before_candidate(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Purge removes title projection and candidate before the Binding root."""
        fixture = await _create_title_fixture(rdb_session, suffix="purge-title")
        lifecycle_repository = ExternalChannelLifecycleRepository()

        await lifecycle_repository.purge_session_tree(
            rdb_session,
            session_ids=(fixture.agent_session_id,),
        )
        verification = await lifecycle_repository.verify_session_tree_purged(
            rdb_session,
            session_ids=(fixture.agent_session_id,),
        )

        assert verification.remaining_binding_count == 0
        assert (
            await rdb_session.get(
                RDBExternalChannelDiscordThreadTitleProjection,
                fixture.projection_id,
            )
            is None
        )
        assert (
            await rdb_session.get(
                RDBExternalChannelSessionTitleCandidate,
                fixture.candidate_id,
            )
            is None
        )

    @pytest.mark.parametrize(
        ("owner_kind", "suffix"),
        (
            ("archive_binding", "nowait-archive"),
            ("disconnect_connection", "nowait-disconnect"),
        ),
    )
    async def test_settlement_nowait_releases_contended_owner_locks(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
        owner_kind: str,
        suffix: str,
    ) -> None:
        """Contended owners reject settlement without terminalizing title work."""
        del latest_db_schema
        assert RDBWorkspaceRuntimeProfile.__tablename__ == "workspace_runtime_profiles"
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            repository, fixture, claim = await _claim_title_for_settlement(
                setup,
                suffix=suffix,
            )
            assert claim.title_claimed_at is not None
            await setup.commit()

        try:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as owner:
                if owner_kind == "archive_binding":
                    await owner.scalar(
                        sa.select(RDBExternalChannelBinding)
                        .where(RDBExternalChannelBinding.id == fixture.binding_id)
                        .with_for_update()
                    )
                else:
                    await owner.scalar(
                        sa.select(RDBExternalChannelConnection)
                        .where(RDBExternalChannelConnection.id == fixture.connection_id)
                        .with_for_update()
                    )
                async with AsyncSession(
                    rdb_engine,
                    expire_on_commit=False,
                ) as settlement:
                    with pytest.raises(OperationalError) as error:
                        await repository.settle_title_applied(
                            settlement,
                            projection_id=fixture.projection_id,
                            expected_title_attempt_count=claim.title_attempt_count,
                            expected_title_claimed_at=claim.title_claimed_at,
                            now=_at(4),
                        )
                    assert getattr(error.value.orig, "sqlstate", None) == "55P03"
                    await settlement.rollback()

                projection = await owner.get(
                    RDBExternalChannelDiscordThreadTitleProjection,
                    fixture.projection_id,
                )
                assert projection is not None
                assert (
                    projection.title_status
                    is ExternalChannelDiscordThreadTitleStatus.ATTEMPTING
                )
                assert projection.title_failure_kind is None
                await owner.rollback()

            async with AsyncSession(rdb_engine, expire_on_commit=False) as recovery:
                recovered = await repository.claim_due_titles(
                    recovery,
                    now=_at(5),
                    stale_before=_at(4),
                    limit=10,
                )
                assert [item.id for item in recovered] == [fixture.projection_id]
                await recovery.rollback()
        finally:
            async with AsyncSession(rdb_engine, expire_on_commit=False) as cleanup:
                await _cleanup_committed_title_fixture(cleanup, fixture=fixture)

    @pytest.mark.parametrize(
        ("lifecycle_kind", "suffix", "reason"),
        (
            ("archive", "nowait-lifecycle-archive", "session_archived"),
            (
                "disconnect",
                "nowait-lifecycle-disconnect",
                "manager_disconnected",
            ),
        ),
    )
    async def test_settlement_nowait_allows_lifecycle_owner_to_commit(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
        monkeypatch: pytest.MonkeyPatch,
        lifecycle_kind: str,
        suffix: str,
        reason: str,
    ) -> None:
        """A real lifecycle transaction commits after title settlement yields."""
        del latest_db_schema
        assert RDBWorkspaceRuntimeProfile.__tablename__ == "workspace_runtime_profiles"
        repository = ExternalChannelTitleRepository()
        projection_claimed = asyncio.Event()
        lifecycle_owner_locked = asyncio.Event()
        original_lock_resource = getattr(  # noqa: B009
            ExternalChannelTitleRepository,
            "_lock_projection_resource",
        )
        original_terminalize = (
            ExternalChannelTitleRepository.terminalize_lifecycle_projections
        )

        async def pause_settlement_after_projection_claim(
            session: AsyncSession,
            *,
            projection: RDBExternalChannelDiscordThreadTitleProjection,
        ) -> RDBExternalChannelResource | None:
            projection_claimed.set()
            await asyncio.wait_for(lifecycle_owner_locked.wait(), timeout=1)
            return await original_lock_resource(session, projection=projection)

        async def signal_lifecycle_owner_before_terminalization(
            title_repository: ExternalChannelTitleRepository,
            session: AsyncSession,
            *,
            session_ids: Sequence[str],
            binding_ids: Sequence[str],
            resource_ids: Sequence[str],
            reason: str,
            now: datetime.datetime,
        ) -> None:
            lifecycle_owner_locked.set()
            await original_terminalize(
                title_repository,
                session,
                session_ids=session_ids,
                binding_ids=binding_ids,
                resource_ids=resource_ids,
                reason=reason,
                now=now,
            )

        monkeypatch.setattr(
            ExternalChannelTitleRepository,
            "_lock_projection_resource",
            pause_settlement_after_projection_claim,
        )
        monkeypatch.setattr(
            ExternalChannelTitleRepository,
            "terminalize_lifecycle_projections",
            signal_lifecycle_owner_before_terminalization,
        )

        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            _, fixture, claim = await _claim_title_for_settlement(setup, suffix=suffix)
            assert claim.title_claimed_at is not None
            claimed_at = claim.title_claimed_at
            await setup.commit()

        settlement_task: asyncio.Task[OperationalError] | None = None
        lifecycle_task: asyncio.Task[None] | None = None
        try:

            async def settle_title() -> OperationalError:
                async with AsyncSession(
                    rdb_engine,
                    expire_on_commit=False,
                ) as settlement:
                    with pytest.raises(OperationalError) as error:
                        await repository.settle_title_applied(
                            settlement,
                            projection_id=fixture.projection_id,
                            expected_title_attempt_count=claim.title_attempt_count,
                            expected_title_claimed_at=claimed_at,
                            now=_at(4),
                        )
                    await settlement.rollback()
                    return error.value

            async def commit_lifecycle_owner() -> None:
                async with AsyncSession(
                    rdb_engine,
                    expire_on_commit=False,
                ) as lifecycle_session:
                    lifecycle_repository = ExternalChannelLifecycleRepository()
                    if lifecycle_kind == "archive":
                        archived = await lifecycle_repository.terminate_session_tree(
                            lifecycle_session,
                            session_ids=(fixture.agent_session_id,),
                            now=_at(4),
                        )
                        assert archived.disconnected_binding_count == 1
                    else:
                        disconnected = (
                            await lifecycle_repository.disconnect_single_connection(
                                lifecycle_session,
                                connection_id=fixture.connection_id,
                                now=_at(4),
                                reason=reason,
                            )
                        )
                        assert disconnected is not None
                    await lifecycle_session.commit()

            settlement_task = asyncio.create_task(settle_title())
            await asyncio.wait_for(projection_claimed.wait(), timeout=1)
            lifecycle_task = asyncio.create_task(commit_lifecycle_owner())
            await asyncio.wait_for(lifecycle_owner_locked.wait(), timeout=1)

            settlement_error = await asyncio.wait_for(settlement_task, timeout=1)
            assert getattr(settlement_error.orig, "sqlstate", None) == "55P03"
            await asyncio.wait_for(lifecycle_task, timeout=1)

            async with AsyncSession(rdb_engine, expire_on_commit=False) as verify:
                projection = await verify.get(
                    RDBExternalChannelDiscordThreadTitleProjection,
                    fixture.projection_id,
                )
                binding = await verify.get(
                    RDBExternalChannelBinding,
                    fixture.binding_id,
                )
                assert projection is not None
                assert binding is not None
                assert (
                    projection.title_status
                    is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
                )
                assert projection.title_failure_kind == reason
                assert binding.disconnected_at == _at(4)
                if lifecycle_kind == "disconnect":
                    connection = await verify.get(
                        RDBExternalChannelConnection,
                        fixture.connection_id,
                    )
                    assert connection is not None
                    assert (
                        connection.status
                        is ExternalChannelConnectionStatus.DISCONNECTED
                    )
        finally:
            lifecycle_owner_locked.set()
            for task in (settlement_task, lifecycle_task):
                if task is not None and not task.done():
                    task.cancel()
            if settlement_task is not None:
                await asyncio.gather(settlement_task, return_exceptions=True)
            if lifecycle_task is not None:
                await asyncio.gather(lifecycle_task, return_exceptions=True)
            async with AsyncSession(rdb_engine, expire_on_commit=False) as cleanup:
                await _cleanup_committed_title_fixture(cleanup, fixture=fixture)

    @pytest.mark.parametrize(
        ("transition", "suffix", "reason", "expected_status"),
        (
            (
                "clear_callback",
                "connection-revocation-clear-callback",
                "discord_callback_registration_failed",
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            ),
            (
                "activation_failure",
                "connection-revocation-activation-failure",
                "discord_activation_failed",
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            ),
            (
                "gateway_reconnect",
                "connection-revocation-gateway-reconnect",
                "gateway_lost",
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            ),
            (
                "generic_reconnect",
                "connection-revocation-generic-reconnect",
                "credential_revoked",
                ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
            ),
            (
                "replace_single",
                "connection-revocation-replace-single",
                "discord_configuration_replaced",
                ExternalChannelConnectionStatus.CONFIGURING,
            ),
            (
                "replace_multi",
                "connection-revocation-replace-multi",
                "discord_configuration_replaced",
                ExternalChannelConnectionStatus.CONFIGURING,
            ),
        ),
    )
    async def test_connection_authority_revocation_terminalizes_only_its_titles(
        self,
        rdb_session: AsyncSession,
        transition: str,
        suffix: str,
        reason: str,
        expected_status: ExternalChannelConnectionStatus,
    ) -> None:
        """Discord authority loss terminalizes only its prior title work."""
        app_mode = (
            ExternalChannelAppMode.MULTI
            if transition == "replace_multi"
            else ExternalChannelAppMode.SINGLE
        )
        fixture = await _create_title_fixture(
            rdb_session,
            suffix=suffix,
            app_mode=app_mode,
        )
        unrelated = await _create_title_fixture(
            rdb_session,
            suffix=f"{suffix}-unrelated",
        )
        repository = ExternalChannelRepository()
        title_repository = ExternalChannelTitleRepository()
        management_repository = ExternalChannelManagementRepository()
        connection = await rdb_session.get(
            RDBExternalChannelConnection,
            fixture.connection_id,
        )
        assert connection is not None

        if transition == "clear_callback":
            connection.http_callback_selector_hash = "callback-selector"
            connection.capabilities = {"interaction_public_key": "a" * 64}
            await rdb_session.flush()
            assert await repository.clear_prepared_discord_callback(
                rdb_session,
                connection_id=connection.id,
                expected_encrypted_credentials="ciphertext",
                expected_configuration_generation=connection.configuration_generation,
                callback_selector_hash="callback-selector",
                checked_at=_at(4),
            )
        elif transition == "activation_failure":
            recorded = await repository.record_discord_activation_failure(
                rdb_session,
                connection_id=connection.id,
                expected_encrypted_credentials="ciphertext",
                expected_configuration_generation=connection.configuration_generation,
                failure_code="provider_registration_failed",
                checked_at=_at(4),
            )
            assert recorded is not None
        elif transition == "gateway_reconnect":
            connection.ingress_profile = (
                ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
            )
            assert connection.provider_app_id is not None
            app_claim = RDBExternalChannelAppClaim(
                provider=ExternalChannelProvider.DISCORD,
                provider_app_id=connection.provider_app_id,
                connection_id=connection.id,
                claim_generation=1,
            )
            rdb_session.add(app_claim)
            await rdb_session.flush()
            rdb_session.add(
                RDBExternalChannelIngressLease(
                    connection_id=connection.id,
                    lease_owner="gateway-worker",
                    lease_generation=1,
                    lease_until=_at(10),
                    heartbeat_at=_at(3),
                    required_configuration_generation=(
                        connection.configuration_generation
                    ),
                    required_app_claim_generation=app_claim.claim_generation,
                    gap_detected_at=None,
                    gap_reason=None,
                )
            )
            await rdb_session.flush()
            assert await repository.mark_discord_gateway_reconnect_required(
                rdb_session,
                connection_id=connection.id,
                lease_owner="gateway-worker",
                lease_generation=1,
                now=_at(4),
                reason=reason,
            )
        elif transition == "generic_reconnect":
            assert await repository.mark_connection_reconnect_required(
                rdb_session,
                connection_id=connection.id,
                reason=reason,
                now=_at(4),
                required_configuration_generation=None,
                required_socket_lease_owner=None,
            )
        elif transition == "replace_single":
            agent_session = await rdb_session.get(
                RDBAgentSession,
                fixture.agent_session_id,
            )
            assert agent_session is not None
            replaced = await management_repository.replace_discord_configuration(
                rdb_session,
                workspace_id=agent_session.workspace_id,
                agent_id=agent_session.agent_id,
                connection_id=connection.id,
                provider_app_id=f"replacement-app-{suffix}",
                encrypted_credentials="replacement-ciphertext",
                provider_config={"target_guild_id": f"replacement-{suffix}"},
            )
            assert replaced is not None
        else:
            agent_session = await rdb_session.get(
                RDBAgentSession,
                fixture.agent_session_id,
            )
            assert agent_session is not None
            replaced = await management_repository.replace_multi_discord_configuration(
                rdb_session,
                workspace_id=agent_session.workspace_id,
                connection_id=connection.id,
                provider_app_id=f"replacement-app-{suffix}",
                encrypted_credentials="replacement-ciphertext",
                provider_config={"target_guild_id": f"replacement-{suffix}"},
            )
            assert replaced is not None

        projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            fixture.projection_id,
        )
        unrelated_projection = await rdb_session.get(
            RDBExternalChannelDiscordThreadTitleProjection,
            unrelated.projection_id,
        )
        assert projection is not None
        assert unrelated_projection is not None
        assert connection.status is expected_status
        assert (
            projection.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
        )
        assert (
            projection.title_status
            is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )
        assert projection.provision_failure_kind == reason
        assert projection.title_failure_kind == reason
        assert (
            unrelated_projection.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.PENDING
        )
        assert (
            unrelated_projection.title_status
            is ExternalChannelDiscordThreadTitleStatus.WAITING
        )

        connection.status = ExternalChannelConnectionStatus.ACTIVE
        connection.disconnected_at = None
        await rdb_session.flush()
        reclaimed = await title_repository.claim_due_provisioning(
            rdb_session,
            now=_at(6),
            stale_before=_at(5),
            limit=10,
        )
        assert fixture.projection_id not in {item.id for item in reclaimed}
        assert unrelated.projection_id in {item.id for item in reclaimed}

    async def test_settlement_terminalizes_delivery_target_conflict(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A competing canonical delivery target relinquishes without overwriting it."""
        fixture = await _create_title_fixture(rdb_session, suffix="delivery-conflict")
        repository = ExternalChannelTitleRepository()
        claimed = await repository.claim_due_provisioning(
            rdb_session,
            now=_at(1),
            stale_before=_at(0),
            limit=10,
        )
        assert len(claimed) == 1
        claim = claimed[0]
        assert claim.provision_claimed_at is not None
        resource = await rdb_session.get(
            RDBExternalChannelResource,
            fixture.resource_id,
        )
        assert resource is not None
        resource.labels = {
            **(resource.labels or {}),
            "delivery_channel_id": "existing-thread",
        }
        await rdb_session.flush()

        settled = await repository.settle_provisioning_ready(
            rdb_session,
            projection_id=fixture.projection_id,
            expected_provision_attempt_count=claim.provision_attempt_count,
            expected_provision_claimed_at=claim.provision_claimed_at,
            delivery_channel_id="new-thread",
            thread_channel_id="new-thread",
            expected_provisional_title="New conversation",
            proof_kind=ExternalChannelDiscordThreadTitleProofKind.DIRECT,
            now=_at(2),
        )

        assert settled is not None
        assert (
            settled.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.UNMANAGED
        )
        assert (
            settled.title_status is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )
        assert settled.provision_failure_kind == "delivery_channel_conflict"
        labels = resource.labels
        assert labels is not None
        assert labels["delivery_channel_id"] == "existing-thread"

    async def test_settlement_terminalizes_revoked_authority(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Final settlement fails closed when an owner revokes title authority."""
        fixture = await _create_title_fixture(rdb_session, suffix="authority-revoked")
        repository = ExternalChannelTitleRepository()
        claimed = await repository.claim_due_provisioning(
            rdb_session,
            now=_at(1),
            stale_before=_at(0),
            limit=10,
        )
        assert len(claimed) == 1
        claim = claimed[0]
        assert claim.provision_claimed_at is not None
        agent_session = await rdb_session.get(
            RDBAgentSession,
            fixture.agent_session_id,
        )
        assert agent_session is not None
        agent = await rdb_session.get(RDBAgent, agent_session.agent_id)
        assert agent is not None
        agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        await rdb_session.flush()

        settled = await repository.settle_provisioning_ready(
            rdb_session,
            projection_id=fixture.projection_id,
            expected_provision_attempt_count=claim.provision_attempt_count,
            expected_provision_claimed_at=claim.provision_claimed_at,
            delivery_channel_id="new-thread",
            thread_channel_id="new-thread",
            expected_provisional_title="New conversation",
            proof_kind=ExternalChannelDiscordThreadTitleProofKind.DIRECT,
            now=_at(2),
        )

        assert settled is not None
        assert (
            settled.provisioning_status
            is ExternalChannelDiscordThreadTitleProvisioningStatus.FAILED
        )
        assert (
            settled.title_status is ExternalChannelDiscordThreadTitleStatus.RELINQUISHED
        )
        assert settled.provision_failure_kind == "authority_revoked"
