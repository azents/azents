"""High-level discord.py Gateway integration."""

import asyncio
import contextlib
import dataclasses
import threading
from collections.abc import Awaitable, Callable, Iterator
from typing import Literal, Protocol, TypeGuard

import discord
from discord.gateway import DiscordWebSocket
from discord.http import Route
from yarl import URL

from azents.services.external_channel.discord_endpoint import (
    discord_test_api_base_url,
    discord_test_gateway_url,
)

DISCORD_GATEWAY_INTENTS = 1 | 512 | 32768

type DiscordMessageChannel = (
    discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel
)
type DiscordGatewayMessageEventType = Literal["message_create"]
type DiscordGatewayLifecycleState = Literal["disconnected", "ready", "resumed"]


class DiscordGatewayError(RuntimeError):
    """Base class for controlled Discord library failures."""


class DiscordGatewayCredentialError(DiscordGatewayError):
    """Discord rejected the configured Bot credential."""


class DiscordGatewayIntentsError(DiscordGatewayError):
    """Discord rejected the Gateway intents required by the connection."""


class DiscordGatewayTerminalError(DiscordGatewayError):
    """The SDK rejected reconnecting the current Gateway configuration."""

    def __init__(self, reason: str) -> None:
        super().__init__("Discord Gateway requires operator reconnection.")
        self.reason = reason


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
type DiscordGatewayLifecycleHandler = Callable[
    [DiscordGatewayLifecycleState],
    Awaitable[None],
]
type DiscordGatewayCallback = Callable[[], Awaitable[None]]


class DiscordGatewayRunner(Protocol):
    """High-level discord.py client consumed by the lease manager."""

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        """Run until the SDK client closes or a terminal failure occurs."""
        ...


class _DiscordLibraryClient(discord.Client):
    """Translate high-level discord.py callbacks into serialized typed events."""

    def __init__(
        self,
        *,
        target_guild_id: int,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
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
        self.handle_lifecycle = handle_lifecycle
        self.event_lock = asyncio.Lock()
        self.event_error: Exception | None = None

    async def on_message(self, message: discord.Message) -> None:
        """Admit one typed message-create callback."""
        if message.guild is None or message.guild.id != self.target_guild_id:
            return

        async def emit_message() -> None:
            channel = await self._resolve_guild_channel(message.channel)
            await self.handle_event(
                DiscordGatewayMessageEvent(
                    event_type="message_create",
                    channel=channel,
                    message=message,
                )
            )

        await self._emit(emit_message)

    async def on_disconnect(self) -> None:
        """Project one SDK disconnect lifecycle callback."""
        await self._emit(lambda: self.handle_lifecycle("disconnected"))

    async def on_ready(self) -> None:
        """Project one SDK ready lifecycle callback."""
        await self._emit(lambda: self.handle_lifecycle("ready"))

    async def on_resumed(self) -> None:
        """Project one SDK resumed lifecycle callback."""
        await self._emit(lambda: self.handle_lifecycle("resumed"))

    async def _emit(self, callback: DiscordGatewayCallback) -> None:
        """Serialize typed SDK callbacks and close on any failure."""
        async with self.event_lock:
            if self.event_error is not None:
                return
            try:
                await callback()
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
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        """Let discord.py own discovery, heartbeat, reconnect, and Resume."""
        if not target_guild_id.isdigit():
            raise DiscordGatewayError("Discord Guild identity is invalid.")
        client = _DiscordLibraryClient(
            target_guild_id=int(target_guild_id),
            handle_event=handle_event,
            handle_lifecycle=handle_lifecycle,
        )
        with _discord_test_endpoint_override():
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
                raise DiscordGatewayTerminalError(
                    _closed_connection_reason(error)
                ) from error
            except (
                discord.GatewayNotFound,
                discord.HTTPException,
                discord.InvalidData,
                OSError,
            ) as error:
                raise DiscordGatewayError(
                    "Discord Gateway transport is unavailable."
                ) from error
            finally:
                if not client.is_closed():
                    await client.close()
        if client.event_error is not None:
            if isinstance(client.event_error, DiscordGatewayError):
                raise client.event_error
            raise DiscordGatewayError(
                "Discord typed callback processing failed."
            ) from client.event_error
        raise DiscordGatewayError("Discord Gateway client stopped unexpectedly.")


@dataclasses.dataclass
class _DiscordTestEndpointState:
    """Reference-counted deterministic endpoint state."""

    lock: threading.Lock = dataclasses.field(default_factory=threading.Lock)
    depth: int = 0
    originals: tuple[str, URL] | None = None
    values: tuple[str | None, str | None] | None = None


_test_endpoint_state = _DiscordTestEndpointState()


@contextlib.contextmanager
def _discord_test_endpoint_override() -> Iterator[None]:
    """Temporarily apply explicit deterministic endpoints with reference counting."""
    api_base_url = discord_test_api_base_url()
    gateway_url = discord_test_gateway_url()
    if api_base_url is None and gateway_url is None:
        yield
        return

    configured = (api_base_url, gateway_url)
    state = _test_endpoint_state
    with state.lock:
        if state.depth == 0:
            state.originals = (Route.BASE, DiscordWebSocket.DEFAULT_GATEWAY)
            state.values = configured
            if api_base_url is not None:
                Route.BASE = api_base_url
            if gateway_url is not None:
                DiscordWebSocket.DEFAULT_GATEWAY = type(
                    DiscordWebSocket.DEFAULT_GATEWAY
                )(gateway_url)
        elif state.values != configured:
            raise DiscordGatewayError(
                "Discord deterministic endpoint configuration changed while active."
            )
        state.depth += 1
    try:
        yield
    finally:
        with state.lock:
            state.depth -= 1
            if state.depth == 0:
                assert state.originals is not None
                Route.BASE, DiscordWebSocket.DEFAULT_GATEWAY = state.originals
                state.originals = None
                state.values = None


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


def _closed_connection_reason(error: discord.ConnectionClosed) -> str:
    """Classify one SDK-declared non-recoverable close without provider details."""
    terminal_reasons = {
        4004: "gateway_credentials_rejected",
        4013: "intents_invalid",
        4014: "intents_disallowed",
    }
    return terminal_reasons.get(error.code, "gateway_connection_rejected")
