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
    ExternalChannelTrigger,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.admission import ExternalChannelAdmissionService
from azents.services.external_channel.discord_http import DiscordHTTPAdmissionService
from azents.services.external_channel.discord_interaction import (
    DiscordInteractionInvalidPayload,
    DiscordInteractionUnauthorized,
)
from azents.services.external_channel.discord_selector import (
    DiscordSelectorResponseService,
)
from azents.services.external_channel.discord_settings import (
    DiscordSettingsResponseService,
)
from azents.services.external_channel.discord_settings_scope import (
    build_discord_settings_custom_id,
)
from azents.services.external_channel.shortcut_source import (
    ExternalChannelShortcutSourceService,
)
from azents.services.scheduled_task.control import ScheduledTaskProviderControlService

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
            tuple[
                ExternalChannelInteractionCreate,
                ExternalChannelPrincipalCreate,
            ]
        ] = []
        self.claimed_interaction_ids: list[str] = []
        self.finished_interaction_ids: list[str] = []

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
                interaction=SimpleNamespace(
                    id="interaction-row-1",
                    principal_id="principal-1",
                ),
                created=True,
            ),
        )

    async def begin_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        now: datetime.datetime,
    ) -> object:
        del now
        self.claimed_interaction_ids.append(interaction_id)
        return SimpleNamespace(claimed=True)

    async def finish_interaction_provider_mutation(
        self,
        *,
        interaction_id: str,
        status: object,
        error_kind: str | None,
        error_summary: str | None,
    ) -> None:
        del status, error_kind, error_summary
        self.finished_interaction_ids.append(interaction_id)


class _ShortcutSourceDouble:
    """Record materialization without retaining request-local interaction data."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, str, datetime.datetime]] = []

    async def ensure(
        self,
        *,
        shortcut_source_event: object,
        interaction_id: str,
        now: datetime.datetime,
    ) -> object:
        self.calls.append((shortcut_source_event, interaction_id, now))
        return SimpleNamespace(
            selector_interaction=SimpleNamespace(id="interaction-row-1")
        )


class _SelectorResponseDouble:
    """Render a safe static response while recording the trusted scope only."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, datetime.datetime]] = []

    async def initial_response(
        self,
        *,
        selector_interaction_id: str,
        principal_id: str,
        now: datetime.datetime,
    ) -> dict[str, object]:
        self.calls.append((selector_interaction_id, principal_id, now))
        return {
            "type": 4,
            "data": {
                "flags": 64,
                "content": "Select an Agent for this conversation.",
            },
        }

    async def component_response(
        self,
        *,
        custom_id: str,
        selected_route_id: str | None,
        principal_id: str,
        guild_id: str | None,
        channel_id: str | None,
        now: datetime.datetime,
    ) -> object:
        self.calls.append((custom_id, principal_id, now))
        return SimpleNamespace(
            response={
                "type": 7,
                "data": {
                    "content": (
                        "Agent selected."
                        if selected_route_id is not None
                        else "Select an Agent."
                    ),
                    "components": [],
                },
            },
            control_plan="delivery-1",
            connection_id="connection-1",
        )


class _SettingsResponseDouble:
    """Provide deterministic settings rendering without provider I/O."""

    def __init__(self, *, cleanup_plans: tuple[str, ...] = ()) -> None:
        self.config = SimpleNamespace(
            auth=SimpleNamespace(jwt=SimpleNamespace(secret_key="settings-secret"))
        )
        self.cleanup_plans = cleanup_plans
        self.component_calls: list[dict[str, object]] = []

    async def initial_response(self, **_: object) -> object:
        return SimpleNamespace(
            response={"type": 4, "data": {"flags": 64, "content": "Settings."}},
            cleanup_plans=(),
        )

    async def component_response(self, **kwargs: object) -> object:
        self.component_calls.append(kwargs)
        return SimpleNamespace(
            response={"type": 7, "data": {"content": "Saved.", "components": []}},
            cleanup_plans=self.cleanup_plans,
        )


