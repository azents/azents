"""High-level discord.py Gateway integration."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeGuard

import discord

from azents.services.external_channel.discord_endpoint import (
    discord_interactions_endpoint_matches,
)
from azents.services.external_channel.discord_events import (
    DiscordGatewayMessageEvent,
    project_discord_sdk_gateway_message,
)

DISCORD_GATEWAY_INTENTS = 1 | 512 | 32768

type DiscordMessageChannel = (
    discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel
)
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
        interactions_callback_base_url: str,
        interactions_callback_selector_hash: str,
        connected_bot_user_id: str | None = None,
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
        interactions_callback_base_url: str,
        interactions_callback_selector_hash: str,
        connected_bot_user_id: str | None = None,
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
        self.interactions_callback_base_url = interactions_callback_base_url
        self.interactions_callback_selector_hash = interactions_callback_selector_hash
        self.connected_bot_user_id = connected_bot_user_id
        self.handle_event = handle_event
        self.handle_lifecycle = handle_lifecycle
        self.event_lock = asyncio.Lock()
        self.event_error: Exception | None = None

    async def setup_hook(self) -> None:
        """Reject a logged-in Application whose HTTP callback authority drifted."""
        application = self.application
        endpoint_url = (
            None if application is None else application.interactions_endpoint_url
        )
        if not discord_interactions_endpoint_matches(
            endpoint_url=endpoint_url,
            callback_base_url=self.interactions_callback_base_url,
            selector_hash=self.interactions_callback_selector_hash,
        ):
            raise DiscordGatewayTerminalError("interaction_endpoint_drift")

    async def on_message(self, message: discord.Message) -> None:
        """Admit one typed message-create callback."""
        if message.guild is None or message.guild.id != self.target_guild_id:
            return

        async def emit_message() -> None:
            channel = await self._resolve_guild_channel(message.channel)
            await self.handle_event(
                DiscordGatewayMessageEvent(
                    event_type="message_create",
                    guild_id=str(channel.guild.id),
                    channel_id=str(channel.id),
                    message=project_discord_sdk_gateway_message(
                        message=message,
                        channel=channel,
                        connected_bot_user_id=self.connected_bot_user_id,
                    ),
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
        interactions_callback_base_url: str,
        interactions_callback_selector_hash: str,
        connected_bot_user_id: str | None = None,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        """Let discord.py own discovery, heartbeat, reconnect, and Resume."""
        if not target_guild_id.isdigit():
            raise DiscordGatewayError("Discord Guild identity is invalid.")
        client = _DiscordLibraryClient(
            target_guild_id=int(target_guild_id),
            interactions_callback_base_url=interactions_callback_base_url,
            interactions_callback_selector_hash=(interactions_callback_selector_hash),
            connected_bot_user_id=connected_bot_user_id,
            handle_event=handle_event,
            handle_lifecycle=handle_lifecycle,
        )
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
