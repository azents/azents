"""Production-boundary tests for the public discord.py adapter."""

from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
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
    message.channel.id = 300
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
