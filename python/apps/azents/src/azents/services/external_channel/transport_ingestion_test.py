"""Authenticated transport-to-ingestion projection tests."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelConversationScopeKind,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelResource,
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.ingestion import (
    ExternalChannelConversationIngestionService,
    ExternalChannelIngestionOutcome,
    ExternalChannelIngestionOutcomeKind,
    ExternalChannelIngestionReason,
    ExternalChannelIngestionRequest,
    ExternalChannelIngressAuthority,
    ExternalChannelIngressAuthorityKind,
)
from azents.services.external_channel.transport_ingestion import (
    ExternalChannelTransportIngestionService,
    external_channel_transport_deadline,
)

_NOW = datetime.datetime(2026, 7, 29, 1, tzinfo=datetime.UTC)


class _Repository:
    """Return one configuration and optional Discord resource identities."""

    def __init__(
        self,
        *,
        provider_resource: ExternalChannelResource | None = None,
        delivery_resource: ExternalChannelResource | None = None,
        configuration_generation: int = 2,
    ) -> None:
        self.provider_resource = provider_resource
        self.delivery_resource = delivery_resource
        self.configuration_generation = configuration_generation

    async def get_owned_discord_gateway_configuration(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
        lease_owner: str,
        lease_generation: int,
        now: datetime.datetime,
    ) -> object:
        assert connection_id == "connection-1"
        assert (lease_owner, lease_generation) == ("o", 3)
        assert now.tzinfo is not None
        return SimpleNamespace(
            provider=ExternalChannelProvider.DISCORD,
            provider_tenant_id="300",
            provider_bot_user_id="900",
            encrypted_credentials="ciphertext",
            configuration_generation=self.configuration_generation,
            ingress_profile=(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
        )

    async def get_resource_by_provider_key(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
        resource_type: ExternalChannelResourceType,
        provider_resource_key: str,
    ) -> ExternalChannelResource | None:
        assert connection_id == "connection-1"
        assert resource_type is ExternalChannelResourceType.THREAD
        del provider_resource_key
        return self.provider_resource

    async def get_discord_resource_by_delivery_channel(
        self,
        _session: AsyncSession,
        *,
        connection_id: str,
        guild_id: str,
        delivery_channel_id: str,
    ) -> ExternalChannelResource | None:
        assert (connection_id, guild_id, delivery_channel_id) == (
            "connection-1",
            "300",
            "201",
        )
        return self.delivery_resource


class _Ingestion:
    """Capture the credential-free request passed to shared ingestion."""

    def __init__(self) -> None:
        self.requests: list[ExternalChannelIngestionRequest] = []

    async def ingest(
        self,
        request: ExternalChannelIngestionRequest,
    ) -> ExternalChannelIngestionOutcome:
        self.requests.append(request)
        return ExternalChannelIngestionOutcome(
            kind=ExternalChannelIngestionOutcomeKind.ACCEPTED,
            reason=ExternalChannelIngestionReason.ACCEPTED,
            mailbox_item_id="batch-1",
            control_plan=None,
            connection_id=None,
        )


def _service(
    *,
    repository: _Repository | None = None,
) -> tuple[ExternalChannelTransportIngestionService, _Ingestion]:
    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, object())

    ingestion = _Ingestion()
    return (
        ExternalChannelTransportIngestionService(
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            repository=cast(
                ExternalChannelRepository,
                repository or _Repository(),
            ),
            ingestion_service=cast(
                ExternalChannelConversationIngestionService,
                ingestion,
            ),
        ),
        ingestion,
    )


def _authority(
    profile: ExternalChannelIngressProfile,
) -> ExternalChannelIngressAuthority:
    return ExternalChannelIngressAuthority(
        kind=(
            ExternalChannelIngressAuthorityKind.CONFIGURATION
            if profile is ExternalChannelIngressProfile.SLACK_HTTP
            else ExternalChannelIngressAuthorityKind.LEASE
        ),
        ingress_profile=profile,
        configuration_generation=2,
        lease_owner=None
        if profile is ExternalChannelIngressProfile.SLACK_HTTP
        else "o",
        lease_generation=(
            3 if profile is ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP else None
        ),
    )


def _slack_event(
    *,
    thread_ts: str | None = None,
    event_type: str = "app_mention",
    text: str = "private inbound content",
    authorizations: list[dict[str, object]] | None = None,
) -> ExternalChannelTrigger:
    event: dict[str, object] = {
        "type": event_type,
        "channel": "C100",
        "user": "U100",
        "text": text,
        "ts": "100.000001",
    }
    if thread_ts is not None:
        event["thread_ts"] = thread_ts
    envelope: dict[str, object] = {"event": event}
    if authorizations is not None:
        envelope["authorizations"] = authorizations
    return ExternalChannelTrigger(
        connection_id="connection-1",
        provider_event_id="event-1",
        transport_envelope_id=None,
        event_type=event_type,
        provider_app_id="A100",
        provider_tenant_id="T100",
        provider_enterprise_id=None,
        resource_correlation_key=None,
        envelope=envelope,
        provider_occurred_at=None,
        received_at=_NOW,
    )


def _discord_event(
    *,
    channel_id: str,
    thread_id: str | None,
    parent_channel_id: str | None,
    invocation: bool,
) -> ExternalChannelTrigger:
    message: dict[str, object] = {
        "id": "100",
        "channel_id": channel_id,
        "guild_id": "300",
        "content": "private inbound content",
        "timestamp": _NOW.isoformat(),
        "author": {"id": "400", "username": "participant"},
        "mentions": ([{"id": "900", "username": "Azents"}] if invocation else []),
    }
    if thread_id is not None:
        message["thread"] = {
            "id": thread_id,
            "parent_id": parent_channel_id,
        }
    return ExternalChannelTrigger(
        connection_id="connection-1",
        provider_event_id="event-1",
        transport_envelope_id="event-1",
        event_type="discord_message_create",
        provider_app_id="500",
        provider_tenant_id="300",
        provider_enterprise_id=None,
        resource_correlation_key=None,
        envelope={"message": message},
        provider_occurred_at=_NOW,
        received_at=_NOW,
    )


@pytest.mark.asyncio
async def test_slack_parent_invocation_projects_content_free_parent_request() -> None:
    service, ingestion = _service()

    outcome = await service.ingest_slack_event(
        event=_slack_event(),
        connected_bot_user_id="UAUTH",
        authority=_authority(ExternalChannelIngressProfile.SLACK_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    assert isinstance(outcome, ExternalChannelIngestionOutcome)
    request = ingestion.requests[0]
    assert request.scope.kind is ExternalChannelConversationScopeKind.PARENT_CHANNEL
    assert request.scope.provider_thread_key is None
    assert request.locator.delivery_thread_key == "100.000001"
    assert request.locator.provider_resource_key == ("slack:T100:C100:100.000001")
    assert "private inbound content" not in repr(request)


@pytest.mark.asyncio
async def test_slack_manual_thread_invocation_reuses_root_scope() -> None:
    service, ingestion = _service()

    await service.ingest_slack_event(
        event=_slack_event(thread_ts="90.000001"),
        connected_bot_user_id="UAUTH",
        authority=_authority(ExternalChannelIngressProfile.SLACK_SOCKET),
        deadline=external_channel_transport_deadline(_NOW),
    )

    request = ingestion.requests[0]
    assert request.scope.kind is ExternalChannelConversationScopeKind.THREAD
    assert request.scope.provider_thread_key == "90.000001"
    assert request.locator.delivery_thread_key == "90.000001"


@pytest.mark.asyncio
async def test_slack_message_targeting_authorized_bot_projects_invocation() -> None:
    service, ingestion = _service()

    await service.ingest_slack_event(
        event=_slack_event(
            event_type="message",
            text="<@UAUTH> private inbound content",
            authorizations=[
                {
                    "is_bot": True,
                    "team_id": "T100",
                    "user_id": "UAUTH",
                }
            ],
        ),
        connected_bot_user_id="BOLD",
        authority=_authority(ExternalChannelIngressProfile.SLACK_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    request = ingestion.requests[0]
    assert request.locator.invocation is True
    assert "private inbound content" not in repr(request)


@pytest.mark.asyncio
async def test_discord_parent_invocation_defers_thread_provisioning_to_ingestion() -> (
    None
):
    service, ingestion = _service()

    await service.ingest_discord_event(
        event=_discord_event(
            channel_id="200",
            thread_id=None,
            parent_channel_id=None,
            invocation=True,
        ),
        authority=_authority(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    request = ingestion.requests[0]
    assert request.scope.kind is ExternalChannelConversationScopeKind.PARENT_CHANNEL
    assert request.locator.provider_resource_key == "discord:300:100"
    assert request.locator.delivery_thread_key == "100"
    assert request.locator.provider_parent_channel_id == "200"


@pytest.mark.asyncio
async def test_discord_manual_thread_reuses_thread_without_provisioning() -> None:
    service, ingestion = _service()

    await service.ingest_discord_event(
        event=_discord_event(
            channel_id="201",
            thread_id="201",
            parent_channel_id="200",
            invocation=True,
        ),
        authority=_authority(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    request = ingestion.requests[0]
    assert request.scope.kind is ExternalChannelConversationScopeKind.THREAD
    assert request.scope.provider_channel_id == "201"
    assert request.locator.provider_parent_channel_id == "200"
    assert request.locator.delivery_thread_key == "201"


@pytest.mark.asyncio
async def test_discord_bound_thread_uses_retained_resource_identity() -> None:
    resource = cast(
        ExternalChannelResource,
        SimpleNamespace(
            provider_resource_key="discord:300:100",
            labels={"delivery_channel_id": "201"},
        ),
    )
    service, ingestion = _service(repository=_Repository(delivery_resource=resource))

    await service.ingest_discord_event(
        event=_discord_event(
            channel_id="201",
            thread_id="201",
            parent_channel_id="200",
            invocation=False,
        ),
        authority=_authority(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    request = ingestion.requests[0]
    assert request.locator.provider_resource_key == "discord:300:100"
    assert request.locator.invocation is False


@pytest.mark.asyncio
async def test_stale_discord_configuration_stops_before_provider_io() -> None:
    service, ingestion = _service(repository=_Repository(configuration_generation=3))

    outcome = await service.ingest_discord_event(
        event=_discord_event(
            channel_id="200",
            thread_id=None,
            parent_channel_id=None,
            invocation=True,
        ),
        authority=_authority(ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP),
        deadline=external_channel_transport_deadline(_NOW),
    )

    assert outcome is not None
    assert outcome.kind is ExternalChannelIngestionOutcomeKind.RETRYABLE_FAILURE
    assert ingestion.requests == []
