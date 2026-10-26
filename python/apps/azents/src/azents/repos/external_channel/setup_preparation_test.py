"""PostgreSQL coverage for claim-owned first-mention preparation."""

import dataclasses
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import sqlalchemy as sa

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessRequestStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressAuthorityKind,
    ExternalChannelIngressProfile,
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelSetupClaimStatus,
    ExternalChannelSetupPreparationStatus,
    ExternalChannelWorkProjectionStatus,
)
from azents.core.external_channel_conversation_data import (
    ExternalChannelConversationScope,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelOperationDeadline,
)
from azents.core.external_channel_ingestion import (
    ExternalChannelCanonicalHistoryMessage,
    ExternalChannelIngestionOperation,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelSetupPreparationBoundary,
    ExternalChannelTriggerLocator,
)
from azents.core.external_channel_participation_state import (
    build_setup_continuation_request,
    setup_source_from_projection,
)
from azents.core.external_channel_provider_effect import ProviderEffectPlan
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessRequest,
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBlock,
    RDBExternalChannelConnection,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelSetupClaim,
)
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequestCreate,
    ExternalChannelParticipationSetting,
)
from azents.repos.external_channel.mailbox_ingestion import (
    _commit_prepared_setup_control,
)
from azents.repos.external_channel.repository_test import (
    _at,
    _create_discord_gateway_typing_fixture,
)
from azents.repos.external_channel.setup_preparation import (
    ExternalChannelSetupPreparationRepository,
    setup_preparation_current,
)
from azents.repos.external_channel.setup_preparation_fence import (
    setup_preparation_dispatch_current,
)
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.services.external_channel.ingestion_history import (
    _validate_trigger_file_count,
)


@dataclasses.dataclass(frozen=True)
class _Context:
    operations: ExternalChannelSetupPreparationRepository
    request: ExternalChannelIngestionRequest
    sessions: SessionManager[WriteSession]


@pytest_asyncio.fixture
async def preparation_context(
    rdb_session_manager: SessionManager[WriteSession],
) -> _Context:
    async with rdb_session_manager() as session:
        fixture = await _create_discord_gateway_typing_fixture(session)
        config = await fixture.repository.get_connection_configuration(
            session, connection_id=fixture.connection_id
        )
        assert config is not None
        connection = await session.write_session.get(
            RDBExternalChannelConnection, fixture.connection_id
        )
        assert connection is not None
        connection.provider_config = {
            "provider": "discord",
            "target_guild_id": "100",
            "thread_auto_archive_duration_minutes": 1440,
            "suppress_url_previews": True,
        }
        request = ExternalChannelIngestionRequest(
            locator=ExternalChannelTriggerLocator(
                connection_id=fixture.connection_id,
                provider=ExternalChannelProvider.DISCORD,
                provider_event_type="discord_message_create",
                provider_tenant_id="100",
                provider_channel_id="200",
                provider_parent_channel_id="200",
                provider_thread_key=None,
                delivery_thread_key="600",
                provider_resource_key="discord:100:600",
                trigger_provider_message_key="discord:100:600",
                trigger_provider_message_id="600",
                trigger_position="00000000000000000600",
                provider_user_id="400",
                invocation=True,
                expected_file_count=0,
            ),
            scope=ExternalChannelConversationScope(
                connection_id=fixture.connection_id,
                kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id="200",
                provider_thread_key=None,
            ),
            authority=ExternalChannelIngressAuthority(
                kind=ExternalChannelIngressAuthorityKind.LEASE,
                ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
                configuration_generation=config.configuration_generation,
                lease_owner=fixture.lease_owner,
                lease_generation=fixture.lease_generation,
            ),
            deadline=ExternalChannelOperationDeadline(_at(3)),
            operation=ExternalChannelIngestionOperation.CURRENT_TRIGGER,
            selected_route_id=None,
            replay_boundary=None,
            initial_title_eligible=False,
        )
        await session.write_session.commit()
    return _Context(
        ExternalChannelSetupPreparationRepository(
            session_manager=rdb_session_manager, repository=fixture.repository
        ),
        request,
        rdb_session_manager,
    )


