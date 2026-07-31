"""Tests for the high-level discord.py Gateway integration boundary."""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.gateway import DiscordWebSocket
from discord.http import Route

from azents.services.external_channel.discord_gateway import (
    DISCORD_GATEWAY_INTENTS,
    DiscordGatewayClient,
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayMessageEvent,
    DiscordGatewayTerminalError,
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


def _library_client(
    *,
    handle_event: AsyncMock | None = None,
    handle_lifecycle: AsyncMock | None = None,
) -> _DiscordLibraryClient:
    return _DiscordLibraryClient(
        target_guild_id=300,
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
    assert event.message is message
    assert event.channel is channel


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
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert started == [("redacted-token", True)]


@pytest.mark.asyncio
async def test_runner_uses_and_restores_explicit_testenv_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep deterministic I/O isolated and restore private SDK globals afterward."""
    observed_endpoints: list[tuple[str, str]] = []

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        observed_endpoints.append((Route.BASE, str(DiscordWebSocket.DEFAULT_GATEWAY)))

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_API_BASE_URL",
        "http://discord-fake:8085/api/v10",
    )
    monkeypatch.setenv(
        "AZ_TESTENV_DISCORD_GATEWAY_URL",
        "ws://discord-fake:8086",
    )
    monkeypatch.setattr(Route, "BASE", "https://original.example/api/v10")
    original_gateway = type(DiscordWebSocket.DEFAULT_GATEWAY)("wss://original.example")
    monkeypatch.setattr(DiscordWebSocket, "DEFAULT_GATEWAY", original_gateway)
    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert observed_endpoints == [
        ("http://discord-fake:8085/api/v10", "ws://discord-fake:8086")
    ]
    assert Route.BASE == "https://original.example/api/v10"
    assert DiscordWebSocket.DEFAULT_GATEWAY is original_gateway


@pytest.mark.asyncio
async def test_runner_does_not_mutate_production_sdk_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without test overrides, production endpoint selection remains SDK-owned."""
    observed_endpoints: list[tuple[str, object]] = []

    async def start(
        self: _DiscordLibraryClient,
        token: str,
        *,
        reconnect: bool = True,
    ) -> None:
        del self, token, reconnect
        observed_endpoints.append((Route.BASE, DiscordWebSocket.DEFAULT_GATEWAY))

    async def close(self: _DiscordLibraryClient) -> None:
        del self

    monkeypatch.delenv("AZ_TESTENV_DISCORD_API_BASE_URL", raising=False)
    monkeypatch.delenv("AZ_TESTENV_DISCORD_GATEWAY_URL", raising=False)
    monkeypatch.setattr(Route, "BASE", "https://sdk-owned.example/api/v10")
    sdk_gateway = type(DiscordWebSocket.DEFAULT_GATEWAY)("wss://sdk-owned.example")
    monkeypatch.setattr(DiscordWebSocket, "DEFAULT_GATEWAY", sdk_gateway)
    monkeypatch.setattr(_DiscordLibraryClient, "start", start)
    monkeypatch.setattr(_DiscordLibraryClient, "close", close)

    with pytest.raises(DiscordGatewayError, match="stopped unexpectedly"):
        await DiscordGatewayClient().run_connection(
            bot_token="redacted-token",
            target_guild_id="300",
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )

    assert observed_endpoints == [("https://sdk-owned.example/api/v10", sdk_gateway)]
    assert Route.BASE == "https://sdk-owned.example/api/v10"
    assert DiscordWebSocket.DEFAULT_GATEWAY is sdk_gateway


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
            handle_event=AsyncMock(),
            handle_lifecycle=AsyncMock(),
        )
