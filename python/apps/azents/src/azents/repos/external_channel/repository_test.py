"""ExternalChannelRepository tests."""

import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelIngressProfile,
    ExternalChannelInvocationWakeDispatchStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAppClaim,
    RDBExternalChannelConnection,
    RDBExternalChannelIngressLease,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.external_channel.data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBinding,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationPosition,
    ExternalChannelDeliveryAttempt,
    ExternalChannelEventCreate,
    ExternalChannelInvocationBatch,
    ExternalChannelMessage,
    ExternalChannelResource,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


def _at(minute: int) -> datetime.datetime:
    """Return a stable timezone-aware test timestamp."""
    return datetime.datetime(2026, 7, 21, 0, minute, tzinfo=datetime.UTC)


def _discord_capabilities() -> dict[str, object]:
    """Return one complete persisted Discord capability snapshot."""
    return {
        "provider": ExternalChannelProvider.DISCORD.value,
        "transport": ExternalChannelTransport.HTTP.value,
        "inbound_events": True,
        "thread_history": True,
        "post_messages": True,
        "update_messages": True,
        "delete_messages": True,
        "download_files": True,
        "upload_files": True,
    }


async def _create_workspace(
    session: AsyncSession,
    handle: str = "external-channel-repository-test",
) -> str:
    """Create a Workspace required by an External Channel connection."""
    result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name="External Channel repository test",
            handle=handle,
        ),
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        handle,
    )
    assert workspace_id is not None
    return workspace_id


def _connection_create(workspace_id: str) -> ExternalChannelConnectionCreate:
    """Build a redacted test connection persistence payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        app_mode=ExternalChannelAppMode.SINGLE,
        status=ExternalChannelConnectionStatus.ACTIVE,
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials="ciphertext-only",
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
    )


def _event_create(connection_id: str) -> ExternalChannelEventCreate:
    """Build a provider-event admission payload."""
    return ExternalChannelEventCreate(
        connection_id=connection_id,
        provider_event_id="provider-event-1",
        transport_envelope_id="envelope-1",
        event_type="app_mention",
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        provider_enterprise_id=None,
        resource_correlation_key="thread-1",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={"event_id": "provider-event-1"},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=_at(1),
        received_at=_at(2),
    )


@pytest.mark.asyncio
async def test_list_initial_delivery_attempts_scopes_session_link_and_work_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Initial hydration reads only the binding link and active-work parts."""
    repository = ExternalChannelRepository()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=["work-1", "link-1"])
    session.scalars = AsyncMock(
        side_effect=[
            ["part-1", "part-2"],
            [
                SimpleNamespace(
                    id="link-1",
                    binding_id="binding-1",
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id="binding-1",
                    operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                    status=ExternalChannelDeliveryStatus.DELIVERED,
                ),
                SimpleNamespace(
                    id="part-1",
                    binding_id="binding-1",
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id="work-1",
                    operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    status=ExternalChannelDeliveryStatus.DELIVERED,
                    channel_action_id=None,
                    request_payload={"work_id": "work-1"},
                    provider_message_key=None,
                ),
                SimpleNamespace(
                    id="part-2",
                    binding_id="binding-1",
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id="work-1",
                    operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    status=ExternalChannelDeliveryStatus.UNKNOWN,
                    channel_action_id=None,
                    request_payload={"work_id": "work-1"},
                    provider_message_key=None,
                ),
            ],
        ]
    )
    monkeypatch.setattr(
        ExternalChannelDeliveryAttempt,
        "model_validate",
        classmethod(lambda cls, value: value),
    )

    attempts = await repository.list_initial_delivery_attempts(
        session,
        binding_id="binding-1",
    )

    assert [attempt.id for attempt in attempts] == ["link-1", "part-1", "part-2"]
    assert attempts[-1].status is ExternalChannelDeliveryStatus.UNKNOWN
    assert session.scalar.await_count == 2
    assert session.scalars.await_count == 2


