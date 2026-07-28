"""Tests for the high-level discord.py Gateway integration boundary."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayClient,
    DiscordGatewayConnectionResult,
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayMessageEvent,
    _DiscordLibraryClient,  # pyright: ignore[reportPrivateUsage]
)


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
    return message


def test_library_client_requests_required_intents() -> None:
    """Only Guild message and message-content events are requested."""
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=AsyncMock(),
    )

    assert client.intents.value == DISCORD_GATEWAY_INTENTS
    assert client.intents.guilds is True
    assert client.intents.guild_messages is True
    assert client.intents.message_content is True
    assert client.intents.members is False


@pytest.mark.asyncio
async def test_message_callback_emits_typed_sdk_event() -> None:
    """The public on_message callback forwards the SDK Message unchanged."""
    handler = AsyncMock()
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=handler,
    )
    channel = _channel()
    message = _message(channel=channel)

    await client.on_message(message)

    await_args = handler.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert isinstance(event, DiscordGatewayMessageEvent)
    assert event.event_type == "message_create"
    assert event.message is message
    assert event.channel is channel
    assert event.deleted_message is None


@pytest.mark.asyncio
async def test_update_callback_fetches_complete_typed_message() -> None:
    """Message updates fetch a complete Message without reading payload.data."""
    handler = AsyncMock()
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=handler,
    )
    channel = _channel()
    message = _message(channel=channel)
    channel.fetch_message = AsyncMock(return_value=message)
    client.get_channel = MagicMock(return_value=channel)
    payload = MagicMock(spec=discord.RawMessageUpdateEvent)
    payload.guild_id = 300
    payload.channel_id = 200
    payload.message_id = 100
    payload.data = MagicMock(side_effect=AssertionError("raw data accessed"))

    await client.on_raw_message_edit(payload)

    channel.fetch_message.assert_awaited_once_with(100)
    await_args = handler.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert event.event_type == "message_update"
    assert event.message is message


@pytest.mark.asyncio
async def test_delete_callback_resolves_channel_through_public_sdk_api() -> None:
    """Cache misses use Client.fetch_channel and retain a typed channel."""
    handler = AsyncMock()
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=handler,
    )
    channel = _channel()
    client.get_channel = MagicMock(return_value=None)
    client.fetch_channel = AsyncMock(return_value=channel)
    payload = MagicMock(spec=discord.RawMessageDeleteEvent)
    payload.guild_id = 300
    payload.channel_id = 200
    payload.message_id = 100

    await client.on_raw_message_delete(payload)

    client.fetch_channel.assert_awaited_once_with(200)
    await_args = handler.await_args
    assert await_args is not None
    event = await_args.args[0]
    assert event.event_type == "message_delete"
    assert event.deleted_message is payload
    assert event.channel is channel


@pytest.mark.asyncio
async def test_cross_guild_callbacks_are_ignored() -> None:
    handler = AsyncMock()
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=handler,
    )

    await client.on_message(_message(guild_id=301))

    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_failure_closes_client_and_is_retained() -> None:
    """Admission failures stop the SDK connection instead of being logged and lost."""
    error = DiscordGatewayError("admission failed")
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=AsyncMock(side_effect=error),
    )
    client.close = AsyncMock()

    await client.on_message(_message())

    assert client.event_error is error
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_typed_message_fetch_failure_closes_client() -> None:
    """SDK resolution failures stop the connection before admission continues."""
    error = RuntimeError("typed message lookup failed")
    channel = _channel()
    channel.fetch_message = AsyncMock(side_effect=error)
    handler = AsyncMock()
    client = _DiscordLibraryClient(
        target_guild_id=300,
        handle_event=handler,
    )
    client.get_channel = MagicMock(return_value=channel)
    client.close = AsyncMock()
    payload = MagicMock(spec=discord.RawMessageUpdateEvent)
    payload.guild_id = 300
    payload.channel_id = 200
    payload.message_id = 100

    await client.on_raw_message_edit(payload)

    assert client.event_error is error
    handler.assert_not_awaited()
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
        started.append((token, reconnect))

    async def close(self: _DiscordLibraryClient) -> None:
        return None

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    result = await DiscordGatewayClient().run_connection(
        bot_token="redacted-token",
        target_guild_id="300",
        handle_event=AsyncMock(),
    )

    assert started == [("redacted-token", True)]
    assert result == DiscordGatewayConnectionResult(
        reconnect=True,
        reason="gateway_client_closed",
    )


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
        return None

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(
        DiscordGatewayError,
        match="typed callback processing failed",
    ) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
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
        return None

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError) as raised:
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
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
        return None

    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayCredentialError):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_runner_rejects_non_numeric_guild_identity() -> None:
    with pytest.raises(DiscordGatewayError, match="Guild identity"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="not-a-snowflake",
            handle_event=AsyncMock(),
        )
