"""Production-boundary tests for the pinned discord.py private HTTP adapter."""

import inspect
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import discord.http
import pytest

from azents.services.external_channel import discord_sdk
from azents.services.external_channel.discord_sdk import (
    DiscordSDKCredentialsInvalid,
    DiscordSDKPermissionDenied,
    DiscordSDKRequestRejected,
)


def _http_error(status: int) -> discord.HTTPException:
    response = MagicMock()
    response.status = status
    response.reason = "rejected"
    return discord.HTTPException(response, "rejected")


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, DiscordSDKCredentialsInvalid),
        (403, DiscordSDKPermissionDenied),
    ],
)
def test_http_auth_statuses_retain_credentials_permission_distinction(
    status: int,
    expected: type[Exception],
) -> None:
    """HTTP authentication failures retain their provider classification."""
    assert isinstance(discord_sdk._sdk_error(_http_error(status)), expected)


@dataclass
class _PrivateHTTP:
    application_info: AsyncMock = field(default_factory=AsyncMock)
    get_guild_commands: AsyncMock = field(default_factory=AsyncMock)
    edit_guild_command: AsyncMock = field(default_factory=AsyncMock)
    delete_guild_command: AsyncMock = field(default_factory=AsyncMock)
    get_channel: AsyncMock = field(default_factory=AsyncMock)
    get_message: AsyncMock = field(default_factory=AsyncMock)
    logs_from: AsyncMock = field(default_factory=AsyncMock)
    start_thread_with_message: AsyncMock = field(default_factory=AsyncMock)
    edit_channel: AsyncMock = field(default_factory=AsyncMock)
    send_message: AsyncMock = field(default_factory=AsyncMock)
    edit_message: AsyncMock = field(default_factory=AsyncMock)
    delete_message: AsyncMock = field(default_factory=AsyncMock)


def _session(http: _PrivateHTTP) -> discord_sdk._DiscordPySession:
    client = MagicMock()
    client.http = http
    client.application_id = 111
    return discord_sdk._DiscordPySession(client)


def _message(
    *,
    message_id: str = "400",
    channel_id: str = "300",
) -> dict[str, object]:
    return {
        "id": message_id,
        "channel_id": channel_id,
        "content": "hello",
        "timestamp": "2026-08-09T00:00:00+00:00",
        "author": {
            "id": "500",
            "username": "person",
        },
        "mentions": [],
        "attachments": [],
        "embeds": [],
    }


@pytest.mark.asyncio
async def test_history_uses_private_message_routes_without_channel_prefetch() -> None:
    """History projects raw private HTTP responses without fetching a channel."""
    http = _PrivateHTTP()
    http.get_message.return_value = _message()
    http.logs_from.return_value = [_message(message_id="399")]
    session = _session(http)

    exact = await session.fetch_message_projection(
        guild_id="111",
        source_channel_id="200",
        channel_id="300",
        message_id="400",
    )
    history = await session.fetch_history_projections(
        guild_id="111",
        source_channel_id="200",
        channel_id="300",
        before_message_id="400",
        limit=100,
    )

    assert exact["thread"] == {"id": "300", "parent_id": "200"}
    assert history[0]["thread"] == {"id": "300", "parent_id": "200"}
    http.get_message.assert_awaited_once_with(300, 400)
    http.logs_from.assert_awaited_once_with(300, 100, before=400)
    http.get_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_message_mutations_do_not_prefetch_resources() -> None:
    """Message create, update, and delete use direct private HTTP methods."""
    http = _PrivateHTTP()
    http.send_message.return_value = _message(message_id="401")
    http.edit_message.return_value = _message(message_id="401")
    session = _session(http)

    created = await session.create_message(
        guild_id="111",
        channel_id="300",
        content="hello",
        nonce="nonce-1",
        components=None,
        embeds=None,
    )
    updated = await session.update_message(
        guild_id="111",
        channel_id="300",
        message_id="401",
        content="updated",
        components=[],
        embeds=[],
    )
    await session.delete_message(
        guild_id="111",
        channel_id="300",
        message_id="401",
    )

    assert created.message_id == "401"
    assert updated.message_id == "401"
    assert http.send_message.await_count == 1
    assert http.send_message.await_args is not None
    create_params = http.send_message.await_args.kwargs["params"]
    assert create_params.payload["nonce"] == "nonce-1"
    assert create_params.payload["enforce_nonce"] is True
    assert http.edit_message.await_count == 1
    http.delete_message.assert_awaited_once_with(300, 401)
    http.get_channel.assert_not_awaited()
    http.get_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_thread_routes_validate_expected_identity() -> None:
    """Thread operations retain Guild, parent, identity, and name validation."""
    http = _PrivateHTTP()
    thread = {
        "id": "600",
        "parent_id": "300",
        "guild_id": "111",
        "name": "Azents",
        "type": 11,
    }
    http.start_thread_with_message.return_value = thread
    http.get_channel.return_value = thread
    http.edit_channel.return_value = {**thread, "name": "Updated"}
    session = _session(http)

    created = await session.create_thread(
        guild_id="111",
        parent_channel_id="300",
        root_message_id="400",
        name="Azents",
        auto_archive_duration=60,
    )
    fetched = await session.fetch_thread(guild_id="111", channel_id="600")
    updated = await session.update_thread_name(
        guild_id="111",
        channel_id="600",
        name="Updated",
    )

    assert created.thread_id == fetched.thread_id == updated.thread_id == "600"
    http.start_thread_with_message.assert_awaited_once_with(
        300,
        400,
        name="Azents",
        auto_archive_duration=60,
    )
    http.edit_channel.assert_awaited_once_with(600, name="Updated")