def _configuration(
    public_key: str,
    *,
    app_mode: ExternalChannelAppMode = ExternalChannelAppMode.SINGLE,
) -> ExternalChannelConnectionConfiguration:
    return ExternalChannelConnectionConfiguration(
        id="connection-1",
        workspace_id="workspace-1",
        provider=ExternalChannelProvider.DISCORD,
        transport=ExternalChannelTransport.HTTP,
        ingress_profile=ExternalChannelIngressProfile.DISCORD_GATEWAY_HTTP,
        configuration_generation=2,
        status=ExternalChannelConnectionStatus.ACTIVE,
        app_mode=app_mode,
        provider_app_id="app-1",
        provider_tenant_id="guild-1",
        provider_bot_user_id=None,
        http_callback_selector_hash="unused",
        encrypted_credentials="ciphertext",
        capabilities={
            "interaction_public_key": public_key,
            "discord_command_set": {
                "schema_version": 1,
                "command_ids": {
                    "message_action": "100",
                    "azents_settings": "101",
                    "conversation_settings": "102",
                },
            },
        },
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
    cleanup_plans: tuple[str, ...] = (),
) -> tuple[DiscordHTTPAdmissionService, _RepositoryDouble, _ShortcutSourceDouble]:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, object())

    repository = _RepositoryDouble(configuration)
    shortcut_source = _ShortcutSourceDouble()
    selector_response = _SelectorResponseDouble()
    settings_response = _SettingsResponseDouble(cleanup_plans=cleanup_plans)
    return (
        DiscordHTTPAdmissionService(
            session_manager=cast(SessionManager[AsyncSession], session_manager),
            repository=cast(ExternalChannelRepository, repository),
            admission_service=cast(ExternalChannelAdmissionService, admission),
            shortcut_source_service=cast(
                ExternalChannelShortcutSourceService,
                shortcut_source,
            ),
            selector_response_service=cast(
                DiscordSelectorResponseService,
                selector_response,
            ),
            settings_response_service=cast(
                DiscordSettingsResponseService,
                settings_response,
            ),
            scheduled_task_control=cast(
                ScheduledTaskProviderControlService,
                SimpleNamespace(),
            ),
        ),
        repository,
        shortcut_source,
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
            "channel": {"id": "channel-1", "type": 0},
            "member": {"user": {"id": "user-1"}},
            "token": "interaction-token-must-not-persist",
            "data": {
                "id": "101",
                "name": "azents",
                "type": 1,
                "content": "private command content",
                "attachments": [{"id": "attachment-1"}],
            },
        },
        separators=(",", ":"),
    ).encode()


def _signature(private_key: Ed25519PrivateKey, body: bytes) -> tuple[str, str]:
    timestamp = str(int(_NOW.timestamp()))
    return timestamp, private_key.sign(timestamp.encode() + body).hex()


def _message_command_body() -> bytes:
    """Build one selected-message command with deliberately sensitive raw fields."""
    return json.dumps(
        {
            "id": "discord-interaction-1",
            "type": 2,
            "application_id": "app-1",
            "guild_id": "guild-1",
            "channel_id": "channel-1",
            "channel": {"id": "channel-1", "type": 0},
            "member": {"user": {"id": "user-1"}},
            "token": "interaction-token-must-not-persist",
            "data": {
                "id": "100",
                "type": 3,
                "name": "Ask an Azents Agent",
                "target_id": "100",
                "resolved": {
                    "messages": {
                        "100": {
                            "id": "100",
                            "channel_id": "channel-1",
                            "content": "Selected source content.",
                            "timestamp": "2026-07-26T00:00:00+00:00",
                            "author": {
                                "id": "user-2",
                                "avatar": "https://cdn.discordapp.com/private",
                            },
                            "attachments": [
                                {
                                    "id": "attachment-1",
                                    "filename": "report.pdf",
                                    "size": 3,
                                    "url": "https://cdn.discordapp.com/private",
                                    "proxy_url": "https://media.discordapp.net/private",
                                }
                            ],
                        }
                    }
                },
            },
        },
        separators=(",", ":"),
    ).encode()


def _selector_component_body() -> bytes:
    """Build a transient component callback with an opaque selector scope."""
    return json.dumps(
        {
            "id": "discord-component-1",
            "type": 3,
            "application_id": "app-1",
            "guild_id": "guild-1",
            "channel_id": "channel-1",
            "channel": {"id": "channel-1", "type": 0},
            "member": {"user": {"id": "user-1"}},
            "token": "interaction-token-must-not-persist",
            "data": {
                "custom_id": "azents-selector:select:admission-1:0:signature",
                "values": ["route-1"],
            },
        },
        separators=(",", ":"),
    ).encode()


def _settings_component_body() -> bytes:
    """Build one signed settings component callback."""
    custom_id = build_discord_settings_custom_id(
        secret="settings-secret",
        action="open",
        origin_interaction_id="origin-interaction-1",
    )
    return json.dumps(
        {
            "id": "discord-settings-component-1",
            "type": 3,
            "application_id": "app-1",
            "guild_id": "guild-1",
            "channel_id": "channel-1",
            "channel": {"id": "channel-1", "type": 0},
            "member": {"user": {"id": "user-1"}},
            "data": {"custom_id": custom_id},
        },
        separators=(",", ":"),
    ).encode()


@pytest.mark.asyncio
async def test_signed_interaction_admission_redacts_sensitive_input() -> None:
    """A verified Guild interaction commits provenance before acknowledgement."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, repository, _ = _service(
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
        "provider_parent_channel_id": "channel-1",
        "discord_interaction_type": "2",
        "command_role": "azents_settings",
    }
    assert principal.provider is ExternalChannelProvider.DISCORD
    assert principal.provider_tenant_id == "guild-1"
    assert principal.provider_user_id == "user-1"
    assert admission.finished_interaction_ids == ["interaction-row-1"]
    persisted = repr((create, principal, result))
    assert "interaction-token" not in persisted
    assert "private command content" not in persisted
    assert "attachment-1" not in persisted


@pytest.mark.asyncio
async def test_message_command_materializes_safe_source_before_claim() -> None:
    """The selected source becomes canonical before the transient selector claim."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _, shortcut_source = _service(
        configuration=_configuration(
            private_key.public_key().public_bytes_raw().hex(),
            app_mode=ExternalChannelAppMode.MULTI,
        ),
        admission=admission,
    )
    body = _message_command_body()
    timestamp, signature = _signature(private_key, body)

    result = await service.handle(
        selector="opaque-selector",
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        received_at=_NOW,
    )

    create, _ = admission.inputs[0]
    assert create.projection["command_kind"] == "message_command"
    assert create.projection["source_message_id"] == "100"
    assert len(shortcut_source.calls) == 1
    source_event = shortcut_source.calls[0][0]
    assert isinstance(source_event, ExternalChannelTrigger)
    assert source_event.provider_event_id == (
        "discord-interaction-source:discord-interaction-1:100"
    )
    assert source_event.envelope["message"]["content"] == "Selected source content."
    serialized = repr((create, source_event))
    assert "interaction-token" not in serialized
    assert "cdn.discordapp.com" not in serialized
    assert "media.discordapp.net" not in serialized
    assert shortcut_source.calls[0][0] is source_event
    assert admission.claimed_interaction_ids == ["interaction-row-1"]
    assert admission.finished_interaction_ids == ["interaction-row-1"]
    assert result.response == {
        "type": 4,
        "data": {
            "flags": 64,
            "content": "Select an Agent for this conversation.",
        },
    }


@pytest.mark.asyncio
async def test_selector_component_keeps_scope_and_route_request_local() -> None:
    """A component delegates opaque scope without storing selector or route input."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _, _ = _service(
        configuration=_configuration(private_key.public_key().public_bytes_raw().hex()),
        admission=admission,
    )
    body = _selector_component_body()
    timestamp, signature = _signature(private_key, body)

    result = await service.handle(
        selector="opaque-selector",
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        received_at=_NOW,
    )

    create, _ = admission.inputs[0]
    assert create.projection == {
        "interaction_type": "block_action",
        "guild_id": "guild-1",
        "channel_id": "channel-1",
        "provider_parent_channel_id": "channel-1",
        "discord_interaction_type": "3",
    }
    assert admission.claimed_interaction_ids == ["interaction-row-1"]
    assert admission.finished_interaction_ids == ["interaction-row-1"]
    assert result.response == {
        "type": 7,
        "data": {"content": "Agent selected.", "components": []},
    }
    assert "route-1" not in repr(create)
    assert "interaction-token" not in repr((create, result))


@pytest.mark.asyncio
async def test_settings_component_preserves_every_committed_cleanup_intent() -> None:
    """Return all cleanup deliveries without raising after the settings commit."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _, _ = _service(
        configuration=_configuration(private_key.public_key().public_bytes_raw().hex()),
        admission=admission,
        cleanup_plans=("presence-delete-1", "progress-delete-1"),
    )
    body = _settings_component_body()
    timestamp, signature = _signature(private_key, body)

    result = await service.handle(
        selector="opaque-selector",
        raw_body=body,
        timestamp=timestamp,
        signature=signature,
        received_at=_NOW,
    )

    assert result.response == {
        "type": 7,
        "data": {"content": "Saved.", "components": []},
    }
    assert result.control_plans == (
        "presence-delete-1",
        "progress-delete-1",
    )
    assert result.control_delivery_connection_id == "connection-1"
    assert admission.finished_interaction_ids == ["interaction-row-1"]
    settings_response = cast(
        _SettingsResponseDouble,
        service.settings_response_service,
    )
    assert settings_response.component_calls[0]["interaction_id"] == "interaction-row-1"


@pytest.mark.asyncio
async def test_ping_skips_durable_interaction_admission() -> None:
    """Discord endpoint PING authenticates but has no canonical interaction record."""
    private_key = Ed25519PrivateKey.generate()
    admission = _AdmissionDouble()
    service, _, _ = _service(
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
    service, _, _ = _service(
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
