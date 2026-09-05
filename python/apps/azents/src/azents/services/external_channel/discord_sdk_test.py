"""Production-boundary tests for the pinned discord.py private HTTP adapter."""

import inspect
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import aiohttp
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


@pytest.mark.asyncio
async def test_deferred_interaction_response_edits_original_via_public_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Complete deferred ACKs through the request-local interaction webhook."""
    session = MagicMock(spec=aiohttp.ClientSession)
    webhook = MagicMock(spec=discord.Webhook)
    webhook.edit_message = AsyncMock()
    partial = MagicMock(return_value=webhook)
    monkeypatch.setattr(discord.Webhook, "partial", partial)
    client = discord_sdk.DiscordPyInteractionResponseClient(session)

    await client.edit_original(
        application_id="100000000000000001",
        interaction_token="request-local-token",
        response={
            "type": 7,
            "data": {
                "content": "Settings saved.",
                "embeds": [{"title": "Settings saved"}],
                "components": [],
            },
        },
    )

    partial.assert_called_once_with(
        100000000000000001,
        "request-local-token",
        session=session,
    )
    call = webhook.edit_message.await_args
    assert call is not None
    assert call.args == ("@original",)
    assert call.kwargs["content"] == "Settings saved."
    assert len(call.kwargs["embeds"]) == 1
    assert call.kwargs["view"] is None


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


def _channel(
    *,
    channel_id: str = "300",
    guild_id: str = "111",
    channel_type: int = 0,
    parent_id: str | None = None,
    name: str = "general",
) -> dict[str, object]:
    return {
        "id": channel_id,
        "guild_id": guild_id,
        "type": channel_type,
        "parent_id": parent_id,
        "name": name,
    }


@pytest.mark.asyncio
async def test_history_reuses_one_validated_private_channel_scope() -> None:
    """History validates Thread ancestry once for adjacent private routes."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel(
        channel_type=11,
        parent_id="200",
        name="incident",
    )
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
    http.get_channel.assert_awaited_once_with(300)
    http.get_message.assert_awaited_once_with(300, 400)
    http.logs_from.assert_awaited_once_with(300, 100, before=400)


@pytest.mark.asyncio
async def test_private_message_mutations_reuse_validated_channel_scope() -> None:
    """Message mutations validate one Guild channel across one SDK session."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel()
    http.send_message.return_value = _message(message_id="401")
    http.edit_message.return_value = _message(message_id="401")
    session = _session(http)

    created = await session.create_message(
        guild_id="111",
        channel_id="300",
        content="hello",
        nonce="nonce-1",
        suppress_notifications=False,
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
    http.get_channel.assert_awaited_once_with(300)
    http.get_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_create_can_suppress_notifications() -> None:
    """Silent standalone Trackers set Discord's notification-suppression flag."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel()
    http.send_message.return_value = _message(message_id="401")
    session = _session(http)

    await session.create_message(
        guild_id="111",
        channel_id="300",
        content="Tracker",
        nonce="nonce-silent",
        suppress_notifications=True,
        components=None,
        embeds=[{"description": "progress"}],
    )

    call = http.send_message.await_args
    assert call is not None
    assert call.kwargs["params"].payload["flags"] == 1 << 12


