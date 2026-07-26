"""Discord Application metadata client tests."""

import httpx
import pytest

from azents.services.external_channel.discord_api import (
    DiscordAPIClient,
    DiscordAPICredentialsInvalid,
    DiscordAPIUnavailable,
)


def _client(handler: httpx.MockTransport) -> DiscordAPIClient:
    return DiscordAPIClient(httpx.AsyncClient(transport=handler))


@pytest.mark.asyncio
async def test_reads_current_application_verify_key() -> None:
    """Bot-token metadata exposes only validated authority fields."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "app-1", "verify_key": "ab" * 32},
            request=request,
        )
    )
    client = _client(transport)

    metadata = await client.get_current_application(bot_token="redacted-token")

    assert metadata.application_id == "app-1"
    assert metadata.verify_key == "ab" * 32
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_rejects_invalid_bot_token() -> None:
    """Credential rejection remains distinct from provider unavailability."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(401, request=request)
    )
    client = _client(transport)

    with pytest.raises(DiscordAPICredentialsInvalid):
        await client.get_current_application(bot_token="redacted-token")
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_rejects_malformed_verify_key() -> None:
    """Malformed provider metadata cannot become an interaction verifier."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "app-1", "verify_key": "not-hex"},
            request=request,
        )
    )
    client = _client(transport)

    with pytest.raises(DiscordAPIUnavailable):
        await client.get_current_application(bot_token="redacted-token")
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_reads_current_bot_user_identity() -> None:
    """The Bot identity is stored separately from the Discord Application ID."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"id": "123456789012345678"},
            request=request,
        )
    )
    client = _client(transport)

    bot_user_id = await client.get_current_bot_user_id(bot_token="redacted-token")

    assert bot_user_id == "123456789012345678"
    await client.http_client.aclose()


@pytest.mark.asyncio
async def test_configures_interaction_endpoint_without_persisting_selector() -> None:
    """The provider call receives the opaque selector only in its endpoint URL."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    client = _client(httpx.MockTransport(handler))
    endpoint_url = "https://callbacks.example/discord/interactions/opaque-selector"

    await client.configure_interactions_endpoint(
        bot_token="redacted-token",
        application_id="app-1",
        endpoint_url=endpoint_url,
    )

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "PATCH"
    assert request.url.path == "/api/v10/applications/app-1"
    assert request.headers["authorization"] == "Bot redacted-token"
    assert (
        request.json()
        if False
        else request.content
        == (
            b'{"interactions_endpoint_url":"'
            b"https://callbacks.example/discord/interactions/opaque-selector"
            b'"}'
        )
    )
    await client.http_client.aclose()
