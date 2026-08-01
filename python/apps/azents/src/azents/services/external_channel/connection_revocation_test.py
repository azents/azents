"""Direct authenticated Slack connection-revocation tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.repos.external_channel.work_data import ChannelDeliveryTarget
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation

_NOW = datetime.datetime(2026, 7, 29, 1, tzinfo=datetime.UTC)


class _Session:
    """Record lifecycle transaction completion."""

    def __init__(self) -> None:
        self.committed = False

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
        _session: AsyncSession,
        **kwargs: object,
    ) -> tuple[str, ...]:
        self.terminated.append(kwargs)
        return ("delivery-1",)

    async def purge_disconnected_connection_provider_state(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
    ) -> bool:
        assert connection_id == "connection-1"
        self.purged = True
        return True

    async def mark_connection_reconnect_required(
        self,
        _session: AsyncSession,
        **kwargs: object,
    ) -> bool:
        self.reconnect_required.append(kwargs)
        return True


class _ActionService:
    """Prove cleanup provider I/O starts only after the lifecycle commit."""

    def __init__(self, session: _Session) -> None:
        self.session = session
        self.attempted: list[ChannelDeliveryTarget] = []

    async def prepare_delivery_in_session(
        self,
        _session: AsyncSession,
        delivery_attempt_id: str,
    ) -> ChannelDeliveryTarget:
        assert delivery_attempt_id == "delivery-1"
        return cast(
            ChannelDeliveryTarget,
            SimpleNamespace(delivery_attempt_id=delivery_attempt_id),
        )

    async def attempt_captured_terminal_delivery(
        self,
        target: ChannelDeliveryTarget,
    ) -> None:
        assert self.session.committed
        self.attempted.append(target)


def _service() -> tuple[
    ExternalChannelConnectionRevocationService,
    _Session,
    _Repository,
    _ActionService,
]:
    session = _Session()

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    repository = _Repository()
    action_service = _ActionService(session)
    return (
        ExternalChannelConnectionRevocationService(
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            repository=cast(ExternalChannelRepository, repository),
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
