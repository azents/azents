"""High-level discord.py Gateway integration."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol, TypeGuard

import discord

from azents.repos.external_channel.data import DiscordGatewayTypingTarget
from azents.services.external_channel.discord_events import (
    DiscordGatewayMessageEvent,
    project_discord_sdk_gateway_message,
)

DISCORD_GATEWAY_INTENTS = 1 | 512 | 32768
_TYPING_RECONCILE_INTERVAL_SECONDS = 5.0
_TYPING_RENEW_INTERVAL_SECONDS = 8.0
_TYPING_RETRY_INTERVAL_SECONDS = 2.0

logger = logging.getLogger(__name__)

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
type DiscordGatewayTypingTargetLoader = Callable[
    [],
    Awaitable[tuple[DiscordGatewayTypingTarget, ...] | None],
]


class DiscordGatewayRunner(Protocol):
    """High-level discord.py client consumed by the lease manager."""

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        connected_bot_user_id: str | None = None,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
        load_typing_targets: DiscordGatewayTypingTargetLoader,
    ) -> None:
        """Run until the SDK client closes or a terminal failure occurs."""
        ...


class _DiscordLibraryClient(discord.Client):
    """Translate high-level discord.py callbacks into serialized typed events."""

    def __init__(
        self,
        *,
        target_guild_id: int,
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
        self.connected_bot_user_id = connected_bot_user_id
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
        connected_bot_user_id: str | None = None,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
        load_typing_targets: DiscordGatewayTypingTargetLoader,
    ) -> None:
        """Let discord.py own discovery, heartbeat, reconnect, and Resume."""
        if not target_guild_id.isdigit():
            raise DiscordGatewayError("Discord Guild identity is invalid.")

        async def lifecycle(state: DiscordGatewayLifecycleState) -> None:
            await handle_lifecycle(state)
            await typing_runtime.handle_lifecycle(state)

        client = _DiscordLibraryClient(
            target_guild_id=int(target_guild_id),
            connected_bot_user_id=connected_bot_user_id,
            handle_event=handle_event,
            handle_lifecycle=lifecycle,
        )
        typing_runtime = _DiscordGatewayTypingRuntime(
            client=client,
            target_guild_id=target_guild_id,
            load_typing_targets=load_typing_targets,
        )

        typing_task = asyncio.create_task(
            typing_runtime.run(),
            name=f"discord-gateway-typing:{target_guild_id}",
        )
        try:
            await client.start(bot_token, reconnect=True)
        except discord.LoginFailure as error:
            if typing_runtime.error is not None:
                raise typing_runtime.error from error
            raise DiscordGatewayCredentialError(
                "Discord rejected the configured Bot credential."
            ) from error
        except discord.PrivilegedIntentsRequired as error:
            if typing_runtime.error is not None:
                raise typing_runtime.error from error
            raise DiscordGatewayIntentsError(
                "Discord rejected the required Message Content intent."
            ) from error
        except discord.ConnectionClosed as error:
            if typing_runtime.error is not None:
                raise typing_runtime.error from error
            raise DiscordGatewayTerminalError(
                _closed_connection_reason(error)
            ) from error
        except (
            discord.GatewayNotFound,
            discord.HTTPException,
            discord.InvalidData,
            OSError,
        ) as error:
            if typing_runtime.error is not None:
                raise typing_runtime.error from error
            raise DiscordGatewayError(
                "Discord Gateway transport is unavailable."
            ) from error
        finally:
            await typing_runtime.stop(typing_task)
            if not client.is_closed():
                await client.close()
        if client.event_error is not None:
            if isinstance(client.event_error, DiscordGatewayError):
                raise client.event_error
            raise DiscordGatewayError(
                "Discord typed callback processing failed."
            ) from client.event_error
        if typing_runtime.error is not None:
            raise typing_runtime.error
        raise DiscordGatewayError("Discord Gateway client stopped unexpectedly.")


class _DiscordGatewayTypingRuntime:
    """Maintain public-SDK typing indicators for one active Gateway client."""

    def __init__(
        self,
        *,
        client: _DiscordLibraryClient,
        target_guild_id: str,
        load_typing_targets: DiscordGatewayTypingTargetLoader,
    ) -> None:
        self.client = client
        self.target_guild_id = target_guild_id
        self.load_typing_targets = load_typing_targets
        self.ready_event = asyncio.Event()
        self.reconcile_event = asyncio.Event()
        self.lock = asyncio.Lock()
        self.accepting_targets = False
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.error: DiscordGatewayError | None = None

    async def handle_lifecycle(self, state: DiscordGatewayLifecycleState) -> None:
        """Start or stop target reconciliation for one SDK lifecycle transition."""
        match state:
            case "ready" | "resumed":
                async with self.lock:
                    self.accepting_targets = True
                    self.ready_event.set()
                    self.reconcile_event.set()
            case "disconnected":
                await self._deactivate()

    async def run(self) -> None:
        """Reconcile target state until SDK shutdown or source failure."""
        try:
            while True:
                await self.ready_event.wait()
                self.reconcile_event.clear()
                await self._reconcile()
                try:
                    await asyncio.wait_for(
                        self.reconcile_event.wait(),
                        timeout=_TYPING_RECONCILE_INTERVAL_SECONDS,
                    )
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except DiscordGatewayError as error:
            self.error = error
            await self._deactivate()
            await self.client.close()
        except Exception as error:
            self.error = DiscordGatewayError("Discord typing target processing failed.")
            logger.warning(
                "Discord typing target processing failed.",
                extra={"error_type": type(error).__name__},
            )
            await self._deactivate()
            await self.client.close()
        finally:
            await self._deactivate()

    async def stop(self, task: asyncio.Task[None]) -> None:
        """Cancel and join the runtime task before releasing the SDK client."""
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _reconcile(self) -> None:
        targets = await self.load_typing_targets()
        if targets is None:
            raise DiscordGatewayError(
                "Discord Gateway typing target authority is unavailable."
            )
        desired = _typing_targets_by_channel(
            targets,
            target_guild_id=self.target_guild_id,
        )
        async with self.lock:
            if not self.accepting_targets:
                return
            removed_channel_ids = self.tasks.keys() - desired.keys()
            removed_tasks = tuple(
                self.tasks.pop(channel_id) for channel_id in removed_channel_ids
            )
            await self._cancel_tasks_locked(removed_tasks)
            for channel_id, target in desired.items():
                existing = self.tasks.get(channel_id)
                if existing is not None:
                    if existing.done():
                        existing.result()
                    continue
                self.tasks[channel_id] = asyncio.create_task(
                    self._renew_typing(target),
                    name=(
                        "discord-gateway-typing-channel:"
                        f"{target.guild_id}:{target.channel_id}"
                    ),
                )

    async def _deactivate(self) -> None:
        """Prevent further renewal and join all active channel tasks."""
        async with self.lock:
            self.accepting_targets = False
            self.ready_event.clear()
            self.reconcile_event.set()
            await self._cancel_tasks_locked(tuple(self.tasks.values()))
            self.tasks.clear()

    async def _renew_typing(self, target: DiscordGatewayTypingTarget) -> None:
        """Refresh one provider typing indicator until its target is removed."""
        channel = self.client.get_partial_messageable(
            int(target.channel_id),
            guild_id=int(target.guild_id),
        )
        while True:
            retry = False
            try:
                await channel.typing()
            except asyncio.CancelledError:
                raise
            except discord.HTTPException, OSError:
                retry = True
                logger.warning(
                    "Discord typing refresh failed.",
                    extra={
                        "discord_guild_id": target.guild_id,
                        "discord_channel_id": target.channel_id,
                    },
                )
            await asyncio.sleep(
                _TYPING_RETRY_INTERVAL_SECONDS
                if retry
                else _TYPING_RENEW_INTERVAL_SECONDS
            )

    async def _cancel_tasks_locked(
        self,
        tasks: tuple[asyncio.Task[None], ...],
    ) -> None:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _typing_targets_by_channel(
    targets: tuple[DiscordGatewayTypingTarget, ...],
    *,
    target_guild_id: str,
) -> dict[str, DiscordGatewayTypingTarget]:
    """Validate the current Guild and collapse already grouped channel targets."""
    by_channel: dict[str, DiscordGatewayTypingTarget] = {}
    for target in targets:
        if (
            target.guild_id != target_guild_id
            or not target.guild_id.isdigit()
            or not target.channel_id.isdigit()
            or not target.work_cycle_ids
        ):
            raise DiscordGatewayError("Discord typing target is invalid.")
        by_channel[target.channel_id] = target
    return by_channel


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
