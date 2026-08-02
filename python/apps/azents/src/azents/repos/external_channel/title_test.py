"""External Channel automatic title repository tests."""

import datetime
from dataclasses import dataclass

import pytest
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    EventKind,
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDiscordThreadObservationStatus,
    ExternalChannelDiscordThreadTitleProofKind,
    ExternalChannelDiscordThreadTitleProvisioningStatus,
    ExternalChannelDiscordThreadTitleStatus,
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
    RDBExternalChannelDiscordThreadTitleProjection,
    RDBExternalChannelResource,
    RDBExternalChannelSessionTitleCandidate,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelDiscordThreadTitleProjectionCreate,
    ExternalChannelResourceCreate,
    ExternalChannelSessionTitleCandidateCreate,
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
            app_mode=ExternalChannelAppMode.SINGLE,
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
            connection_app_mode=ExternalChannelAppMode.SINGLE,
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
