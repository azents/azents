"""Injected deterministic Discord SDK and Gateway collaborators for testenv."""

import asyncio
import contextlib
from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager
from typing import cast

import httpx

from azents.services.external_channel.discord_events import (
    DiscordGatewayMessageEvent,
    project_discord_message,
)
from azents.services.external_channel.discord_gateway import (
    DiscordGatewayCredentialError,
    DiscordGatewayError,
    DiscordGatewayEventHandler,
    DiscordGatewayIntentsError,
    DiscordGatewayLifecycleHandler,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKApplication,
    DiscordSDKAttachment,
    DiscordSDKCommand,
    DiscordSDKCredentialsInvalid,
    DiscordSDKError,
    DiscordSDKMessage,
    DiscordSDKPermissionDenied,
    DiscordSDKRateLimited,
    DiscordSDKRequestRejected,
    DiscordSDKResourceUnavailable,
    DiscordSDKSession,
    DiscordSDKThread,
    DiscordSDKUnavailable,
)

_MAX_GATEWAY_IDLE_SECONDS = 3600.0


class DiscordTestenvSDKClientFactory:
    """Create credential-free SDK-facing sessions backed by the provider fixture."""

    def __init__(self, fixture_base_url: str) -> None:
        self._fixture_base_url = fixture_base_url.rstrip("/")

    def open(
        self,
        *,
        bot_token: str,
    ) -> AbstractAsyncContextManager[DiscordSDKSession]:
        """Open one injected fixture session without transmitting the credential."""
        del bot_token
        return self._open()

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[DiscordSDKSession]:
        async with httpx.AsyncClient(timeout=20.0) as client:
            yield _DiscordTestenvSDKSession(client, self._fixture_base_url)


