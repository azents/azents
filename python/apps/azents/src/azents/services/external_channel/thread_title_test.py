"""One-shot External Channel Discord thread-title tests."""

import asyncio
import datetime
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest

from azents.core.enums import (
    EventKind,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceType,
)
from azents.engine.events.types import Event, ExternalChannelMessagePayload
from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordDeliveryResult,
    DiscordThreadTitleReadResult,
)
from azents.services.external_channel.thread_title import (
    ExternalChannelThreadTitleService,
)


class _DiscordClient:
    def __init__(self, *, current_name: str, read_status: str = "present") -> None:
        self.current_name = current_name
        self.read_status = read_status
        self.read_calls: list[dict[str, str]] = []
        self.update_calls: list[dict[str, str]] = []

    async def read_thread_title(self, **kwargs: str) -> DiscordThreadTitleReadResult:
        self.read_calls.append(kwargs)
        return DiscordThreadTitleReadResult(
            status=cast(Any, self.read_status),
            name=self.current_name if self.read_status == "present" else None,
            error_kind=None,
        )

    async def update_thread_title(self, **kwargs: str) -> DiscordDeliveryResult:
        self.update_calls.append(kwargs)
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key="discord-thread:444",
            error_kind=None,
            error_summary=None,
        )


def _service(client: _DiscordClient) -> ExternalChannelThreadTitleService:
    return ExternalChannelThreadTitleService(
        session_manager=cast(Any, object()),
        external_channel_repository=cast(Any, object()),
        agent_repository=cast(Any, object()),
        agent_session_repository=cast(Any, object()),
        credentials_codec=cast(Any, object()),
        discord_client=cast(DiscordDeliveryClient, client),
    )


def _event(
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.DISCORD,
    authorization: Literal["context_only", "authorized_invocation"] = (
        "authorized_invocation"
    ),
) -> Event:
    return Event(
        id="1" * 32,
        session_id="session-1",
        kind=EventKind.EXTERNAL_CHANNEL_MESSAGE,
        payload=ExternalChannelMessagePayload(
            provider=provider,
            provider_tenant_id="111",
            resource_id="resource-1",
            resource_label="incident",
            resource_type=ExternalChannelResourceType.THREAD,
            binding_id="binding-1",
            invocation_batch_id="batch-1",
            external_message_id="message-1",
            projection_root_id="external-channel:binding-1:message-1",
            provider_message_key="message-1",
            provider_position="1",
            principal_id="principal-1",
            provider_user_id="user-1",
            sender_display_name="Participant",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            authorization=authorization,
            body="Investigate the incident",
            attachment_metadata={},
            provider_created_at=datetime.datetime.now(datetime.UTC),
            provider_updated_at=None,
            original_url=None,
            truncated_context_message_count=0,
            truncated_context_size=0,
        ),
        created_at=datetime.datetime.now(datetime.UTC),
    )


@pytest.mark.parametrize(
    ("current_name", "expected_updates"),
    [
        ("Test agent", 1),
        ("Incident response", 0),
        ("Human-owned incident", 0),
    ],
)
async def test_projection_conditionally_updates_once(
    monkeypatch: pytest.MonkeyPatch,
    current_name: str,
    expected_updates: int,
) -> None:
    """Only the retained provisional title permits one adjacent update."""
    client = _DiscordClient(current_name=current_name)
    service = _service(client)

    async def load_authority(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="444",
            provisional_title="Test agent",
        )

    monkeypatch.setattr(service, "_load_authority", load_authority)

    await service.project_generated_title(
        session_id="session-1",
        event=_event(),
        title="Incident response",
    )

    assert client.read_calls == [
        {
            "bot_token": "discord-secret",
            "guild_id": "111",
            "channel_id": "444",
        }
    ]
    assert len(client.update_calls) == expected_updates
    if expected_updates:
        assert client.update_calls[0] == {
            "bot_token": "discord-secret",
            "guild_id": "111",
            "channel_id": "444",
            "name": "Incident response",
        }


