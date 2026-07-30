"""High-level discord.py Gateway integration."""

import asyncio
import dataclasses
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeGuard

import discord
from discord.gateway import DiscordWebSocket
from discord.http import Route

from azents.services.external_channel.discord_endpoint import (
    discord_api_base_url,
    discord_gateway_url,
)

DISCORD_GATEWAY_INTENTS = 1 | 512 | 32768

type DiscordMessageChannel = (
    discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel
)
type DiscordGatewayMessageEventType = Literal["message_create"]


class DiscordGatewayError(RuntimeError):
    """Base class for controlled Discord library failures."""


class DiscordGatewayCredentialError(DiscordGatewayError):
    """Discord rejected the configured Bot credential."""


class DiscordGatewayIntentsError(DiscordGatewayError):
    """Discord rejected the Gateway intents required by the connection."""


@dataclasses.dataclass(frozen=True)
class DiscordGatewayConnectionResult:
    """Reason one high-level discord.py client stopped."""

    reconnect: bool
    reason: str


@dataclasses.dataclass(frozen=True)
class DiscordGatewayMessageEvent:
    """One typed discord.py message-create event."""

    event_type: DiscordGatewayMessageEventType
    channel: DiscordMessageChannel
    message: discord.Message | None = None


type DiscordGatewayEventHandler = Callable[
    [DiscordGatewayMessageEvent],
    Awaitable[None],
]
type DiscordGatewayEventFactory = Callable[
    [],
    Awaitable[DiscordGatewayMessageEvent],
]


class DiscordGatewayRunner(Protocol):
    """High-level discord.py client consumed by the lease manager."""

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        handle_event: DiscordGatewayEventHandler,
    ) -> DiscordGatewayConnectionResult:
        """Run until the SDK client closes or a terminal failure occurs."""
        ...


class _DiscordLibraryClient(discord.Client):
    """Translate high-level discord.py callbacks into serialized typed events."""

    def __init__(
        self,
        *,
        target_guild_id: int,
        handle_event: DiscordGatewayEventHandler,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(
            intents=intents,
            member_cache_flags=discord.MemberCacheFlags.none(),
            chunk_guilds_at_startup=False,
        )
        self.target_guild_id = target_guild_id
        self.handle_event = handle_event
        self.event_lock = asyncio.Lock()
        self.event_error: Exception | None = None

    async def on_message(self, message: discord.Message) -> None:
        """Admit one typed message-create callback."""
        if message.guild is None or message.guild.id != self.target_guild_id:
            return

        async def event_factory() -> DiscordGatewayMessageEvent:
            channel = await self._resolve_guild_channel(message.channel)
            return DiscordGatewayMessageEvent(
                event_type="message_create",
                channel=channel,
                message=message,
            )

        await self._emit(event_factory)

    async def _emit(self, event_factory: DiscordGatewayEventFactory) -> None:
        """Serialize typed resolution and admission; close on any failure."""
        async with self.event_lock:
            if self.event_error is not None:
                return
            try:
                event = await event_factory()
                await self.handle_event(event)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.event_error = error
                await self.close()

    async def _resolve_guild_channel(
        self,
        channel: discord.abc.MessageableChannel,
    ) -> DiscordMessageChannel:
        if _is_message_channel(channel):
            return channel
        return await self._resolve_message_channel_id(channel.id)

    async def _resolve_message_channel_id(
        self,
        channel_id: int,
    ) -> DiscordMessageChannel:
        channel = self.get_channel(channel_id)
        if channel is None:
            channel = await self.fetch_channel(channel_id)
        if not _is_message_channel(channel) or channel.guild.id != self.target_guild_id:
            raise discord.InvalidData(
                "Discord channel does not belong to the configured Guild."
            )
        return channel


class DiscordGatewayClient:
    """Run discord.py exclusively through its public high-level client API."""

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        handle_event: DiscordGatewayEventHandler,
    ) -> DiscordGatewayConnectionResult:
        """Let discord.py own discovery, heartbeat, reconnect, and Resume."""
        if not target_guild_id.isdigit():
            raise DiscordGatewayError("Discord Guild identity is invalid.")
        Route.BASE = discord_api_base_url()
        DiscordWebSocket.DEFAULT_GATEWAY = type(DiscordWebSocket.DEFAULT_GATEWAY)(
            discord_gateway_url()
        )
        client = _DiscordLibraryClient(
            target_guild_id=int(target_guild_id),
            handle_event=handle_event,
        )
        result = DiscordGatewayConnectionResult(
            reconnect=True,
            reason="gateway_client_closed",
        )
        try:
            try:
                await client.start(bot_token, reconnect=True)
            except discord.LoginFailure as error:
                raise DiscordGatewayCredentialError(
                    "Discord rejected the configured Bot credential."
                ) from error
            except discord.PrivilegedIntentsRequired as error:
                raise DiscordGatewayIntentsError(
                    "Discord rejected the required Message Content intent."
                ) from error
            except discord.ConnectionClosed as error:
                result = _closed_connection_result(error)
            except (
                discord.GatewayNotFound,
                discord.HTTPException,
                discord.InvalidData,
                OSError,
            ) as error:
                result = DiscordGatewayConnectionResult(
                    reconnect=True,
                    reason=_transport_failure_reason(error),
                )
        finally:
            if not client.is_closed():
                await client.close()
        if client.event_error is not None:
            if isinstance(client.event_error, DiscordGatewayError):
                raise client.event_error
            raise DiscordGatewayError(
                "Discord typed callback processing failed."
            ) from client.event_error
        return result


def _is_message_channel(channel: object) -> TypeGuard[DiscordMessageChannel]:
    return isinstance(
        channel,
        (
            discord.TextChannel,
            discord.Thread,
            discord.VoiceChannel,
            discord.StageChannel,
        ),
    )


def _closed_connection_result(
    error: discord.ConnectionClosed,
) -> DiscordGatewayConnectionResult:
    """Classify public SDK close outcomes for manager lifecycle handling."""
    terminal_reasons = {
        4004: "gateway_credentials_rejected",
        4013: "intents_invalid",
        4014: "intents_disallowed",
    }
    reason = terminal_reasons.get(error.code)
    if reason is not None:
        return DiscordGatewayConnectionResult(reconnect=False, reason=reason)
    return DiscordGatewayConnectionResult(
        reconnect=True,
        reason="connection_closed",
    )


def _transport_failure_reason(
    error: (
        discord.GatewayNotFound | discord.HTTPException | discord.InvalidData | OSError
    ),
) -> str:
    """Classify public SDK failures without exposing provider details."""
    if isinstance(error, discord.HTTPException) and error.status == 429:
        return "gateway_rate_limited"
    cause = error.__cause__
    if isinstance(cause, discord.HTTPException) and cause.status == 429:
        return "gateway_rate_limited"
    return "gateway_transport_unavailable"
