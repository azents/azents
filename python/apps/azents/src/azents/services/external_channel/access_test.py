"""Tests for External Channel access decisions."""

import datetime
import logging
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAccessGrantScope,
    ExternalChannelAccessRequestStatus,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
)
from azents.services.external_channel.access import ExternalChannelAccessService
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
)


class _SessionContext(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self) -> None:
        self.session = cast(AsyncSession, SimpleNamespace(commit=AsyncMock()))

    async def __aenter__(self) -> AsyncSession:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _SessionManager:
    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return _SessionContext()


@pytest.mark.parametrize(
    ("created", "retained_event_type", "logged_event_type", "expected_count"),
    [
        (True, "app_mention", "app_mention", 1),
        (True, "tenant-secret-event", "unknown", 1),
        (False, "app_mention", "app_mention", 0),
    ],
)
async def test_allow_logs_sanitized_event_only_for_new_session(
    caplog: pytest.LogCaptureFixture,
    *,
    created: bool,
    retained_event_type: str,
    logged_event_type: str,
    expected_count: int,
) -> None:
    """Allow emits no provider identity or payload and only logs real creation."""
    now = datetime.datetime(2026, 8, 1, tzinfo=datetime.UTC)
    request = SimpleNamespace(
        id="access-secret",
        route_id="route-1",
        resource_id="resource-secret",
        principal_id="principal-secret",
        agent_session_id=None,
        status=ExternalChannelAccessRequestStatus.PENDING,
        expires_at=now + datetime.timedelta(minutes=5),
    )
    route = SimpleNamespace(
        id="route-1",
        connection_id="connection-secret",
        agent_id="agent-1",
        require_active_agent_id=lambda: "agent-1",
    )
    connection = SimpleNamespace(
        id="connection-secret",
        provider=ExternalChannelProvider.SLACK,
    )
    resource = SimpleNamespace(
        id="resource-secret",
        connection_id=connection.id,
        status=ExternalChannelResourceStatus.ACTIVE,
        labels={
            "provider_event_type": retained_event_type,
            "tenant_id": "tenant-secret",
            "channel_id": "channel-secret",
        },
    )
    binding = SimpleNamespace(
        id="binding-1",
        route_id=route.id,
        agent_session_id="session-secret",
    )
    grant = SimpleNamespace(scope=ExternalChannelAccessGrantScope.AGENT)
    decided = SimpleNamespace(**vars(request))
    decided.status = ExternalChannelAccessRequestStatus.ALLOWED
    decided.agent_session_id = "session-secret"

    repository = MagicMock()
    repository.get_access_request = AsyncMock(return_value=request)
    repository.get_agent_route = AsyncMock(return_value=route)
    repository.lock_connection_for_routing = AsyncMock(return_value=connection)
    repository.get_routable_route_by_id = AsyncMock(return_value=route)
    repository.lock_resource = AsyncMock(return_value=resource)
    repository.lock_connected_binding_by_resource = AsyncMock(return_value=None)
    repository.lock_access_request = AsyncMock(return_value=request)
    repository.get_active_block = AsyncMock(return_value=None)
    repository.create_binding_idempotent = AsyncMock(return_value=binding)
    repository.ensure_access_grant = AsyncMock(return_value=grant)
    repository.decide_access_request = AsyncMock(return_value=decided)
    repository.create_access_request_control_delete_intent = AsyncMock(
        return_value=None
    )

    agent_repository = MagicMock()
    agent_repository.get_by_id = AsyncMock(
        return_value=SimpleNamespace(
            id="agent-1",
            workspace_id="workspace-secret",
            lifecycle_status=AgentLifecycleStatus.ACTIVE,
        )
    )
    root_creation = MagicMock()
    root_creation.create_root_session = AsyncMock(
        return_value=SimpleNamespace(
            agent_session=SimpleNamespace(id="session-secret"),
            created=created,
        )
    )
    replay = MagicMock()
    replay.replay_access_allow = AsyncMock(
        return_value=ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
            reason=ExternalChannelIngestionReason.ACCEPTED,
            mailbox_item_id="mailbox-secret",
            control_delivery_attempt_id=None,
            connection_id=None,
        )
    )
    service = ExternalChannelAccessService(
        session_manager=cast(Any, _SessionManager()),
        repository=cast(Any, repository),
        agent_repository=cast(Any, agent_repository),
        root_agent_session_creation_service=cast(Any, root_creation),
        ingestion_replay_service=cast(Any, replay),
    )

    with caplog.at_level(
        logging.INFO,
        logger="azents.services.external_channel.access",
    ):
        await service.allow(
            access_request_id=request.id,
            scope=ExternalChannelAccessGrantScope.AGENT,
            decided_by_user_id="approver-secret",
            decision_summary=None,
            now=now,
        )

    records = [
        record
        for record in caplog.records
        if record.getMessage() == "Created External Channel AgentSession"
    ]
    assert len(records) == expected_count
    if records:
        assert records[0].__dict__["external_channel_provider"] == "slack"
        assert records[0].__dict__["provider_event_type"] == logged_event_type
    assert "tenant-secret" not in caplog.text
    assert "channel-secret" not in caplog.text
    assert "principal-secret" not in caplog.text
    assert "session-secret" not in caplog.text
