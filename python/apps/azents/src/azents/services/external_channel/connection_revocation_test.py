"""Direct authenticated Slack connection-revocation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelProvider,
)
from azents.core.external_channel_provider_effect import (
    ProviderEffectPlan,
    ProviderOperationKey,
    ProviderTarget,
)
from azents.rdb.models.external_channel import RDBExternalChannelConnection
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadWriteSession,
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.external_channel.connection_revocation_operations import (
    ExternalChannelConnectionRevocationOperations,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.repository_test import (
    _connection_create,
    _create_workspace,
)
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation
from azents.testing.types import require_instance

_NOW = datetime.datetime(2026, 7, 29, 1, tzinfo=datetime.UTC)


def _plan() -> ProviderEffectPlan:
    return ProviderEffectPlan(
        target=ProviderTarget(
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            binding_id="binding-1",
            resource_id="resource-1",
            connection_id="connection-1",
            provider=ExternalChannelProvider.SLACK,
            app_mode=ExternalChannelAppMode.SINGLE,
            encrypted_credentials="encrypted",
            provider_tenant_id="tenant-1",
            capabilities=None,
            provider_configuration=None,
            workspace_handle="workspace",
            agent_id="agent-1",
            agent_session_id="session-1",
            agent_name="Agent",
            agent_avatar=None,
            request_payload={"control_kind": "session_presence"},
        ),
        operation_key=ProviderOperationKey.from_seed("connection-revocation"),
    )


class _Session:
    """Record lifecycle transaction completion."""

    def __init__(self) -> None:
        self.committed = False
        self.closed = False

    async def commit(self) -> None:
        self.committed = True


class _Repository:
    """Capture direct lifecycle transitions without raw event rows."""

    def __init__(self) -> None:
        self.terminated: list[dict[str, object]] = []
        self.reconnect_required: list[dict[str, object]] = []
        self.purged = False

    async def terminate_connection_for_provider_event(
        self,
        _session: WriteSession,
        **kwargs: object,
    ) -> tuple[ProviderEffectPlan, ...]:
        self.terminated.append(kwargs)
        return (_plan(),)

    async def purge_disconnected_connection_provider_state(
        self,
        _session: WriteSession,
        *,
        connection_id: str,
    ) -> bool:
        assert connection_id == "connection-1"
        self.purged = True
        return True

    async def mark_connection_reconnect_required(
        self,
        _session: WriteSession,
        **kwargs: object,
    ) -> bool:
        self.reconnect_required.append(kwargs)
        return True


class _ActionService:
    """Prove cleanup provider I/O starts only after the lifecycle commit."""

    def __init__(self, session: _Session) -> None:
        self.session = session
        self.attempted: list[ProviderEffectPlan] = []

    async def execute_terminal_control(
        self,
        plan: ProviderEffectPlan,
    ) -> None:
        assert self.session.committed
        assert self.session.closed
        self.attempted.append(plan)


def _service() -> tuple[
    ExternalChannelConnectionRevocationService,
    _Session,
    _Repository,
    _ActionService,
]:
    session = _Session()

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[WriteSession]:
        try:
            yield ReadWriteSession(cast(AsyncSession, session))
        finally:
            session.closed = True

    repository = _Repository()
    action_service = _ActionService(session)
    return (
        ExternalChannelConnectionRevocationService(
            operations=ExternalChannelConnectionRevocationOperations(
                session_manager=cast(SessionManager[WriteSession], session_manager),
                repository=cast(ExternalChannelRepository, repository),
            ),
            action_service=cast(ExternalChannelActionService, action_service),
        ),
        session,
        repository,
        action_service,
    )


@pytest.mark.asyncio
async def test_app_uninstalled_commits_before_cleanup_provider_io() -> None:
    service, session, repository, action_service = _service()

    changed = await service.apply(
        connection_id="connection-1",
        revocation=SlackConnectionRevocation(kind="app_uninstalled"),
        required_configuration_generation=2,
        required_socket_lease_owner=None,
        now=_NOW,
    )

    assert changed is True
    assert session.committed is True
    assert repository.purged is True
    assert repository.terminated[0]["reason"] == "app_uninstalled"
    assert repository.terminated[0]["required_configuration_generation"] == 2
    assert len(action_service.attempted) == 1


@pytest.mark.asyncio
async def test_tokens_revoked_uses_current_socket_owner_fence() -> None:
    service, session, repository, action_service = _service()

    changed = await service.apply(
        connection_id="connection-1",
        revocation=SlackConnectionRevocation(kind="tokens_revoked"),
        required_configuration_generation=2,
        required_socket_lease_owner="manager-1",
        now=_NOW,
    )

    assert changed is True
    assert session.committed is True
    assert repository.reconnect_required == [
        {
            "connection_id": "connection-1",
            "reason": "tokens_revoked",
            "now": _NOW,
            "required_configuration_generation": 2,
            "required_socket_lease_owner": "manager-1",
        }
    ]
    assert action_service.attempted == []


async def test_native_revocation_rolls_back_terminal_transition_when_purge_fails(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Purge failure rolls back terminal state and prevents cleanup publication."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    repository = ExternalChannelRepository()
    async with manager() as session:
        workspace_id = await _create_workspace(session, "revocation-atomic-rollback")
        connection = await repository.create_connection(
            session, _connection_create(workspace_id)
        )
    action_service = AsyncMock(spec=ExternalChannelActionService)
    failing_repository = MagicMock(spec=ExternalChannelRepository)
    failing_repository.terminate_connection_for_provider_event = (
        repository.terminate_connection_for_provider_event
    )
    failing_repository.purge_disconnected_connection_provider_state = AsyncMock(
        return_value=False
    )
    service = ExternalChannelConnectionRevocationService(
        operations=ExternalChannelConnectionRevocationOperations(
            session_manager=manager,
            repository=require_instance(failing_repository, ExternalChannelRepository),
        ),
        action_service=require_instance(action_service, ExternalChannelActionService),
    )
    try:
        with pytest.raises(RuntimeError, match="provider state disappeared"):
            await service.apply(
                connection_id=connection.id,
                revocation=SlackConnectionRevocation(kind="app_uninstalled"),
                required_configuration_generation=1,
                required_socket_lease_owner=None,
                now=_NOW,
            )
        async with manager() as session:
            current = await repository.get_connection_configuration(
                session, connection_id=connection.id
            )
        assert current is not None
        assert current.status is ExternalChannelConnectionStatus.ACTIVE
        assert current.encrypted_credentials == "ciphertext-only"
        action_service.execute_terminal_control.assert_not_awaited()
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelConnection).where(
                    RDBExternalChannelConnection.id == connection.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )


async def test_native_revocation_rejects_stale_configuration_then_commits_purge(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Stale generation leaves state intact; matched uninstall commits its purge."""
    del latest_db_schema
    manager = create_read_write_session_manager(rdb_engine)
    repository = ExternalChannelRepository()
    async with manager() as session:
        workspace_id = await _create_workspace(
            session, "revocation-generation-admission"
        )
        connection = await repository.create_connection(
            session, _connection_create(workspace_id)
        )
    action_service = AsyncMock(spec=ExternalChannelActionService)
    service = ExternalChannelConnectionRevocationService(
        operations=ExternalChannelConnectionRevocationOperations(
            session_manager=manager, repository=repository
        ),
        action_service=require_instance(action_service, ExternalChannelActionService),
    )
    try:
        assert not await service.apply(
            connection_id=connection.id,
            revocation=SlackConnectionRevocation(kind="app_uninstalled"),
            required_configuration_generation=2,
            required_socket_lease_owner=None,
            now=_NOW,
        )
        assert not await service.apply(
            connection_id=connection.id,
            revocation=SlackConnectionRevocation(kind="tokens_revoked"),
            required_configuration_generation=1,
            required_socket_lease_owner="stale-socket-manager",
            now=_NOW,
        )
        async with manager() as session:
            current = await repository.get_connection_configuration(
                session, connection_id=connection.id
            )
        assert current is not None
        assert current.status is ExternalChannelConnectionStatus.ACTIVE
        assert current.encrypted_credentials == "ciphertext-only"
        assert await service.apply(
            connection_id=connection.id,
            revocation=SlackConnectionRevocation(kind="app_uninstalled"),
            required_configuration_generation=1,
            required_socket_lease_owner=None,
            now=_NOW,
        )
        async with manager() as session:
            current = await repository.get_connection_configuration(
                session, connection_id=connection.id
            )
        assert current is not None
        assert current.status is ExternalChannelConnectionStatus.DISCONNECTED
        assert current.encrypted_credentials is None
        assert current.provider_tenant_id is None
    finally:
        async with manager() as session:
            await session.write_session.execute(
                sa.delete(RDBExternalChannelConnection).where(
                    RDBExternalChannelConnection.id == connection.id
                )
            )
            await session.write_session.execute(
                sa.delete(RDBWorkspace).where(RDBWorkspace.id == workspace_id)
            )
