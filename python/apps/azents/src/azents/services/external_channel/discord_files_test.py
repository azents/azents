"""Discord SDK attachment metadata and G3 byte transport tests."""

import contextlib
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import cast

import httpx
import pytest

from azents.services.external_channel.discord_files import (
    DiscordAttachmentByteTransport,
    DiscordChannelClient,
    DiscordFileNotFound,
    DiscordFileRequestRejected,
    DiscordFileTooLarge,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKAttachment,
    DiscordSDKResourceUnavailable,
    DiscordSDKSession,
)


@dataclass
class _SDKSession:
    attachment: DiscordSDKAttachment | None

    async def fetch_attachment(self, **values: object) -> DiscordSDKAttachment:
        assert values == {
            "guild_id": "111",
            "channel_id": "333",
            "message_id": "444",
            "attachment_id": "555",
        }
        if self.attachment is None:
            raise DiscordSDKResourceUnavailable()
        return self.attachment


@dataclass
class _SDKFactory:
    session: _SDKSession

    @contextlib.asynccontextmanager
    async def open(self, *, bot_token: str) -> AsyncIterator[DiscordSDKSession]:
        assert bot_token == "discord-secret"
        yield cast(DiscordSDKSession, self.session)


def _client(
    attachment: DiscordSDKAttachment | None,
    http_client: httpx.AsyncClient,
) -> DiscordChannelClient:
    return DiscordChannelClient(
        _SDKFactory(_SDKSession(attachment)),
        DiscordAttachmentByteTransport(http_client),
    )


@pytest.mark.asyncio
async def test_attachment_metadata_comes_from_public_sdk_message() -> None:
    """Current SDK metadata is projected without retaining a raw response."""
    attachment = DiscordSDKAttachment(
        attachment_id="555",
        filename="report.txt",
        size=3,
        content_type="text/plain",
        download_url="https://cdn.discordapp.com/attachments/333/555/report.txt",
    )
    async with httpx.AsyncClient() as http:
        info = await _client(attachment, http).fetch_attachment_download_info(
            bot_token="discord-secret",
            guild_id="111",
            channel_id="333",
            message_id="444",
            attachment_id="555",
        )

    assert info.metadata.provider_file_id == "555"
    assert info.metadata.name == "report.txt"
    assert info.metadata.declared_size == 3
    assert info.download_url == attachment.download_url


@pytest.mark.asyncio
async def test_missing_sdk_attachment_maps_to_not_found() -> None:
    """A missing current SDK attachment retains the provider not-found contract."""
    async with httpx.AsyncClient() as http:
        with pytest.raises(DiscordFileNotFound):
            await _client(None, http).fetch_attachment_download_info(
                bot_token="discord-secret",
                guild_id="111",
                channel_id="333",
                message_id="444",
                attachment_id="555",
            )


@pytest.mark.asyncio
async def test_g3_content_length_rejects_redirect_and_oversize() -> None:
    """The CDN length gap rejects redirects and declared sizes above the bound."""
    responses = iter(
        [
            httpx.Response(302, headers={"Location": "https://example.com"}),
            httpx.Response(200, headers={"Content-Length": "11"}),
        ]
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    url = "https://cdn.discordapp.com/attachments/333/555/report.txt"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        transport = DiscordAttachmentByteTransport(http)
        with pytest.raises(DiscordFileRequestRejected):
            await transport.fetch_content_length(download_url=url, max_bytes=10)
        with pytest.raises(DiscordFileTooLarge):
            await transport.fetch_content_length(download_url=url, max_bytes=10)


@pytest.mark.asyncio
async def test_g3_stream_yields_bounded_bytes_and_closes_response() -> None:
    """The direct CDN gap yields bytes within the declared and configured bounds."""
    url = "https://cdn.discordapp.com/attachments/333/555/report.txt"

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "3"}, content=b"abc")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        transport = DiscordAttachmentByteTransport(http)
        async with transport.open_stream(
            download_url=url,
            max_bytes=3,
            maximum_chunk_size=2,
        ) as response:
            chunks = [chunk async for chunk in response.chunks]

    assert response.content_length == 3
    assert b"".join(chunks) == b"abc"


@pytest.mark.asyncio
async def test_g3_rejects_untrusted_attachment_origin() -> None:
    """G3 never follows a provider-controlled URL outside approved CDN origins."""
    async with httpx.AsyncClient() as http:
        transport = DiscordAttachmentByteTransport(http)
        with pytest.raises(DiscordFileRequestRejected):
            await transport.fetch_content_length(
                download_url="https://example.com/attachments/333/555/report.txt",
                max_bytes=3,
            )
