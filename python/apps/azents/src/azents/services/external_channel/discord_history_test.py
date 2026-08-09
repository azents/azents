"""Deterministic Discord public SDK bounded-history adapter tests."""

import contextlib
import datetime
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast

import pytest

from azents.services.external_channel.conversation import (
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
    DiscordConversationHistoryTrigger,
    DiscordHistoryRateLimited,
    DiscordHistoryResponseMalformed,
    discord_provider_position,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKCredentialsInvalid,
    DiscordSDKRateLimited,
    DiscordSDKSession,
)


def _message(
    message_id: int,
    *,
    channel_id: str = "200",
    author_id: str | None = None,
    content: str | None = None,
) -> dict[str, object]:
    return {
        "id": str(message_id),
        "channel_id": channel_id,
        "guild_id": "111",
        "content": content or f"message-{message_id}",
        "author": {"id": author_id or str(message_id + 1000)},
        "timestamp": "2026-07-28T00:00:00.000000+00:00",
    }


@dataclass
class _SDKSession:
    exact: dict[str, object]
    pages: dict[str, tuple[dict[str, object], ...]] = field(default_factory=dict)
    error: Exception | None = None
    calls: list[tuple[str, str, int | None]] = field(default_factory=list)

    async def fetch_message_projection(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        message_id: str,
    ) -> dict[str, object]:
        assert guild_id == "111"
        self.calls.append(("message", message_id, None))
        if self.error is not None:
            raise self.error
        return dict(self.exact)

    async def fetch_history_projections(
        self,
        *,
        guild_id: str,
        source_channel_id: str,
        channel_id: str,
        before_message_id: str,
        limit: int,
    ) -> tuple[dict[str, object], ...]:
        assert guild_id == "111"
        self.calls.append(("history", before_message_id, limit))
        if self.error is not None:
            raise self.error
        return self.pages.get(before_message_id, ())


@dataclass
class _SDKFactory:
    session: _SDKSession
    opens: int = 0

    @contextlib.asynccontextmanager
    async def open(self, *, bot_token: str) -> AsyncIterator[DiscordSDKSession]:
        assert bot_token == "discord-secret"
        self.opens += 1
        yield cast(DiscordSDKSession, self.session)


def _client(
    session: _SDKSession,
) -> tuple[DiscordConversationHistoryClient, _SDKFactory]:
    factory = _SDKFactory(session)
    return DiscordConversationHistoryClient(factory), factory


def _deadline(seconds: float = 1) -> ExternalChannelOperationDeadline:
    return ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=seconds)
    )


@pytest.mark.asyncio
async def test_root_history_fetches_only_canonical_sdk_message() -> None:
    """An unthreaded root never imports unrelated parent-channel history."""
    exact = _message(100, content="Need help")
    exact["embeds"] = [
        {
            "title": "Incident",
            "description": "A visible provider card.",
            "image": {"present": True},
        }
    ]
    session = _SDKSession(exact=exact)
    client, factory = _client(session)

    page = await client.fetch_thread_page(
        bot_token="discord-secret",
        guild_id="111",
        source_channel_id="200",
        root_message_id="100",
        thread_channel_id=None,
        cursor=None,
        limit=100,
        connected_bot_user_id="900",
    )

    assert [message.message_id for message in page.messages] == ["100"]
    assert page.messages[0].attachment_metadata == {
        "embeds": [
            {
                "title": "Incident",
                "description": "A visible provider card.",
                "has_image": True,
            }
        ]
    }
    assert page.next_cursor is None
    assert factory.opens == 1
    assert session.calls == [("message", "100", None)]


@pytest.mark.asyncio
async def test_read_range_orders_and_bounds_after_bot_exclusion() -> None:
    """SDK ranges exclude the connected Bot before the retained-context bound."""
    page = tuple(
        _message(
            message_id,
            author_id="900" if message_id == 101 else None,
        )
        for message_id in range(120, 99, -1)
    )
    session = _SDKSession(
        exact=_message(121),
        pages={"121": page},
    )
    client, factory = _client(session)

    result = await client.read_range(
        trigger=DiscordConversationHistoryTrigger(
            guild_id="111",
            source_channel_id="200",
            conversation_channel_id="200",
            trigger_message_id="121",
            connected_bot_user_id="900",
        ),
        bot_token="discord-secret",
        exclusive_start_position=None,
        deadline=_deadline(),
    )

    assert result.context_omitted is True
    assert len(result.messages) == 20
    assert result.messages[0].message_id == "102"
    assert result.messages[-1].message_id == "121"
    assert all(message.provider_user_id != "900" for message in result.messages)
    assert result.trigger_position == discord_provider_position("121")
    assert result.scanned_message_count == 21
    assert result.provider_request_count == 2
    assert factory.opens == 1
    assert session.calls == [
        ("message", "121", None),
        ("history", "121", 100),
    ]


