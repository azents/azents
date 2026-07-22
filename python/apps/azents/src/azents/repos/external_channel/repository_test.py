"""ExternalChannelRepository tests."""

import datetime

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.models.external_channel import RDBExternalChannelConnection
from azents.repos.external_channel.data import (
    ExternalChannelConnectionCreate,
    ExternalChannelEventCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate


def _at(minute: int) -> datetime.datetime:
    """Return a stable timezone-aware test timestamp."""
    return datetime.datetime(2026, 7, 21, 0, minute, tzinfo=datetime.UTC)


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
        await rdb_session.execute(
            sa.update(RDBExternalChannelConnection)
            .where(RDBExternalChannelConnection.id == first.id)
            .values(
                status=ExternalChannelConnectionStatus.DISCONNECTED,
                provider_tenant_id=None,
                provider_bot_user_id=None,
                capabilities=None,
            )
        )
        await rdb_session.flush()

        second = await repo.create_connection(
            rdb_session,
            _connection_create(second_workspace_id),
        )

        assert second.workspace_id == second_workspace_id
        assert second.provider_app_id == "app-1"
        assert second.provider_tenant_id == "tenant-1"

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

        updated = await repo.update_connection_health(
            rdb_session,
            connection_id=created.id,
            status=ExternalChannelConnectionStatus.ACTIVE,
            provider_tenant_id="tenant-1",
            provider_bot_user_id="bot-1",
            capabilities={"supports_reply": True},
            checked_at=_at(3),
        )

        assert updated is not None
        assert updated.status is ExternalChannelConnectionStatus.ACTIVE
        assert updated.provider_tenant_id == "tenant-1"
        assert updated.provider_bot_user_id == "bot-1"
        assert updated.capabilities == {"supports_reply": True}
        assert updated.last_verified_at == _at(3)
        assert updated.last_health_at == _at(3)

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
