"""External Channel management orchestration tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from azents.core.enums import (
    ExternalChannelBindingStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelTransport,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.data import (
    ExternalChannelMultiConnectionDisconnect,
)
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
    progress_projection_state,
)
from azents.repos.external_channel.management_data import (
    ManagedConnection,
    ManagedMultiRoute,
)
from azents.services.external_channel.data import (
    DiscordConnectionConfiguration,
    DiscordConnectionCredentials,
)
from azents.services.external_channel.management import (
    ExternalChannelManagementService,
    slack_manifest_guidance,
)


def _connection() -> ManagedConnection:
    return ManagedConnection(
        id="connection-1",
        route_id="route-1",
        agent_id="agent-1",
        provider=ExternalChannelProvider.SLACK,
        transport=ExternalChannelTransport.HTTP,
        status=ExternalChannelConnectionStatus.DISCONNECTED,
        provider_app_id="A1",
        provider_tenant_id=None,
        provider_bot_user_id=None,
        credentials_configured=False,
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
    )


async def test_setup_discord_commits_route_before_callback_activation() -> None:
    """Dedicated setup cannot make provider ingress active before its route exists."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    domain_repository = AsyncMock()

    async def create_agent_route(*args: object, **kwargs: object) -> None:
        del args, kwargs
        events.append("route")

    domain_repository.create_agent_route.side_effect = create_agent_route
    connection_service = AsyncMock()
    connection_service.create_discord_connection.return_value = SimpleNamespace(
        connection=SimpleNamespace(id="connection-1")
    )
    activation_service = AsyncMock()

    async def activate(*, connection_id: str) -> object:
        assert connection_id == "connection-1"
        events.append("activate")
        return object()

    activation_service.activate.side_effect = activate
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=AsyncMock(),
        domain_repository=domain_repository,
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=connection_service,
        discord_activation_service=activation_service,
        action_service=AsyncMock(),
        access_service=AsyncMock(),
    )
    managed = _connection().model_copy(
        update={
            "provider": ExternalChannelProvider.DISCORD,
            "status": ExternalChannelConnectionStatus.ACTIVE,
        }
    )
    service.list_connections = AsyncMock(return_value=[managed])

    result = await service.setup_discord(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        app_id="app-1",
        configuration=DiscordConnectionConfiguration(target_guild_id="guild-1"),
        credentials=DiscordConnectionCredentials(bot_token="discord-bot-token"),
    )

    assert result.connection == managed
    assert events == ["route", "commit", "activate"]
    activation_service.activate.assert_awaited_once_with(connection_id="connection-1")


def _multi_route(
    *,
    status: ExternalChannelRouteCatalogStatus = (
        ExternalChannelRouteCatalogStatus.AVAILABLE
    ),
) -> ManagedMultiRoute:
    now = datetime.datetime(2026, 7, 26, tzinfo=datetime.UTC)
    return ManagedMultiRoute(
        id="route-1",
        agent_id="agent-1",
        agent_id_snapshot="agent-1",
        agent_name="Agent One",
        catalog_status=status,
        catalog_removed_at=None,
        created_at=now,
        updated_at=now,
    )


def test_socket_manifest_keeps_required_bot_events_without_callback() -> None:
    """Socket Mode manifests still contain every subscribed Bot Event."""
    guidance = slack_manifest_guidance(
        ExternalChannelTransport.SOCKET,
        callback_url="https://callbacks.example.test/external-channel/v1/slack/events",
        app_name="Incident Agent",
    )

    settings = guidance.manifest["settings"]
    assert isinstance(settings, dict)
    subscriptions = settings["event_subscriptions"]
    assert isinstance(subscriptions, dict)
    assert subscriptions["bot_events"] == list(guidance.event_subscriptions)
    assert "channels:read" in guidance.bot_scopes
    assert "groups:read" in guidance.bot_scopes
    assert "files:read" in guidance.bot_scopes
    assert "files:write" in guidance.bot_scopes
    assert "request_url" not in subscriptions
    assert guidance.callback_url is None
    assert "signing_secret" not in guidance.manifest_json


