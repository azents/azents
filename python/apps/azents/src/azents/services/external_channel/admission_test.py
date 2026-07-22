"""External Channel admission transaction tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelEventAdmission,
    ExternalChannelEventCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService


class _SessionDouble:
    """Record whether provider acknowledgement can follow a durable commit."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record the admission commit."""
        self.committed = True


class _RepositoryDouble:
    """Return or fail one deterministic admission."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[ExternalChannelEventCreate] = []
        self.admission = cast(ExternalChannelEventAdmission, object())

    async def admit_event(
        self,
        session: AsyncSession,
        create: ExternalChannelEventCreate,
    ) -> ExternalChannelEventAdmission:
        """Record one repository admission."""
        del session
        self.calls.append(create)
        if self.fail:
            raise RuntimeError("database unavailable")
        return self.admission


def _create() -> ExternalChannelEventCreate:
    """Build one stable normalized provider event."""
    return ExternalChannelEventCreate(
        connection_id="connection-1",
        provider_event_id="event-1",
        transport_envelope_id="event-1",
        event_type="app_mention",
        provider_app_id="app-1",
        provider_tenant_id="team-1",
        provider_enterprise_id=None,
        resource_correlation_key="channel-1:thread-1",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={"type": "event_callback"},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=datetime.datetime(2026, 7, 21, tzinfo=datetime.UTC),
        received_at=datetime.datetime(2026, 7, 21, tzinfo=datetime.UTC),
    )


@pytest.mark.asyncio
async def test_admission_commits_before_return() -> None:
    """A successful callback acknowledgement follows the admission commit."""
    session = _SessionDouble()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    repository = _RepositoryDouble()
    service = ExternalChannelAdmissionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    )

    result = await service.admit(_create())

    assert result is repository.admission
    assert session.committed is True
    assert repository.calls == [_create()]


@pytest.mark.asyncio
async def test_admission_failure_does_not_acknowledge_or_commit() -> None:
    """A database failure propagates so Slack can redeliver the event."""
    session = _SessionDouble()

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    service = ExternalChannelAdmissionService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, _RepositoryDouble(fail=True)),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.admit(_create())

    assert session.committed is False