@pytest.mark.asyncio
async def test_claim_binding_wake_has_one_winner_and_reclaims_stale_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh claims fence concurrent reconcilers while stale claims recover."""
    repository = ExternalChannelRepository()
    binding = SimpleNamespace(
        id="binding-1",
        activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
        activation_wake_claimed_at=None,
        projected_through_position=None,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=binding)
    session.flush = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelBinding,
        "model_validate",
        classmethod(lambda cls, value: value),
    )
    now = _at(10)

    claimed, should_wake = await repository.claim_binding_wake(
        session,
        binding_id="binding-1",
        now=now,
        projected_through_position="position-9",
    )
    assert claimed is binding
    assert should_wake is True
    assert binding.activation_status is (
        ExternalChannelBindingActivationStatus.WAKE_PENDING
    )
    assert binding.projected_through_position == "position-9"

    claimed, should_wake = await repository.claim_binding_wake(
        session,
        binding_id="binding-1",
        now=now + datetime.timedelta(seconds=1),
        projected_through_position="position-9",
    )
    assert claimed is binding
    assert should_wake is False

    binding.activation_wake_claimed_at = now - datetime.timedelta(minutes=2)
    claimed, should_wake = await repository.claim_binding_wake(
        session,
        binding_id="binding-1",
        now=now,
        projected_through_position="position-9",
    )
    assert claimed is binding
    assert should_wake is True
    assert binding.activation_wake_claimed_at == now


@pytest.mark.asyncio
async def test_conversation_position_lock_and_compare_and_set_are_fenced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The durable position row is locked and advances only from its expected value."""
    repository = ExternalChannelRepository()
    position = SimpleNamespace(id="position-1", read_through_position=None)
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=position)
    first_update = MagicMock()
    first_update.scalar_one_or_none.return_value = "position-1"
    stale_update = MagicMock()
    stale_update.scalar_one_or_none.return_value = None
    session.execute = AsyncMock(side_effect=[first_update, stale_update])
    session.flush = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelConversationPosition,
        "model_validate",
        classmethod(lambda cls, value: value),
    )

    locked = await repository.lock_conversation_position(
        session,
        position_id="position-1",
    )
    advanced = await repository.advance_conversation_position_if_current(
        session,
        position_id="position-1",
        expected_read_through_position=None,
        read_through_position="0000000002",
    )
    stale = await repository.advance_conversation_position_if_current(
        session,
        position_id="position-1",
        expected_read_through_position="0000000001",
        read_through_position="0000000003",
    )

    assert locked is position
    assert advanced is True
    assert stale is False
    lock_statement = session.scalar.await_args.args[0]
    assert "FOR UPDATE" in str(lock_statement.compile(dialect=postgresql.dialect()))
    assert session.flush.await_count == 2


@pytest.mark.asyncio
async def test_message_identity_metadata_does_not_create_content_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval preparation updates identity metadata without retaining content."""
    repository = ExternalChannelRepository()
    message = SimpleNamespace(
        id="message-1",
        principal_id=None,
        author_type=ExternalChannelPrincipalAuthorType.SYSTEM,
        provider_created_at=None,
        provider_updated_at=None,
        current_revision_id=None,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=message)
    session.flush = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelMessage,
        "model_validate",
        classmethod(lambda cls, value: value),
    )

    updated = await repository.update_message_identity_metadata(
        session,
        message_id=message.id,
        principal_id="principal-1",
        author_type=ExternalChannelPrincipalAuthorType.HUMAN,
        provider_created_at=_at(4),
        provider_updated_at=_at(5),
    )

    assert updated is message
    assert message.principal_id == "principal-1"
    assert message.author_type is ExternalChannelPrincipalAuthorType.HUMAN
    assert message.provider_created_at == _at(4)
    assert message.provider_updated_at == _at(5)
    assert message.current_revision_id is None
    statement = session.scalar.await_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_synchronous_history_marks_resource_bounded_without_event_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synchronous provider history records a bounded terminal resource state."""
    repository = ExternalChannelRepository()
    resource = SimpleNamespace(
        id="resource-1",
        hydration_status=ExternalChannelHydrationStatus.PENDING,
        hydration_cursor=None,
        hydration_high_watermark_position=None,
        hydration_error_kind="legacy_error",
        hydration_error_summary="legacy summary",
        hydration_started_at=None,
        hydration_completed_at=None,
        updated_at=_at(1),
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=resource)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelResource,
        "model_validate",
        classmethod(lambda cls, value: value),
    )

    updated = await repository.mark_resource_history_ready(
        session,
        resource_id=resource.id,
        through_provider_position="0000000005",
        completed_at=_at(5),
    )

    assert updated is resource
    assert resource.hydration_status is ExternalChannelHydrationStatus.BOUNDED
    assert resource.hydration_cursor == "0000000005"
    assert resource.hydration_high_watermark_position == "0000000005"
    assert resource.hydration_error_kind is None
    assert resource.hydration_error_summary is None
    assert resource.hydration_started_at == _at(5)
    assert resource.hydration_completed_at == _at(5)
    statement = session.scalar.await_args.args[0]
    assert "FOR UPDATE" in str(statement.compile(dialect=postgresql.dialect()))