async def test_add_multi_route_returns_existing_available_association() -> None:
    """Repeated catalog addition is idempotent under the connection lock."""
    session = AsyncMock(spec=AsyncSession)

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.get_multi_connection.return_value = SimpleNamespace(id="connection-1")
    existing = _multi_route()
    repository.get_multi_route_by_agent.return_value = existing
    domain_repository = AsyncMock()
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=domain_repository,
        lifecycle_repository=AsyncMock(),
        agent_repository=agent_repository,
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=AsyncMock(),
        access_service=AsyncMock(),
    )

    result = await service.add_multi_route(
        workspace_id="workspace-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )

    assert result == existing
    repository.get_multi_route_by_agent.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        connection_id="connection-1",
        agent_id="agent-1",
    )
    domain_repository.create_agent_route.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_repeated_disconnect_reterminalizes_connection() -> None:
    """An already disconnected row still passes through terminalization."""
    connection = SimpleNamespace(
        status=ExternalChannelConnectionStatus.DISCONNECTED,
    )
    route = SimpleNamespace(id="route-1")
    session = AsyncMock(spec=AsyncSession)
    scalars = Mock()
    scalars.all.return_value = []
    session.scalars.return_value = scalars
    repository = ExternalChannelManagementRepository()
    repository.get_connection = AsyncMock(return_value=(connection, route))
    now = datetime.datetime.now(datetime.UTC)

    cleanup_ids = await repository.begin_connection_disconnect(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        now=now,
    )

    assert cleanup_ids == ()
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTING
    repository.get_connection.assert_awaited_once_with(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        lock=True,
        include_disconnected=True,
    )
    session.flush.assert_awaited_once()


async def test_disconnect_retry_recovers_pending_progress_cleanup_ids() -> None:
    """A crash retry can prepare cleanup created by the prior transaction."""
    connection = SimpleNamespace(
        status=ExternalChannelConnectionStatus.DISCONNECTING,
    )
    route = SimpleNamespace(id="route-1")
    resource = SimpleNamespace(id="resource-1")
    binding = SimpleNamespace(
        id="binding-1",
        resource_id=resource.id,
        status=ExternalChannelBindingStatus.DISCONNECTED,
    )
    resource_rows = Mock()
    resource_rows.all.return_value = [resource]
    binding_rows = Mock()
    binding_rows.all.return_value = [binding]
    session = AsyncMock(spec=AsyncSession)
    session.scalars.side_effect = [
        resource_rows,
        binding_rows,
        ("cleanup-1",),
    ]
    repository = ExternalChannelManagementRepository()
    repository.get_connection = AsyncMock(return_value=(connection, route))

    cleanup_ids = await repository.begin_connection_disconnect(
        session,
        workspace_id="workspace-1",
        agent_id="agent-1",
        connection_id="connection-1",
        now=datetime.datetime.now(datetime.UTC),
    )

    assert cleanup_ids == ("cleanup-1",)
    session.flush.assert_awaited_once()