@pytest.mark.asyncio
async def test_private_update_can_omit_reply_content() -> None:
    """Tracker-only edits preserve the existing conversational reply body."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel()
    http.edit_message.return_value = _message(message_id="401")
    session = _session(http)

    await session.update_message(
        guild_id="111",
        channel_id="300",
        message_id="401",
        content=None,
        components=[],
        embeds=[],
    )

    call = http.edit_message.await_args
    assert call is not None
    payload = call.kwargs["params"].payload
    assert "content" not in payload
    assert payload["components"] == []
    assert payload["embeds"] == []


@pytest.mark.asyncio
async def test_native_forward_uses_exact_public_thread_message() -> None:
    """Forwarding uses public SDK objects and the exact created Message identity."""
    http = _PrivateHTTP()
    session = _session(http)
    source = MagicMock(spec=discord.Thread)
    source.id = 300
    source.parent_id = 200
    source.guild.id = 111
    destination = MagicMock(spec=discord.TextChannel)
    destination.id = 200
    destination.guild.id = 111
    forwarded = MagicMock(spec=discord.Message)
    forwarded.id = 401
    forwarded.channel = destination
    forwarded.guild = destination.guild
    partial = source.get_partial_message.return_value
    partial.forward = AsyncMock(return_value=forwarded)
    session._client.fetch_channel = AsyncMock(  # noqa: SLF001
        side_effect=[source, destination]
    )

    result = await session.forward_message(
        message=discord_sdk.DiscordSDKMessage("400", "300", "111"),
        destination_channel_id="200",
    )

    assert result == discord_sdk.DiscordSDKMessage("401", "200", "111")
    assert session._client.fetch_channel.await_args_list == [  # noqa: SLF001
        ((300,),),
        ((200,),),
    ]
    source.get_partial_message.assert_called_once_with(400)
    partial.forward.assert_awaited_once_with(destination)
    http.get_channel.assert_not_awaited()
    http.get_message.assert_not_awaited()
    http.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_native_forward_rejects_a_non_parent_destination() -> None:
    """A caller cannot forward a Thread message to an unrelated channel."""
    http = _PrivateHTTP()
    session = _session(http)
    source = MagicMock(spec=discord.Thread)
    source.id = 300
    source.parent_id = 200
    source.guild.id = 111
    destination = MagicMock(spec=discord.TextChannel)
    destination.id = 999
    destination.guild.id = 111
    session._client.fetch_channel = AsyncMock(  # noqa: SLF001
        side_effect=[source, destination]
    )

    with pytest.raises(DiscordSDKRequestRejected):
        await session.forward_message(
            message=discord_sdk.DiscordSDKMessage("400", "300", "111"),
            destination_channel_id="999",
        )

    source.get_partial_message.assert_not_called()


@pytest.mark.asyncio
async def test_private_thread_routes_validate_expected_identity() -> None:
    """Thread operations retain Guild, parent, identity, and name validation."""
    http = _PrivateHTTP()
    thread: dict[str, object] = {
        "id": "600",
        "parent_id": "300",
        "guild_id": "111",
        "name": "Azents",
        "type": 11,
    }
    http.start_thread_with_message.return_value = thread

    async def get_channel(channel_id: int) -> dict[str, object]:
        if channel_id == 300:
            return _channel()
        assert channel_id == 600
        return thread

    http.get_channel.side_effect = get_channel
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
    http.get_channel.assert_awaited_once_with(300)


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
    http.get_channel.return_value = _channel()
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
    http.get_channel.assert_awaited_once_with(300)
    http.get_message.assert_awaited_once_with(300, 400)


@pytest.mark.asyncio
async def test_private_history_rejects_cross_channel_response() -> None:
    """A private Message response cannot cross the requested channel boundary."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel()
    http.get_message.return_value = _message(channel_id="999")
    session = _session(http)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_message_projection(
            guild_id="111",
            source_channel_id="300",
            channel_id="300",
            message_id="400",
        )


@pytest.mark.asyncio
async def test_private_message_mutation_rejects_cross_guild_channel() -> None:
    """A channel from another Guild is rejected before message mutation."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel(guild_id="222")
    session = _session(http)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.create_message(
            guild_id="111",
            channel_id="300",
            content="hello",
            nonce="nonce-1",
            suppress_notifications=False,
            components=None,
            embeds=None,
        )

    http.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_history_rejects_unproven_thread_parent() -> None:
    """History cannot synthesize Thread ancestry from caller-supplied IDs."""
    http = _PrivateHTTP()
    http.get_channel.return_value = _channel(
        channel_type=11,
        parent_id="999",
        name="incident",
    )
    session = _session(http)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_history_projections(
            guild_id="111",
            source_channel_id="200",
            channel_id="300",
            before_message_id="400",
            limit=100,
        )

    http.logs_from.assert_not_awaited()


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