@pytest.mark.asyncio
async def test_invocation_wake_dispatch_claim_transitions_are_recoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fresh claims fence dispatchers; stale claims recover; dispatch is terminal."""
    repository = ExternalChannelRepository()
    batch = SimpleNamespace(
        id="batch-1",
        wake_dispatch_status=ExternalChannelInvocationWakeDispatchStatus.PENDING,
        wake_dispatch_claimed_at=None,
    )
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(return_value=batch)
    session.flush = AsyncMock()
    monkeypatch.setattr(
        ExternalChannelInvocationBatch,
        "model_validate",
        classmethod(lambda cls, value: value),
    )
    now = _at(10)

    claimed, should_dispatch = await repository.claim_invocation_wake_dispatch(
        session,
        batch_id=batch.id,
        now=now,
    )
    assert claimed is batch
    assert should_dispatch is True
    assert (
        batch.wake_dispatch_status
        is ExternalChannelInvocationWakeDispatchStatus.CLAIMED
    )

    claimed, should_dispatch = await repository.claim_invocation_wake_dispatch(
        session,
        batch_id=batch.id,
        now=now + datetime.timedelta(seconds=1),
    )
    assert claimed is batch
    assert should_dispatch is False

    batch.wake_dispatch_claimed_at = now - datetime.timedelta(minutes=2)
    claimed, should_dispatch = await repository.claim_invocation_wake_dispatch(
        session,
        batch_id=batch.id,
        now=now,
    )
    assert claimed is batch
    assert should_dispatch is True

    dispatched = await repository.mark_invocation_wake_dispatched(
        session,
        batch_id=batch.id,
        dispatched_at=now,
    )
    assert dispatched is batch
    assert (
        batch.wake_dispatch_status
        is ExternalChannelInvocationWakeDispatchStatus.DISPATCHED
    )
    assert batch.wake_dispatch_claimed_at is None

    claimed, should_dispatch = await repository.claim_invocation_wake_dispatch(
        session,
        batch_id=batch.id,
        now=now + datetime.timedelta(minutes=2),
    )
    assert claimed is batch
    assert should_dispatch is False


@pytest.mark.asyncio
async def test_cutover_preflight_counts_preserve_aggregate_counter_values() -> None:
    """Preflight returns the repository's content-free aggregate counters unchanged."""
    repository = ExternalChannelRepository()
    session = MagicMock(spec=AsyncSession)
    session.scalar = AsyncMock(side_effect=range(1, 8))
    active_bindings = MagicMock()
    active_bindings.tuples.return_value = []
    session.execute = AsyncMock(return_value=active_bindings)

    counts = await repository.get_cutover_preflight_counts(session)

    assert counts.undrained_events == 1
    assert counts.unactivated_bindings == 2
    assert counts.incomplete_hydrations == 3
    assert counts.pending_contexts == 4
    assert counts.open_conversation_admissions == 5
    assert counts.pending_access_requests == 6
    assert counts.inflight_resource_provisionings == 7
    assert counts.active_bindings_without_delivery_target == 0
    assert counts.active_bindings_without_session == 0
    assert counts.active_bindings_without_route == 0
    assert counts.active_bindings_without_latest_batch == 0
    assert counts.active_bindings_without_thread_position == 0
    assert counts.active_bindings_with_ambiguous_thread_position == 0


async def test_invocation_projection_query_preserves_inner_revision_from() -> None:
    """The original-revision subquery retains an independent FROM clause."""
    session = MagicMock(spec=AsyncSession)

    async def compile_statement(statement: ClauseElement) -> MagicMock:
        statement.compile(dialect=postgresql.dialect())
        result = MagicMock()
        result.mappings.return_value = []
        return result

    session.execute = AsyncMock(side_effect=compile_statement)

    items = await ExternalChannelRepository().list_invocation_projection_items(
        cast(AsyncSession, session),
        batch_id="batch-1",
    )

    assert items == []


