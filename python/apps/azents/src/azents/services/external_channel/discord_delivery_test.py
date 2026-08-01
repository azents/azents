"""Deterministic Discord message-delivery adapter tests."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordOutboundFile,
    discord_delivery_nonce,
)


@pytest.mark.asyncio
async def test_create_message_uses_a_deterministic_nonce_and_returns_identity() -> None:
    """A durable attempt maps to one provider nonce and canonical message key."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={"id": "555", "channel_id": "333"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        result = await DiscordDeliveryClient(http_client).create_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="Reply",
            delivery_attempt_id="delivery-1",
        )

    assert result.status == "delivered"
    assert result.provider_message_key == "discord:111:555"
    assert calls[0].url == "https://discord.com/api/v10/channels/333/messages"
    assert calls[0].headers["Authorization"] == "Bot discord-secret"
    assert json.loads(calls[0].content) == {
        "content": "Reply",
        "nonce": discord_delivery_nonce("delivery-1"),
        "enforce_nonce": True,
    }
    assert len(discord_delivery_nonce("delivery-1")) == 25


@pytest.mark.asyncio
async def test_create_and_update_message_preserve_rich_embeds_and_components() -> None:
    """Operational messages retain their provider-native rich presentation."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "555", "channel_id": "333"})

    embed: dict[str, object] = {
        "title": "Azents session ready",
        "description": "Continue in the linked session.",
        "color": 0x5865F2,
    }
    components: list[dict[str, object]] = [
        {
            "type": 1,
            "components": [
                {
                    "type": 2,
                    "style": 5,
                    "label": "Open Azents session",
                    "url": "https://azents.example/session",
                }
            ],
        }
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DiscordDeliveryClient(http_client)
        await client.create_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="Your Azents session is ready.",
            delivery_attempt_id="delivery-1",
            embeds=[embed],
            components=components,
        )
        await client.update_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            message_id="555",
            content="",
            embeds=[embed],
        )

    assert json.loads(calls[0].content)["embeds"] == [embed]
    assert json.loads(calls[0].content)["components"] == components
    assert json.loads(calls[1].content) == {
        "content": "",
        "embeds": [embed],
    }


@pytest.mark.asyncio
async def test_ensure_thread_creates_a_missing_root_message_thread() -> None:
    """A parent-channel mention gets a usable thread before any reply."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        return httpx.Response(201, json={"id": "333", "parent_id": "222"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        result = await DiscordDeliveryClient(http_client).ensure_thread(
            bot_token="discord-secret",
            parent_channel_id="222",
            root_message_id="333",
            name=None,
        )

    assert result.status == "delivered"
    assert result.provider_message_key == "discord-thread:333"
    assert [request.url.path for request in calls] == [
        "/api/v10/channels/222/messages/333",
        "/api/v10/channels/222/messages/333/threads",
    ]
    assert json.loads(calls[1].content) == {
        "name": "Azents",
        "auto_archive_duration": 60,
    }


@pytest.mark.asyncio
async def test_ensure_thread_reuses_a_thread_returned_by_the_root_message() -> None:
    """A later durable attempt resolves the same thread without creating another."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "333",
                "channel_id": "222",
                "thread": {"id": "444", "parent_id": "222"},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        result = await DiscordDeliveryClient(http_client).ensure_thread(
            bot_token="discord-secret",
            parent_channel_id="222",
            root_message_id="333",
            name=None,
        )

    assert result.status == "delivered"
    assert result.provider_message_key == "discord-thread:444"
    assert [request.url.path for request in calls] == [
        "/api/v10/channels/222/messages/333"
    ]


@pytest.mark.asyncio
async def test_ensure_thread_treats_root_200_without_thread_as_absent() -> None:
    """A valid root response without a thread performs exactly one create POST."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "333", "channel_id": "222"})
        return httpx.Response(201, json={"id": "444", "parent_id": "222"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DiscordDeliveryClient(client).ensure_thread(
            bot_token="discord-secret",
            parent_channel_id="222",
            root_message_id="333",
            name=None,
        )

    assert result.status == "delivered"
    assert [request.method for request in calls] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_ensure_thread_reconciles_ambiguous_create_without_replay() -> None:
    """An ambiguous create reconciles an existing thread without a second POST."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET" and len(calls) == 1:
            return httpx.Response(404)
        if request.method == "POST":
            return httpx.Response(500, json={"error": "provider unavailable"})
        return httpx.Response(200, json={"thread": {"id": "444", "parent_id": "222"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DiscordDeliveryClient(client).ensure_thread(
            bot_token="discord-secret",
            parent_channel_id="222",
            root_message_id="333",
            name=None,
        )

    assert result.status == "delivered"
    assert result.provider_message_key == "discord-thread:444"
    assert [request.method for request in calls] == ["GET", "POST", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "expected_status", "expected_kind"),
    [
        (401, "failed", "credentials_invalid"),
        (403, "failed", "permission_denied"),
        (404, "failed", "message_not_found"),
        (429, "failed", "rate_limited"),
        (500, "unknown", "provider_5xx_unknown"),
    ],
)
async def test_delivery_maps_provider_failures_without_retry(
    status_code: int,
    expected_status: str,
    expected_kind: str,
) -> None:
    """Confirmed failures and ambiguous provider outcomes stay distinct."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(status_code)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        result = await DiscordDeliveryClient(http_client).create_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="Reply",
            delivery_attempt_id="delivery-1",
        )

    assert result.status == expected_status
    assert result.error_kind == expected_kind
    assert result.provider_message_key is None


@pytest.mark.asyncio
async def test_update_and_delete_validate_the_current_message_boundary() -> None:
    """Update returns identity; delete treats a missing message as a safe failure."""
    responses = [
        httpx.Response(200, json={"id": "555", "channel_id": "333"}),
        httpx.Response(404),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return responses.pop(0)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DiscordDeliveryClient(http_client)
        updated = await client.update_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            message_id="555",
            content="Updated",
        )
        deleted = await client.delete_message(
            bot_token="discord-secret",
            channel_id="333",
            message_id="555",
        )

    assert updated.provider_message_key == "discord:111:555"
    assert deleted.status == "failed"
    assert deleted.error_kind == "message_not_found"


@pytest.mark.asyncio
async def test_file_message_streams_multipart_body_with_the_attempt_nonce() -> None:
    """Files are sent as one bounded multipart request without a retained buffer."""
    calls: list[httpx.Request] = []

    async def content() -> AsyncIterator[bytes]:
        yield b"report"

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"id": "777", "channel_id": "333"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        result = await DiscordDeliveryClient(http_client).create_file_message(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            content="Reply",
            files=(
                DiscordOutboundFile(
                    filename="report.txt",
                    media_type="text/plain",
                    length=6,
                    content=content,
                ),
            ),
            delivery_attempt_id="delivery-file-1",
        )

    assert result.provider_message_key == "discord:111:777"
    request = calls[0]
    assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
    assert request.headers["Content-Length"] == str(len(request.content))
    assert b'name="payload_json"' in request.content
    assert b'"nonce":"' + discord_delivery_nonce("delivery-file-1").encode() in (
        request.content
    )
    assert b'name="files[0]"; filename="report.txt"' in request.content
    assert b"\r\nreport\r\n--" in request.content
