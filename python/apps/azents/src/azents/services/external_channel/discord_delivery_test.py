"""Deterministic Discord message-delivery adapter tests."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from azents.services.external_channel.discord_delivery import (
    DiscordDeliveryClient,
    DiscordOutboundFile,
    discord_delivery_nonce,
    normalize_discord_projected_title,
    normalize_discord_thread_name,
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
            return httpx.Response(
                200,
                json={"id": "333", "channel_id": "222", "flags": 0},
            )
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
@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        ({"id": "333", "channel_id": "222", "flags": 0}, "absent"),
        ({"id": "333", "channel_id": "222"}, "unknown"),
        (
            {
                "id": "333",
                "channel_id": "222",
                "flags": 32,
            },
            "unknown",
        ),
    ],
)
async def test_read_root_thread_fails_closed_for_incomplete_thread_evidence(
    payload: dict[str, object],
    expected_status: str,
) -> None:
    """Only a complete no-thread flag can establish current root absence."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        result = await DiscordDeliveryClient(client).read_root_thread(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
        )

    assert result.status == expected_status


@pytest.mark.asyncio
async def test_read_root_thread_maps_rate_limit_to_retryable_unknown() -> None:
    """Discord rate limiting never terminalizes projection provisioning."""
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(429, json={"retry_after": 1})
        )
    ) as client:
        result = await DiscordDeliveryClient(client).read_root_thread(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
        )

    assert result.status == "unknown"
    assert result.error_kind == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_guild_id", [None, "other-guild"])
async def test_read_root_thread_keeps_guild_mismatch_out_of_ownership_proof(
    thread_guild_id: str | None,
) -> None:
    """Usable thread delivery metadata cannot synthesize exact Guild ownership."""
    thread: dict[str, object] = {
        "id": "444",
        "parent_id": "222",
        "owner_id": "bot-001",
        "name": "Stored title",
        "thread_metadata": {"create_timestamp": "2026-08-02T00:00:00+00:00"},
    }
    if thread_guild_id is not None:
        thread["guild_id"] = thread_guild_id
    payload = {
        "id": "333",
        "channel_id": "222",
        "flags": 32,
        "thread": thread,
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        result = await DiscordDeliveryClient(client).read_root_thread(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
        )

    assert result.status == "present"
    assert result.thread_channel_id == "444"
    assert result.observed_thread is None


@pytest.mark.asyncio
@pytest.mark.parametrize("thread_guild_id", [None, "other-guild"])
async def test_create_root_thread_keeps_guild_mismatch_out_of_ownership_proof(
    thread_guild_id: str | None,
) -> None:
    """A create response also needs provider-supplied exact Guild proof."""
    thread: dict[str, object] = {
        "id": "444",
        "parent_id": "222",
        "owner_id": "bot-001",
        "name": "Stored title",
        "thread_metadata": {"create_timestamp": "2026-08-02T00:00:00+00:00"},
    }
    if thread_guild_id is not None:
        thread["guild_id"] = thread_guild_id
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(201, json=thread))
    ) as client:
        result = await DiscordDeliveryClient(client).create_root_thread(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            requested_provisional_title="Stored title",
        )

    assert result.status == "present"
    assert result.thread_channel_id == "444"
    assert result.observed_thread is None


def test_normalize_discord_thread_name_is_deterministic_and_bounded() -> None:
    """Stored provisional names use one public provider-valid normalizer."""
    assert (
        normalize_discord_thread_name("  Incident   response ") == "Incident response"
    )
    assert normalize_discord_thread_name(None) == "Azents"
    assert len(normalize_discord_thread_name("x" * 101)) == 100


def test_normalize_discord_projected_title_rejects_blank_content_without_fallback() -> (
    None
):
    """Final generated titles do not gain a provisional-name fallback."""
    assert normalize_discord_projected_title("  Incident   response ") == (
        "Incident response"
    )
    assert normalize_discord_projected_title(" \t\n ") is None
    assert len(normalize_discord_projected_title("x" * 101) or "") == 100


@pytest.mark.asyncio
async def test_read_thread_channel_requires_exact_complete_identity() -> None:
    """A final title GET accepts only the immutable thread's complete identity."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "444",
                "guild_id": "111",
                "parent_id": "222",
                "owner_id": "bot-001",
                "name": "Stored provisional title",
                "thread_metadata": {"create_timestamp": "2026-08-02T00:00:00+00:00"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DiscordDeliveryClient(client).read_thread_channel(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            thread_channel_id="444",
        )

    assert result.status == "present"
    assert result.observed_thread is not None
    assert result.observed_thread.name == "Stored provisional title"
    assert calls[0].url.path == "/api/v10/channels/444"
    assert calls[0].headers["Authorization"] == "Bot discord-secret"


@pytest.mark.asyncio
async def test_read_thread_channel_rejects_mismatched_or_incomplete_identity() -> None:
    """A direct GET never treats a different or incomplete thread as current."""
    responses = [
        {
            "id": "other",
            "guild_id": "111",
            "parent_id": "222",
            "owner_id": "bot-001",
            "name": "Stored provisional title",
            "thread_metadata": {"create_timestamp": "2026-08-02T00:00:00+00:00"},
        },
        {
            "id": "444",
            "guild_id": "111",
            "parent_id": "222",
            "name": "Stored provisional title",
        },
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=responses.pop(0))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        discord = DiscordDeliveryClient(client)
        mismatched = await discord.read_thread_channel(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            thread_channel_id="444",
        )
        incomplete = await discord.read_thread_channel(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            thread_channel_id="444",
        )

    assert mismatched.status == "unknown"
    assert mismatched.error_kind == "thread_identity_invalid"
    assert incomplete.status == "unknown"
    assert incomplete.error_kind == "thread_proof_incomplete"


@pytest.mark.asyncio
async def test_patch_thread_name_is_name_only_and_rejects_empty_title() -> None:
    """The final-title adapter changes only a normalized nonempty thread name."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "444",
                "guild_id": "111",
                "parent_id": "222",
                "owner_id": "bot-001",
                "name": "Generated final title",
                "thread_metadata": {"create_timestamp": "2026-08-02T00:00:00+00:00"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        discord = DiscordDeliveryClient(client)
        rejected = await discord.patch_thread_name(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            thread_channel_id="444",
            name=" \t",
        )
        result = await discord.patch_thread_name(
            bot_token="discord-secret",
            guild_id="111",
            parent_channel_id="222",
            root_message_id="333",
            thread_channel_id="444",
            name=" Generated   final title ",
        )

    assert rejected.status == "failed"
    assert rejected.error_kind == "title_invalid"
    assert result.status == "present"
    assert json.loads(calls[0].content) == {"name": "Generated final title"}
    assert calls[0].method == "PATCH"
    assert calls[0].url.path == "/api/v10/channels/444"


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