class TestExternalChannelRepository:
    """External Channel foundation repository tests."""

    async def test_connection_lookup_is_redacted_and_provider_scoped(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Connection lookup retains ciphertext in storage but not its DTO."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()

        created = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        configuration = await repo.get_slack_http_configuration_by_provider_identity(
            rdb_session,
            provider_app_id="app-1",
            provider_tenant_id="tenant-1",
        )

        assert configuration is not None
        assert configuration.id == created.id
        assert not hasattr(created, "encrypted_credentials")
        assert created.provider is ExternalChannelProvider.SLACK
        by_id = await repo.get_connection_configuration(
            rdb_session,
            connection_id=created.id,
        )
        assert by_id is not None
        assert by_id.encrypted_credentials == "ciphertext-only"

    async def test_installation_identity_is_unique_across_workspaces(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """One active Slack App and Team installation has one callback owner."""
        first_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-installation-first",
        )
        second_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-installation-second",
        )
        repo = ExternalChannelRepository()
        await repo.create_connection(
            rdb_session,
            _connection_create(first_workspace_id),
        )

        with pytest.raises(
            IntegrityError,
            match="uq_external_channel_connections_installation_identity",
        ):
            async with rdb_session.begin_nested():
                await repo.create_connection(
                    rdb_session,
                    _connection_create(second_workspace_id),
                )

    async def test_released_disconnected_identity_can_be_added_again(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Clearing retained disconnected identity releases the installation."""
        first_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-released-first",
        )
        second_workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-released-second",
        )
        repo = ExternalChannelRepository()
        first = await repo.create_connection(
            rdb_session,
            _connection_create(first_workspace_id),
        )
        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=first.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=None,
            required_socket_lease_owner=None,
            defer_provider_state_purge=False,
        )
        released = await repo.get_connection_configuration(
            rdb_session,
            connection_id=first.id,
        )

        second = await repo.create_connection(
            rdb_session,
            _connection_create(second_workspace_id),
        )

        assert terminated == ()
        assert released is not None
        assert released.status is ExternalChannelConnectionStatus.DISCONNECTED
        assert released.encrypted_credentials is None
        assert released.provider_tenant_id is None
        assert second.workspace_id == second_workspace_id
        assert second.provider_app_id == "app-1"
        assert second.provider_tenant_id == "tenant-1"

    async def test_provider_state_purge_can_follow_cleanup_target_capture(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Uninstall keeps credentials only until cleanup targets are captured."""
        workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-deferred-provider-purge",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )

        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=connection.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=None,
            required_socket_lease_owner=None,
            defer_provider_state_purge=True,
        )
        retained = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert terminated == ()
        assert retained is not None
        assert retained.status is ExternalChannelConnectionStatus.DISCONNECTED
        assert retained.encrypted_credentials is not None
        assert retained.provider_tenant_id == "tenant-1"

        assert await repo.purge_disconnected_connection_provider_state(
            rdb_session,
            connection_id=connection.id,
        )
        purged = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert purged is not None
        assert purged.encrypted_credentials is None
        assert purged.provider_tenant_id is None

    async def test_provider_lifecycle_rejects_stale_configuration_generation(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A replaced configuration wins over an in-flight provider callback."""
        workspace_id = await _create_workspace(
            rdb_session,
            "external-channel-stale-provider-lifecycle",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        stale_generation = connection.configuration_generation + 1

        terminated = await repo.terminate_connection_for_provider_event(
            rdb_session,
            connection_id=connection.id,
            status=ExternalChannelConnectionStatus.DISCONNECTED,
            reason="app_uninstalled",
            now=_at(4),
            required_configuration_generation=stale_generation,
            required_socket_lease_owner=None,
            defer_provider_state_purge=True,
        )
        reconnect_required = await repo.mark_connection_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            reason="tokens_revoked",
            now=_at(4),
            required_configuration_generation=stale_generation,
            required_socket_lease_owner=None,
        )
        retained = await repo.get_connection_configuration(
            rdb_session,
            connection_id=connection.id,
        )

        assert terminated is None
        assert reconnect_required is False
        assert retained is not None
        assert retained.status is ExternalChannelConnectionStatus.ACTIVE

    async def test_connection_health_update_returns_refreshed_projection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Health updates return server-updated fields without lazy loading."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        created = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        configuration = await repo.get_connection_configuration(
            rdb_session,
            connection_id=created.id,
        )
        assert configuration is not None
        assert configuration.encrypted_credentials is not None

        updated = await repo.update_connection_health(
            rdb_session,
            connection_id=created.id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id="tenant-1",
            provider_bot_user_id="bot-1",
            capabilities={"supports_reply": True},
            checked_at=_at(3),
            expected_encrypted_credentials=configuration.encrypted_credentials,
        )

        assert updated is not None
        assert updated.status is ExternalChannelConnectionStatus.ACTIVE
        assert updated.provider_tenant_id == "tenant-1"
        assert updated.provider_bot_user_id == "bot-1"
        assert updated.capabilities == {"supports_reply": True}
        assert updated.last_verified_at == _at(3)
        assert updated.last_health_at == _at(3)

    async def test_prepared_discord_callback_restores_ping_authority_on_retry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A retry exposes only provisional PING authority before activation."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-prepared-callback-retry",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "status": ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
                    "provider_app_id": "discord-app-retry",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )

        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-retry",
            interaction_public_key="a" * 64,
            callback_selector_hash="retry-selector-hash",
        )
        configured = await repo.get_discord_http_configuration_by_selector_hash(
            rdb_session,
            selector_hash="retry-selector-hash",
        )

        assert prepared is True
        assert configured is not None
        assert configured.status is ExternalChannelConnectionStatus.CONFIGURING
        assert configured.capabilities == {"interaction_public_key": "a" * 64}

    async def test_event_admission_returns_existing_event_for_provider_retry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A duplicate connection-scoped provider event is not inserted twice."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        create = _event_create(connection.id)

        first = await repo.admit_event(rdb_session, create)
        second = await repo.admit_event(rdb_session, create)

        assert first.created is True
        assert second.created is False
        assert second.event.id == first.event.id
        assert second.event.provider_event_id == "provider-event-1"

    async def test_discord_activation_reclaims_a_disconnected_app_claim(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A disconnected App history cannot block a later activation."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-disconnected-app-claim",
        )
        repo = ExternalChannelRepository()
        stale = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "status": ExternalChannelConnectionStatus.DISCONNECTED,
                    "provider_app_id": "discord-app-reclaimed",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )
        rdb_session.add(
            RDBExternalChannelAppClaim(
                provider=ExternalChannelProvider.DISCORD,
                provider_app_id="discord-app-reclaimed",
                connection_id=stale.id,
                claim_generation=1,
            )
        )
        replacement = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-reclaimed",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )
        await rdb_session.flush()

        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=replacement.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=replacement.configuration_generation,
            provider_app_id="discord-app-reclaimed",
            interaction_public_key="a" * 64,
            callback_selector_hash="reclaimed-selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=replacement.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=replacement.configuration_generation,
            provider_app_id="discord-app-reclaimed",
            provider_tenant_id="guild-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            message_command_id="123456789012345678",
            capabilities=_discord_capabilities(),
            callback_selector_hash="reclaimed-selector-hash",
            checked_at=_at(1),
        )

        assert activated is not None
        claim = await rdb_session.scalar(
            sa.select(RDBExternalChannelAppClaim).where(
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
                RDBExternalChannelAppClaim.provider_app_id == "discord-app-reclaimed",
            )
        )
        assert claim is not None
        assert claim.connection_id == replacement.id
        assert claim.claim_generation == 2

    async def test_discord_gateway_admission_is_lease_fenced(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Typed Gateway admission remains idempotent under one current lease."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-gateway-admission",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-1",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-1"},
                }
            ),
        )
        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-1",
            interaction_public_key="a" * 64,
            callback_selector_hash="selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-1",
            provider_tenant_id="guild-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            message_command_id="123456789012345678",
            capabilities=_discord_capabilities(),
            callback_selector_hash="selector-hash",
            checked_at=_at(1),
        )
        assert activated is not None
        assert activated.capabilities == {
            **_discord_capabilities(),
            "interaction_public_key": "a" * 64,
            "message_command_id": "123456789012345678",
        }
        claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(2),
            lease_until=_at(10),
        )
        assert claim is not None
        first_provider_event_id = (
            "discord:discord_message_create:guild-1:channel-1:message-1"
        )
        create = _event_create(connection.id).model_copy(
            update={
                "provider_event_id": first_provider_event_id,
                "transport_envelope_id": first_provider_event_id,
                "event_type": "discord_message_create",
                "provider_app_id": "discord-app-1",
                "provider_tenant_id": "guild-1",
                "resource_correlation_key": "guild-1:channel-1",
                "envelope": {
                    "message": {
                        "id": "message-1",
                        "channel_id": "channel-1",
                        "guild_id": "guild-1",
                    }
                },
            }
        )

        first = await repo.admit_discord_gateway_event(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            lease_generation=claim.lease.lease_generation,
            now=_at(3),
            create=create,
        )
        duplicate = await repo.admit_discord_gateway_event(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            lease_generation=claim.lease.lease_generation,
            now=_at(4),
            create=create,
        )
        lease = await rdb_session.scalar(
            sa.select(RDBExternalChannelIngressLease).where(
                RDBExternalChannelIngressLease.connection_id == connection.id
            )
        )

        assert first is not None
        assert first.created is True
        assert duplicate is not None
        assert duplicate.created is False
        assert lease is not None

        rdb_connection = await rdb_session.get(
            RDBExternalChannelConnection,
            connection.id,
        )
        assert rdb_connection is not None
        rdb_connection.configuration_generation += 1
        await rdb_session.flush()
        second_provider_event_id = (
            "discord:discord_message_create:guild-1:channel-1:message-2"
        )
        fenced = await repo.admit_discord_gateway_event(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            lease_generation=claim.lease.lease_generation,
            now=_at(5),
            create=create.model_copy(
                update={
                    "provider_event_id": second_provider_event_id,
                    "transport_envelope_id": second_provider_event_id,
                }
            ),
        )

        assert fenced is None
        assert (
            await repo.get_event_by_provider_identity(
                rdb_session,
                connection_id=connection.id,
                provider_event_id=second_provider_event_id,
            )
            is None
        )

    async def test_discord_gateway_terminal_transition_fences_stale_lease(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only the current Gateway lease can suppress future scheduler claims."""
        workspace_id = await _create_workspace(
            rdb_session,
            "discord-gateway-terminal-transition",
        )
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "provider": ExternalChannelProvider.DISCORD,
                    "ingress_profile": (
                        ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP
                    ),
                    "provider_app_id": "discord-app-terminal-1",
                    "provider_tenant_id": None,
                    "provider_config": {"target_guild_id": "guild-terminal-1"},
                }
            ),
        )
        prepared = await repo.prepare_discord_callback(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-terminal-1",
            interaction_public_key="a" * 64,
            callback_selector_hash="terminal-selector-hash",
        )
        assert prepared is True
        activated = await repo.activate_discord_connection(
            rdb_session,
            connection_id=connection.id,
            expected_encrypted_credentials="ciphertext-only",
            expected_configuration_generation=connection.configuration_generation,
            provider_app_id="discord-app-terminal-1",
            provider_tenant_id="guild-terminal-1",
            provider_bot_user_id=None,
            interaction_public_key="a" * 64,
            message_command_id="123456789012345678",
            capabilities=_discord_capabilities(),
            callback_selector_hash="terminal-selector-hash",
            checked_at=_at(1),
        )
        assert activated is not None
        stale_claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            now=_at(2),
            lease_until=_at(3),
        )
        assert stale_claim is not None
        current_claim = await repo.claim_discord_gateway_lease(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            now=_at(4),
            lease_until=_at(10),
        )
        assert current_claim is not None

        stale_terminalized = await repo.mark_discord_gateway_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-stale",
            lease_generation=stale_claim.lease.lease_generation,
            now=_at(5),
            reason="gateway_credentials_invalid",
        )
        terminalized = await repo.mark_discord_gateway_reconnect_required(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-current",
            lease_generation=current_claim.lease.lease_generation,
            now=_at(5),
            reason="gateway_credentials_invalid",
        )

        rdb_connection = await rdb_session.get(
            RDBExternalChannelConnection,
            connection.id,
        )
        lease = await rdb_session.scalar(
            sa.select(RDBExternalChannelIngressLease).where(
                RDBExternalChannelIngressLease.connection_id == connection.id
            )
        )

        assert stale_terminalized is False
        assert terminalized is True
        assert rdb_connection is not None
        assert (
            rdb_connection.status is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
        )
        assert lease is not None
        assert lease.lease_owner is None
        assert lease.lease_until is None
        assert lease.gap_detected_at == _at(5)
        assert lease.gap_reason == "gateway_credentials_invalid"
        assert await repo.list_discord_gateway_connection_ids(rdb_session) == []

    async def test_event_claim_is_fenced_and_completion_is_idempotent(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only the current event lease owner can commit terminal processing."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        admitted = await repo.admit_event(
            rdb_session,
            _event_create(connection.id),
        )

        claimed = await repo.claim_events(
            rdb_session,
            claim_owner="processor-1",
            now=_at(2),
            claim_until=_at(5),
            limit=10,
        )
        fenced = await repo.claim_events(
            rdb_session,
            claim_owner="processor-2",
            now=_at(3),
            claim_until=_at(6),
            limit=10,
        )
        stale_completion = await repo.complete_event(
            rdb_session,
            event_id=admitted.event.id,
            claim_owner="processor-2",
            now=_at(3),
            eligibility_state=ExternalChannelEventEligibilityState.PROCESSED,
            status=ExternalChannelEventStatus.PROCESSED,
            purge_envelope=False,
        )
        completed = await repo.complete_event(
            rdb_session,
            event_id=admitted.event.id,
            claim_owner="processor-1",
            now=_at(4),
            eligibility_state=ExternalChannelEventEligibilityState.PROCESSED,
            status=ExternalChannelEventStatus.PROCESSED,
            purge_envelope=False,
        )
        final = await repo.get_event_by_provider_identity(
            rdb_session,
            connection_id=connection.id,
            provider_event_id="provider-event-1",
        )

        assert [event.id for event in claimed] == [admitted.event.id]
        assert claimed[0].attempt_count == 1
        assert fenced == []
        assert stale_completion is False
        assert completed is True
        assert final is not None
        assert final.status is ExternalChannelEventStatus.PROCESSED
        assert final.claim_owner is None

    async def test_event_defer_respects_retry_boundary(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """A deferred unlinked event cannot be reclaimed before its retry time."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id),
        )
        admitted = await repo.admit_event(
            rdb_session,
            _event_create(connection.id),
        )
        await repo.claim_events(
            rdb_session,
            claim_owner="processor-1",
            now=_at(2),
            claim_until=_at(5),
            limit=1,
        )
        deferred = await repo.defer_event(
            rdb_session,
            event_id=admitted.event.id,
            claim_owner="processor-1",
            now=_at(3),
            retry_at=_at(8),
            error_kind="awaiting_thread_mention",
            error_summary="Waiting for a mention.",
        )

        early = await repo.claim_events(
            rdb_session,
            claim_owner="processor-2",
            now=_at(7),
            claim_until=_at(9),
            limit=1,
        )
        ready = await repo.claim_events(
            rdb_session,
            claim_owner="processor-2",
            now=_at(8),
            claim_until=_at(10),
            limit=1,
        )

        assert deferred is True
        assert early == []
        assert [event.id for event in ready] == [admitted.event.id]
        assert ready[0].attempt_count == 2

    async def test_socket_lease_fences_owner_and_reclaims_after_expiry(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Only one manager owns a socket until its durable lease expires."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "transport": ExternalChannelTransport.SOCKET,
                    "status": ExternalChannelConnectionStatus.ACTIVE,
                    "http_callback_selector_hash": None,
                }
            ),
        )

        first = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(1),
            lease_until=_at(3),
        )
        fenced = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-2",
            now=_at(2),
            lease_until=_at(4),
        )
        reclaimed = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-2",
            now=_at(4),
            lease_until=_at(6),
        )

        assert first is not None
        assert first.socket_lease_owner == "manager-1"
        assert fenced is None
        assert reclaimed is not None
        assert reclaimed.socket_lease_owner == "manager-2"

    async def test_socket_gap_is_visible_until_reconnection(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Record transport gaps and clear them only after a leased reconnect."""
        workspace_id = await _create_workspace(rdb_session)
        repo = ExternalChannelRepository()
        connection = await repo.create_connection(
            rdb_session,
            _connection_create(workspace_id).model_copy(
                update={
                    "transport": ExternalChannelTransport.SOCKET,
                    "status": ExternalChannelConnectionStatus.ACTIVE,
                    "http_callback_selector_hash": None,
                }
            ),
        )
        claimed = await repo.claim_socket_connection(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(1),
            lease_until=_at(5),
        )
        assert claimed is not None

        recorded = await repo.record_socket_connection_gap(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(2),
            gap_reason="connection_closed",
        )
        degraded = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )
        active = await repo.mark_socket_connection_active(
            rdb_session,
            connection_id=connection.id,
            lease_owner="manager-1",
            now=_at(3),
        )
        recovered = await repo.get_connection(
            rdb_session,
            connection_id=connection.id,
        )

        assert recorded is True
        assert degraded is not None
        assert degraded.status is ExternalChannelConnectionStatus.DEGRADED
        assert degraded.socket_gap_reason == "connection_closed"
        assert active is True
        assert recovered is not None
        assert recovered.status is ExternalChannelConnectionStatus.ACTIVE
        assert recovered.socket_gap_reason is None