class _DiscordTestenvSDKSession:
    """Project bounded SDK-operation fixture responses into production DTOs."""

    def __init__(self, client: httpx.AsyncClient, fixture_base_url: str) -> None:
        self._client = client
        self._url = f"{fixture_base_url}/__testenv/sdk"
        self._application_id: str | None = None
        self._bot_user_id: str | None = None

    async def fetch_application(self) -> DiscordSDKApplication:
        result = await self._call("fetch_application")
        application_id = _required_string(result, "application_id")
        verify_key = _required_string(result, "verify_key")
        self._application_id = application_id
        self._bot_user_id = _required_string(result, "bot_user_id")
        return DiscordSDKApplication(
            application_id=application_id,
            verify_key=verify_key,
        )

    def current_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            raise DiscordSDKUnavailable("Discord SDK Bot identity is unavailable.")
        return self._bot_user_id

    async def configure_interactions_endpoint(self, endpoint_url: str) -> None:
        await self._call(
            "configure_interactions_endpoint",
            {"endpoint_url": endpoint_url},
        )

    async def list_guild_commands(
        self,
        *,
        application_id: str,
        guild_id: str,
    ) -> tuple[DiscordSDKCommand, ...]:
        result = await self._call(
            "list_guild_commands",
            {"application_id": application_id, "guild_id": guild_id},
        )
        return tuple(_command(item) for item in _object_list(result, "commands"))

    async def update_guild_command(
        self,
        *,
        command_id: str,
        name: str,
        command_type: int,
        description: str | None,
    ) -> DiscordSDKCommand:
        result = await self._call(
            "update_guild_command",
            {
                "command_id": command_id,
                "name": name,
                "command_type": command_type,
                "description": description,
            },
        )
        return _command(result)

    async def delete_guild_command(self, *, command_id: str) -> None:
        await self._call("delete_guild_command", {"command_id": command_id})

    async def fetch_root_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
    ) -> DiscordSDKThread | None:
        result = await self._call(
            "fetch_root_thread",
            {
                "guild_id": guild_id,
                "parent_channel_id": parent_channel_id,
                "root_message_id": root_message_id,
            },
        )
        if result.get("thread") is None:
            return None
        return _thread(_required_object(result, "thread"))

    async def create_thread(
        self,
        *,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str,
        auto_archive_duration: int,
    ) -> DiscordSDKThread:
        result = await self._call(
            "create_thread",
            {
                "guild_id": guild_id,
                "parent_channel_id": parent_channel_id,
                "root_message_id": root_message_id,
                "name": name,
                "auto_archive_duration": auto_archive_duration,
            },
        )
        return _thread(result)

    async def fetch_thread(
        self,
        *,
        guild_id: str,
        channel_id: str,
    ) -> DiscordSDKThread:
        return _thread(
            await self._call(
                "fetch_thread",
                {"guild_id": guild_id, "channel_id": channel_id},
            )
        )

    async def update_thread_name(
        self,
        *,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordSDKThread:
        return _thread(
            await self._call(
                "update_thread_name",
                {"guild_id": guild_id, "channel_id": channel_id, "name": name},
            )
        )

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
        return _message(
            await self._call(
                "create_message",
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "content": content,
                    "nonce": nonce,
                    "components": components,
                    "embeds": embeds,
                },
            )
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
        return _message(
            await self._call(
                "update_message",
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "message_id": message_id,
                    "content": content,
                    "components": components,
                    "embeds": embeds,
                },
            )
        )

    async def delete_message(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> None:
        await self._call(
            "delete_message",
            {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "message_id": message_id,
            },
        )

    async def fetch_attachment(
        self,
        *,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordSDKAttachment:
        result = await self._call(
            "fetch_attachment",
            {
                "guild_id": guild_id,
                "channel_id": channel_id,
                "message_id": message_id,
                "attachment_id": attachment_id,
            },
        )
        size = result.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise DiscordSDKUnavailable("Discord SDK fixture attachment is invalid.")
        content_type = result.get("content_type")
        return DiscordSDKAttachment(
            attachment_id=_required_string(result, "attachment_id"),
            filename=_required_string(result, "filename"),
            size=size,
            content_type=content_type if isinstance(content_type, str) else None,
            download_url=_required_string(result, "download_url"),
        )

    async def fetch_message_projection(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        message_id: str,
    ) -> dict[str, object]:
        result = await self._call(
            "fetch_message_projection",
            {
                "guild_id": guild_id,
                "source_channel_id": source_channel_id,
                "channel_id": channel_id,
                "message_id": message_id,
            },
        )
        return _history_projection(
            result,
            guild_id=guild_id,
            source_channel_id=source_channel_id,
            channel_id=channel_id,
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
        result = await self._call(
            "fetch_history_projections",
            {
                "guild_id": guild_id,
                "source_channel_id": source_channel_id,
                "channel_id": channel_id,
                "before_message_id": before_message_id,
                "limit": limit,
            },
        )
        return tuple(
            _history_projection(
                item,
                guild_id=guild_id,
                source_channel_id=source_channel_id,
                channel_id=channel_id,
            )
            for item in _object_list(result, "messages")
        )

    async def _call(
        self,
        operation: str,
        arguments: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        try:
            response = await self._client.post(
                self._url,
                json={"operation": operation, "arguments": dict(arguments or {})},
            )
        except (httpx.HTTPError, OSError) as error:
            raise DiscordSDKUnavailable from error
        if response.status_code >= 400:
            raise _fixture_sdk_error(response)
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordSDKUnavailable from error
        if not isinstance(payload, dict):
            raise DiscordSDKUnavailable("Discord SDK fixture response is invalid.")
        return cast(dict[str, object], payload)


class DiscordTestenvGatewayRunner:
    """Drive deterministic Gateway callbacks through an injected fixture contract."""

    def __init__(self, fixture_base_url: str) -> None:
        self._url = f"{fixture_base_url.rstrip('/')}/__testenv/gateway"

    async def run_connection(
        self,
        *,
        bot_token: str,
        target_guild_id: str,
        connected_bot_user_id: str | None = None,
        handle_event: DiscordGatewayEventHandler,
        handle_lifecycle: DiscordGatewayLifecycleHandler,
    ) -> None:
        del bot_token
        resumed = False
        channel_names: dict[str, str] = {}
        managed_roles: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                payload = await _gateway_attempt(
                    client,
                    self._url,
                    target_guild_id=target_guild_id,
                    resumed=resumed,
                )
                scenario = _required_string(payload, "scenario")
                if scenario == "reconnect":
                    await handle_lifecycle("disconnected")
                    resumed = True
                    continue
                if scenario in {
                    "invalid_session_resumable",
                    "invalid_session_fresh",
                }:
                    await handle_lifecycle("disconnected")
                    resumed = scenario == "invalid_session_resumable"
                    continue
                if scenario == "close_4014":
                    raise DiscordGatewayIntentsError(
                        "Discord rejected the required Message Content intent."
                    )
                if scenario != "open":
                    raise DiscordGatewayError(
                        "Discord deterministic Gateway scenario is unsupported."
                    )
                await handle_lifecycle("resumed" if resumed else "ready")
                for dispatch in _object_list(payload, "dispatches"):
                    event_type = _required_string(dispatch, "event_type")
                    event_payload = _required_object(dispatch, "payload")
                    if event_type == "GUILD_CREATE":
                        _capture_gateway_guild(
                            event_payload,
                            channel_names=channel_names,
                            managed_roles=managed_roles,
                        )
                        continue
                    if event_type != "MESSAGE_CREATE":
                        continue
                    projection_source = dict(event_payload)
                    channel_id = _required_string(projection_source, "channel_id")
                    channel_name = channel_names.get(channel_id)
                    if channel_name is not None:
                        projection_source["channel_name"] = channel_name
                    role_mentions = projection_source.get("mention_roles")
                    if isinstance(role_mentions, list):
                        projected_roles = [
                            {"id": role_id, "bot_user_id": managed_roles[role_id]}
                            for role_id in role_mentions
                            if isinstance(role_id, str) and role_id in managed_roles
                        ]
                        if connected_bot_user_id is not None:
                            projected_roles = [
                                item
                                for item in projected_roles
                                if item["bot_user_id"] == connected_bot_user_id
                            ]
                        if projected_roles:
                            projection_source["managed_bot_role_mentions"] = (
                                projected_roles
                            )
                    projection = project_discord_message(
                        message=projection_source,
                        guild_id=target_guild_id,
                    )
                    await handle_event(
                        DiscordGatewayMessageEvent(
                            event_type="message_create",
                            guild_id=target_guild_id,
                            channel_id=channel_id,
                            message=projection,
                        )
                    )
                while True:
                    await asyncio.sleep(_MAX_GATEWAY_IDLE_SECONDS)


async def _gateway_attempt(
    client: httpx.AsyncClient,
    url: str,
    *,
    target_guild_id: str,
    resumed: bool,
) -> dict[str, object]:
    try:
        response = await client.post(
            url,
            json={"target_guild_id": target_guild_id, "resumed": resumed},
        )
    except (httpx.HTTPError, OSError) as error:
        raise DiscordGatewayError(
            "Discord deterministic Gateway fixture is unavailable."
        ) from error
    if response.status_code == 401:
        raise DiscordGatewayCredentialError(
            "Discord rejected the configured Bot credential."
        )
    if response.status_code >= 400:
        raise DiscordGatewayError(
            "Discord deterministic Gateway fixture is unavailable."
        )
    try:
        payload: object = response.json()
    except ValueError as error:
        raise DiscordGatewayError(
            "Discord deterministic Gateway fixture response is invalid."
        ) from error
    if not isinstance(payload, dict):
        raise DiscordGatewayError(
            "Discord deterministic Gateway fixture response is invalid."
        )
    return cast(dict[str, object], payload)


def _fixture_sdk_error(response: httpx.Response) -> DiscordSDKError:
    if response.status_code == 401:
        return DiscordSDKCredentialsInvalid()
    if response.status_code == 403:
        return DiscordSDKPermissionDenied()
    if response.status_code == 404:
        return DiscordSDKResourceUnavailable()
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After", "1")
        return DiscordSDKRateLimited(int(retry_after) if retry_after.isdigit() else 1)
    if response.status_code >= 500:
        return DiscordSDKUnavailable()
    return DiscordSDKRequestRejected()


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise DiscordSDKUnavailable(f"Discord SDK fixture field '{key}' is invalid.")
    return value


def _required_object(
    payload: Mapping[str, object],
    key: str,
) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise DiscordSDKUnavailable(f"Discord SDK fixture field '{key}' is invalid.")
    return cast(dict[str, object], value)


def _object_list(
    payload: Mapping[str, object],
    key: str,
) -> list[dict[str, object]]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise DiscordSDKUnavailable(f"Discord SDK fixture field '{key}' is invalid.")
    return [cast(dict[str, object], item) for item in value]


def _command(payload: Mapping[str, object]) -> DiscordSDKCommand:
    command_type = payload.get("type")
    description = payload.get("description")
    if not isinstance(command_type, int) or isinstance(command_type, bool):
        raise DiscordSDKUnavailable("Discord SDK fixture command is invalid.")
    return DiscordSDKCommand(
        command_id=_required_string(payload, "id"),
        name=_required_string(payload, "name"),
        command_type=command_type,
        description=description if isinstance(description, str) else None,
    )


def _thread(payload: Mapping[str, object]) -> DiscordSDKThread:
    return DiscordSDKThread(
        thread_id=_required_string(payload, "id"),
        parent_id=_required_string(payload, "parent_id"),
        guild_id=_required_string(payload, "guild_id"),
        name=_required_string(payload, "name"),
    )


def _message(payload: Mapping[str, object]) -> DiscordSDKMessage:
    return DiscordSDKMessage(
        message_id=_required_string(payload, "id"),
        channel_id=_required_string(payload, "channel_id"),
        guild_id=_required_string(payload, "guild_id"),
    )


def _history_projection(
    payload: Mapping[str, object],
    *,
    guild_id: str,
    source_channel_id: str,
    channel_id: str,
) -> dict[str, object]:
    source = dict(payload)
    if channel_id != source_channel_id:
        source["thread"] = {"id": channel_id, "parent_id": source_channel_id}
    return project_discord_message(message=source, guild_id=guild_id)


def _capture_gateway_guild(
    payload: Mapping[str, object],
    *,
    channel_names: dict[str, str],
    managed_roles: dict[str, str],
) -> None:
    channels = payload.get("channels")
    if isinstance(channels, list):
        for raw_channel in channels:
            if not isinstance(raw_channel, dict):
                continue
            channel = cast(dict[str, object], raw_channel)
            channel_id = channel.get("id")
            name = channel.get("name")
            if isinstance(channel_id, str) and isinstance(name, str):
                channel_names[channel_id] = name
    roles = payload.get("roles")
    if isinstance(roles, list):
        for raw_role in roles:
            if not isinstance(raw_role, dict):
                continue
            role = cast(dict[str, object], raw_role)
            role_id = role.get("id")
            tags = role.get("tags")
            if not isinstance(role_id, str) or not isinstance(tags, dict):
                continue
            bot_id = cast(dict[str, object], tags).get("bot_id")
            if isinstance(bot_id, str):
                managed_roles[role_id] = bot_id
