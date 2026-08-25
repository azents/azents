"""Pinned discord.py REST lifecycle and bounded private-HTTP adapter."""

import contextlib
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

import aiohttp
import discord
from discord.http import handle_message_parameters

from azents.core.external_channel_projection import is_external_channel_projection
from azents.services.external_channel.discord_events import (
    project_discord_message,
)


class DiscordSDKError(RuntimeError):
    """Base class for controlled pinned discord.py failures."""


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


@dataclass(frozen=True)
class _DiscordHTTPChannel:
    """Validated private HTTP channel scope retained in one SDK session."""

    channel_id: str
    guild_id: str
    channel_type: int
    parent_id: str | None
    name: str

    @property
    def thread(self) -> bool:
        return self.channel_type in {10, 11, 12}


class DiscordSDKSession(Protocol):
    """One authenticated pinned discord.py REST session."""

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
        auto_archive_duration: Literal[60, 1440, 4320, 10080],
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
    """Create request-scoped authenticated discord.py sessions."""

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
        except (TypeError, ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error


class DiscordPyClientFactory:
    """Create pinned discord.py REST-only clients without credential caching."""

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
    """Isolate pinned private HTTP calls for one authenticated Bot token."""

    def __init__(self, client: discord.Client) -> None:
        self._client = client
        self._http = client.http
        self._commands: dict[str, DiscordSDKCommand] = {}
        self._command_application_id: int | None = None
        self._command_guild_id: int | None = None
        self._channels: dict[str, _DiscordHTTPChannel] = {}

    async def fetch_application(self) -> DiscordSDKApplication:
        application = self._client.application
        if application is None:
            raise DiscordSDKUnavailable("Discord SDK Application is unavailable.")
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
            application_snowflake = int(application_id)
            guild_snowflake = int(guild_id)
            payload: object = await self._http.get_guild_commands(
                application_snowflake,
                guild_snowflake,
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        if not isinstance(payload, list):
            raise DiscordSDKUnavailable("Discord command response is invalid.")
        commands = tuple(_http_command(item) for item in payload)
        self._commands = {command.command_id: command for command in commands}
        self._command_application_id = application_snowflake
        self._command_guild_id = guild_snowflake
        return commands

    async def update_guild_command(
        self,
        *,
        command_id: str,
        name: str,
        command_type: int,
        description: str | None,
    ) -> DiscordSDKCommand:
        command = self._commands.get(command_id)
        if command is None or command.command_type != command_type:
            raise DiscordSDKRequestRejected(
                "Discord command is unavailable in the current SDK session."
            )
        if self._command_application_id is None or self._command_guild_id is None:
            raise DiscordSDKRequestRejected(
                "Discord command scope is unavailable in the current SDK session."
            )
        payload: dict[str, object] = {"name": name}
        if command_type == 1:
            if description is None:
                raise DiscordSDKRequestRejected(
                    "Discord chat command description is required."
                )
            payload["description"] = description
        try:
            response: object = await self._http.edit_guild_command(
                self._command_application_id,
                self._command_guild_id,
                int(command_id),
                payload,
            )
        except (discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        updated = _http_command(response)
        if updated.command_id != command_id or updated.command_type != command_type:
            raise DiscordSDKRequestRejected(
                "Discord command response changed its identity or command type."
            )
        self._commands[command_id] = updated
        return updated

    async def delete_guild_command(self, *, command_id: str) -> None:
        if command_id not in self._commands:
            raise DiscordSDKRequestRejected(
                "Discord command is unavailable in the current SDK session."
            )
        if self._command_application_id is None or self._command_guild_id is None:
            raise DiscordSDKRequestRejected(
                "Discord command scope is unavailable in the current SDK session."
            )
        try:
            await self._http.delete_guild_command(
                self._command_application_id,
                self._command_guild_id,
                int(command_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        self._commands.pop(command_id, None)

    async def fetch_root_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
    ) -> DiscordSDKThread | None:
        await self._validated_root_parent_channel(
            guild_id=guild_id,
            channel_id=parent_channel_id,
        )
        try:
            payload: object = await self._http.get_message(
                int(parent_channel_id),
                int(root_message_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        message = _http_mapping(payload, "Discord root message response is invalid.")
        _validate_message_identity(
            message,
            channel_id=parent_channel_id,
            message_id=root_message_id,
            guild_id=guild_id,
        )
        thread = message.get("thread")
        if thread is None:
            return None
        result = _http_thread(
            thread,
            guild_id=guild_id,
            parent_channel_id=parent_channel_id,
        )
        self._remember_thread(result)
        return result

    async def create_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str,
        auto_archive_duration: Literal[60, 1440, 4320, 10080],
    ) -> DiscordSDKThread:
        await self._validated_root_parent_channel(
            guild_id=guild_id,
            channel_id=parent_channel_id,
        )
        try:
            payload: object = await self._http.start_thread_with_message(
                int(parent_channel_id),
                int(root_message_id),
                name=name,
                auto_archive_duration=auto_archive_duration,
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        result = _http_thread(
            payload,
            guild_id=guild_id,
            parent_channel_id=parent_channel_id,
        )
        self._remember_thread(result)
        return result

    async def fetch_thread(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> DiscordSDKThread:
        channel = await self._validated_thread_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        assert channel.parent_id is not None
        return DiscordSDKThread(
            thread_id=channel.channel_id,
            parent_id=channel.parent_id,
            guild_id=channel.guild_id,
            name=channel.name,
        )

    async def update_thread_name(
        self,
        *,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordSDKThread:
        await self._validated_thread_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            payload: object = await self._http.edit_channel(
                int(channel_id),
                name=name,
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        result = _http_thread(
            payload,
            guild_id=guild_id,
            thread_id=channel_id,
            name=name,
        )
        self._remember_thread(result)
        return result

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
        await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            view = _sdk_view(components)
            sdk_embeds = _sdk_embeds(embeds)
            if view is None and sdk_embeds is None:
                parameters = handle_message_parameters(content, nonce=nonce)
            elif view is None:
                assert sdk_embeds is not None
                parameters = handle_message_parameters(
                    content,
                    nonce=nonce,
                    embeds=sdk_embeds,
                )
            elif sdk_embeds is None:
                parameters = handle_message_parameters(
                    content,
                    nonce=nonce,
                    view=view,
                )
            else:
                parameters = handle_message_parameters(
                    content,
                    nonce=nonce,
                    view=view,
                    embeds=sdk_embeds,
                )
            with parameters as params:
                if params.payload is None:
                    raise DiscordSDKUnavailable(
                        "Discord text message payload is unavailable."
                    )
                params.payload["enforce_nonce"] = True
                payload: object = await self._http.send_message(
                    int(channel_id),
                    params=params,
                )
        except (TypeError, ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        return _http_message(
            payload,
            guild_id=guild_id,
            channel_id=channel_id,
        )

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
        await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            with handle_message_parameters(
                content=content,
                view=_sdk_view(components),
                embeds=_sdk_embeds(embeds) or [],
            ) as params:
                payload: object = await self._http.edit_message(
                    int(channel_id),
                    int(message_id),
                    params=params,
                )
        except (TypeError, ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        return _http_message(
            payload,
            guild_id=guild_id,
            channel_id=channel_id,
            message_id=message_id,
        )

    async def delete_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> None:
        await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            await self._http.delete_message(
                int(channel_id),
                int(message_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error

    async def fetch_attachment(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordSDKAttachment:
        await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        try:
            payload: object = await self._http.get_message(
                int(channel_id),
                int(message_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        message = _http_mapping(payload, "Discord attachment response is invalid.")
        _validate_message_identity(
            message,
            channel_id=channel_id,
            message_id=message_id,
            guild_id=guild_id,
        )
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            raise DiscordSDKUnavailable(
                "Discord attachment response omitted attachment metadata."
            )
        for item in attachments:
            if not is_external_channel_projection(item):
                continue
            if item.get("id") == attachment_id:
                filename = item.get("filename")
                size = item.get("size")
                content_type = item.get("content_type")
                download_url = item.get("url")
                if (
                    not isinstance(filename, str)
                    or not filename
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                    or content_type is not None
                    and not isinstance(content_type, str)
                    or not isinstance(download_url, str)
                    or not download_url
                ):
                    raise DiscordSDKUnavailable(
                        "Discord attachment metadata is invalid."
                    )
                return DiscordSDKAttachment(
                    attachment_id=attachment_id,
                    filename=filename,
                    size=size,
                    content_type=content_type,
                    download_url=download_url,
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
        await self._validated_history_channel(
            guild_id=guild_id,
            source_channel_id=source_channel_id,
            channel_id=channel_id,
        )
        try:
            payload: object = await self._http.get_message(
                int(channel_id),
                int(message_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        return _project_http_history_message(
            payload,
            guild_id=guild_id,
            source_channel_id=source_channel_id,
            channel_id=channel_id,
            message_id=message_id,
        )

    async def fetch_history_projections(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        before_message_id: str,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        await self._validated_history_channel(
            guild_id=guild_id,
            source_channel_id=source_channel_id,
            channel_id=channel_id,
        )
        try:
            payload: object = await self._http.logs_from(
                int(channel_id),
                limit,
                before=int(before_message_id),
            )
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        if not isinstance(payload, list):
            raise DiscordSDKUnavailable("Discord history response is invalid.")
        return tuple(
            _project_http_history_message(
                item,
                guild_id=guild_id,
                source_channel_id=source_channel_id,
                channel_id=channel_id,
            )
            for item in payload
        )

    async def _validated_root_parent_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> _DiscordHTTPChannel:
        channel = await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if channel.thread:
            raise DiscordSDKRequestRejected(
                "Discord root message parent cannot be a Thread."
            )
        return channel

    async def _validated_thread_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> _DiscordHTTPChannel:
        channel = await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if not channel.thread or channel.parent_id is None:
            raise DiscordSDKRequestRejected(
                "Discord Thread identity does not match the request."
            )
        return channel

    async def _validated_history_channel(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
    ) -> _DiscordHTTPChannel:
        channel = await self._validated_message_channel(
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if channel_id == source_channel_id:
            if channel.thread:
                raise DiscordSDKRequestRejected(
                    "Discord source history channel cannot be a Thread."
                )
            return channel
        if not channel.thread or channel.parent_id != source_channel_id:
            raise DiscordSDKRequestRejected(
                "Discord history Thread parent does not match the source channel."
            )
        return channel

    async def _validated_message_channel(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> _DiscordHTTPChannel:
        cached = self._channels.get(channel_id)
        if cached is not None:
            if cached.guild_id != guild_id:
                raise DiscordSDKRequestRejected(
                    "Discord channel Guild identity does not match the request."
                )
            return cached
        try:
            payload: object = await self._http.get_channel(int(channel_id))
        except (ValueError, discord.HTTPException, OSError) as error:
            raise _sdk_error(error) from error
        channel = _http_channel(
            payload,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        self._channels[channel_id] = channel
        return channel

    def _remember_thread(self, thread: DiscordSDKThread) -> None:
        self._channels[thread.thread_id] = _DiscordHTTPChannel(
            channel_id=thread.thread_id,
            guild_id=thread.guild_id,
            channel_type=11,
            parent_id=thread.parent_id,
            name=thread.name,
        )


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


def _http_command(payload: object) -> DiscordSDKCommand:
    command = _http_mapping(payload, "Discord command response is invalid.")
    command_id = command.get("id")
    name = command.get("name")
    command_type = command.get("type")
    description = command.get("description")
    if (
        not isinstance(command_id, str)
        or not command_id.isdigit()
        or not isinstance(name, str)
        or not name
        or not isinstance(command_type, int)
        or isinstance(command_type, bool)
        or description is not None
        and not isinstance(description, str)
    ):
        raise DiscordSDKUnavailable("Discord command response is invalid.")
    return DiscordSDKCommand(
        command_id=command_id,
        name=name,
        command_type=command_type,
        description=description if command_type == 1 else None,
    )


def _http_channel(
    payload: object,
    *,
    guild_id: str,
    channel_id: str,
) -> _DiscordHTTPChannel:
    channel = _http_mapping(payload, "Discord channel response is invalid.")
    response_channel_id = channel.get("id")
    response_guild_id = channel.get("guild_id")
    channel_type = channel.get("type")
    parent_id = channel.get("parent_id")
    name = channel.get("name")
    if (
        response_channel_id != channel_id
        or response_guild_id != guild_id
        or not isinstance(channel_type, int)
        or isinstance(channel_type, bool)
        or channel_type not in {0, 2, 10, 11, 12, 13}
        or not isinstance(name, str)
        or not name
        or channel_type in {10, 11, 12}
        and (not isinstance(parent_id, str) or not parent_id.isdigit())
    ):
        raise DiscordSDKRequestRejected("Discord channel response is invalid.")
    return _DiscordHTTPChannel(
        channel_id=channel_id,
        guild_id=guild_id,
        channel_type=channel_type,
        parent_id=parent_id if isinstance(parent_id, str) else None,
        name=name,
    )


def _http_message(
    payload: object,
    *,
    guild_id: str,
    channel_id: str,
    message_id: str | None = None,
) -> DiscordSDKMessage:
    message = _http_mapping(payload, "Discord Message response is invalid.")
    response_message_id = message.get("id")
    _validate_message_identity(
        message,
        channel_id=channel_id,
        message_id=message_id,
        guild_id=guild_id,
    )
    assert isinstance(response_message_id, str)
    return DiscordSDKMessage(
        message_id=response_message_id,
        channel_id=channel_id,
        guild_id=guild_id,
    )


def _http_thread(
    payload: object,
    *,
    guild_id: str,
    parent_channel_id: str | None = None,
    thread_id: str | None = None,
    name: str | None = None,
) -> DiscordSDKThread:
    thread = _http_mapping(payload, "Discord Thread response is invalid.")
    response_thread_id = thread.get("id")
    response_parent_id = thread.get("parent_id")
    response_guild_id = thread.get("guild_id")
    response_name = thread.get("name")
    channel_type = thread.get("type")
    if (
        not isinstance(response_thread_id, str)
        or not response_thread_id.isdigit()
        or thread_id is not None
        and response_thread_id != thread_id
        or not isinstance(response_parent_id, str)
        or not response_parent_id.isdigit()
        or parent_channel_id is not None
        and response_parent_id != parent_channel_id
        or response_guild_id != guild_id
        or not isinstance(response_name, str)
        or not response_name
        or name is not None
        and response_name != name
        or channel_type not in {10, 11, 12}
    ):
        raise DiscordSDKRequestRejected("Discord Thread response is invalid.")
    return DiscordSDKThread(
        thread_id=response_thread_id,
        parent_id=response_parent_id,
        guild_id=guild_id,
        name=response_name,
    )


def _project_http_history_message(
    payload: object,
    *,
    guild_id: str,
    source_channel_id: str,
    channel_id: str,
    message_id: str | None = None,
) -> dict[str, object]:
    message = _http_mapping(payload, "Discord history Message response is invalid.")
    _validate_message_identity(
        message,
        channel_id=channel_id,
        message_id=message_id,
        guild_id=guild_id,
    )
    source = dict(message)
    if channel_id != source_channel_id:
        source["thread"] = {
            "id": channel_id,
            "parent_id": source_channel_id,
        }
    return project_discord_message(message=source, guild_id=guild_id)


def _validate_message_identity(
    message: dict[str, object],
    *,
    channel_id: str,
    message_id: str | None,
    guild_id: str,
) -> None:
    response_message_id = message.get("id")
    response_channel_id = message.get("channel_id")
    response_guild_id = message.get("guild_id")
    if (
        not isinstance(response_message_id, str)
        or not response_message_id.isdigit()
        or message_id is not None
        and response_message_id != message_id
        or response_channel_id != channel_id
        or response_guild_id is not None
        and response_guild_id != guild_id
    ):
        raise DiscordSDKRequestRejected("Discord Message response is invalid.")


def _http_mapping(payload: object, message: str) -> dict[str, object]:
    if not is_external_channel_projection(payload):
        raise DiscordSDKUnavailable(message)
    return payload


def _sdk_embeds(
    values: list[dict[str, object]] | None,
) -> list[discord.Embed] | None:
    if values is None:
        return None
    return [discord.Embed.from_dict(value) for value in values]


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
