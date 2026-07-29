"""Slack Socket manager lifecycle tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelConnectionStatus,
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionProcessor,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
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


def _event(
    event_type: str,
    *,
    subtype: str | None = None,
) -> ExternalChannelEventCreate:
    """Build one bounded Socket event for quiesce classification."""
    event: dict[str, object] = {"type": event_type}
    if subtype is not None:
        event["subtype"] = subtype
    return ExternalChannelEventCreate(
        connection_id="connection-1",
        provider_event_id=f"event-{event_type}-{subtype}",
        transport_envelope_id=None,
        event_type=event_type,
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        provider_enterprise_id=None,
        resource_correlation_key=None,
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={"event": event},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=None,
        received_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
    )


def _service(
    session: _SessionDouble,
    repository: _RepositoryDouble,
    config: Config | None = None,
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
        interaction_processor=cast(ExternalChannelInteractionProcessor, object()),
        shortcut_source_service=cast(ExternalChannelShortcutSourceService, object()),
        manager_id="manager-1",
        config=config,
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


def test_quiesced_socket_blocks_normal_messages_but_keeps_revocations() -> None:
    """Socket quiesce is limited to normal message ingress."""
    config = MagicMock()
    config.external_channel_conversation.quiesce.slack_socket = True
    service = _service(_SessionDouble(), _RepositoryDouble(), config=config)

    assert service._message_ingress_quiesced(_event("app_mention"))  # pyright: ignore[reportPrivateUsage]
    assert service._message_ingress_quiesced(_event("message"))  # pyright: ignore[reportPrivateUsage]
    assert not service._message_ingress_quiesced(  # pyright: ignore[reportPrivateUsage]
        _event("message", subtype="message_changed")
    )
    assert not service._message_ingress_quiesced(  # pyright: ignore[reportPrivateUsage]
        _event("message", subtype="message_deleted")
    )
    assert not service._message_ingress_quiesced(_event("app_uninstalled"))  # pyright: ignore[reportPrivateUsage]
    assert not service._message_ingress_quiesced(_event("tokens_revoked"))  # pyright: ignore[reportPrivateUsage]


def test_socket_quiesce_is_disabled_by_default() -> None:
    """The default configuration preserves legacy Socket admission."""
    service = _service(_SessionDouble(), _RepositoryDouble())

    assert not service._message_ingress_quiesced(_event("app_mention"))  # pyright: ignore[reportPrivateUsage]
