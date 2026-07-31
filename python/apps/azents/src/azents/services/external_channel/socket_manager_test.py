"""Slack Socket manager lifecycle tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import azents.services.external_channel.socket_manager as socket_manager_module
from azents.core.config import Config
from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.connection_revocation import (
    ExternalChannelConnectionRevocationService,
)
from azents.services.external_channel.credentials import (
    ExternalChannelCredentialsCodec,
)
from azents.services.external_channel.data import SlackConnectionCredentials
from azents.services.external_channel.ingestion import (
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngressAuthority,
)
from azents.services.external_channel.interaction import (
    ExternalChannelInteractionProcessor,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.external_channel.slack_events import SlackConnectionRevocation
from azents.services.external_channel.slack_socket import (
    SlackSocketInvalidEnvelope,
    SlackSocketRetryableIngestion,
)
from azents.services.external_channel.socket_manager import (
    SlackSocketManagerService,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
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
        required_configuration_generation: int | None,
        required_socket_lease_owner: str | None,
    ) -> bool:
        """Record one reconnect-required health transition."""
        del session
        self.reconnect_required_calls.append(
            {
                "connection_id": connection_id,
                "reason": reason,
                "now": now,
                "required_configuration_generation": (
                    required_configuration_generation
                ),
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

    async def socket_connection_owned_active(
        self,
        _session: AsyncSession,
        **_kwargs: object,
    ) -> object:
        return object()


def _event(
    event_type: str,
    *,
    subtype: str | None = None,
) -> ExternalChannelTrigger:
    """Build one bounded Socket event for quiesce classification."""
    event: dict[str, object] = {"type": event_type}
    if subtype is not None:
        event["subtype"] = subtype
    return ExternalChannelTrigger(
        connection_id="connection-1",
        provider_event_id=f"event-{event_type}-{subtype}",
        transport_envelope_id=None,
        event_type=event_type,
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        provider_enterprise_id=None,
        resource_correlation_key=None,
        envelope={"event": event},
        provider_occurred_at=None,
        received_at=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
    )


def _service(
    session: _SessionDouble,
    repository: _RepositoryDouble,
    config: Config | None = None,
    *,
    transport_ingestion_service: object | None = None,
    revocation_service: object | None = None,
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
        transport_ingestion_service=cast(
            ExternalChannelTransportIngestionService,
            transport_ingestion_service or object(),
        ),
        revocation_service=cast(
            ExternalChannelConnectionRevocationService,
            revocation_service or object(),
        ),
        manager_id="manager-1",
        config=config,
    )


def _configuration() -> ExternalChannelConnectionConfiguration:
    return cast(
        ExternalChannelConnectionConfiguration,
        SimpleNamespace(
            provider_app_id="app-1",
            provider_tenant_id="tenant-1",
            configuration_generation=2,
        ),
    )


def _outcome(
    kind: ExternalChannelIngestionOutcomeKind,
) -> ExternalChannelIngestionOutcome:
    return ExternalChannelIngestionOutcome(
        kind=kind,
        reason=(
            ExternalChannelIngestionReason.ACCEPTED
            if kind is ExternalChannelIngestionOutcomeKind.ACCEPTED
            else ExternalChannelIngestionReason.HISTORY_UNAVAILABLE
        ),
        batch_id=(
            "batch-1" if kind is ExternalChannelIngestionOutcomeKind.ACCEPTED else None
        ),
        control_delivery_attempt_id=None,
        connection_id=None,
    )


@pytest.mark.asyncio
async def test_owned_socket_event_uses_lease_authority_without_legacy_admission() -> (
    None
):
    session = _SessionDouble()
    repository = _RepositoryDouble()
    transport = SimpleNamespace(
        ingest_slack_event=AsyncMock(
            return_value=_outcome(ExternalChannelIngestionOutcomeKind.ACCEPTED)
        )
    )
    service = _service(
        session,
        repository,
        transport_ingestion_service=transport,
    )

    result = await service._handle_owned_event(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        configuration=_configuration(),
        event=_event("app_mention"),
    )

    assert isinstance(result, ExternalChannelIngestionOutcome)
    call = transport.ingest_slack_event.await_args.kwargs
    authority = call["authority"]
    assert isinstance(authority, ExternalChannelIngressAuthority)
    assert authority.ingress_profile is ExternalChannelIngressProfile.SLACK_SOCKET
    assert authority.lease_owner == "manager-1"
    assert authority.lease_generation is None


@pytest.mark.asyncio
async def test_owned_socket_retryable_result_raises_before_acknowledgement() -> None:
    transport = SimpleNamespace(
        ingest_slack_event=AsyncMock(
            return_value=_outcome(ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE)
        )
    )
    service = _service(
        _SessionDouble(),
        _RepositoryDouble(),
        transport_ingestion_service=transport,
    )

    with pytest.raises(SlackSocketRetryableIngestion):
        await service._handle_owned_event(  # pyright: ignore[reportPrivateUsage]
            connection_id="connection-1",
            configuration=_configuration(),
            event=_event("app_mention"),
        )


@pytest.mark.asyncio
async def test_owned_socket_revocation_uses_configuration_and_lease_fences() -> None:
    transport = SimpleNamespace(
        ingest_slack_event=AsyncMock(
            return_value=SlackConnectionRevocation(kind="tokens_revoked")
        )
    )
    revocation = SimpleNamespace(apply=AsyncMock(return_value=True))
    service = _service(
        _SessionDouble(),
        _RepositoryDouble(),
        transport_ingestion_service=transport,
        revocation_service=revocation,
    )

    await service._handle_owned_event(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        configuration=_configuration(),
        event=_event("tokens_revoked"),
    )

    revocation.apply.assert_awaited_once_with(
        connection_id="connection-1",
        revocation=SlackConnectionRevocation(kind="tokens_revoked"),
        required_configuration_generation=2,
        required_socket_lease_owner="manager-1",
        now=datetime.datetime(2026, 7, 29, tzinfo=datetime.UTC),
    )


@pytest.mark.asyncio
async def test_stale_owned_socket_revocation_is_not_acknowledged() -> None:
    transport = SimpleNamespace(
        ingest_slack_event=AsyncMock(
            return_value=SlackConnectionRevocation(kind="tokens_revoked")
        )
    )
    revocation = SimpleNamespace(apply=AsyncMock(return_value=False))
    service = _service(
        _SessionDouble(),
        _RepositoryDouble(),
        transport_ingestion_service=transport,
        revocation_service=revocation,
    )

    with pytest.raises(SlackSocketInvalidEnvelope):
        await service._handle_owned_event(  # pyright: ignore[reportPrivateUsage]
            connection_id="connection-1",
            configuration=_configuration(),
            event=_event("tokens_revoked"),
        )


@pytest.mark.asyncio
async def test_retryable_ingestion_releases_degraded_after_sdk_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A no-ack failure closes the SDK so provider redelivery can recover."""
    service = _service(_SessionDouble(), _RepositoryDouble())
    configuration = SimpleNamespace(
        provider_app_id="app-1",
        provider_tenant_id="tenant-1",
        configuration_generation=2,
        encrypted_credentials="ciphertext",
        app_mode=ExternalChannelAppMode.SINGLE,
        transport=ExternalChannelTransport.SOCKET,
    )
    service.credentials_codec = cast(
        ExternalChannelCredentialsCodec,
        SimpleNamespace(
            decrypt=lambda _: SlackConnectionCredentials(
                bot_token="bot-token",
                signing_secret="signing-secret",
                app_token="app-token",
            )
        ),
    )
    claim = AsyncMock(return_value=configuration)
    mark_active = AsyncMock(return_value=True)
    record_gap = AsyncMock(return_value=True)
    release = AsyncMock(return_value=True)

    class _RetryableRunner:
        def __init__(self, **kwargs: object) -> None:
            self.report_active = kwargs["report_active"]
            self.report_gap = kwargs["report_gap"]

        async def run_connection(self, **_: object) -> None:
            await self.report_gap("socket_connecting")  # type: ignore[operator]
            await self.report_active()  # type: ignore[operator]
            raise SlackSocketRetryableIngestion("retryable")

    monkeypatch.setattr(service, "_claim", claim)
    monkeypatch.setattr(service, "_mark_active", mark_active)
    monkeypatch.setattr(service, "_record_gap", record_gap)
    monkeypatch.setattr(service, "_release", release)
    monkeypatch.setattr(
        socket_manager_module,
        "create_slack_web_client",
        object,
    )
    monkeypatch.setattr(
        socket_manager_module,
        "SlackSocketModeRunner",
        _RetryableRunner,
    )

    await service._run_owned_connection(  # pyright: ignore[reportPrivateUsage]
        connection_id="connection-1",
        shutdown_event=asyncio.Event(),
    )

    record_gap.assert_awaited_once_with(
        "connection-1",
        "socket_connecting",
    )
    mark_active.assert_awaited_once_with("connection-1")
    release.assert_awaited_once_with(
        "connection-1",
        reason="socket_ingestion_retryable",
        status=ExternalChannelConnectionStatus.DEGRADED,
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
    assert health_call["required_configuration_generation"] is None
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
