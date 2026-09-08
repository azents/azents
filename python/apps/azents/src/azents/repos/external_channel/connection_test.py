"""Completed External Channel connection operation repository tests."""

import datetime
from typing import Never

import pytest
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.connection import (
    ExternalChannelConnectionRepository,
)
from azents.repos.external_channel.data import ExternalChannelConnectionCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate


async def _create_workspace(
    session_manager: SessionManager[AsyncSession],
    *,
    handle: str,
) -> str:
    """Create one Workspace outside the operation under test."""
    async with session_manager() as session:
        workspace_repository = WorkspaceRepository()
        result = await workspace_repository.create(
            session,
            WorkspaceCreate(name="Connection operation test", handle=handle),
        )
        assert isinstance(result, Success)
        workspace_id = await workspace_repository.resolve_id(session, handle)
        assert workspace_id is not None
        return workspace_id


def _connection_create(workspace_id: str) -> ExternalChannelConnectionCreate:
    """Build one complete encrypted-only connection payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.SLACK_HTTP,
        configuration_generation=1,
        status=ExternalChannelConnectionStatus.CONFIGURING,
        app_mode=ExternalChannelAppMode.SINGLE,
        provider_app_id="app-operation-test",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials="ciphertext-only",
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        last_health_code=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
    )


class _FailAfterConnectionCreateRepository(ExternalChannelRepository):
    """Raise after a lower repository write to prove operation rollback."""

    def __init__(self) -> None:
        super().__init__()
        self.connection_id: str | None = None

    async def create_connection(
        self,
        session: AsyncSession,
        create: ExternalChannelConnectionCreate,
    ) -> Never:
        connection = await super().create_connection(session, create)
        self.connection_id = connection.id
        raise RuntimeError("rollback after connection insert")


@pytest.mark.asyncio
async def test_create_connection_commits_completed_record_and_rolls_back_failure(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """A failed lower operation cannot retain a partially-created connection."""
    workspace_id = await _create_workspace(
        rdb_session_manager,
        handle="external-channel-connection-operation-create",
    )
    operation_repository = ExternalChannelConnectionRepository(
        repository=ExternalChannelRepository(),
        session_manager=rdb_session_manager,
    )

    created = await operation_repository.create_connection(
        create=_connection_create(workspace_id)
    )

    async with rdb_session_manager() as session:
        persisted = await ExternalChannelRepository().get_connection_configuration(
            session,
            connection_id=created.id,
        )
    assert persisted is not None
    assert persisted.workspace_id == workspace_id

    failing_repository = _FailAfterConnectionCreateRepository()
    failing_operation = ExternalChannelConnectionRepository(
        repository=failing_repository,
        session_manager=rdb_session_manager,
    )
    with pytest.raises(RuntimeError, match="rollback after connection insert"):
        await failing_operation.create_connection(
            create=_connection_create(workspace_id)
        )

    assert failing_repository.connection_id is not None
    async with rdb_session_manager() as session:
        rolled_back = await ExternalChannelRepository().get_connection_configuration(
            session,
            connection_id=failing_repository.connection_id,
        )
    assert rolled_back is None


@pytest.mark.asyncio
async def test_load_connection_configuration_hides_missing_and_cross_workspace_rows(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Completed configuration reads preserve the Workspace ownership boundary."""
    workspace_id = await _create_workspace(
        rdb_session_manager,
        handle="external-channel-connection-operation-owner",
    )
    other_workspace_id = await _create_workspace(
        rdb_session_manager,
        handle="external-channel-connection-operation-foreign",
    )
    operation_repository = ExternalChannelConnectionRepository(
        repository=ExternalChannelRepository(),
        session_manager=rdb_session_manager,
    )
    created = await operation_repository.create_connection(
        create=_connection_create(workspace_id)
    )

    owned = await operation_repository.load_connection_configuration(
        workspace_id=workspace_id,
        connection_id=created.id,
    )
    foreign = await operation_repository.load_connection_configuration(
        workspace_id=other_workspace_id,
        connection_id=created.id,
    )
    missing = await operation_repository.load_connection_configuration(
        workspace_id=workspace_id,
        connection_id="missing-connection",
    )

    assert owned is not None
    assert owned.id == created.id
    assert foreign is None
    assert missing is None


@pytest.mark.asyncio
async def test_update_connection_health_generation_fence_reports_stale_and_missing(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Health persistence distinguishes successful, stale, and missing outcomes."""
    workspace_id = await _create_workspace(
        rdb_session_manager,
        handle="external-channel-connection-operation-health",
    )
    operation_repository = ExternalChannelConnectionRepository(
        repository=ExternalChannelRepository(),
        session_manager=rdb_session_manager,
    )
    created = await operation_repository.create_connection(
        create=_connection_create(workspace_id)
    )
    configuration = await operation_repository.load_connection_configuration(
        workspace_id=workspace_id,
        connection_id=created.id,
    )
    assert configuration is not None
    assert configuration.encrypted_credentials is not None
    checked_at = datetime.datetime(2026, 9, 8, 1, 0, tzinfo=datetime.UTC)

    updated = await operation_repository.update_connection_health(
        connection_id=created.id,
        status=ExternalChannelConnectionStatus.ACTIVE,
        provider_tenant_id="tenant-1",
        provider_bot_user_id="bot-1",
        capabilities={"supports_reply": True},
        checked_at=checked_at,
        expected_encrypted_credentials=configuration.encrypted_credentials,
        expected_configuration_generation=configuration.configuration_generation,
    )
    stale = await operation_repository.update_connection_health(
        connection_id=created.id,
        status=ExternalChannelConnectionStatus.DEGRADED,
        provider_tenant_id=None,
        provider_bot_user_id=None,
        capabilities=None,
        checked_at=checked_at,
        expected_encrypted_credentials=configuration.encrypted_credentials,
        expected_configuration_generation=configuration.configuration_generation + 1,
    )
    missing = await operation_repository.update_connection_health(
        connection_id="missing-connection",
        status=ExternalChannelConnectionStatus.DEGRADED,
        provider_tenant_id=None,
        provider_bot_user_id=None,
        capabilities=None,
        checked_at=checked_at,
        expected_encrypted_credentials="ciphertext-only",
        expected_configuration_generation=1,
    )

    assert updated.connection is not None
    assert updated.connection.status is ExternalChannelConnectionStatus.ACTIVE
    assert updated.connection_exists
    assert stale.connection is None
    assert stale.connection_exists
    assert missing.connection is None
    assert not missing.connection_exists