async def test_projection_stops_without_provider_io_when_authority_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle or ownership loss prevents both provider read and update."""
    client = _DiscordClient(current_name="Test agent")
    service = _service(client)

    async def load_authority(**kwargs: object) -> None:
        del kwargs
        return None

    monkeypatch.setattr(service, "_load_authority", load_authority)

    await service.project_generated_title(
        session_id="session-1",
        event=_event(),
        title="Incident response",
    )

    assert client.read_calls == []
    assert client.update_calls == []


@pytest.mark.parametrize("read_status", ["missing", "failed", "unknown"])
async def test_projection_read_failure_ends_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    read_status: Literal["missing", "failed", "unknown"],
) -> None:
    """One non-present provider read ends the one-shot operation."""
    client = _DiscordClient(
        current_name="Test agent",
        read_status=read_status,
    )
    service = _service(client)

    async def load_authority(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="444",
            provisional_title="Test agent",
        )

    monkeypatch.setattr(service, "_load_authority", load_authority)

    await service.project_generated_title(
        session_id="session-1",
        event=_event(),
        title="Incident response",
    )

    assert len(client.read_calls) == 1
    assert client.update_calls == []


async def test_projection_update_failure_ends_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failed provider update does not issue another read or update."""
    client = _DiscordClient(current_name="Test agent")
    service = _service(client)

    async def load_authority(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="444",
            provisional_title="Test agent",
        )

    async def failed_update(**kwargs: str) -> DiscordDeliveryResult:
        client.update_calls.append(kwargs)
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="permission_denied",
            error_summary="Discord rejected the update.",
        )

    monkeypatch.setattr(service, "_load_authority", load_authority)
    monkeypatch.setattr(client, "update_thread_title", failed_update)

    await service.project_generated_title(
        session_id="session-1",
        event=_event(),
        title="Incident response",
    )

    assert len(client.read_calls) == 1
    assert len(client.update_calls) == 1


@pytest.mark.parametrize("cancel_at", ["read", "update"])
async def test_projection_cancellation_propagates_without_retry(
    monkeypatch: pytest.MonkeyPatch,
    cancel_at: Literal["read", "update"],
) -> None:
    """Cancellation ends the current one-shot provider operation."""
    client = _DiscordClient(current_name="Test agent")
    service = _service(client)

    async def load_authority(**kwargs: object) -> object:
        del kwargs
        return SimpleNamespace(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="444",
            provisional_title="Test agent",
        )

    async def cancelled_read(**kwargs: str) -> DiscordThreadTitleReadResult:
        client.read_calls.append(kwargs)
        raise asyncio.CancelledError

    async def cancelled_update(**kwargs: str) -> DiscordDeliveryResult:
        client.update_calls.append(kwargs)
        raise asyncio.CancelledError

    monkeypatch.setattr(service, "_load_authority", load_authority)
    if cancel_at == "read":
        monkeypatch.setattr(client, "read_thread_title", cancelled_read)
    else:
        monkeypatch.setattr(client, "update_thread_title", cancelled_update)

    with pytest.raises(asyncio.CancelledError):
        await service.project_generated_title(
            session_id="session-1",
            event=_event(),
            title="Incident response",
        )

    assert len(client.read_calls) == 1
    assert len(client.update_calls) == (1 if cancel_at == "update" else 0)


@pytest.mark.parametrize(
    "event",
    [
        _event(provider=ExternalChannelProvider.SLACK),
        _event(authorization="context_only"),
    ],
)
async def test_projection_ignores_noneligible_external_events(
    monkeypatch: pytest.MonkeyPatch,
    event: Event,
) -> None:
    """Slack and context-only Events never start Discord title projection."""
    client = _DiscordClient(current_name="Test agent")
    service = _service(client)

    async def unexpected_authority(**kwargs: object) -> object:
        del kwargs
        raise AssertionError("authority should not be loaded")

    monkeypatch.setattr(service, "_load_authority", unexpected_authority)

    await service.project_generated_title(
        session_id="session-1",
        event=event,
        title="Incident response",
    )

    assert client.read_calls == []
    assert client.update_calls == []
