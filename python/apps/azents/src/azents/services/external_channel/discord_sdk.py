"""Public discord.py REST lifecycle and bounded projection adapter."""

import contextlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import aiohttp
import discord
from discord import app_commands

from azents.core.external_channel_projection import is_external_channel_projection
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


@dataclass(frozen=True)
class DiscordSDKMessage:
    """Bounded message identity returned by public delivery operations."""

    message_id: str
    channel_id: str
    guild_id: str


@dataclass(frozen=True)
class DiscordSDKThread:
    """Bounded Thread identity and title returned by public SDK operations."""

    thread_id: str
    parent_id: str
    guild_id: str
    name: str


@dataclass(frozen=True)
class DiscordSDKAttachment:
    """Bounded current attachment metadata with an ephemeral CDN URL."""

    attachment_id: str
    filename: str
    size: int
    content_type: str | None
    download_url: str


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

    async def fetch_root_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
    ) -> DiscordSDKThread | None:
        """Return the public Thread attached to one exact root message."""
        ...

    async def create_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str,
        auto_archive_duration: int,
    ) -> DiscordSDKThread:
        """Create one public Thread from an exact root message."""
        ...

    async def fetch_thread(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> DiscordSDKThread:
        """Return one exact public Thread."""
        ...

    async def update_thread_name(
        self,
        *,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordSDKThread:
        """Apply one name-only public Thread edit."""
        ...

    async def create_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        content: str,
        nonce: str,
        components: list[dict[str, object]] | None,
        embeds: list[dict[str, object]] | None,
    ) -> DiscordSDKMessage:
        """Create one text message through the public SDK."""
        ...

    async def update_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        content: str,
        components: list[dict[str, object]] | None,
        embeds: list[dict[str, object]] | None,
    ) -> DiscordSDKMessage:
        """Update one exact message through the public SDK."""
        ...

    async def delete_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> None:
        """Delete one exact message through the public SDK."""
        ...

    async def fetch_attachment(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordSDKAttachment:
        """Return one current attachment from an exact public SDK Message."""
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


@runtime_checkable
class DiscordSDKMessageForwardingSession(Protocol):
    """Public-SDK capability for forwarding one exact created message."""

    async def forward_message(
        self,
        *,
        message: DiscordSDKMessage,
        destination_channel_id: str,
    ) -> DiscordSDKMessage:
        """Forward one exact message to its parent channel."""
        ...


class DiscordSDKClientFactory(Protocol):
    """Create request-scoped public discord.py sessions."""

    def open(self, *, bot_token: str) -> AbstractAsyncContextManager[DiscordSDKSession]:
        """Open one authenticated SDK session and close it after use."""
        ...


class DiscordInteractionResponseClient(Protocol):
    """Complete one deferred Discord interaction through its request-local token."""

    async def edit_original(
        self,
        *,
        application_id: str,
        interaction_token: str,
        response: dict[str, object],
    ) -> None:
        """Replace the original interaction response after deferred ACK."""
        ...


class DiscordPyInteractionResponseClient:
    """Complete deferred interactions through the public webhook SDK."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def edit_original(
        self,
        *,
        application_id: str,
        interaction_token: str,
        response: dict[str, object],
    ) -> None:
        """Replace one deferred original response without authenticating a Bot."""
        data = response.get("data")
        if not is_external_channel_projection(data):
            raise DiscordSDKRequestRejected(
                "Discord interaction response data is invalid."
            )
        content = data.get("content")
        embeds = data.get("embeds")
        components = data.get("components")
        if content is not None and not isinstance(content, str):
            raise DiscordSDKRequestRejected(
                "Discord interaction response content is invalid."
            )
        if embeds is not None and (
            not isinstance(embeds, list)
            or not all(isinstance(item, dict) for item in embeds)
        ):
            raise DiscordSDKRequestRejected(
                "Discord interaction response embeds are invalid."
            )
        if components is not None and components != []:
            raise DiscordSDKRequestRejected(
                "Deferred Discord interaction response components are unsupported."
            )
        try:
            webhook = discord.Webhook.partial(
                int(application_id),
                interaction_token,
                session=self.session,
            )
            await webhook.edit_message(
                "@original",  # ty: ignore[invalid-argument-type] # Discord's documented original-response locator is not represented by discord.py's int-only annotation.
                content=content,
                embeds=(
                    []
                    if embeds is None
                    else [
                        discord.Embed.from_dict(item)
                        for item in embeds
                        if isinstance(item, dict)
                    ]
                ),
                view=None,
            )
        except (
            TypeError,
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error


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
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error
        projected = tuple(
            _sdk_command(
                command,
                expected_command_id=None,
                expected_command_type=None,
                expected_application_id=application_id,
                expected_guild_id=guild_id,
            )
            for command in commands
        )
        self._commands = {str(command.id): command for command in commands}
        return projected

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
        projected = _sdk_command(
            updated,
            expected_command_id=command_id,
            expected_command_type=command_type,
            expected_application_id=str(command.application_id),
            expected_guild_id=(
                None if command.guild_id is None else str(command.guild_id)
            ),
        )
        self._commands[command_id] = updated
        return projected

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

    async def fetch_root_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
    ) -> DiscordSDKThread | None:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=parent_channel_id,
            )
            if isinstance(channel, discord.Thread):
                raise DiscordSDKRequestRejected(
                    "Discord root message parent cannot be a Thread."
                )
            message = await channel.fetch_message(int(root_message_id))
            _validate_sdk_message_identity(
                message,
                guild_id=guild_id,
                channel_id=parent_channel_id,
                message_id=root_message_id,
            )
            thread = message.thread
            return (
                None
                if thread is None
                else _sdk_thread(
                    thread,
                    guild_id=guild_id,
                    parent_id=parent_channel_id,
                    thread_id=None,
                    name=None,
                )
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def create_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str,
        auto_archive_duration: int,
    ) -> DiscordSDKThread:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=parent_channel_id,
            )
            if isinstance(channel, discord.Thread):
                raise DiscordSDKRequestRejected(
                    "Discord root message parent cannot be a Thread."
                )
            message = await channel.fetch_message(int(root_message_id))
            _validate_sdk_message_identity(
                message,
                guild_id=guild_id,
                channel_id=parent_channel_id,
                message_id=root_message_id,
            )
            thread = await message.create_thread(
                name=name,
                auto_archive_duration=auto_archive_duration,
            )
            return _sdk_thread(
                thread,
                guild_id=guild_id,
                parent_id=parent_channel_id,
                thread_id=None,
                name=name,
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def fetch_thread(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> DiscordSDKThread:
        try:
            channel = await self._validated_thread_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error
        return _sdk_thread(
            channel,
            guild_id=guild_id,
            parent_id=None,
            thread_id=channel_id,
            name=None,
        )

    async def update_thread_name(
        self,
        *,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordSDKThread:
        try:
            channel = await self._validated_thread_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
            updated = await channel.edit(name=name)
            return _sdk_thread(
                updated,
                guild_id=guild_id,
                parent_id=None,
                thread_id=channel_id,
                name=name,
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def create_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        content: str,
        nonce: str,
        components: list[dict[str, object]] | None,
        embeds: list[dict[str, object]] | None,
    ) -> DiscordSDKMessage:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
            message = await _send_sdk_message(
                channel,
                content=content,
                nonce=nonce,
                view=_sdk_view(components),
                embeds=_sdk_embeds(embeds),
            )
            return _sdk_message(
                message,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=None,
            )
        except (
            TypeError,
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def forward_message(
        self,
        *,
        message: DiscordSDKMessage,
        destination_channel_id: str,
    ) -> DiscordSDKMessage:
        """Forward one exact Thread message through discord.py public APIs."""
        try:
            source = await self._client.fetch_channel(int(message.channel_id))
            destination = await self._client.fetch_channel(int(destination_channel_id))
        except (
            TypeError,
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error
        if (
            not isinstance(source, discord.Thread)
            or str(source.id) != message.channel_id
            or str(source.guild.id) != message.guild_id
            or source.parent_id is None
            or str(source.parent_id) != destination_channel_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord forwarding source does not match the exact Thread."
            )
        if (
            isinstance(destination, discord.Thread)
            or not isinstance(
                destination,
                (discord.TextChannel, discord.VoiceChannel, discord.StageChannel),
            )
            or str(destination.id) != destination_channel_id
            or str(destination.guild.id) != message.guild_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord forwarding destination does not match the Thread parent."
            )
        try:
            forwarded = await source.get_partial_message(
                int(message.message_id)
            ).forward(destination)
        except (
            TypeError,
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error
        if (
            forwarded.guild is None
            or str(forwarded.guild.id) != message.guild_id
            or str(forwarded.channel.id) != destination_channel_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord forwarded Message response changed its destination."
            )
        return DiscordSDKMessage(
            message_id=str(forwarded.id),
            channel_id=destination_channel_id,
            guild_id=message.guild_id,
        )

    async def update_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        content: str,
        components: list[dict[str, object]] | None,
        embeds: list[dict[str, object]] | None,
    ) -> DiscordSDKMessage:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
            message = await channel.fetch_message(int(message_id))
            _validate_sdk_message_identity(
                message,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            updated = await message.edit(
                content=content,
                view=_sdk_view(components),
                embeds=_sdk_embeds(embeds) or [],
            )
            return _sdk_message(
                updated,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
        except (
            TypeError,
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def delete_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> None:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
            message = await channel.fetch_message(int(message_id))
            _validate_sdk_message_identity(
                message,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            await message.delete()
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error

    async def fetch_attachment(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordSDKAttachment:
        try:
            channel = await self._validated_message_channel(
                guild_id=guild_id,
                channel_id=channel_id,
            )
            message = await channel.fetch_message(int(message_id))
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
            raise _sdk_error(error) from error
        _validate_sdk_message_identity(
            message,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
        )
        for attachment in message.attachments:
            if str(attachment.id) == attachment_id:
                return DiscordSDKAttachment(
                    attachment_id=str(attachment.id),
                    filename=attachment.filename,
                    size=attachment.size,
                    content_type=attachment.content_type,
                    download_url=attachment.url,
                )
        raise DiscordSDKResourceUnavailable(
            "Discord no longer exposes the requested attachment."
        )

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
            _validate_sdk_message_identity(
                message,
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
            return project_discord_sdk_history_message(
                message=message,
                guild_id=guild_id,
                conversation_channel_id=channel_id,
                thread_parent_id=thread_parent_id,
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
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
                _sdk_history_projection(
                    message=message,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    thread_parent_id=thread_parent_id,
                )
                for message in messages
            )
        except (
            ValueError,
            discord.InvalidData,
            discord.HTTPException,
            OSError,
        ) as error:
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

    async def _validated_message_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> DiscordSDKHistoryChannel:
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
                "Discord message channel type is unsupported."
            )
        if str(channel.id) != channel_id or str(channel.guild.id) != guild_id:
            raise DiscordSDKRequestRejected(
                "Discord message channel identity does not match the request."
            )
        return channel

    async def _validated_thread_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> discord.Thread:
        channel = await self._client.fetch_channel(int(channel_id))
        if (
            not isinstance(channel, discord.Thread)
            or str(channel.id) != channel_id
            or str(channel.guild.id) != guild_id
        ):
            raise DiscordSDKRequestRejected(
                "Discord Thread identity does not match the request."
            )
        return channel


def get_discord_sdk_client_factory() -> DiscordSDKClientFactory:
    """Provide the public SDK factory or the injected deterministic testenv fixture."""
    from azents.services.external_channel.discord_endpoint import (  # noqa: PLC0415
        discord_test_api_base_url,
    )
    from azents.services.external_channel.discord_testenv import (  # noqa: PLC0415
        DiscordTestenvSDKClientFactory,
    )

    test_api_base_url = discord_test_api_base_url()
    if test_api_base_url is not None:
        return DiscordTestenvSDKClientFactory(
            test_api_base_url.removesuffix("/api/v10")
        )
    return DiscordPyClientFactory()


async def get_discord_interaction_response_client() -> AsyncIterator[
    DiscordInteractionResponseClient
]:
    """Provide a short-lived public webhook client for deferred responses."""
    from azents.services.external_channel.discord_endpoint import (  # noqa: PLC0415
        discord_test_api_base_url,
    )

    test_api_base_url = discord_test_api_base_url()
    if test_api_base_url is not None:
        from azents.services.external_channel.discord_testenv import (  # noqa: PLC0415
            DiscordTestenvInteractionResponseClient,
        )

        yield DiscordTestenvInteractionResponseClient(
            test_api_base_url.removesuffix("/api/v10")
        )
        return
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=20.0)
    ) as session:
        yield DiscordPyInteractionResponseClient(session)


def _sdk_command(
    command: app_commands.AppCommand,
    *,
    expected_command_id: str | None,
    expected_command_type: int | None,
    expected_application_id: str,
    expected_guild_id: str | None,
) -> DiscordSDKCommand:
    command_type = command.type.value
    command_id = str(command.id)
    if (
        expected_command_id is not None
        and command_id != expected_command_id
        or expected_command_type is not None
        and command_type != expected_command_type
        or str(command.application_id) != expected_application_id
        or command.guild_id is None
        or expected_guild_id is not None
        and str(command.guild_id) != expected_guild_id
        or not isinstance(command.name, str)
        or not command.name
    ):
        raise DiscordSDKRequestRejected(
            "Discord command response has invalid identity, scope, or name."
        )
    return DiscordSDKCommand(
        command_id=command_id,
        name=command.name,
        command_type=command_type,
        description=command.description if command_type == 1 else None,
    )


def _sdk_message(
    message: discord.Message,
    *,
    guild_id: str,
    channel_id: str,
    message_id: str | None,
) -> DiscordSDKMessage:
    _validate_sdk_message_identity(
        message,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=message_id,
    )
    return DiscordSDKMessage(
        message_id=str(message.id),
        channel_id=channel_id,
        guild_id=guild_id,
    )


def _sdk_thread(
    thread: discord.Thread,
    *,
    guild_id: str,
    parent_id: str | None,
    thread_id: str | None,
    name: str | None,
) -> DiscordSDKThread:
    response_parent_id = None if thread.parent_id is None else str(thread.parent_id)
    if (
        str(thread.guild.id) != guild_id
        or response_parent_id is None
        or not isinstance(thread.name, str)
        or not thread.name
        or parent_id is not None
        and response_parent_id != parent_id
        or thread_id is not None
        and str(thread.id) != thread_id
        or name is not None
        and thread.name != name
    ):
        raise DiscordSDKRequestRejected("Discord Thread response is invalid.")
    return DiscordSDKThread(
        thread_id=str(thread.id),
        parent_id=response_parent_id,
        guild_id=guild_id,
        name=thread.name,
    )


def _validate_sdk_message_identity(
    message: discord.Message,
    *,
    guild_id: str,
    channel_id: str,
    message_id: str | None,
) -> None:
    if (
        message.guild is None
        or str(message.guild.id) != guild_id
        or str(message.channel.id) != channel_id
        or message_id is not None
        and str(message.id) != message_id
    ):
        raise DiscordSDKRequestRejected(
            "Discord Message identity does not match the request."
        )


def _sdk_history_projection(
    *,
    message: discord.Message,
    guild_id: str,
    channel_id: str,
    thread_parent_id: str | None,
) -> dict[str, object]:
    _validate_sdk_message_identity(
        message,
        guild_id=guild_id,
        channel_id=channel_id,
        message_id=None,
    )
    return project_discord_sdk_history_message(
        message=message,
        guild_id=guild_id,
        conversation_channel_id=channel_id,
        thread_parent_id=thread_parent_id,
    )


def _sdk_embeds(
    values: list[dict[str, object]] | None,
) -> list[discord.Embed] | None:
    if values is None:
        return None
    return [discord.Embed.from_dict(value) for value in values]


async def _send_sdk_message(
    channel: discord.abc.Messageable,
    *,
    content: str,
    nonce: str,
    view: discord.ui.View | None,
    embeds: list[discord.Embed] | None,
) -> discord.Message:
    if view is None and embeds is None:
        return await channel.send(content, nonce=nonce)
    if view is None:
        assert embeds is not None
        return await channel.send(content, nonce=nonce, embeds=embeds)
    if embeds is None:
        return await channel.send(content, nonce=nonce, view=view)
    return await channel.send(content, nonce=nonce, view=view, embeds=embeds)


def _sdk_view(components: list[dict[str, object]] | None) -> discord.ui.View | None:
    if components is None:
        return None
    view = discord.ui.View(timeout=None)
    for row_index, row in enumerate(components):
        row_components = row.get("components")
        if row.get("type") != 1 or not isinstance(row_components, list):
            raise ValueError("Discord component row is invalid.")
        for item in row_components:
            if not isinstance(item, dict) or item.get("type") != 2:
                raise ValueError("Discord component is unsupported.")
            style = item.get("style")
            if not isinstance(style, int):
                raise ValueError("Discord button style is invalid.")
            label = item.get("label")
            custom_id = item.get("custom_id")
            url = item.get("url")
            view.add_item(
                discord.ui.Button(
                    style=_sdk_button_style(style),
                    label=label if isinstance(label, str) else None,
                    custom_id=custom_id if isinstance(custom_id, str) else None,
                    url=url if isinstance(url, str) else None,
                    disabled=item.get("disabled") is True,
                    row=row_index,
                )
            )
    return view


def _sdk_button_style(value: int) -> discord.ButtonStyle:
    match value:
        case 1:
            return discord.ButtonStyle.primary
        case 2:
            return discord.ButtonStyle.secondary
        case 3:
            return discord.ButtonStyle.success
        case 4:
            return discord.ButtonStyle.danger
        case 5:
            return discord.ButtonStyle.link
        case _:
            raise ValueError("Discord button style is unsupported.")


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
    if isinstance(error, TypeError | ValueError):
        return DiscordSDKRequestRejected()
    return DiscordSDKUnavailable()
