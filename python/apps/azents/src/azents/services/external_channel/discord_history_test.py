"""Deterministic Discord bounded-history adapter tests."""

import httpx
import pytest

from azents.services.external_channel.discord_history import (
    DiscordConversationHistoryClient,
    DiscordHistoryRateLimited,
    DiscordHistoryResponseMalformed,
)


@pytest.mark.asyncio
async def test_root_history_fetches_only_the_canonical_source_message() -> None:
    """An unthreaded root never imports unrelated parent-channel history."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "100",
                "channel_id": "200",
                "content": "Need help",
                "author": {"id": "300"},
                "timestamp": "2026-07-28T00:00:00.000000+00:00",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        page = await DiscordConversationHistoryClient(http_client).fetch_thread_page(
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
    assert page.next_cursor is None
    assert calls[0].url.path == "/api/v10/channels/200/messages/100"
    assert calls[0].headers["Authorization"] == "Bot discord-secret"


@pytest.mark.asyncio
async def test_root_history_rejects_a_cross_channel_root_response() -> None:
    """A matching root id from another channel cannot enter hydration."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"id": "100", "channel_id": "999"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordHistoryResponseMalformed):
            await DiscordConversationHistoryClient(client).fetch_thread_page(
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
async def test_thread_history_rejects_unrelated_channel_items_without_projection() -> (
    None
):
    """A page crossing channels is rejected before any item is normalized."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=[{"id": "200", "channel_id": "999"}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordHistoryResponseMalformed):
            await DiscordConversationHistoryClient(client).fetch_thread_page(
                bot_token="discord-secret",
                guild_id="111",
                source_channel_id="200",
                root_message_id="100",
                thread_channel_id="444",
                cursor=None,
                limit=100,
                connected_bot_user_id="900",
            )


@pytest.mark.asyncio
async def test_thread_history_pages_backward_with_a_bounded_cursor() -> None:
    """An existing Discord thread uses a stable oldest-message cursor."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json=[
                {
                    "id": "200",
                    "channel_id": "444",
                    "content": "later",
                    "author": {"id": "300"},
                },
                {
                    "id": "100",
                    "channel_id": "444",
                    "content": "earlier",
                    "author": {"id": "301"},
                },
            ],
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        page = await DiscordConversationHistoryClient(http_client).fetch_thread_page(
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
    assert calls[0].url.path == "/api/v10/channels/444/messages"
    assert calls[0].url.params == httpx.QueryParams({"limit": "2", "before": "300"})


@pytest.mark.asyncio
async def test_thread_history_rejects_more_items_than_requested_limit() -> None:
    """Oversized pages are rejected before any hydration projection."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                {"id": "200", "channel_id": "444"},
                {"id": "100", "channel_id": "444"},
            ],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordHistoryResponseMalformed):
            await DiscordConversationHistoryClient(client).fetch_thread_page(
                bot_token="discord-secret",
                guild_id="111",
                source_channel_id="200",
                root_message_id="100",
                thread_channel_id="444",
                cursor=None,
                limit=1,
                connected_bot_user_id="900",
            )


@pytest.mark.asyncio
async def test_history_rejects_oversized_message_before_projection() -> None:
    """An oversized message body cannot enter normalized hydration state."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[{"id": "200", "channel_id": "444", "content": "x" * 70000}],
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(DiscordHistoryResponseMalformed):
            await DiscordConversationHistoryClient(client).fetch_thread_page(
                bot_token="discord-secret",
                guild_id="111",
                source_channel_id="200",
                root_message_id="100",
                thread_channel_id="444",
                cursor=None,
                limit=100,
                connected_bot_user_id="900",
            )


@pytest.mark.asyncio
async def test_history_rate_limit_has_a_bounded_retry_delay() -> None:
    """Provider retry metadata becomes a bounded controlled error."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, json={"retry_after": 2.9})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        with pytest.raises(DiscordHistoryRateLimited) as raised:
            await DiscordConversationHistoryClient(http_client).fetch_thread_page(
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
