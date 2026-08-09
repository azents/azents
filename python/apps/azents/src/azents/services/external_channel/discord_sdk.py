"""Public discord.py REST lifecycle and bounded projection adapter."""

import contextlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

import discord
from discord import app_commands

from azents.services.external_channel.discord_events import (
    project_discord_sdk_history_message,
)

type DiscordSDKHistoryChannel = (
    discord.TextChannel | discord.Thread | discord.VoiceChannel | discord.StageChannel
)


class DiscordSDKError(RuntimeError):
    """Base class for controlled public discord.py failures."""


class DiscordSDKCredentialsInvalid(DiscordSDKError):
    """Discord rejected the configured Bot token."""


class DiscordSDKPermissionDenied(DiscordSDKError):
    """Discord denied the requested operation."""


class DiscordSDKResourceUnavailable(DiscordSDKError):
    """Discord no longer exposes the requested resource."""


class DiscordSDKRateLimited(DiscordSDKError):
    """Discord rejected waiting beyond the configured rate-limit boundary."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Discord rate limited the SDK operation.")
        self.retry_after_seconds = retry_after_seconds


class DiscordSDKRequestRejected(DiscordSDKError):
    """Discord rejected a valid public SDK operation."""


class DiscordSDKUnavailable(DiscordSDKError):
    """Discord or the public SDK could not complete the operation."""


@dataclass(frozen=True)
class DiscordSDKApplication:
    """Bounded public Application fields used by connection activation."""

    application_id: str
    verify_key: str


@dataclass(frozen=True)
class DiscordSDKCommand:
    """Bounded public command fields used by preservation-safe reconciliation."""

    command_id: str
    name: str
    command_type: int
    description: str | None


class DiscordSDKSession(Protocol):
    """One request-scoped public discord.py REST session."""

    async def fetch_application(self) -> DiscordSDKApplication:
        """Return current Application identity and interaction verification key."""
        ...

    def current_bot_user_id(self) -> str:
        """Return the authenticated Bot user identity."""
        ...

    async def list_guild_commands(
        self,
        *,
        application_id: str,
        guild_id: str,
    ) -> tuple[DiscordSDKCommand, ...]:
        """List current commands without making the local tree authoritative."""
        ...

    async def update_guild_command(
        self,
        *,
        command_id: str,
        name: str,
        command_type: int,
        description: str | None,
    ) -> DiscordSDKCommand:
        """Update one command returned by the current list operation."""
        ...

    async def delete_guild_command(self, *, command_id: str) -> None:
        """Delete one command returned by the current list operation."""
        ...

    async def fetch_message_projection(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        message_id: str,
    ) -> dict[str, object]:
        """Fetch and immediately project one public SDK Message."""
        ...

    async def fetch_history_projections(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        before_message_id: str,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        """Fetch and immediately project one bounded history page."""
        ...


class DiscordSDKClientFactory(Protocol):
    """Create request-scoped public discord.py sessions."""

    def open(self, *, bot_token: str) -> AbstractAsyncContextManager[DiscordSDKSession]:
        """Open one authenticated SDK session and close it after use."""
        ...


class DiscordPyClientFactory:
    """Create public discord.py REST-only clients without shared credential state."""

    def open(
        self,
        *,
        bot_token: str,
    ) -> AbstractAsyncContextManager[DiscordSDKSession]:
        """Open one request-scoped public Client.login/close lifecycle."""
        return self._open(bot_token=bot_token)

    @contextlib.asynccontextmanager
    async def _open(
        self,
        *,
        bot_token: str,
    ) -> AsyncIterator[DiscordSDKSession]:
        from azents.services.external_channel.discord_gateway import (  # noqa: PLC0415
            _discord_test_endpoint_override,
        )

        with _discord_test_endpoint_override():
            client = discord.Client(intents=discord.Intents.none())
            try:
                try:
                    await client.login(bot_token)
                except discord.LoginFailure as error:
                    raise DiscordSDKCredentialsInvalid from error
                except (discord.HTTPException, OSError) as error:
                    raise _sdk_error(error) from error
                yield _DiscordPySession(client)
            finally:
                if not client.is_closed():
                    await client.close()


class _DiscordPySession:
    """Public discord.py operations for one authenticated Bot token."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client
        self._commands: dict[str, app_commands.AppCommand] = {}

    async def fetch_application(self) -> DiscordSDKApplication:
        try:
            application = await self._client.application_info()
        except (discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        return DiscordSDKApplication(
            application_id=str(application.id),
            verify_key=application.verify_key,
        )

    def current_bot_user_id(self) -> str:
        user = self._client.user
        if user is None:
            raise DiscordSDKUnavailable("Discord SDK Bot identity is unavailable.")
        return str(user.id)

    async def list_guild_commands(
        self,
        *,
        application_id: str,
        guild_id: str,
    ) -> tuple[DiscordSDKCommand, ...]:
        if (
            self._client.application_id is None
            or str(self._client.application_id) != application_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord Application identity does not match the authenticated Bot."
            )
        try:
            commands = await app_commands.CommandTree(self._client).fetch_commands(
                guild=discord.Object(id=int(guild_id))
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        self._commands = {str(command.id): command for command in commands}
        return tuple(_sdk_command(command) for command in commands)

    async def update_guild_command(
        self,
        *,
        command_id: str,
        name: str,
        command_type: int,
        description: str | None,
    ) -> DiscordSDKCommand:
        command = self._commands.get(command_id)
        if command is None or command.type.value != command_type:
            raise DiscordSDKRequestRejected(
                "Discord command is unavailable in the current SDK session."
            )
        try:
            if command_type == 1:
                if description is None:
                    raise DiscordSDKRequestRejected(
                        "Discord chat command description is required."
                    )
                updated = await command.edit(
                    name=name,
                    description=description,
                )
            else:
                updated = await command.edit(name=name)
        except (discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        self._commands[command_id] = updated
        return _sdk_command(updated)

    async def delete_guild_command(self, *, command_id: str) -> None:
        command = self._commands.get(command_id)
        if command is None:
            raise DiscordSDKRequestRejected(
                "Discord command is unavailable in the current SDK session."
            )
        try:
            await command.delete()
        except (discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        self._commands.pop(command_id, None)

    async def fetch_message_projection(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        message_id: str,
    ) -> dict[str, object]:
        try:
            channel, thread_parent_id = await self._validated_history_channel(
                guild_id=guild_id,
                source_channel_id=source_channel_id,
                channel_id=channel_id,
            )
            message = await channel.fetch_message(int(message_id))
            return project_discord_sdk_history_message(
                message=message,
                guild_id=guild_id,
                conversation_channel_id=channel_id,
                thread_parent_id=thread_parent_id,
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error

    async def fetch_history_projections(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        before_message_id: str,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        try:
            channel, thread_parent_id = await self._validated_history_channel(
                guild_id=guild_id,
                source_channel_id=source_channel_id,
                channel_id=channel_id,
            )
            messages = [
                message
                async for message in channel.history(
                    limit=limit,
                    before=discord.Object(id=int(before_message_id)),
                    oldest_first=False,
                )
            ]
            return tuple(
                project_discord_sdk_history_message(
                    message=message,
                    guild_id=guild_id,
                    conversation_channel_id=channel_id,
                    thread_parent_id=thread_parent_id,
                )
                for message in messages
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error

    async def _validated_history_channel(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
    ) -> tuple[DiscordSDKHistoryChannel, str | None]:
        channel = await self._client.fetch_channel(int(channel_id))
        if not isinstance(
            channel,
            (
                discord.TextChannel,
                discord.Thread,
                discord.VoiceChannel,
                discord.StageChannel,
            ),
        ):
            raise DiscordSDKRequestRejected(
                "Discord history channel type is unsupported."
            )
        if str(channel.id) != channel_id or str(channel.guild.id) != guild_id:
            raise DiscordSDKRequestRejected(
                "Discord history channel identity does not match the request."
            )
        if channel_id == source_channel_id:
            if isinstance(channel, discord.Thread):
                raise DiscordSDKRequestRejected(
                    "Discord source history channel cannot be a Thread."
                )
            return channel, None
        if (
            not isinstance(channel, discord.Thread)
            or channel.parent_id is None
            or str(channel.parent_id) != source_channel_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord history Thread parent does not match the source channel."
            )
        return channel, str(channel.parent_id)


def get_discord_sdk_client_factory() -> DiscordSDKClientFactory:
    """Provide the production public discord.py client factory."""
    return DiscordPyClientFactory()


def _sdk_command(command: app_commands.AppCommand) -> DiscordSDKCommand:
    command_type = command.type.value
    return DiscordSDKCommand(
        command_id=str(command.id),
        name=command.name,
        command_type=command_type,
        description=command.description if command_type == 1 else None,
    )


def _sdk_error(error: BaseException) -> DiscordSDKError:
    if isinstance(error, DiscordSDKError):
        return error
    if isinstance(error, discord.Forbidden):
        return DiscordSDKPermissionDenied()
    if isinstance(error, discord.NotFound):
        return DiscordSDKResourceUnavailable()
    if isinstance(error, discord.RateLimited):
        return DiscordSDKRateLimited(max(1, min(int(error.retry_after), 300)))
    if isinstance(error, discord.HTTPException):
        if error.status == 401:
            return DiscordSDKCredentialsInvalid()
        if error.status == 403:
            return DiscordSDKPermissionDenied()
        if error.status == 404:
            return DiscordSDKResourceUnavailable()
        if error.status == 429:
            return DiscordSDKRateLimited(1)
        if error.status >= 500:
            return DiscordSDKUnavailable()
        return DiscordSDKRequestRejected()
    if isinstance(error, ValueError):
        return DiscordSDKRequestRejected()
    return DiscordSDKUnavailable()
