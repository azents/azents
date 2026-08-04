"""Deterministic Discord attachment lookup and download adapter tests."""

import httpx
import pytest

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import ExternalChannelFileMetadata
from azents.services.external_channel.discord_files import (
    DiscordAttachmentDownloadInfo,
    DiscordChannelClient,
    DiscordFileRequestRejected,
    DiscordFileTooLarge,
)


@pytest.mark.asyncio
async def test_lookup_omits_non_discord_cdn_url_from_current_attachment_info() -> None:
    """Provider metadata may not turn an arbitrary HTTPS URL into a download target."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "id": "444",
                "channel_id": "333",
                "attachments": [
                    {
                        "id": "555",
                        "filename": "report.csv",
                        "size": 7,
                        "content_type": "text/csv",
                        "url": "https://untrusted.example/attachments/333/555/report.csv",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DiscordChannelClient(http_client)
        info = await client.fetch_attachment_download_info(
            bot_token="discord-secret",
            channel_id="333",
            message_id="444",
            attachment_id="555",
        )

    assert info.download_url is None
    assert info.metadata.provider_file_id == "555"
    assert len(calls) == 1
    assert calls[0].url == "https://discord.com/api/v10/channels/333/messages/444"
    assert calls[0].headers["Authorization"] == "Bot discord-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_size", (None, -1, "7", True))
async def test_lookup_treats_invalid_metadata_size_as_advisory(
    declared_size: object,
) -> None:
    """Fresh attachment identity remains supported without a provider size."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "id": "444",
                "channel_id": "333",
                "attachments": [
                    {
                        "id": "555",
                        "filename": "report.csv",
                        "size": declared_size,
                        "content_type": "text/csv",
                        "url": (
                            "https://cdn.discordapp.com/attachments/333/555/report.csv"
                        ),
                    }
                ],
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        info = await DiscordChannelClient(http_client).fetch_attachment_download_info(
            bot_token="discord-secret",
            channel_id="333",
            message_id="444",
            attachment_id="555",
        )

    assert info.metadata.declared_size is None
    assert info.metadata.supported is True
    assert info.metadata.unsupported_reason is None
    assert info.download_url is not None


@pytest.mark.asyncio
async def test_content_length_uses_final_attachment_url() -> None:
    """The final CDN URL HEAD response exclusively declares transfer size."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers={"Content-Length": "7"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        size = await DiscordChannelClient(http_client).fetch_attachment_content_length(
            download_url=("https://cdn.discordapp.com/attachments/333/555/report.csv"),
            max_bytes=10,
        )

    assert size == 7
    assert len(calls) == 1
    assert calls[0].method == "HEAD"
    assert calls[0].url == ("https://cdn.discordapp.com/attachments/333/555/report.csv")


@pytest.mark.asyncio
async def test_download_rejects_non_cdn_urls_without_http_access() -> None:
    """The adapter rejects an invalid URL before a potentially unsafe request."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DiscordChannelClient(http_client)
        with pytest.raises(DiscordFileRequestRejected, match="invalid"):
            async with client.open_attachment_stream(
                download_url="https://untrusted.example/attachments/333/555/report.csv",
                max_bytes=7,
                maximum_chunk_size=4,
            ) as chunks:
                _ = [chunk async for chunk in chunks.chunks]

    assert calls == []


@pytest.mark.asyncio
async def test_download_enforces_content_length_and_rejects_redirects() -> None:
    """Current Discord URLs cannot bypass the bounded streaming policy."""
    responses = [
        httpx.Response(302, headers={"Location": "https://untrusted.example/file"}),
        httpx.Response(200, headers={"Content-Length": "8"}, content=b"12345678"),
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return responses.pop(0)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as http_client:
        client = DiscordChannelClient(http_client)
        with pytest.raises(DiscordFileRequestRejected, match="redirected"):
            async with client.open_attachment_stream(
                download_url="https://cdn.discordapp.com/attachments/333/555/report.csv",
                max_bytes=7,
                maximum_chunk_size=4,
            ) as chunks:
                _ = [chunk async for chunk in chunks.chunks]
        with pytest.raises(DiscordFileTooLarge, match="limit"):
            async with client.open_attachment_stream(
                download_url="https://media.discordapp.net/attachments/333/555/report.csv",
                max_bytes=7,
                maximum_chunk_size=4,
            ) as chunks:
                _ = [chunk async for chunk in chunks.chunks]

    assert responses == []


@pytest.mark.asyncio
async def test_download_requires_valid_content_length() -> None:
    """A complete Discord response must contain one non-negative decimal size."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"Content-Length": "invalid"},
            content=b"1234567",
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        with pytest.raises(DiscordFileRequestRejected, match="content length"):
            async with DiscordChannelClient(http_client).open_attachment_stream(
                download_url="https://cdn.discordapp.com/attachments/333/555/report.csv",
                max_bytes=7,
                maximum_chunk_size=3,
            ):
                pass


@pytest.mark.asyncio
async def test_download_yields_bounded_chunks_without_retaining_complete_body() -> None:
    """The adapter exposes only bounded chunks from one owned HTTP response."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"1234567")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
    ) as http_client:
        client = DiscordChannelClient(http_client)
        async with client.open_attachment_stream(
            download_url="https://cdn.discordapp.com/attachments/333/555/report.csv",
            max_bytes=7,
            maximum_chunk_size=3,
        ) as chunks:
            bodies = [chunk async for chunk in chunks.chunks]

    assert bodies == [b"123", b"456", b"7"]


def test_discord_attachment_info_repr_excludes_current_url() -> None:
    """A current CDN URL cannot accidentally appear in diagnostics."""
    info = DiscordAttachmentDownloadInfo(
        metadata=ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.DISCORD,
            provider_file_id="555",
            name="report.csv",
            title=None,
            media_type="text/csv",
            declared_size=7,
            mode=None,
            external=False,
            file_access=None,
            supported=True,
            unsupported_reason=None,
        ),
        download_url="https://cdn.discordapp.com/attachments/333/555/report.csv",
    )

    assert "cdn.discordapp.com" not in repr(info)
