"""Deterministic Discord bounded-history adapter tests."""

import datetime

import httpx
import pytest

from azents.services.external_channel.conversation import (
    ExternalChannelHistoryDeadlineExceeded,
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
                "embeds": [
                    {
                        "title": "Incident",
                        "description": "A visible provider card.",
                        "url": "https://untrusted.example/card",
                        "image": {"url": "https://cdn.discordapp.com/incident.png"},
                    }
                ],
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
    assert calls[0].url.path == "/api/v10/channels/200/messages/100"
    assert calls[0].headers["Authorization"] == "Bot discord-secret"


@pytest.mark.asyncio
async def test_read_range_orders_and_bounds_after_bot_exclusion() -> None:
    """Discord ranges exclude the connected Bot before applying the context bound."""
    raw_messages = [
        {
            "id": str(message_id),
            "channel_id": "200",
            "content": f"message-{message_id}",
            "author": {"id": "900" if message_id == 101 else str(message_id + 1000)},
            "timestamp": "2026-07-28T00:00:00.000000+00:00",
        }
        for message_id in range(121, 99, -1)
    ]

    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/121"):
            return httpx.Response(200, json=raw_messages[0])
        return httpx.Response(200, json=raw_messages[1:])

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DiscordConversationHistoryClient(client).read_range(
            trigger=DiscordConversationHistoryTrigger(
                guild_id="111",
                source_channel_id="200",
                conversation_channel_id="200",
                trigger_message_id="121",
                connected_bot_user_id="900",
            ),
            bot_token="discord-secret",
            exclusive_start_position=None,
            deadline=deadline,
        )

    assert result.context_omitted is True
    assert len(result.messages) == 20
    assert result.messages[0].message_id == "102"
    assert result.messages[-1].message_id == "121"
    assert all(message.provider_user_id != "900" for message in result.messages)
    assert [message.provider_position for message in result.messages] == sorted(
        message.provider_position for message in result.messages
    )
    assert result.trigger.message_id == "121"
    assert result.trigger_position == discord_provider_position("121")
    assert result.scanned_message_count == 21
    assert [request.url.path for request in calls] == [
        "/api/v10/channels/200/messages/121",
        "/api/v10/channels/200/messages",
    ]
    assert calls[0].headers["Authorization"] == "Bot discord-secret"
    assert calls[1].url.params == httpx.QueryParams({"limit": "100", "before": "121"})


@pytest.mark.asyncio
async def test_read_range_requires_exact_trigger() -> None:
    """A complete page without the trigger is not accepted as a range."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/121"):
            return httpx.Response(
                200,
                json={
                    "id": "120",
                    "channel_id": "200",
                    "content": "message-120",
                    "author": {"id": "1000"},
                    "timestamp": "2026-07-28T00:00:00.000000+00:00",
                },
            )
        return httpx.Response(
            200,
            json=[
                {
                    "id": "120",
                    "channel_id": "200",
                    "content": "message-120",
                    "author": {"id": "1000"},
                    "timestamp": "2026-07-28T00:00:00.000000+00:00",
                }
            ],
        )

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryTriggerMissing):
            await DiscordConversationHistoryClient(client).read_range(
                trigger=DiscordConversationHistoryTrigger(
                    guild_id="111",
                    source_channel_id="200",
                    conversation_channel_id="200",
                    trigger_message_id="121",
                    connected_bot_user_id="900",
                ),
                bot_token="discord-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )


@pytest.mark.asyncio
async def test_read_range_checks_expired_deadline_before_request() -> None:
    """An expired range budget does not construct a Discord request."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("expired history must not reach the provider")

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryDeadlineExceeded):
            await DiscordConversationHistoryClient(client).read_range(
                trigger=DiscordConversationHistoryTrigger(
                    guild_id="111",
                    source_channel_id="200",
                    conversation_channel_id="200",
                    trigger_message_id="121",
                    connected_bot_user_id=None,
                ),
                bot_token="discord-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )

    assert calls == []


@pytest.mark.asyncio
async def test_read_range_maps_invalid_start_position() -> None:
    """Discord snowflake cursors use the typed invalid-position failure."""
    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        with pytest.raises(ExternalChannelHistoryPositionInvalid):
            await DiscordConversationHistoryClient(client).read_range(
                trigger=DiscordConversationHistoryTrigger(
                    guild_id="111",
                    source_channel_id="200",
                    conversation_channel_id="200",
                    trigger_message_id="121",
                    connected_bot_user_id=None,
                ),
                bot_token="discord-secret",
                exclusive_start_position="not-a-snowflake",
                deadline=deadline,
            )


@pytest.mark.asyncio
async def test_read_range_maps_provider_rate_limit() -> None:
    """Discord range provider failures retain the typed retry classification."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(429, json={"retry_after": 2})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryRateLimited) as raised:
            await DiscordConversationHistoryClient(client).read_range(
                trigger=DiscordConversationHistoryTrigger(
                    guild_id="111",
                    source_channel_id="200",
                    conversation_channel_id="200",
                    trigger_message_id="121",
                    connected_bot_user_id=None,
                ),
                bot_token="discord-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )

    assert raised.value.retry_after_seconds == 2


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
