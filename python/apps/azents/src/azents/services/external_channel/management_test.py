"""External Channel management orchestration tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.models.external_channel import (
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelWork,
)
from azents.repos.external_channel.management import (
    ExternalChannelManagementRepository,
    progress_projection_state,
)
from azents.repos.external_channel.management_data import ManagedConnection
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
        last_verified_at=None,
        last_health_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        disconnected_at=None,
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
    assert "request_url" not in subscriptions
    assert guidance.callback_url is None
    assert "signing_secret" not in guidance.manifest_json


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
        agent_repository=agent_repository,
        agent_admin_repository=agent_admin_repository,
        workspace_user_repository=AsyncMock(),
        connection_service=AsyncMock(),
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
        "complete",
        "commit",
        "delivery",
    ]


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
    deliveries = (
        []
        if operation is None or status is None
        else [
            cast(
                RDBExternalChannelDeliveryAttempt,
                SimpleNamespace(operation=operation, status=status),
            )
        ]
    )

    assert progress_projection_state(work, deliveries) == expected