@pytest.mark.asyncio
async def test_private_command_routes_reuse_list_scope() -> None:
    """Command mutation uses the Application and Guild proven by the current list."""
    http = _PrivateHTTP()
    command = {
        "id": "700",
        "name": "azents",
        "type": 1,
        "description": "old",
    }
    http.get_guild_commands.return_value = [command]
    http.edit_guild_command.return_value = {
        **command,
        "description": "Configure Azents settings.",
    }
    session = _session(http)

    listed = await session.list_guild_commands(
        application_id="111",
        guild_id="222",
    )
    updated = await session.update_guild_command(
        command_id="700",
        name="azents",
        command_type=1,
        description="Configure Azents settings.",
    )
    await session.delete_guild_command(command_id="700")

    assert listed[0].command_id == updated.command_id == "700"
    http.get_guild_commands.assert_awaited_once_with(111, 222)
    http.edit_guild_command.assert_awaited_once_with(
        111,
        222,
        700,
        {
            "name": "azents",
            "description": "Configure Azents settings.",
        },
    )
    http.delete_guild_command.assert_awaited_once_with(111, 222, 700)


@pytest.mark.asyncio
async def test_private_command_update_rejects_changed_response_identity() -> None:
    """A command mutation response cannot change the listed command identity."""
    http = _PrivateHTTP()
    command = {
        "id": "700",
        "name": "azents",
        "type": 1,
        "description": "old",
    }
    http.get_guild_commands.return_value = [command]
    http.edit_guild_command.return_value = {
        **command,
        "id": "701",
        "description": "Configure Azents settings.",
    }
    session = _session(http)
    await session.list_guild_commands(application_id="111", guild_id="222")

    with pytest.raises(DiscordSDKRequestRejected):
        await session.update_guild_command(
            command_id="700",
            name="azents",
            command_type=1,
            description="Configure Azents settings.",
        )


@pytest.mark.asyncio
async def test_private_attachment_lookup_validates_current_message() -> None:
    """Attachment metadata comes directly from one exact private Message response."""
    http = _PrivateHTTP()
    http.get_message.return_value = {
        **_message(),
        "attachments": [
            {
                "id": "800",
                "filename": "report.txt",
                "size": 12,
                "content_type": "text/plain",
                "url": "https://cdn.discordapp.com/attachments/1/2/report.txt",
            }
        ],
    }
    session = _session(http)

    attachment = await session.fetch_attachment(
        guild_id="111",
        channel_id="300",
        message_id="400",
        attachment_id="800",
    )

    assert attachment.filename == "report.txt"
    http.get_message.assert_awaited_once_with(300, 400)
    http.get_channel.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_history_rejects_cross_channel_response() -> None:
    """A private Message response cannot cross the requested channel boundary."""
    http = _PrivateHTTP()
    http.get_message.return_value = _message(channel_id="999")
    session = _session(http)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_message_projection(
            guild_id="111",
            source_channel_id="300",
            channel_id="300",
            message_id="400",
        )


def test_private_http_signatures_match_pinned_discord_release() -> None:
    """Pinned private methods retain the exact adapter call shapes."""
    expected = {
        "get_guild_commands": ("self", "application_id", "guild_id"),
        "edit_guild_command": (
            "self",
            "application_id",
            "guild_id",
            "command_id",
            "payload",
        ),
        "delete_guild_command": (
            "self",
            "application_id",
            "guild_id",
            "command_id",
        ),
        "get_channel": ("self", "channel_id"),
        "edit_channel": ("self", "channel_id", "reason", "options"),
        "get_message": ("self", "channel_id", "message_id"),
        "logs_from": (
            "self",
            "channel_id",
            "limit",
            "before",
            "after",
            "around",
        ),
        "send_message": ("self", "channel_id", "params"),
        "edit_message": ("self", "channel_id", "message_id", "params"),
        "delete_message": ("self", "channel_id", "message_id", "reason"),
        "start_thread_with_message": (
            "self",
            "channel_id",
            "message_id",
            "name",
            "auto_archive_duration",
            "rate_limit_per_user",
            "reason",
        ),
    }

    for method_name, parameters in expected.items():
        method: Any = getattr(discord.http.HTTPClient, method_name)
        assert tuple(inspect.signature(method).parameters) == parameters

    assert tuple(
        inspect.signature(discord.http.handle_message_parameters).parameters
    ) == (
        "content",
        "username",
        "avatar_url",
        "tts",
        "nonce",
        "flags",
        "file",
        "files",
        "embed",
        "embeds",
        "attachments",
        "view",
        "allowed_mentions",
        "message_reference",
        "stickers",
        "previous_allowed_mentions",
        "mention_author",
        "thread_name",
        "channel_payload",
        "applied_tags",
        "poll",
    )