async def test_disconnect_prepares_cleanup_before_terminal_secret_purge() -> None:
    """Provider cleanup retains its target while terminal state commits first."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    repository = AsyncMock()
    repository.get_connection.return_value = object()

    async def begin_disconnect(*args: object, **kwargs: object) -> tuple[str, ...]:
        events.append("begin")
        return ("cleanup-1",)

    async def complete_disconnect(*args: object, **kwargs: object) -> ManagedConnection:
        events.append("complete")
        return _connection()

    repository.begin_connection_disconnect.side_effect = begin_disconnect
    repository.complete_connection_disconnect.side_effect = complete_disconnect
    lifecycle_repository = AsyncMock()

    async def disconnect_single(*args: object, **kwargs: object) -> object:
        events.append("lifecycle")
        return object()

    lifecycle_repository.disconnect_single_connection.side_effect = disconnect_single

    action_service = AsyncMock()
    prepared_target = object()

    async def prepare_delivery(delivery_id: str) -> object:
        assert delivery_id == "cleanup-1"
        events.append("prepare")
        return prepared_target

    async def attempt_prepared_delivery(target: object) -> None:
        assert target is prepared_target
        events.append("delivery")

    action_service.prepare_delivery.side_effect = prepare_delivery
    action_service.attempt_prepared_delivery.side_effect = attempt_prepared_delivery
    agent_repository = AsyncMock()
    agent_repository.get_by_id.return_value = SimpleNamespace(
        workspace_id="workspace-1"
    )
    agent_admin_repository = AsyncMock()
    agent_admin_repository.is_admin.return_value = True

    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=lifecycle_repository,
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=action_service,
        access_service=AsyncMock(),
    )

    result = await service.disconnect_connection(
        workspace_id="workspace-1",
        agent_id="agent-1",
        workspace_user_id="workspace-user-1",
        connection_id="connection-1",
    )

    assert result.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert events == [
        "begin",
        "commit",
        "prepare",
        "lifecycle",
        "complete",
        "commit",
        "delivery",
    ]


async def test_multi_disconnect_captures_cleanup_before_provider_state_purge() -> None:
    """Multi disconnect captures cleanup before it purges provider state."""
    events: list[str] = []
    session = AsyncMock(spec=AsyncSession)

    async def commit() -> None:
        events.append("commit")

    session.commit.side_effect = commit

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield session

    now = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)
    connection = SimpleNamespace(id="connection-1", updated_at=now)
    disconnected = ExternalChannelMultiConnectionDisconnect(
        disconnected_route_count=1,
        invalidated_default_count=0,
        expired_admission_count=0,
        expired_access_request_count=0,
        unavailable_resource_count=0,
        disconnected_binding_count=1,
        deleted_pending_context_count=0,
        progress_delete_intent_ids=("cleanup-1",),
    )
    repository = AsyncMock()
    repository.get_multi_connection.return_value = connection
    lifecycle_repository = AsyncMock()

    async def disconnect_multi(*args: object, **kwargs: object) -> object:
        events.append("disconnect")
        assert kwargs["defer_provider_state_purge"] is True
        return disconnected

    async def purge(*args: object, **kwargs: object) -> int:
        events.append("purge")
        return 1

    lifecycle_repository.disconnect_multi_connection.side_effect = disconnect_multi
    lifecycle_repository.purge_disconnected_connection_provider_state.side_effect = (
        purge
    )
    action_service = AsyncMock()
    target = object()

    async def prepare(*args: object, **kwargs: object) -> object:
        events.append("prepare")
        return target

    async def deliver(value: object) -> None:
        assert value is target
        events.append("delivery")

    action_service.prepare_delivery_in_session.side_effect = prepare
    action_service.attempt_prepared_delivery.side_effect = deliver
    service = ExternalChannelManagementService(
        session_manager=session_manager,
        repository=repository,
        domain_repository=AsyncMock(),
        lifecycle_repository=lifecycle_repository,
        agent_repository=AsyncMock(),
        agent_admin_repository=AsyncMock(),
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
        discord_activation_service=AsyncMock(),
        action_service=action_service,
        access_service=AsyncMock(),
    )

    result = await service.disconnect_multi_connection(
        workspace_id="workspace-1",
        connection_id=connection.id,
        expected_generation=now,
    )

    assert result.disconnected_binding_count == 1
    assert events == ["disconnect", "prepare", "purge", "commit", "delivery"]


@pytest.mark.parametrize(
    ("desired_payload", "provider_key", "operation", "status", "expected"),
    [
        ({}, "slack:T1:C1:1.1", None, None, "synchronized"),
        ({}, None, None, None, "missing"),
        (
            {},
            "slack:T1:C1:1.1",
            ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
            ExternalChannelDeliveryStatus.FAILED,
            "stale",
        ),
        (
            None,
            "slack:T1:C1:1.1",
            ExternalChannelDeliveryOperation.PROGRESS_DELETE,
            ExternalChannelDeliveryStatus.FAILED,
            "delete_failed",
        ),
        (
            {},
            "slack:T1:C1:1.1",
            ExternalChannelDeliveryOperation.PROGRESS_UPDATE,
            ExternalChannelDeliveryStatus.UNKNOWN,
            "unknown",
        ),
        (None, None, None, None, "none"),
    ],
)
def test_progress_projection_state_uses_delivery_lifecycle(
    desired_payload: dict[str, object] | None,
    provider_key: str | None,
    operation: ExternalChannelDeliveryOperation | None,
    status: ExternalChannelDeliveryStatus | None,
    expected: str,
) -> None:
    """Projection state follows durable provider outcomes, not revision counters."""
    work = cast(
        RDBExternalChannelWork,
        SimpleNamespace(
            desired_progress_payload=desired_payload,
            progress_provider_message_key=provider_key,
            state_revision=100,
            desired_progress_revision=1,
        ),
    )
    progress = (
        None
        if operation is None or status is None
        else cast(
            RDBExternalChannelDeliveryAttempt,
            SimpleNamespace(operation=operation, status=status),
        )
    )

    assert progress_projection_state(work, progress) == expected


async def test_latest_progress_query_is_scoped_to_current_work_cycle() -> None:
    """Ignore prior work deliveries while retaining lifecycle cleanup."""
    work = cast(
        RDBExternalChannelWork,
        SimpleNamespace(
            id="work-current",
            created_at=datetime.datetime(2026, 7, 23, tzinfo=datetime.UTC),
        ),
    )
    session = AsyncMock(spec=AsyncSession)
    captured_sql: list[str] = []

    async def compile_statement(statement: ClauseElement) -> None:
        sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        captured_sql.append(sql)
        return None

    session.scalar.side_effect = compile_statement
    result = (
        await ExternalChannelManagementRepository().get_latest_work_progress_delivery(
            session,
            binding_id="binding-1",
            work=work,
        )
    )
    sql = captured_sql[0]

    assert result is None
    assert "external_channel_delivery_attempts.binding_id = 'binding-1'" in sql
    assert "external_channel_actions.work_id = 'work-current'" in sql
    assert "external_channel_delivery_attempts.channel_action_id IS NULL" in sql
    assert "external_channel_delivery_attempts.created_at >= " in sql
