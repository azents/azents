"""Production-boundary tests for the public discord.py adapter."""

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord
import pytest
from discord import app_commands

from azents.services.external_channel import discord_sdk
from azents.services.external_channel.discord_sdk import (
    DiscordSDKCredentialsInvalid,
    DiscordSDKMessage,
    DiscordSDKPermissionDenied,
    DiscordSDKRequestRejected,
    DiscordSDKUnavailable,
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


def _channel(
    channel_type: type[discord.TextChannel] | type[discord.Thread],
    *,
    channel_id: int,
    guild_id: int = 111,
    parent_id: int | None = None,
) -> MagicMock:
    channel = MagicMock(spec=channel_type)
    channel.id = channel_id
    channel.guild.id = guild_id
    if channel_type is discord.Thread:
        channel.parent_id = parent_id
    channel.fetch_message = AsyncMock()
    channel.history = MagicMock()
    return channel


def _session(channel: object) -> discord_sdk._DiscordPySession:
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(return_value=channel)
    return discord_sdk._DiscordPySession(cast(discord.Client, client))


@pytest.mark.asyncio
async def test_native_forward_uses_exact_public_thread_message() -> None:
    """Forwarding uses public SDK objects and the exact created Message identity."""
    source = _channel(discord.Thread, channel_id=300, parent_id=200)
    destination = _channel(discord.TextChannel, channel_id=200)
    forwarded = MagicMock(spec=discord.Message)
    forwarded.id = 401
    forwarded.channel = destination
    forwarded.guild = destination.guild
    partial = source.get_partial_message.return_value
    partial.forward = AsyncMock(return_value=forwarded)
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(side_effect=[source, destination])
    session = discord_sdk._DiscordPySession(cast(discord.Client, client))

    result = await session.forward_message(
        message=DiscordSDKMessage("400", "300", "111"),
        destination_channel_id="200",
    )

    assert result == DiscordSDKMessage("401", "200", "111")
    assert client.fetch_channel.await_args_list == [
        ((300,),),
        ((200,),),
    ]
    source.get_partial_message.assert_called_once_with(400)
    partial.forward.assert_awaited_once_with(destination)


@pytest.mark.asyncio
async def test_native_forward_rejects_a_non_parent_destination() -> None:
    """A caller cannot forward a Thread message to an unrelated channel."""
    source = _channel(discord.Thread, channel_id=300, parent_id=200)
    destination = _channel(discord.TextChannel, channel_id=999)
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(side_effect=[source, destination])
    session = discord_sdk._DiscordPySession(cast(discord.Client, client))

    with pytest.raises(DiscordSDKRequestRejected):
        await session.forward_message(
            message=DiscordSDKMessage("400", "300", "111"),
            destination_channel_id="999",
        )

    source.get_partial_message.assert_not_called()


@pytest.mark.asyncio
async def test_command_update_rejects_changed_response_identity() -> None:
    """A public command edit cannot change the listed command identity."""
    channel = _channel(discord.TextChannel, channel_id=300)
    session = _session(channel)
    command = MagicMock(spec=app_commands.AppCommand)
    command.id = 700
    command.type.value = 1
    command.application_id = 100
    command.guild_id = 111
    command.edit = AsyncMock()
    changed = MagicMock(spec=app_commands.AppCommand)
    changed.id = 701
    changed.type.value = 1
    changed.application_id = 100
    changed.guild_id = 111
    changed.name = "azents"
    changed.description = "Configure Azents settings."
    command.edit.return_value = changed
    session._commands["700"] = command  # noqa: SLF001

    with pytest.raises(DiscordSDKRequestRejected):
        await session.update_guild_command(
            command_id="700",
            name="azents",
            command_type=1,
            description="Configure Azents settings.",
        )


@pytest.mark.asyncio
async def test_command_list_rejects_changed_guild_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A listed command cannot change the guild route used by later mutations."""
    client = MagicMock(spec=discord.Client)
    client.application_id = 100
    command = MagicMock(spec=app_commands.AppCommand)
    command.id = 700
    command.type.value = 1
    command.application_id = 100
    command.guild_id = None
    command.name = "azents"
    command.description = "Configure Azents settings."
    tree = MagicMock(spec=app_commands.CommandTree)
    tree.fetch_commands = AsyncMock(return_value=[command])
    command_tree = MagicMock(return_value=tree)
    monkeypatch.setattr(app_commands, "CommandTree", command_tree)
    session = discord_sdk._DiscordPySession(cast(discord.Client, client))

    with pytest.raises(DiscordSDKRequestRejected):
        await session.list_guild_commands(
            application_id="100",
            guild_id="111",
        )

    assert session._commands == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_thread_projection_rejects_empty_name() -> None:
    """Malformed provider Thread data cannot erase the required display name."""
    thread = _channel(discord.Thread, channel_id=300, parent_id=200)
    thread.name = ""
    session = _session(thread)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_thread(
            guild_id="111",
            channel_id="300",
        )


@pytest.mark.asyncio
async def test_message_update_rejects_changed_response_identity() -> None:
    """A public Message edit cannot change the requested Message identity."""
    channel = _channel(discord.TextChannel, channel_id=300)
    session = _session(channel)
    current = MagicMock(spec=discord.Message)
    current.id = 400
    current.channel = channel
    current.guild = channel.guild
    changed = MagicMock(spec=discord.Message)
    changed.id = 401
    changed.channel = channel
    changed.guild = channel.guild
    current.edit = AsyncMock(return_value=changed)
    channel.fetch_message.return_value = current

    with pytest.raises(DiscordSDKRequestRejected):
        await session.update_message(
            guild_id="111",
            channel_id="300",
            message_id="400",
            content="updated",
            components=None,
            embeds=None,
        )


@pytest.mark.asyncio
async def test_root_thread_rejects_changed_parent_identity() -> None:
    """A public root-message response cannot return an unrelated Thread."""
    channel = _channel(discord.TextChannel, channel_id=300)
    session = _session(channel)
    message = MagicMock(spec=discord.Message)
    message.id = 400
    message.channel = channel
    message.guild = channel.guild
    thread = _channel(discord.Thread, channel_id=600, parent_id=999)
    thread.name = "Azents"
    message.thread = thread
    channel.fetch_message.return_value = message

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_root_thread(
            guild_id="111",
            parent_channel_id="300",
            root_message_id="400",
        )


@pytest.mark.asyncio
async def test_channel_invalid_data_maps_to_sdk_error() -> None:
    """Malformed public channel data remains inside the adapter error contract."""
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(side_effect=discord.InvalidData("invalid channel"))
    session = discord_sdk._DiscordPySession(cast(discord.Client, client))

    with pytest.raises(DiscordSDKUnavailable):
        await session.fetch_message_projection(
            guild_id="111",
            source_channel_id="300",
            channel_id="300",
            message_id="400",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel",
    [
        _channel(discord.TextChannel, channel_id=300),
        _channel(discord.Thread, channel_id=300, parent_id=999),
        _channel(discord.Thread, channel_id=300, guild_id=222, parent_id=200),
    ],
)
async def test_message_history_rejects_invalid_channel_thread_relationships(
    channel: MagicMock,
) -> None:
    """History cannot cross channel type, Thread parent, or Guild boundaries."""
    session = _session(channel)

    with pytest.raises(DiscordSDKRequestRejected):
        await session.fetch_message_projection(
            guild_id="111",
            source_channel_id="200",
            channel_id="300",
            message_id="400",
        )

    channel.fetch_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_history_projection_uses_validated_thread_parent() -> None:
    """A valid Thread reaches history only after its actual parent is proven."""
    channel = _channel(discord.Thread, channel_id=300, parent_id=200)
    session = _session(channel)
    message = MagicMock(spec=discord.Message)
    message.id = 400
    message.channel = channel
    message.guild = channel.guild
    message.content = "hello"
    message.created_at.isoformat.return_value = "2026-08-09T00:00:00+00:00"
    message.author.id = 500
    message.author.name = "person"
    message.author.bot = False
    message.author.system = False
    message.author.global_name = None
    message.mentions = []
    message.attachments = []
    message.edited_at = None
    message.embeds = []

    async def history(**_: object) -> AsyncIterator[discord.Message]:
        yield cast(discord.Message, message)

    channel.history = history

    projections = await session.fetch_history_projections(
        guild_id="111",
        source_channel_id="200",
        channel_id="300",
        before_message_id="401",
        limit=100,
    )

    assert projections[0]["thread"] == {"id": "300", "parent_id": "200"}
