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
    """Record terminal connection fencing and recoverable lease release."""

    def __init__(self) -> None:
        self.terminal_calls: list[dict[str, object]] = []
        self.release_calls: list[dict[str, object]] = []

    async def terminate_connection_for_provider_event(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        status: ExternalChannelConnectionStatus,
        reason: str,
        now: datetime.datetime,
        required_socket_lease_owner: str | None,
    ) -> bool:
        """Record one terminal connection lifecycle."""
        del session
        self.terminal_calls.append(
            {
                "connection_id": connection_id,
                "status": status,
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
async def test_reconnect_required_terminally_fences_owned_connection() -> None:
    """A non-reconnectable Socket closure terminates dependent route state."""
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
    assert len(repository.terminal_calls) == 1
    terminal_call = repository.terminal_calls[0]
    assert terminal_call["connection_id"] == "connection-1"
    assert terminal_call["status"] is ExternalChannelConnectionStatus.RECONNECT_REQUIRED
    assert terminal_call["reason"] == "link_disabled"
    assert terminal_call["required_socket_lease_owner"] == "manager-1"


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
    assert repository.terminal_calls == []
    assert len(repository.release_calls) == 1
    release_call = repository.release_calls[0]
    assert release_call["connection_id"] == "connection-1"
    assert release_call["lease_owner"] == "manager-1"
    assert release_call["gap_reason"] == "socket_transport_unavailable"
    assert release_call["gap_status"] is ExternalChannelConnectionStatus.DEGRADED