@pytest.mark.asyncio
async def test_read_range_requires_exact_trigger_identity() -> None:
    """A mismatched exact SDK message cannot become the trigger."""
    client, _ = _client(_SDKSession(exact=_message(120)))

    with pytest.raises(ExternalChannelHistoryTriggerMissing):
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=_deadline(),
        )


@pytest.mark.asyncio
async def test_read_range_checks_deadline_before_opening_sdk() -> None:
    """An expired range budget does not open a provider SDK context."""
    client, factory = _client(_SDKSession(exact=_message(121)))

    with pytest.raises(ExternalChannelHistoryDeadlineExceeded):
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=_deadline(-1),
        )

    assert factory.opens == 0
    assert factory.session.calls == []


@pytest.mark.asyncio
async def test_read_range_maps_invalid_start_before_sdk() -> None:
    """Discord snowflake cursors retain the typed invalid-position failure."""
    client, factory = _client(_SDKSession(exact=_message(121)))

    with pytest.raises(ExternalChannelHistoryPositionInvalid):
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position="not-a-snowflake",
            deadline=_deadline(),
        )

    assert factory.opens == 0


@pytest.mark.asyncio
async def test_read_range_maps_sdk_credentials_invalid() -> None:
    """SDK authentication rejection remains a credentials-invalid failure."""
    session = _SDKSession(
        exact=_message(121),
        error=DiscordSDKCredentialsInvalid(),
    )
    client, _ = _client(session)

    with pytest.raises(ExternalChannelHistoryCredentialsInvalid):
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=_deadline(),
        )


@pytest.mark.asyncio
async def test_read_range_maps_sdk_rate_limit() -> None:
    """SDK rate-limit errors retain the bounded provider classification."""
    session = _SDKSession(
        exact=_message(121),
        error=DiscordSDKRateLimited(2),
    )
    client, _ = _client(session)

    with pytest.raises(ExternalChannelHistoryRateLimited) as raised:
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=_deadline(),
        )

    assert raised.value.retry_after_seconds == 2


@pytest.mark.asyncio
async def test_root_history_rejects_cross_channel_sdk_projection() -> None:
    """A matching root ID from another channel cannot enter hydration."""
    client, _ = _client(_SDKSession(exact=_message(100, channel_id="999")))

    with pytest.raises(DiscordHistoryResponseMalformed):
        await client.fetch_thread_page(
            bot_token="discord-secret",
            guild_id="111",
            source_channel_id="200",
            root_message_id="100",
            thread_channel_id=None,
            cursor=None,
            limit=100,
            connected_bot_user_id="900",
        )


@pytest.mark.asyncio
async def test_thread_history_pages_backward_with_bounded_cursor() -> None:
    """An existing thread uses the requested public SDK history cursor."""
    session = _SDKSession(
        exact=_message(100),
        pages={
            "300": (
                _message(200, channel_id="444"),
                _message(100, channel_id="444"),
            )
        },
    )
    client, _ = _client(session)

    page = await client.fetch_thread_page(
        bot_token="discord-secret",
        guild_id="111",
        source_channel_id="200",
        root_message_id="100",
        thread_channel_id="444",
        cursor="300",
        limit=2,
        connected_bot_user_id="900",
    )

    assert [message.message_id for message in page.messages] == ["200", "100"]
    assert page.next_cursor == "100"
    assert session.calls == [("history", "300", 2)]


@pytest.mark.asyncio
async def test_history_rejects_oversized_projected_message() -> None:
    """An oversized SDK projection cannot enter normalized hydration state."""
    session = _SDKSession(
        exact=_message(100),
        pages={"300": (_message(200, channel_id="444", content="x" * 70000),)},
    )
    client, _ = _client(session)

    with pytest.raises(DiscordHistoryResponseMalformed):
        await client.fetch_thread_page(
            bot_token="discord-secret",
            guild_id="111",
            source_channel_id="200",
            root_message_id="100",
            thread_channel_id="444",
            cursor="300",
            limit=100,
            connected_bot_user_id="900",
        )


@pytest.mark.asyncio
async def test_read_range_maps_oversized_sdk_projection_to_malformed() -> None:
    """SDK projection bounds retain the canonical malformed-history result."""
    session = _SDKSession(
        exact=_message(121),
        pages={"121": (_message(120, content="x" * 70000),)},
    )
    client, _ = _client(session)

    with pytest.raises(ExternalChannelHistoryMalformed):
        await client.read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id=None,
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=_deadline(),
        )


@pytest.mark.asyncio
async def test_fetch_thread_page_maps_sdk_rate_limit() -> None:
    """SDK retry metadata remains a bounded controlled provider error."""
    session = _SDKSession(
        exact=_message(100),
        error=DiscordSDKRateLimited(2),
    )
    client, _ = _client(session)

    with pytest.raises(DiscordHistoryRateLimited) as raised:
        await client.fetch_thread_page(
            bot_token="discord-secret",
            guild_id="111",
            source_channel_id="200",
            root_message_id="100",
            thread_channel_id=None,
            cursor=None,
            limit=100,
            connected_bot_user_id="900",
        )

    assert raised.value.retry_after_seconds == 2