@pytest.mark.asyncio
async def test_setup_receipt_deduplicates_and_replaces_latest_source(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    assert await c.operations.admit(request=c.request, now=_at(2)) == claim_id
    locator = dataclasses.replace(
        c.request.locator,
        trigger_provider_message_id="601",
        trigger_provider_message_key="discord:100:601",
        trigger_position="00000000000000000601",
        provider_resource_key="discord:100:601",
        delivery_thread_key="601",
    )
    newer = dataclasses.replace(c.request, locator=locator)
    assert await c.operations.admit(request=newer, now=_at(3)) == claim_id
    assert await c.operations.admit(request=c.request, now=_at(3)) == claim_id
    async with c.sessions() as session:
        rows = list(
            await session.read_session.scalars(sa.select(RDBExternalChannelSetupClaim))
        )
        assert len(rows) == 1
        assert rows[0].source_revision == 2
        assert (
            rows[0].source_projection["setup_source"]["trigger_provider_message_id"]
            == "601"
        )
        assert rows[0].status is ExternalChannelSetupClaimStatus.PENDING_LOCATION
    assert await c.operations.recoverable_ids(now=_at(3), limit=10) == [claim_id]


@pytest.mark.asyncio
async def test_expired_preparation_reclaims_and_fences_previous_owner(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    first = await c.operations.claim(
        claim_id=claim_id,
        owner="first",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert first.request is not None
    blocked = await c.operations.claim(
        claim_id=claim_id,
        owner="second",
        now=_at(3),
        deadline=ExternalChannelOperationDeadline(_at(5)),
    )
    assert blocked.request is None
    reclaimed = await c.operations.claim(
        claim_id=claim_id,
        owner="second",
        now=_at(6),
        deadline=ExternalChannelOperationDeadline(_at(8)),
    )
    assert reclaimed.request is not None
    old = first.request.replay_boundary
    current = reclaimed.request.replay_boundary
    assert isinstance(old, ExternalChannelSetupPreparationBoundary)
    assert isinstance(current, ExternalChannelSetupPreparationBoundary)
    async with c.sessions() as session:
        assert not await setup_preparation_current(
            session,
            boundary=old,
            configuration_generation=c.request.authority.configuration_generation,
            now=_at(6),
        )
        assert await setup_preparation_current(
            session,
            boundary=current,
            configuration_generation=c.request.authority.configuration_generation,
            now=_at(6),
        )
    assert not await c.operations.transition(
        boundary=old, dispatch=True, retry=False, now=_at(6)
    )


@pytest.mark.asyncio
async def test_expired_dispatch_is_uncertain_and_not_replayed(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="first",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    boundary = attempt.request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    assert await c.operations.transition(
        boundary=boundary, dispatch=True, retry=False, now=_at(2)
    )
    recovered = await c.operations.claim(
        claim_id=claim_id,
        owner="second",
        now=_at(6),
        deadline=ExternalChannelOperationDeadline(_at(8)),
    )
    assert recovered.request is None
    assert recovered.failure_code == "setup_dispatch_uncertain"
    assert await c.operations.recoverable_ids(now=_at(6), limit=10) == []


@pytest.mark.asyncio
async def test_configuration_change_revokes_preparation(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    async with c.sessions() as session:
        connection = await session.write_session.get(
            RDBExternalChannelConnection, c.request.locator.connection_id
        )
        assert connection is not None
        connection.configuration_generation += 1
        await session.write_session.commit()
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="new",
        now=_at(3),
        deadline=ExternalChannelOperationDeadline(_at(5)),
    )
    assert attempt.request is None
    assert attempt.failure_code == "setup_authority_changed"


@pytest.mark.asyncio
async def test_blocked_mention_does_not_replace_eligible_source(
    preparation_context: _Context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    monkeypatch.setattr(
        c.operations.repository, "get_active_block", AsyncMock(return_value=MagicMock())
    )
    newer = dataclasses.replace(
        c.request,
        locator=dataclasses.replace(
            c.request.locator,
            trigger_provider_message_id="601",
            trigger_provider_message_key="discord:100:601",
            trigger_position="00000000000000000601",
            provider_resource_key="discord:100:601",
            delivery_thread_key="601",
        ),
    )
    assert await c.operations.admit(request=newer, now=_at(3)) is None
    async with c.sessions() as session:
        row = await session.read_session.get(RDBExternalChannelSetupClaim, claim_id)
        assert row is not None
        assert row.source_revision == 1
        assert (
            row.source_projection["setup_source"]["trigger_provider_message_id"]
            == "600"
        )


async def _reserve_access_control(
    c: _Context,
    request: ExternalChannelIngestionRequest,
) -> ProviderEffectPlan:
    boundary = request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    async with c.sessions() as session:
        claim = await c.operations.repository.lock_setup_claim(
            session, claim_id=boundary.claim_id
        )
        assert claim is not None and claim.route_id is not None
        access = await c.operations.repository.create_access_request_idempotent(
            session,
            ExternalChannelAccessRequestCreate(
                route_id=claim.route_id,
                source_resource_id=claim.source_resource_id,
                resource_id=claim.source_resource_id,
                trigger_provider_message_key=request.locator.trigger_provider_message_key,
                principal_id=claim.principal_id,
                agent_session_id=None,
                setup_claim_id=claim.id,
                status=ExternalChannelAccessRequestStatus.PENDING,
                decision_policy_snapshot={"policy_version": 2},
                decided_by_user_id=None,
                decision_summary=None,
                expires_at=_at(17),
                decided_at=None,
                control_provider_message_key=None,
                control_projection_status=None,
                connection_id=claim.connection_id,
                conversation_position_id=claim.conversation_position_id,
                range_start_position=None,
                trigger_position=boundary.trigger_position,
            ),
        )
        plan = await ExternalChannelWorkRepository().prepare_access_control_create(
            session,
            access_request_id=access.id,
            connection_id=claim.connection_id,
            resource_id=None,
            route_id=None,
            binding_id=None,
            request_payload={
                "provider": "discord",
                "guild_id": "100",
                "channel_id": "200",
                "access_request_id": access.id,
                "participant_provider_user_id": "400",
                "text": "Access approval required",
                "embeds": [],
                "components": [],
            },
            operation_seed=f"access-request:{access.id}",
        )
        assert plan is not None
        # Use the request's test clock instead of wall time in the shared helper.
        with patch(
            "azents.repos.external_channel.mailbox_ingestion._utc_now",
            return_value=_at(2),
        ):
            await _commit_prepared_setup_control(session, request=request, plan=plan)
        return plan


@pytest.mark.asyncio
async def test_access_reservation_and_dispatch_intent_commit_together(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="owner",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    await _reserve_access_control(c, attempt.request)
    async with c.sessions() as session:
        row = await session.read_session.get(RDBExternalChannelSetupClaim, claim_id)
        access = await session.read_session.scalar(
            sa.select(RDBExternalChannelAccessRequest)
        )
        assert row is not None and access is not None
        assert (
            row.preparation_status is ExternalChannelSetupPreparationStatus.DISPATCHING
        )
        assert (
            access.control_projection_status
            is ExternalChannelWorkProjectionStatus.UNKNOWN
        )
    recovered = await c.operations.claim(
        claim_id=claim_id,
        owner="recovery",
        now=_at(6),
        deadline=ExternalChannelOperationDeadline(_at(8)),
    )
    assert recovered.request is None
    assert recovered.failure_code == "setup_dispatch_uncertain"


@pytest.mark.asyncio
async def test_definite_failed_access_control_can_be_reprepared(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="owner",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    await _reserve_access_control(c, attempt.request)
    async with c.sessions() as session:
        await session.write_session.execute(
            sa.update(RDBExternalChannelAccessRequest).values(
                control_projection_status=ExternalChannelWorkProjectionStatus.FAILED
            )
        )
        await session.write_session.commit()
    boundary = attempt.request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    assert await c.operations.transition(
        boundary=boundary, dispatch=False, retry=True, now=_at(2)
    )
    retried = await c.operations.claim(
        claim_id=claim_id,
        owner="retry",
        now=_at(3),
        deadline=ExternalChannelOperationDeadline(_at(5)),
    )
    assert retried.request is not None
    await _reserve_access_control(c, retried.request)


@pytest.mark.asyncio
async def test_new_source_invalidates_inflight_preparation(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="old",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    old = attempt.request.replay_boundary
    assert isinstance(old, ExternalChannelSetupPreparationBoundary)
    newer = dataclasses.replace(
        c.request,
        locator=dataclasses.replace(
            c.request.locator,
            trigger_provider_message_id="601",
            trigger_provider_message_key="discord:100:601",
            trigger_position="00000000000000000601",
            provider_resource_key="discord:100:601",
            delivery_thread_key="601",
        ),
    )
    assert await c.operations.admit(request=newer, now=_at(3)) == claim_id
    assert not await c.operations.transition(
        boundary=old, dispatch=True, retry=False, now=_at(3)
    )
    current = await c.operations.claim(
        claim_id=claim_id,
        owner="new",
        now=_at(3),
        deadline=ExternalChannelOperationDeadline(_at(5)),
    )
    assert current.request is not None
    assert current.request.locator.trigger_provider_message_id == "601"


@pytest.mark.asyncio
async def test_retry_limit_finishes_with_explicit_terminal_result(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    now = _at(2)
    for index in range(5):
        attempt = await c.operations.claim(
            claim_id=claim_id,
            owner=f"attempt-{index}",
            now=now,
            deadline=ExternalChannelOperationDeadline(
                now + datetime.timedelta(minutes=2)
            ),
        )
        assert attempt.request is not None
        boundary = attempt.request.replay_boundary
        assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
        assert await c.operations.transition(
            boundary=boundary, dispatch=False, retry=True, now=now
        )
        now += datetime.timedelta(seconds=61)
    exhausted = await c.operations.claim(
        claim_id=claim_id,
        owner="exhausted",
        now=now,
        deadline=ExternalChannelOperationDeadline(now + datetime.timedelta(minutes=2)),
    )
    assert exhausted.request is None
    assert exhausted.failure_code == "setup_retry_exhausted"
    assert await c.operations.recoverable_ids(now=now, limit=10) == []


@pytest.mark.asyncio
async def test_invalidated_selection_cannot_dispatch_prepared_control(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="old",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    boundary = attempt.request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    async with c.sessions() as session:
        await c.operations.repository.terminate_setup_claim(
            session,
            claim_id=claim_id,
            expected_claim_generation=boundary.claim_generation,
            status=ExternalChannelSetupClaimStatus.INVALIDATED,
        )
        await session.write_session.commit()
    assert not await c.operations.transition(
        boundary=boundary, dispatch=True, retry=False, now=_at(3)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        "source",
        "selection",
        "invalidation",
        "configuration",
        "disconnect",
        "owner",
        "lease",
        "status",
        "expiry",
        "setting",
        "block",
        "route_removed",
        "agent_deleting",
    ],
)
async def test_final_dispatch_rejects_changes_after_dispatch_commit(
    preparation_context: _Context,
    change: str,
) -> None:
    c = preparation_context
    claim_id = await c.operations.admit(request=c.request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="owner",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    boundary = attempt.request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    plan = await _reserve_access_control(c, attempt.request)
    async with c.sessions() as session:
        assert await setup_preparation_dispatch_current(
            session, boundary=boundary, now=_at(3)
        )
        with patch("azents.repos.external_channel.work.datetime") as clock:
            clock.datetime.now.return_value = _at(3)
            assert (
                await ExternalChannelWorkRepository().revalidate_direct_control(
                    session, plan=plan, preparation_boundary=boundary
                )
                is not None
            )
        row = await session.write_session.get(RDBExternalChannelSetupClaim, claim_id)
        connection = await session.write_session.get(
            RDBExternalChannelConnection, boundary.connection_id
        )
        assert row is not None and connection is not None
        if change == "source":
            row.source_revision += 1
        elif change == "selection":
            row.claim_generation += 1
        elif change == "invalidation":
            row.status = ExternalChannelSetupClaimStatus.INVALIDATED
        elif change == "configuration":
            connection.configuration_generation += 1
        elif change == "disconnect":
            connection.disconnected_at = _at(3)
        elif change == "owner":
            row.preparation_lease_owner = "replacement"
        elif change == "lease":
            row.preparation_lease_until = _at(3)
        elif change == "status":
            row.preparation_status = ExternalChannelSetupPreparationStatus.RUNNING
        elif change == "expiry":
            row.expires_at = _at(3)
        elif change == "setting":
            assert row.route_id is not None
            session.write_session.add(
                RDBExternalChannelParticipationSetting(
                    connection_id=row.connection_id,
                    provider_parent_channel_id=row.provider_parent_channel_id,
                    route_id=row.route_id,
                    location=ExternalChannelConversationLocation.THREADS,
                    response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                    settings_generation=1,
                    status=ExternalChannelParticipationSettingStatus.ACTIVE,
                    configured_by_principal_id=row.principal_id,
                )
            )
        elif change in {"block", "route_removed", "agent_deleting"}:
            assert row.route_id is not None
            route = await session.write_session.get(
                RDBExternalChannelAgentRoute, row.route_id
            )
            assert route is not None and route.agent_id is not None
            if change == "block":
                user = await UserRepository().create(
                    session, UserCreate(email="setup-block-actor@example.com")
                )
                session.write_session.add(
                    RDBExternalChannelBlock(
                        agent_id=route.agent_id,
                        principal_id=row.principal_id,
                        blocked_by_user_id=user.id,
                    )
                )
            elif change == "route_removed":
                route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
                route.catalog_removed_at = _at(3)
            else:
                agent = await session.write_session.get(RDBAgent, route.agent_id)
                assert agent is not None
                agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        else:
            raise AssertionError(change)
        await session.write_session.commit()
    async with c.sessions() as session:
        assert not await setup_preparation_dispatch_current(
            session, boundary=boundary, now=_at(3)
        )
        with patch("azents.repos.external_channel.work.datetime") as clock:
            clock.datetime.now.return_value = _at(3)
            assert (
                await ExternalChannelWorkRepository().revalidate_direct_control(
                    session, plan=plan, preparation_boundary=boundary
                )
                is None
            )


@pytest.mark.asyncio
async def test_setup_recovery_preserves_callback_attachment_count(
    preparation_context: _Context,
) -> None:
    c = preparation_context
    request = dataclasses.replace(
        c.request, locator=dataclasses.replace(c.request.locator, expected_file_count=2)
    )
    claim_id = await c.operations.admit(request=request, now=_at(2))
    assert claim_id is not None
    attempt = await c.operations.claim(
        claim_id=claim_id,
        owner="owner",
        now=_at(2),
        deadline=ExternalChannelOperationDeadline(_at(4)),
    )
    assert attempt.request is not None
    assert attempt.request.locator.expected_file_count == 2
    incomplete_trigger = ExternalChannelCanonicalHistoryMessage(
        provider_message_key=request.locator.trigger_provider_message_key,
        provider_position=request.locator.trigger_position,
        revision_key="revision",
        revision_kind=ExternalChannelMessageRevisionKind.ORIGINAL,
        lifecycle=ExternalChannelMessageLifecycle.CURRENT,
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_user_id="400",
        sender_display_name=None,
        normalized_body=None,
        attachment_metadata=None,
        reference_mappings=None,
        normalized_size=0,
        provider_created_at=None,
        provider_updated_at=None,
        original_url=None,
    )
    with pytest.raises(ExternalChannelHistoryTemporaryFailure):
        _validate_trigger_file_count(
            locator=attempt.request.locator, trigger=incomplete_trigger
        )
    boundary = attempt.request.replay_boundary
    assert isinstance(boundary, ExternalChannelSetupPreparationBoundary)
    assert await c.operations.transition(
        boundary=boundary, dispatch=False, retry=True, now=_at(2)
    )
    retried = await c.operations.claim(
        claim_id=claim_id,
        owner="retry",
        now=_at(3),
        deadline=ExternalChannelOperationDeadline(_at(5)),
    )
    assert retried.request is not None
    assert retried.request.locator.expected_file_count == 2
    async with c.sessions() as session:
        repository = c.operations.repository
        claim = await repository.get_setup_claim(session, claim_id=claim_id)
        configuration = await repository.get_connection_configuration(
            session, connection_id=request.locator.connection_id
        )
        assert claim is not None and configuration is not None
        resource = await repository.get_resource(
            session, resource_id=claim.source_resource_id
        )
        principal = await repository.get_principal(
            session, principal_id=claim.principal_id
        )
        assert resource is not None and principal is not None
        selected = claim.model_copy(
            update={
                "selected_resource_id": resource.id,
                "selected_source_revision": claim.source_revision,
                "selected_setting_id": "setting",
            }
        )
        continuation = build_setup_continuation_request(
            configuration=configuration,
            claim=selected,
            setting=ExternalChannelParticipationSetting.model_construct(
                id="setting",
                settings_generation=1,
                location=ExternalChannelConversationLocation.THREADS,
            ),
            source_resource=resource,
            principal=principal,
            source=setup_source_from_projection(claim.source_projection),
            deadline=request.deadline,
        )
        assert continuation.locator.expected_file_count == 2
