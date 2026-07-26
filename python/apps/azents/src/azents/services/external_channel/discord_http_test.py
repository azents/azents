"""Discord HTTP durable interaction admission tests."""

import datetime
import hashlib
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelIngressProfile,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelConnectionConfiguration,
    ExternalChannelInteractionAdmission,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_http import DiscordHTTPAdmissionService
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
)

_NOW = datetime.datetime(2026, 7, 26, 1, 0, tzinfo=datetime.UTC)


class _RepositoryDouble:
    """Return one selector-scoped active connection."""

    def __init__(self, configuration: ExternalChannelConnectionConfiguration) -> None:
        self.configuration = configuration
        self.selector_hashes: list[str] = []

    async def get_discord_http_configuration_by_selector_hash(
        self,
        session: AsyncSession,
        *,
        selector_hash: str,
    ) -> ExternalChannelConnectionConfiguration:
        del session
        self.selector_hashes.append(selector_hash)
        return self.configuration


class _AdmissionDouble:
    """Record only canonical token-free admission inputs."""

    def __init__(self) -> None:
        self.inputs: list[
            tuple[ExternalChannelInteractionCreate, ExternalChannelPrincipalCreate]
        ] = []

    async def admit_interaction(
        self,
        *,
        create: ExternalChannelInteractionCreate,
        principal: ExternalChannelPrincipalCreate,
    ) -> ExternalChannelInteractionAdmission:
        self.inputs.append((create, principal))
        return cast(
            ExternalChannelInteractionAdmission,
            SimpleNamespace(
                interaction=SimpleNamespace(id="interaction-row-1"),
                created=True,
            ),
        )


def _configuration(
    public_key: str,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.DISCORD,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        configuration_generation=2,
        status=ExternalChannelConnectionStatus.ACTIVE,
        app_mode=ExternalChannelAppMode.SINGLE,
        provider_app_id="app-1",
        provider_tenant_id="guild-1",
        provider_bot_user_id=None,
        http_callback_selector_hash="unused",
        encrypted_credentials="ciphertext",
        capabilities={"interaction_public_key": public_key},
        provider_config={"target_guild_id": "guild-1"},
        last_verified_at=_NOW,
        last_health_at=_NOW,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _service(
    *,
    configuration: ExternalChannelConnectionConfiguration,
    admission: _AdmissionDouble,
) -> tuple[DiscordHTTPAdmissionService, _RepositoryDouble]:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, object())

    repository = _RepositoryDouble(configuration)
    return (
        DiscordHTTPAdmissionService(
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            repository=cast(ExternalChannelRepository, repository),
            admission_service=cast(ExternalChannelAdmissionService, admission),
        ),
        repository,
    )


def _body(
    *,
    interaction_type: int = 2,
    application_id: str = "app-1",
    guild_id: str = "guild-1",
) -> bytes:
    return json.dumps(
        {
            "id": "discord-interaction-1",
            "type": interaction_type,
            "application_id": application_id,
            "guild_id": guild_id,
            "channel_id": "channel-1",
            "member": {"user": {"id": "user-1"}},
            "token": "interaction-token-must-not-persist",
            "data": {
                "name": "Ask an Azents Agent",
                "content": "private command content",
                "attachments": [{"id": "attachment-1"}],
            },
        },
        separators=(",", ":"),
    ).encode()


def _signature(private_key: Ed25519PrivateKey, body: bytes) -> tuple[str, str]:
    timestamp = str(int(_NOW.timestamp()))
    return timestamp, private_key.sign(timestamp.encode() + body).hex()


@pytest.mark.asyncio
async def test_signed_interaction_admission_redacts_sensitive_input() -> None:
    """A verified Guild interaction commits provenance before acknowledgement."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, repository = _service(
        configuration=_configuration(private_key.public_key().public_bytes_raw().hex()),
        admission=admission,
    )
    body = _body()
    timestamp, signature = _signature(private_key, body)

    result = await service.handle(
        selector="opaque-selector",
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        received_at=_NOW,
    )

    assert result.ping is False
    assert result.admission is not None
    assert repository.selector_hashes == [
        hashlib.sha256(b"opaque-selector").hexdigest()
    ]
    assert len(admission.inputs) == 1
    create, principal = admission.inputs[0]
    assert create.connection_id == "connection-1"
    assert create.provider_interaction_key == "discord-interaction-1"
    assert create.resource_correlation_key == "channel-1"
    assert create.projection == {
        "interaction_type": "shortcut",
        "guild_id": "guild-1",
        "channel_id": "channel-1",
        "discord_interaction_type": "2",
    }
    assert principal.provider is ExternalChannelProvider.DISCORD
    assert principal.provider_tenant_id == "guild-1"
    assert principal.provider_user_id == "user-1"
    persisted = repr((create, principal, result))
    assert "interaction-token" not in persisted
    assert "private command content" not in persisted
    assert "attachment-1" not in persisted


@pytest.mark.asyncio
async def test_ping_skips_durable_interaction_admission() -> None:
    """Discord endpoint PING authenticates but has no canonical interaction record."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(private_key.public_key().public_bytes_raw().hex()),
        admission=admission,
    )
    body = json.dumps(
        {"id": "ping-1", "type": 1, "application_id": "app-1"},
        separators=(",", ":"),
    ).encode()
    timestamp, signature = _signature(private_key, body)

    result = await service.handle(
        selector="opaque-selector",
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        received_at=_NOW,
    )

    assert result.ping is True
    assert result.admission is None
    assert admission.inputs == []


@pytest.mark.asyncio
async def test_unsupported_or_cross_scope_interactions_fail_before_admission() -> None:
    """Unsupported types and cross-scope identities cannot create work."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _ = _service(
        configuration=_configuration(private_key.public_key().public_bytes_raw().hex()),
        admission=admission,
    )
    unsupported = _body(interaction_type=99)
    unsupported_timestamp, unsupported_signature = _signature(private_key, unsupported)
    with pytest.raises(DiscordInteractionInvalidPayload, match="not supported"):
        await service.handle(
            selector="opaque-selector",
            raw_body=unsupported,
            timestamp=unsupported_timestamp,
            signature=unsupported_signature,
            received_at=_NOW,
        )
    cross_app = _body(application_id="app-2")
    cross_app_timestamp, cross_app_signature = _signature(private_key, cross_app)
    with pytest.raises(DiscordInteractionUnauthorized):
        await service.handle(
            selector="opaque-selector",
            raw_body=cross_app,
            timestamp=cross_app_timestamp,
            signature=cross_app_signature,
            received_at=_NOW,
        )
    cross_guild = _body(guild_id="guild-2")
    cross_guild_timestamp, cross_guild_signature = _signature(private_key, cross_guild)
    with pytest.raises(DiscordInteractionUnauthorized):
        await service.handle(
            selector="opaque-selector",
            raw_body=cross_guild,
            timestamp=cross_guild_timestamp,
            signature=cross_guild_signature,
            received_at=_NOW,
        )

    assert admission.inputs == []
