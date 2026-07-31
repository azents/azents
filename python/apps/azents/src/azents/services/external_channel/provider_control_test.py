"""External Channel provider-control recovery tests."""

import datetime
from contextlib import AbstractAsyncContextManager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelDeliveryStatus
from azents.rdb.session import SessionManager
from azents.repos.external_channel.work import ExternalChannelWorkRepository
from azents.services.external_channel.channel_action import (
    ExternalChannelActionService,
)
from azents.services.external_channel.conversation import (
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.provider_control import (
    ExternalChannelProviderControlService,
)


def _at(second: int) -> datetime.datetime:
    return datetime.datetime(
        2026,
        7,
        29,
        tzinfo=datetime.UTC,
    ) + datetime.timedelta(seconds=second)


class _Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")


class _SessionScope(AbstractAsyncContextManager[AsyncSession]):
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> AsyncSession:
        return cast(AsyncSession, self.session)

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class _SessionManager:
    def __init__(self, events: list[str]) -> None:
        self.session = _Session(events)

    def __call__(self) -> _SessionScope:
        return _SessionScope(self.session)


class _Repository:
    def __init__(
        self,
        events: list[str],
        *,
        delivery_statuses: list[ExternalChannelDeliveryStatus | None] | None = None,
    ) -> None:
        self.events = events
        self.delivery_statuses = delivery_statuses or []

    async def recover_stale_provider_control_deliveries(
        self,
        session: AsyncSession,
        *,
        stale_before: datetime.datetime,
        completed_at: datetime.datetime,
        limit: int,
    ) -> int:
        del session
        assert stale_before == _at(0)
        assert completed_at == _at(120)
        assert limit == 2
        self.events.append("recover")
        return 1

    async def list_pending_provider_control_delivery_ids(
        self,
        session: AsyncSession,
        *,
        limit: int,
    ) -> list[str]:
        del session
        assert limit == 2
        self.events.append("list")
        return ["delivery-1", "delivery-2"]

    async def get_delivery_status(
        self,
        session: AsyncSession,
        *,
        delivery_attempt_id: str,
    ) -> ExternalChannelDeliveryStatus | None:
        del session
        assert delivery_attempt_id == "delivery-1"
        self.events.append("status")
        return self.delivery_statuses.pop(0)


class _ActionService:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def attempt_delivery(
        self,
        delivery_attempt_id: str,
    ) -> ExternalChannelDeliveryStatus:
        self.events.append(delivery_attempt_id)
        return ExternalChannelDeliveryStatus.DELIVERED


@pytest.mark.asyncio
async def test_drain_commits_recovery_before_provider_attempts() -> None:
    """The scan transaction closes before each existing delivery primitive runs."""
    events: list[str] = []
    service = ExternalChannelProviderControlService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _SessionManager(events),
        ),
        repository=cast(
            ExternalChannelWorkRepository,
            _Repository(events),
        ),
        action_service=cast(
            ExternalChannelActionService,
            _ActionService(events),
        ),
        stale_threshold=datetime.timedelta(minutes=2),
        interval=datetime.timedelta(seconds=1),
        limit=2,
    )

    result = await service.drain_once(now=_at(120))

    assert result.stale_unknown == 1
    assert result.attempted == 2
    assert events == ["recover", "list", "commit", "delivery-1", "delivery-2"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        ExternalChannelDeliveryStatus.FAILED,
        ExternalChannelDeliveryStatus.UNKNOWN,
        ExternalChannelDeliveryStatus.NOT_ATTEMPTED,
        None,
    ],
)
async def test_required_delivery_terminal_or_missing_status_fails_closed(
    status: ExternalChannelDeliveryStatus | None,
) -> None:
    events: list[str] = []
    service = ExternalChannelProviderControlService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _SessionManager(events),
        ),
        repository=cast(
            ExternalChannelWorkRepository,
            _Repository(events, delivery_statuses=[status]),
        ),
        action_service=cast(
            ExternalChannelActionService,
            _ActionService(events),
        ),
    )

    delivered = await service.ensure_delivered(
        delivery_attempt_id="delivery-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert delivered is False
    assert events == ["status"]


@pytest.mark.asyncio
async def test_required_pending_delivery_is_attempted_then_observed_delivered() -> None:
    events: list[str] = []
    service = ExternalChannelProviderControlService(
        session_manager=cast(
            SessionManager[AsyncSession],
            _SessionManager(events),
        ),
        repository=cast(
            ExternalChannelWorkRepository,
            _Repository(
                events,
                delivery_statuses=[
                    ExternalChannelDeliveryStatus.PENDING,
                    ExternalChannelDeliveryStatus.DELIVERED,
                ],
            ),
        ),
        action_service=cast(
            ExternalChannelActionService,
            _ActionService(events),
        ),
    )

    delivered = await service.ensure_delivered(
        delivery_attempt_id="delivery-1",
        deadline=ExternalChannelOperationDeadline(
            datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        ),
    )

    assert delivered is True
    assert events == ["status", "delivery-1", "status"]
