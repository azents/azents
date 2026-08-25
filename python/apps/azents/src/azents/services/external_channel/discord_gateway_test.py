"""Tests for the high-level discord.py Gateway integration boundary."""

import hashlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from azents.services.external_channel.discord_events import DiscordGatewayMessageEvent
from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayClient,
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayTerminalError,
    _DiscordLibraryClient,
)

_CALLBACK_BASE_URL = "https://callbacks.example/"
_CALLBACK_SELECTOR = "opaque-selector"
_CALLBACK_SELECTOR_HASH = hashlib.sha256(_CALLBACK_SELECTOR.encode()).hexdigest()


def _guild(*, guild_id: int = 300) -> MagicMock:
    guild = MagicMock(spec=discord.Guild)
    guild.id = guild_id
    return guild


def _channel(*, channel_id: int = 200, guild_id: int = 300) -> MagicMock:
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.guild = _guild(guild_id=guild_id)
    channel.name = "general"
    return channel


def _message(
    *,
    channel: MagicMock | None = None,
    guild_id: int = 300,
) -> MagicMock:
    resolved_channel = channel or _channel(guild_id=guild_id)
    message = MagicMock(spec=discord.Message)
    message.id = 100
    message.guild = resolved_channel.guild
    message.channel = resolved_channel
    message.content = "hello"
    message.created_at = discord.utils.utcnow()
    message.author = MagicMock(spec=discord.User)
    message.author.id = 400
    message.author.name = "participant"
    message.author.global_name = None
    message.author.bot = False
    message.author.system = False
    message.mentions = []
    message.role_mentions = []
    message.attachments = []
    message.embeds = []
    return message


def _library_client(
    *,
    handle_event: AsyncMock | None = None,
    handle_lifecycle: AsyncMock | None = None,
) -> _DiscordLibraryClient:
    return _DiscordLibraryClient(
        target_guild_id=300,
        interactions_callback_base_url=_CALLBACK_BASE_URL,
        interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
        connected_bot_user_id="900",
        handle_event=handle_event or AsyncMock(),
        handle_lifecycle=handle_lifecycle or AsyncMock(),
    )


def test_library_client_requests_required_intents() -> None:
    """Only Guild message and message-content events are requested."""
    client = _library_client()

    assert client.intents.value == DISCORD_GATEWAY_INTENTS
    assert client.intents.guilds is True
    assert client.intents.guild_messages is True
    assert client.intents.message_content is True
    assert client.intents.members is False


@pytest.mark.asyncio
async def test_setup_hook_accepts_exact_interaction_endpoint() -> None:
    """Gateway login accepts only the current callback selector authority."""
    client = _library_client()
    client._application = cast(
        discord.AppInfo,
        SimpleNamespace(
            interactions_endpoint_url=(
                f"{_CALLBACK_BASE_URL}external-channel/v1/discord/interactions/"
                f"{_CALLBACK_SELECTOR}"
            )
        ),
    )

    await client.setup_hook()


@pytest.mark.asyncio
async def test_setup_hook_rejects_missing_interaction_endpoint() -> None:
    """Provider callback removal becomes a terminal reconnect requirement."""
    client = _library_client()
    client._application = cast(
        discord.AppInfo,
        SimpleNamespace(interactions_endpoint_url=None),
    )

    with pytest.raises(DiscordGatewayTerminalError) as raised:
        await client.setup_hook()

    assert raised.value.reason == "interaction_endpoint_drift"


@pytest.mark.asyncio
async def test_message_callback_emits_typed_sdk_event() -> None:
    """The public on_message callback forwards the SDK Message unchanged."""
    handler = AsyncMock()
    client = _library_client(handle_event=handler)
    channel = _channel()
    message = _message(channel=channel)

    await client.on_message(message)

    await_args = handler.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert isinstance(event, DiscordGatewayMessageEvent)
    assert event.event_type == "message_create"
    assert event.guild_id == "300"
    assert event.channel_id == "200"
    assert event.message["id"] == "100"
    assert event.message["content"] == "hello"


@pytest.mark.asyncio
async def test_lifecycle_callbacks_emit_typed_sdk_state_in_order() -> None:
    """Ready, disconnect, and Resume use the serialized SDK callback boundary."""
    lifecycle = AsyncMock()
    client = _library_client(handle_lifecycle=lifecycle)

    await client.on_ready()
    await client.on_disconnect()
    await client.on_resumed()

    assert [call.args[0] for call in lifecycle.await_args_list] == [
        "ready",
        "disconnected",
        "resumed",
    ]


@pytest.mark.asyncio
async def test_cross_guild_callbacks_are_ignored() -> None:
    handler = AsyncMock()
    client = _library_client(handle_event=handler)

    await client.on_message(_message(guild_id=301))

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_closes_client_and_is_retained() -> None:
    """Admission failures stop the SDK connection instead of being logged and lost."""
    error = DiscordGatewayError("admission failed")
    client = _library_client(handle_event=AsyncMock(side_effect=error))
    client.close = AsyncMock()

    await client.on_message(_message())

    assert client.event_error is error
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifecycle_failure_closes_client_and_is_retained() -> None:
    """Lease-fenced health failures stop the SDK lifecycle."""
    error = DiscordGatewayError("lease lost")
    client = _library_client(handle_lifecycle=AsyncMock(side_effect=error))
    client.close = AsyncMock()

    await client.on_ready()

    assert client.event_error is error
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_uses_public_start_with_sdk_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery, heartbeat, reconnect, and Resume stay inside Client.start."""
    started: list[tuple[str, bool]] = []

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self
        started.append((token, reconnect))

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert started == [("redacted-token", True)]


@pytest.mark.asyncio
async def test_runner_wraps_uncontrolled_callback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typed callback failures enter the manager's controlled gap path."""
    failure = RuntimeError("private failure detail")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        self.event_error = failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(
        DiscordGatewayError,
        match="typed callback processing failed",
    ) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert raised.value.__cause__ is failure


@pytest.mark.asyncio
async def test_runner_preserves_controlled_callback_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lease and admission errors retain their controlled subtype."""
    failure = DiscordGatewayError("controlled failure")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del token, reconnect
        self.event_error = failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert raised.value is failure


@pytest.mark.asyncio
async def test_runner_classifies_public_login_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        raise discord.LoginFailure("rejected")

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayCredentialError):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_runner_preserves_terminal_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = DiscordGatewayTerminalError("gateway_connection_rejected")

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        raise failure

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayTerminalError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert raised.value.reason == "gateway_connection_rejected"


@pytest.mark.asyncio
async def test_runner_rejects_non_numeric_guild_identity() -> None:
    with pytest.raises(DiscordGatewayError, match="Guild identity"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="not-a-snowflake",
            interactions_callback_base_url=_CALLBACK_BASE_URL,
            interactions_callback_selector_hash=_CALLBACK_SELECTOR_HASH,
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )
