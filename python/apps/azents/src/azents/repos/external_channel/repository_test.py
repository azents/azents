"""ExternalChannelRepository tests."""

import datetime

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
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


async def _create_workspace(session: AsyncSession) -> str:
    """Create a Workspace required by an External Channel connection."""
    result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(
            name="External Channel repository test",
            handle="external-channel-repository-test",
        ),
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        "external-channel-repository-test",
    )
    assert workspace_id is not None
    return workspace_id


def _connection_create(workspace_id: str) -> ExternalChannelConnectionCreate:
    """Build a redacted test connection persistence payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        provider_app_id=None,
        provider_tenant_id=None,
        provider_bot_user_id=None,
        http_callback_selector_hash="callback-selector-hash",
        encrypted_credentials="ciphertext-only",
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
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

    async def test_connection_lookup_is_redacted_and_callback_scoped(
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
        found = await repo.get_connection_by_http_callback_selector_hash(
            rdb_session,
            http_callback_selector_hash="callback-selector-hash",
        )

        assert found == created
        assert not hasattr(created, "encrypted_credentials")
        assert created.provider is ExternalChannelProvider.SLACK
        configuration = await repo.get_connection_configuration(
            rdb_session,
            connection_id=created.id,
        )
        assert configuration is not None
        assert configuration.encrypted_credentials == "ciphertext-only"

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
