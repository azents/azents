"""Slack Socket manager lifecycle tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import ExternalChannelConnectionStatus
from azents.rdb.session import SessionManager
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.socket_manager import (
    SlackSocketManagerService,
)


class _SessionDouble:
    """Record the lifecycle transaction commit."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record one committed lifecycle transition."""
        self.committed = True


class _RepositoryDouble:
    """Record connection health changes and recoverable lease release."""

    def __init__(self) -> None:
        self.reconnect_required_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    async def mark_connection_reconnect_required(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        reason: str,
        now: datetime.datetime,
        required_socket_lease_owner: str | None,
    ) -> bool:
        """Record one reconnect-required health transition."""
        del session
        self.reconnect_required_calls.append(
            {
                "connection_id": connection_id,
                "reason": reason,
                "now": now,
                "required_socket_lease_owner": required_socket_lease_owner,
            }
        )
        return True

    async def release_socket_connection_lease(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        now: datetime.datetime,
        gap_reason: str | None,
        gap_status: ExternalChannelConnectionStatus | None,
    ) -> bool:
        """Record one recoverable Socket lease release."""
        del session
        self.release_calls.append(
            {
                "connection_id": connection_id,
                "lease_owner": lease_owner,
                "now": now,
                "gap_reason": gap_reason,
                "gap_status": gap_status,
            }
        )
        return True


def _service(
    session: _SessionDouble,
    repository: _RepositoryDouble,
) -> SlackSocketManagerService:
    """Build a manager around lifecycle-only doubles."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return SlackSocketManagerService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
        credentials_codec=cast(ExternalChannelCredentialsCodec, object()),
        admission_service=cast(ExternalChannelAdmissionService, object()),
        http_client=cast(httpx.AsyncClient, object()),
        manager_id="manager-1",
    )


@pytest.mark.asyncio
async def test_reconnect_required_preserves_owned_route() -> None:
    """A credential failure changes health without terminating Agent routing."""
    session = _SessionDouble()
    repository = _RepositoryDouble()

    released = await _service(session, repository)._release(  # pyright: ignore[reportPrivateUsage]  # Exercise the terminal Socket release boundary directly.
        "connection-1",
        reason="link_disabled",
        status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
    )

    assert released is True
    assert session.committed is True
    assert repository.release_calls == []
    assert len(repository.reconnect_required_calls) == 1
    health_call = repository.reconnect_required_calls[0]
    assert health_call["connection_id"] == "connection-1"
    assert health_call["reason"] == "link_disabled"
    assert health_call["required_socket_lease_owner"] == "manager-1"


@pytest.mark.asyncio
async def test_degraded_socket_release_preserves_connection_lifecycle() -> None:
    """A recoverable transport gap releases only the current Socket lease."""
    session = _SessionDouble()
    repository = _RepositoryDouble()

    released = await _service(session, repository)._release(  # pyright: ignore[reportPrivateUsage]  # Exercise the terminal Socket release boundary directly.
        "connection-1",
        reason="socket_transport_unavailable",
        status=ExternalChannelConnectionStatus.DEGRADED,
    )

    assert released is True
    assert session.committed is True
    assert repository.reconnect_required_calls == []
    assert len(repository.release_calls) == 1
    release_call = repository.release_calls[0]
    assert release_call["connection_id"] == "connection-1"
    assert release_call["lease_owner"] == "manager-1"
    assert release_call["gap_reason"] == "socket_transport_unavailable"
    assert release_call["gap_status"] is ExternalChannelConnectionStatus.DEGRADED
