"""External Channel event processing domain tests."""

import datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    AgentLifecycleStatus,
    AgentSessionStartReason,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelBindingActivationStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelMessageLifecycle,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAccessGrant,
    RDBExternalChannelAccessRequest,
    RDBExternalChannelBinding,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInvocationBatch,
    RDBExternalChannelPendingContext,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.session import SessionManager
from azents.repos.action_execution import ActionExecutionRepository
from azents.repos.agent import AgentRepository
from azents.repos.agent_execution import AgentRunRepository, EventTranscriptRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.external_channel.data import (
    ExternalChannelAccessRequestCreate,
    ExternalChannelAgentRoute,
    ExternalChannelAgentRouteCreate,
    ExternalChannelConnectionConfiguration,
    ExternalChannelConnectionCreate,
    ExternalChannelEvent,
    ExternalChannelEventCreate,
    ExternalChannelMessageCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.input_buffer import InputBufferRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.services.exchange_file import ExchangeFileService
from azents.services.external_channel.access import (
    ExternalChannelAccessDecisionError,
    ExternalChannelAccessService,
)
from azents.services.external_channel.credentials import ExternalChannelCredentialsCodec
from azents.services.external_channel.event_processor import (
    ExternalChannelEventProcessorService,
    ExternalChannelPersistedMessage,
    ExternalChannelPersistedRevision,
)
from azents.services.external_channel.slack_events import (
    SlackConversationClient,
    SlackNormalizedMessage,
    normalize_slack_event,
)
from azents.services.input_buffer import InputBufferService
from azents.services.model_file import ModelFileService
from azents.testing.model_selection import make_test_model_selection_dict
from azents.worker.session.lifecycle import SessionLifecycleService


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(2026, 7, 22, 0, 0, second, tzinfo=datetime.UTC)


async def _setup_route(
    session: AsyncSession,
) -> tuple[str, str, str, ExternalChannelRepository]:
    workspace_result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name="External Channel processor test",
            handle="external-channel-processor-test",
        ),
    )
    assert isinstance(workspace_result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        "external-channel-processor-test",
    )
    assert workspace_id is not None
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name="external-channel-processor-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="external-channel-processor-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="External Channel processor Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    session.add(agent)
    await session.flush()
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        session,
        ExternalChannelConnectionCreate(
            workspace_id=workspace_id,
            provider=ExternalChannelProvider.SLACK,
            transport=ExternalChannelTransport.HTTP,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_app_id="A1",
            provider_tenant_id="T1",
            provider_bot_user_id="B1",
            http_callback_selector_hash="processor-selector",
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
    route = await repository.create_agent_route(
        session,
        ExternalChannelAgentRouteCreate(
            connection_id=connection.id,
            agent_id=agent.id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
        ),
    )
    await session.commit()
    return connection.id, route.id, agent.id, repository


class _TestEventProcessorService(ExternalChannelEventProcessorService):
    """Expose transaction helpers only to focused database tests."""

    async def persist_message_event_for_test(
        self,
        *,
        event: ExternalChannelEvent,
        configuration: ExternalChannelConnectionConfiguration,
        message: SlackNormalizedMessage,
        original_url: str | None,
    ) -> ExternalChannelPersistedMessage:
        return await self._persist_message_event(
            event=event,
            configuration=configuration,
            message=message,
            original_url=original_url,
        )

    async def persist_normalized_message_for_test(
        self,
        session: AsyncSession,
        *,
        route: ExternalChannelAgentRoute,
        resource: ExternalChannelResource,
        message: SlackNormalizedMessage,
        now: datetime.datetime,
    ) -> ExternalChannelPersistedRevision:
        return await self._persist_normalized_message(
            session,
            route=route,
            resource=resource,
            message=message,
            source_event_id=None,
            now=now,
            original_url=None,
        )


def _service(
    session_manager: SessionManager[AsyncSession],
    repository: ExternalChannelRepository,
) -> _TestEventProcessorService:
    session_lifecycle = MagicMock(spec=SessionLifecycleService)
    session_lifecycle.send_session_wake_up = AsyncMock()
    return _TestEventProcessorService(
        session_manager=session_manager,
        repository=repository,
        credentials_codec=cast(
            ExternalChannelCredentialsCodec,
            MagicMock(spec=ExternalChannelCredentialsCodec),
        ),
        slack_client=cast(
            SlackConversationClient,
            MagicMock(spec=SlackConversationClient),
        ),
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        config=Config.model_construct(web_url="https://azents.example"),
        input_buffer_service=InputBufferService(
            session_manager=session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=cast(ExchangeFileService, MagicMock()),
            model_file_service=cast(ModelFileService, MagicMock()),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
            vfs_projection_service=None,
            external_channel_repository=repository,
        ),
        session_lifecycle=cast(SessionLifecycleService, session_lifecycle),
    )


async def test_unknown_human_mention_creates_request_without_session_or_wake(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Unknown participants remain pending and do not create AgentSession state."""
    async with rdb_session_manager() as session:
        connection_id, _, agent_id, repository = await _setup_route(session)
        admission = await repository.admit_event(
            session,
            ExternalChannelEventCreate(
                connection_id=connection_id,
                provider_event_id="Ev1",
                transport_envelope_id="Ev1",
                event_type="app_mention",
                provider_app_id="A1",
                provider_tenant_id="T1",
                provider_enterprise_id=None,
                resource_correlation_key="C1:1784678400.000100",
                eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
                envelope={"event": {"type": "app_mention"}},
                status=ExternalChannelEventStatus.ACCEPTED,
                provider_occurred_at=_at(1),
                received_at=_at(1),
            ),
        )
        await session.commit()
    normalized = normalize_slack_event(
        event_type="app_mention",
        tenant_id="T1",
        envelope={
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1784678400.000100",
                "text": "<@B1> investigate",
            }
        },
    )
    assert isinstance(normalized, SlackNormalizedMessage)
    async with rdb_session_manager() as session:
        configuration = await repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
    assert configuration is not None

    result = await _service(
        rdb_session_manager,
        repository,
    ).persist_message_event_for_test(
        event=admission.event,
        configuration=configuration,
        message=normalized,
        original_url=("https://example.slack.com/archives/C1/p1721600000000100"),
    )

    async with rdb_session_manager() as session:
        requests = list(
            await session.scalars(sa.select(RDBExternalChannelAccessRequest))
        )
        bindings = list(await session.scalars(sa.select(RDBExternalChannelBinding)))
        sessions = list(
            await session.scalars(
                sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
            )
        )
        pending = list(
            await session.scalars(sa.select(RDBExternalChannelPendingContext))
        )
        attempts = list(
            await session.scalars(sa.select(RDBExternalChannelDeliveryAttempt))
        )
        source_message = await repository.get_message(
            session,
            message_id=requests[0].source_message_id,
        )

    assert len(requests) == 1
    assert requests[0].status is ExternalChannelAccessRequestStatus.PENDING
    assert requests[0].agent_session_id is None
    assert bindings == []
    assert sessions == []
    assert len(pending) == 1
    assert len(attempts) == 1
    assert attempts[0].status is ExternalChannelDeliveryStatus.PENDING
    assert source_message is not None
    assert source_message.original_url == (
        "https://example.slack.com/archives/C1/p1721600000000100"
    )
    assert result.control_delivery_attempt_id == attempts[0].id
    assert result.hydration_required is True

    async with rdb_session_manager() as session:
        approver = await UserRepository().create(
            session,
            UserCreate(email="external-channel-approver@example.com"),
        )
        await session.commit()
    access_service = ExternalChannelAccessService(
        session_manager=rdb_session_manager,
        repository=repository,
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        input_buffer_service=InputBufferService(
            session_manager=rdb_session_manager,
            input_buffer_repository=InputBufferRepository(),
            exchange_file_service=cast(ExchangeFileService, MagicMock()),
            model_file_service=cast(ModelFileService, MagicMock()),
            agent_session_repository=AgentSessionRepository(),
            event_transcript_repository=EventTranscriptRepository(),
            agent_run_repository=AgentRunRepository(),
            action_execution_repository=ActionExecutionRepository(),
            vfs_projection_service=None,
            external_channel_repository=repository,
        ),
        session_lifecycle=cast(
            SessionLifecycleService,
            MagicMock(send_session_wake_up=AsyncMock()),
        ),
    )
    allowed = await access_service.allow(
        access_request_id=requests[0].id,
        scope=ExternalChannelAccessGrantScope.SESSION,
        decided_by_user_id=approver.id,
        decision_summary="Approved for this linked Session.",
        now=_at(3),
    )
    repeated = await access_service.allow(
        access_request_id=requests[0].id,
        scope=ExternalChannelAccessGrantScope.SESSION,
        decided_by_user_id=approver.id,
        decision_summary="Repeated decision.",
        now=_at(4),
    )

    async with rdb_session_manager() as session:
        created_session = await session.get(
            RDBAgentSession,
            allowed.binding.agent_session_id,
        )
        grants = list(await session.scalars(sa.select(RDBExternalChannelAccessGrant)))

    assert allowed.request.status is ExternalChannelAccessRequestStatus.ALLOWED
    assert allowed.binding.activation_status is (
        ExternalChannelBindingActivationStatus.WAITING_HYDRATION
    )
    assert created_session is not None
    assert created_session.start_reason is AgentSessionStartReason.EXTERNAL_CHANNEL
    assert len(grants) == 1
    assert repeated.binding.id == allowed.binding.id
    assert repeated.grant.id == allowed.grant.id

    async with rdb_session_manager() as session:
        active_binding = await session.get(
            RDBExternalChannelBinding,
            allowed.binding.id,
        )
        assert active_binding is not None
        active_binding.activation_status = ExternalChannelBindingActivationStatus.ACTIVE
        active_binding.activated_at = _at(4)
        await session.commit()

    async with rdb_session_manager() as session:
        second_admission = await repository.admit_event(
            session,
            ExternalChannelEventCreate(
                connection_id=connection_id,
                provider_event_id="Ev2",
                transport_envelope_id="Ev2",
                event_type="app_mention",
                provider_app_id="A1",
                provider_tenant_id="T1",
                provider_enterprise_id=None,
                resource_correlation_key="C1:1784678400.000100",
                eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
                envelope={"event": {"type": "app_mention"}},
                status=ExternalChannelEventStatus.ACCEPTED,
                provider_occurred_at=_at(5),
                received_at=_at(5),
            ),
        )
        await session.commit()
    second_mention = normalize_slack_event(
        event_type="app_mention",
        tenant_id="T1",
        envelope={
            "event": {
                "type": "app_mention",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U2",
                "ts": "1784678401.000100",
                "thread_ts": "1784678400.000100",
                "text": "<@B1> can I add context?",
            }
        },
    )
    assert isinstance(second_mention, SlackNormalizedMessage)
    second_result = await _service(
        rdb_session_manager,
        repository,
    ).persist_message_event_for_test(
        event=second_admission.event,
        configuration=configuration,
        message=second_mention,
        original_url=None,
    )

    async with rdb_session_manager() as session:
        all_requests = list(
            await session.scalars(
                sa.select(RDBExternalChannelAccessRequest).order_by(
                    RDBExternalChannelAccessRequest.created_at
                )
            )
        )
        all_bindings = list(await session.scalars(sa.select(RDBExternalChannelBinding)))
        all_sessions = list(
            await session.scalars(
                sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
            )
        )
        second_attempt = await session.get(
            RDBExternalChannelDeliveryAttempt,
            second_result.control_delivery_attempt_id,
        )

    assert len(all_requests) == 2
    assert all_requests[1].agent_session_id == allowed.binding.agent_session_id
    assert len(all_bindings) == 1
    assert len(all_sessions) == 1
    assert second_attempt is not None
    assert second_attempt.binding_id == allowed.binding.id

    async with rdb_session_manager() as session:
        later_admission = await repository.admit_event(
            session,
            ExternalChannelEventCreate(
                connection_id=connection_id,
                provider_event_id="Ev3",
                transport_envelope_id="Ev3",
                event_type="message",
                provider_app_id="A1",
                provider_tenant_id="T1",
                provider_enterprise_id=None,
                resource_correlation_key="C1:1784678400.000100",
                eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
                envelope={"event": {"type": "message"}},
                status=ExternalChannelEventStatus.ACCEPTED,
                provider_occurred_at=_at(6),
                received_at=_at(6),
            ),
        )
        await session.commit()
    later_context = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope={
            "event": {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U3",
                "ts": "1784678402.000100",
                "thread_ts": "1784678400.000100",
                "text": "later context",
            }
        },
    )
    assert isinstance(later_context, SlackNormalizedMessage)
    await _service(
        rdb_session_manager,
        repository,
    ).persist_message_event_for_test(
        event=later_admission.event,
        configuration=configuration,
        message=later_context,
        original_url=None,
    )

    second_allowed = await access_service.allow(
        access_request_id=all_requests[1].id,
        scope=ExternalChannelAccessGrantScope.SESSION,
        decided_by_user_id=approver.id,
        decision_summary="Approved in the existing linked Session.",
        now=_at(7),
    )

    async with rdb_session_manager() as session:
        final_sessions = list(
            await session.scalars(
                sa.select(RDBAgentSession).where(RDBAgentSession.agent_id == agent_id)
            )
        )
        batches = list(
            await session.scalars(sa.select(RDBExternalChannelInvocationBatch))
        )
        projection_items = await repository.list_invocation_projection_items(
            session,
            batch_id=batches[0].id,
        )
        remaining_pending = list(
            await session.scalars(sa.select(RDBExternalChannelPendingContext))
        )

    assert second_allowed.binding.id == allowed.binding.id
    assert second_allowed.binding.agent_session_id == allowed.binding.agent_session_id
    assert len(final_sessions) == 1
    assert len(batches) == 1
    assert batches[0].trigger_message_id == all_requests[1].source_message_id
    assert [item.message_id for item in projection_items] == [
        all_requests[0].source_message_id,
        all_requests[1].source_message_id,
    ]
    assert all(item.correction_of_revision_id is None for item in projection_items)
    assert len(remaining_pending) == 1
    assert remaining_pending[0].provider_position == later_context.provider_position


async def test_pending_context_is_trimmed_by_count_and_size(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Oldest context is removed until both configured bounds are satisfied."""
    async with rdb_session_manager() as session:
        connection_id, route_id, _, repository = await _setup_route(session)
        route = await repository.get_agent_route(session, route_id=route_id)
        assert route is not None
        resource = await repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key="slack:T1:C1:1784678400.000100",
                labels={
                    "provider": "slack",
                    "tenant_id": "T1",
                    "channel_id": "C1",
                    "thread_ts": "1784678400.000100",
                },
                status=ExternalChannelResourceStatus.ACTIVE,
                hydration_status=ExternalChannelHydrationStatus.PENDING,
                hydration_cursor=None,
                hydration_high_watermark_position=None,
                reconciliation_boundary_received_at=None,
                reconciliation_boundary_event_id=None,
                hydration_error_kind=None,
                hydration_error_summary=None,
                hydration_started_at=None,
                hydration_completed_at=None,
                latest_activity_at=_at(1),
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        service = _service(rdb_session_manager, repository)
        for index in range(101):
            timestamp = f"1784678{index:03d}.000100"
            normalized = normalize_slack_event(
                event_type="message",
                tenant_id="T1",
                envelope={
                    "event": {
                        "type": "message",
                        "channel": "C1",
                        "channel_type": "channel",
                        "user": f"U{index}",
                        "ts": timestamp,
                        "thread_ts": "1784678400.000100",
                        "text": "x" * 3000,
                    }
                },
            )
            assert isinstance(normalized, SlackNormalizedMessage)
            await service.persist_normalized_message_for_test(
                session,
                route=route,
                resource=resource,
                message=normalized,
                now=_at(2),
            )
        await session.commit()

    async with rdb_session_manager() as session:
        rows = list(
            await session.scalars(
                sa.select(RDBExternalChannelPendingContext)
                .where(
                    RDBExternalChannelPendingContext.route_id == route_id,
                    RDBExternalChannelPendingContext.resource_id == resource.id,
                )
                .order_by(RDBExternalChannelPendingContext.provider_position)
            )
        )

    assert len(rows) <= 100
    assert sum(row.normalized_size for row in rows) <= 256 * 1024
    assert rows[0].provider_position > "00000000001784678000.000100"


async def test_credential_failure_preserves_agent_route(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Provider credential health never removes the configured Agent route."""
    async with rdb_session_manager() as session:
        connection_id, route_id, _, repository = await _setup_route(session)
        changed = await repository.mark_connection_reconnect_required(
            session,
            connection_id=connection_id,
            reason="missing_scope",
            now=_at(2),
            required_socket_lease_owner=None,
        )
        await session.commit()

    async with rdb_session_manager() as session:
        connection = await repository.get_connection(
            session,
            connection_id=connection_id,
        )
        route = await repository.get_agent_route(session, route_id=route_id)

    assert changed is True
    assert connection is not None
    assert connection.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert connection.socket_gap_detected_at is None
    assert connection.socket_gap_reason is None
    assert route is not None


async def test_valid_health_restores_connection_without_mutating_route(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Successful validation restores connection health without route state."""
    async with rdb_session_manager() as session:
        connection_id, route_id, _, repository = await _setup_route(session)
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        connection.disconnected_at = _at(1)
        connection.socket_gap_detected_at = _at(1)
        connection.socket_gap_reason = "credentials_invalid"
        await session.commit()

    async with rdb_session_manager() as session:
        configuration = await repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
        assert configuration is not None
        assert configuration.encrypted_credentials is not None
        updated = await repository.update_connection_health(
            session,
            connection_id=connection_id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id="T1",
            provider_bot_user_id="B1",
            capabilities={"inbound_events": True},
            checked_at=_at(3),
            expected_encrypted_credentials=configuration.encrypted_credentials,
        )
        await session.commit()

    async with rdb_session_manager() as session:
        route = await repository.get_agent_route(session, route_id=route_id)

    assert updated is not None
    assert updated.status is ExternalChannelConnectionStatus.ACTIVE
    assert updated.socket_gap_detected_at is None
    assert updated.socket_gap_reason is None
    assert route is not None


async def test_routable_route_requires_active_agent_lifecycle(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Only the routed Agent lifecycle controls new execution eligibility."""
    async with rdb_session_manager() as session:
        connection_id, route_id, agent_id, repository = await _setup_route(session)
        route = await repository.get_agent_route(session, route_id=route_id)
        agent = await session.get(RDBAgent, agent_id)
        assert route is not None
        assert agent is not None
        agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
        await session.commit()

    async with rdb_session_manager() as session:
        route = await repository.get_agent_route(session, route_id=route_id)
        routable = await repository.get_routable_route_by_connection_id(
            session,
            connection_id=connection_id,
        )

    assert route is not None
    assert routable is None


async def test_routable_route_rejects_disconnecting_connection(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A disconnecting connection cannot admit new routing work."""
    async with rdb_session_manager() as session:
        connection_id, _, _, repository = await _setup_route(session)
        connection = await session.scalar(
            sa.select(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == connection_id)
            .with_for_update()
        )
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTING
        await session.commit()

    async with rdb_session_manager() as session:
        routable = await repository.get_routable_route_by_connection_id(
            session,
            connection_id=connection_id,
        )

    assert routable is None


async def test_pending_allow_requires_routable_connection(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Pending approval cannot create state while disconnect is in progress."""
    async with rdb_session_manager() as session:
        connection_id, route_id, agent_id, repository = await _setup_route(session)
        resource = await repository.create_resource_idempotent(
            session,
            ExternalChannelResourceCreate(
                connection_id=connection_id,
                resource_type=ExternalChannelResourceType.THREAD,
                provider_resource_key="slack:T1:C1:1784678400.000100",
                labels=None,
                status=ExternalChannelResourceStatus.ACTIVE,
                hydration_status=ExternalChannelHydrationStatus.PENDING,
                hydration_cursor=None,
                hydration_high_watermark_position=None,
                reconciliation_boundary_received_at=None,
                reconciliation_boundary_event_id=None,
                hydration_error_kind=None,
                hydration_error_summary=None,
                hydration_started_at=None,
                hydration_completed_at=None,
                latest_activity_at=None,
                unavailable_at=None,
                deleted_at=None,
            ),
        )
        principal = await repository.create_principal_idempotent(
            session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="T1",
                provider_user_id="U1",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        )
        message = await repository.create_message_idempotent(
            session,
            ExternalChannelMessageCreate(
                resource_id=resource.id,
                provider_message_key="1710000000.000100",
                provider_position="00000000001710000000.000100",
                principal_id=principal.id,
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                current_revision_id=None,
                original_url=None,
                lifecycle=ExternalChannelMessageLifecycle.CURRENT,
                pending_size=0,
                provider_created_at=_at(1),
                provider_updated_at=None,
            ),
        )
        request = await repository.create_access_request_idempotent(
            session,
            ExternalChannelAccessRequestCreate(
                route_id=route_id,
                resource_id=resource.id,
                source_message_id=message.id,
                principal_id=principal.id,
                agent_session_id=None,
                status=ExternalChannelAccessRequestStatus.PENDING,
                decision_policy_snapshot={},
                decided_by_user_id=None,
                decision_summary=None,
                expires_at=_at(10),
                decided_at=None,
            ),
        )
        approver = await UserRepository().create(
            session,
            UserCreate(email="disconnected-allow-approver@example.com"),
        )
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTING
        await session.commit()

    access_service = ExternalChannelAccessService(
        session_manager=rdb_session_manager,
        repository=repository,
        agent_repository=AgentRepository(),
        agent_session_repository=AgentSessionRepository(),
        input_buffer_service=cast(InputBufferService, MagicMock()),
        session_lifecycle=cast(SessionLifecycleService, MagicMock()),
    )
    with pytest.raises(
        ExternalChannelAccessDecisionError,
        match="route is unavailable",
    ):
        await access_service.allow(
            access_request_id=request.id,
            scope=ExternalChannelAccessGrantScope.SESSION,
            decided_by_user_id=approver.id,
            decision_summary="Approve after disconnect.",
            now=_at(2),
        )

    async with rdb_session_manager() as session:
        persisted_request = await session.get(
            RDBExternalChannelAccessRequest,
            request.id,
        )
        bindings = list(
            await session.scalars(
                sa.select(RDBExternalChannelBinding).where(
                    RDBExternalChannelBinding.resource_id == resource.id,
                    RDBExternalChannelBinding.route_id == route_id,
                )
            )
        )
        grants = list(
            await session.scalars(
                sa.select(RDBExternalChannelAccessGrant).where(
                    RDBExternalChannelAccessGrant.agent_id == agent_id,
                    RDBExternalChannelAccessGrant.principal_id == principal.id,
                )
            )
        )
        agent_sessions = list(
            await session.scalars(
                sa.select(RDBAgentSession).where(
                    RDBAgentSession.agent_id == agent_id,
                )
            )
        )

    assert persisted_request is not None
    assert persisted_request.status is ExternalChannelAccessRequestStatus.PENDING
    assert bindings == []
    assert grants == []
    assert agent_sessions == []


async def test_unavailable_http_health_clears_legacy_socket_gap(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """HTTP health updates never retain Socket-only gap metadata."""
    async with rdb_session_manager() as session:
        connection_id, _, _, repository = await _setup_route(session)
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        connection.disconnected_at = _at(1)
        connection.socket_heartbeat_at = _at(1)
        connection.socket_gap_detected_at = _at(1)
        connection.socket_gap_reason = "credentials_invalid"
        await session.commit()

    async with rdb_session_manager() as session:
        configuration = await repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
        assert configuration is not None
        assert configuration.encrypted_credentials is not None
        updated = await repository.update_connection_health(
            session,
            connection_id=connection_id,
            status=ExternalChannelConnectionStatus.DEGRADED,
            provider_tenant_id=None,
            provider_bot_user_id=None,
            capabilities=None,
            checked_at=_at(3),
            expected_encrypted_credentials=configuration.encrypted_credentials,
        )
        await session.commit()

    assert updated is not None
    assert updated.status is ExternalChannelConnectionStatus.DEGRADED
    assert updated.socket_heartbeat_at is None
    assert updated.socket_gap_detected_at is None
    assert updated.socket_gap_reason is None


async def test_stale_validation_does_not_revive_disconnecting_connection(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A validation started before disconnect cannot overwrite its fenced state."""
    async with rdb_session_manager() as session:
        connection_id, _, _, repository = await _setup_route(session)
        configuration = await repository.get_connection_configuration(
            session,
            connection_id=connection_id,
        )
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        assert configuration is not None
        assert configuration.encrypted_credentials is not None
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTING
        await session.commit()

    async with rdb_session_manager() as session:
        updated = await repository.update_connection_health(
            session,
            connection_id=connection_id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id="T1",
            provider_bot_user_id="B1",
            capabilities={"inbound_events": True},
            checked_at=_at(3),
            expected_encrypted_credentials=configuration.encrypted_credentials,
        )
        await session.commit()

    async with rdb_session_manager() as session:
        connection = await repository.get_connection(
            session,
            connection_id=connection_id,
        )

    assert updated is None
    assert connection is not None
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTING


async def test_provider_failure_does_not_revive_disconnected_connection(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A late provider failure cannot overwrite an explicit disconnect."""
    async with rdb_session_manager() as session:
        connection_id, _, _, repository = await _setup_route(session)
        connection = await session.get(RDBExternalChannelConnection, connection_id)
        assert connection is not None
        connection.status = ExternalChannelConnectionStatus.DISCONNECTED
        connection.encrypted_credentials = None
        connection.disconnected_at = _at(1)
        await session.commit()

    async with rdb_session_manager() as session:
        changed = await repository.mark_connection_reconnect_required(
            session,
            connection_id=connection_id,
            reason="credentials_invalid",
            now=_at(2),
            required_socket_lease_owner=None,
        )
        await session.commit()

    async with rdb_session_manager() as session:
        connection = await repository.get_connection(
            session,
            connection_id=connection_id,
        )

    assert changed is False
    assert connection is not None
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTED


async def test_app_uninstall_preserves_agent_route(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Slack App uninstall clears provider state without removing Agent routing."""
    async with rdb_session_manager() as session:
        connection_id, route_id, _, repository = await _setup_route(session)
        changed = await repository.terminate_connection_for_provider_event(
            session,
            connection_id=connection_id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(2),
            required_socket_lease_owner=None,
        )
        await session.commit()

    async with rdb_session_manager() as session:
        connection = await repository.get_connection(
            session,
            connection_id=connection_id,
        )
        route = await repository.get_agent_route(session, route_id=route_id)

    assert changed is True
    assert connection is not None
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert route is not None