async def test_create_agent_route_enforces_mode_and_workspace_boundaries(
    rdb_session: AsyncSession,
) -> None:
    """Route creation locks the connection and rejects mismatched boundaries."""
    first_workspace = await _create_workspace(rdb_session, "route-boundary-first")
    second_workspace = await _create_workspace(rdb_session, "route-boundary-second")
    integration = RDBLLMProviderIntegration(
        workspace_id=first_workspace,
        provider=LLMProvider.ANTHROPIC,
        name="route-boundary-integration",
        encrypted_credentials="encrypted",
        config=None,
    )
    rdb_session.add(integration)
    await rdb_session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier="route-boundary-model",
    )
    agent = RDBAgent(
        workspace_id=first_workspace,
        name="Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    foreign_agent = RDBAgent(
        workspace_id=second_workspace,
        name="Foreign Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    second_agent = RDBAgent(
        workspace_id=first_workspace,
        name="Second Route Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    rdb_session.add_all((agent, second_agent, foreign_agent))
    await rdb_session.flush()
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        rdb_session, _connection_create(first_workspace)
    )
    create = ExternalChannelAgentRouteCreate(
        connection_id=connection.id,
        agent_id=agent.id,
        agent_id_snapshot=agent.id,
        route_mode=ExternalChannelRouteMode.DEDICATED,
        connection_app_mode=ExternalChannelAppMode.SINGLE,
        catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
        catalog_removed_at=None,
        catalog_removed_by_user_id=None,
    )
    route = await repository.create_agent_route(rdb_session, create)
    assert route.agent_id == agent.id
    assert route.agent_id_snapshot == agent.id
    with pytest.raises(
        IntegrityError,
        match="uq_external_channel_agent_routes_single_connection",
    ):
        async with rdb_session.begin_nested():
            await repository.create_agent_route(
                rdb_session,
                create.model_copy(
                    update={
                        "agent_id": second_agent.id,
                        "agent_id_snapshot": second_agent.id,
                    }
                ),
            )
    with pytest.raises(ValueError, match="App mode"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"connection_app_mode": ExternalChannelAppMode.MULTI}
            ),
        )
    with pytest.raises(ValueError, match="Workspace"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={
                    "agent_id": foreign_agent.id,
                    "agent_id_snapshot": foreign_agent.id,
                }
            ),
        )
    with pytest.raises(ValueError, match="dedicated mode"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(update={"route_mode": ExternalChannelRouteMode.PLATFORM}),
        )
    with pytest.raises(ValueError, match="catalog-available"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"catalog_status": ExternalChannelRouteCatalogStatus.REMOVED}
            ),
        )
    with pytest.raises(ValueError, match="catalog-removal metadata"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(update={"catalog_removed_at": _at(1)}),
        )
    with pytest.raises(ValueError, match="catalog-removal metadata"):
        await repository.create_agent_route(
            rdb_session,
            create.model_copy(
                update={"catalog_removed_by_user_id": "not-a-route-owner"}
            ),
        )
