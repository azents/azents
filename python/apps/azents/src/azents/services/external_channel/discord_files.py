"""Discord attachment metadata through the SDK and bounded G3 byte transport."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from typing import TypeGuard
from urllib.parse import urlparse

import httpx

from azents.core.enums import ExternalChannelProvider
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    ExternalChannelFileMetadata,
    ExternalChannelFileUnsupportedReason,
)
from azents.runtime.transfer.provider_source import ProviderByteStreamResponse
from azents.services.external_channel.discord_endpoint import (
    discord_test_origin_matches,
)
from azents.services.external_channel.discord_sdk import (
    DiscordSDKAttachment,
    DiscordSDKClientFactory,
    DiscordSDKCredentialsInvalid,
    DiscordSDKError,
    DiscordSDKPermissionDenied,
    DiscordSDKRequestRejected,
    DiscordSDKResourceUnavailable,
)

_DISCORD_METADATA_TIMEOUT_SECONDS = 20.0


class DiscordFileProviderError(RuntimeError):
    """Base class for controlled Discord attachment retrieval failures."""


class DiscordFileCredentialsInvalid(DiscordFileProviderError):
    """Discord rejected the configured Bot credential."""


class DiscordFilePermissionDenied(DiscordFileProviderError):
    """Discord denied access to a source message or attachment."""


class DiscordFileNotFound(DiscordFileProviderError):
    """Discord no longer exposes the retained message or attachment."""


class DiscordFileTooLarge(DiscordFileProviderError):
    """Discord returned attachment content beyond the configured byte limit."""


class DiscordFileTemporaryError(DiscordFileProviderError):
    """Discord or the network did not provide a complete file response."""


class DiscordFileRequestRejected(DiscordFileProviderError):
    """Discord rejected a syntactically valid file retrieval request."""


@dataclass(frozen=True)
class DiscordAttachmentDownloadInfo:
    """Fresh provider metadata and an in-memory-only attachment download URL."""

    metadata: ExternalChannelFileMetadata
    download_url: str | None = field(repr=False)


class DiscordAttachmentByteTransport:
    """G3 direct Discord CDN HEAD/GET byte transport."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def fetch_content_length(self, *, download_url: str, max_bytes: int) -> int:
        """Return the bounded final attachment response length."""
        if not _download_url_allowed(download_url):
            raise DiscordFileRequestRejected(
                "Discord returned an invalid attachment download URL."
            )
        try:
            response = await self.http_client.head(download_url, follow_redirects=False)
        except httpx.RequestError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment download is temporarily unavailable."
            ) from error
        if response.status_code < 200 or response.status_code >= 300:
            raise DiscordFileRequestRejected("Discord attachment length check failed.")
        size = _declared_length(response)
        if size > max_bytes:
            raise DiscordFileTooLarge(
                "Discord attachment exceeds the configured limit."
            )
        return size

    def open_stream(
        self,
        *,
        download_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[ProviderByteStreamResponse]:
        """Return one owned bounded attachment stream."""
        return self._open_stream(
            download_url=download_url,
            max_bytes=max_bytes,
            maximum_chunk_size=maximum_chunk_size,
        )

    @asynccontextmanager
    async def _open_stream(
        self,
        *,
        download_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AsyncIterator[ProviderByteStreamResponse]:
        if max_bytes < 0:
            raise ValueError("Discord attachment limit must not be negative.")
        if maximum_chunk_size <= 0:
            raise ValueError("Discord stream chunk size must be positive.")
        if not _download_url_allowed(download_url):
            raise DiscordFileRequestRejected(
                "Discord returned an invalid attachment download URL."
            )
        try:
            async with self.http_client.stream(
                "GET", download_url, follow_redirects=False
            ) as response:
                if response.status_code == 404:
                    raise DiscordFileNotFound(
                        "Discord no longer exposes the requested attachment."
                    )
                if response.status_code in {401, 403}:
                    raise DiscordFilePermissionDenied(
                        "Discord denied attachment download access."
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    raise DiscordFileTemporaryError(
                        "Discord attachment download is temporarily unavailable."
                    )
                if 300 <= response.status_code < 400:
                    raise DiscordFileRequestRejected(
                        "Discord attachment download redirected unexpectedly."
                    )
                if response.status_code >= 400:
                    raise DiscordFileRequestRejected(
                        "Discord rejected attachment download."
                    )
                declared_length = _declared_length(response)
                if declared_length > max_bytes:
                    raise DiscordFileTooLarge(
                        "Discord attachment exceeds the configured limit."
                    )

                async def chunks() -> AsyncIterator[bytes]:
                    actual_size = 0
                    async for chunk in response.aiter_bytes(
                        chunk_size=maximum_chunk_size
                    ):
                        actual_size += len(chunk)
                        if actual_size > max_bytes:
                            raise DiscordFileTooLarge(
                                "Discord attachment exceeds the configured limit."
                            )
                        yield chunk

                yield ProviderByteStreamResponse(
                    content_length=declared_length,
                    chunks=chunks(),
                )
        except httpx.RequestError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment download did not produce a complete response."
            ) from error


class DiscordChannelClient:
    """Fetch current Discord attachment metadata through public SDK models."""

    def __init__(
        self,
        sdk_factory: DiscordSDKClientFactory,
        byte_transport: DiscordAttachmentByteTransport,
    ) -> None:
        self.sdk_factory = sdk_factory
        self.byte_transport = byte_transport

    async def fetch_attachment_download_info(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordAttachmentDownloadInfo:
        """Revalidate one attachment from its current public SDK Message."""
        try:
            async with asyncio.timeout(_DISCORD_METADATA_TIMEOUT_SECONDS):
                async with self.sdk_factory.open(bot_token=bot_token) as sdk:
                    attachment = await sdk.fetch_attachment(
                        guild_id=guild_id,
                        channel_id=channel_id,
                        message_id=message_id,
                        attachment_id=attachment_id,
                    )
        except DiscordSDKCredentialsInvalid as error:
            raise DiscordFileCredentialsInvalid(
                "Discord rejected the active Bot credential."
            ) from error
        except DiscordSDKPermissionDenied as error:
            raise DiscordFilePermissionDenied(
                "Discord denied access to the source message."
            ) from error
        except DiscordSDKResourceUnavailable as error:
            raise DiscordFileNotFound(
                "Discord no longer exposes the requested attachment."
            ) from error
        except DiscordSDKRequestRejected as error:
            raise DiscordFileRequestRejected(
                "Discord rejected source message retrieval."
            ) from error
        except DiscordSDKError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment metadata is temporarily unavailable."
            ) from error
        except TimeoutError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment metadata is temporarily unavailable."
            ) from error
        url = attachment.download_url
        return DiscordAttachmentDownloadInfo(
            metadata=_attachment_metadata(attachment),
            download_url=url if _download_url_allowed(url) else None,
        )

    async def fetch_attachment_content_length(
        self, *, download_url: str, max_bytes: int
    ) -> int:
        """Delegate exact CDN length validation to approved gap G3."""
        return await self.byte_transport.fetch_content_length(
            download_url=download_url,
            max_bytes=max_bytes,
        )

    def open_attachment_stream(
        self,
        *,
        download_url: str,
        max_bytes: int,
        maximum_chunk_size: int,
    ) -> AbstractAsyncContextManager[ProviderByteStreamResponse]:
        """Delegate bounded CDN streaming to approved gap G3."""
        return self.byte_transport.open_stream(
            download_url=download_url,
            max_bytes=max_bytes,
            maximum_chunk_size=maximum_chunk_size,
        )


def _attachment_metadata(
    attachment: DiscordSDKAttachment,
) -> ExternalChannelFileMetadata:
    provider_file_id = _bounded_string(attachment.attachment_id)
    name = _bounded_string(attachment.filename)
    media_type = _bounded_string(attachment.content_type)
    if provider_file_id is None:
        return ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.DISCORD,
            provider_file_id=None,
            name=name,
            title=None,
            media_type=media_type,
            declared_size=attachment.size if _valid_size(attachment.size) else None,
            mode=None,
            external=False,
            file_access=None,
            supported=False,
            unsupported_reason=ExternalChannelFileUnsupportedReason.MISSING_FILE_ID,
        )
    return ExternalChannelFileMetadata(
        provider=ExternalChannelProvider.DISCORD,
        provider_file_id=provider_file_id,
        name=name,
        title=None,
        media_type=media_type,
        declared_size=attachment.size if _valid_size(attachment.size) else None,
        mode=None,
        external=False,
        file_access=None,
        supported=True,
        unsupported_reason=None,
    )


def _declared_length(response: httpx.Response) -> int:
    values = response.headers.get_list("Content-Length")
    if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
        raise DiscordFileRequestRejected(
            "Discord attachment response has an invalid content length."
        )
    return int(values[0])


def _valid_size(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _bounded_string(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]


def _download_url_allowed(value: str) -> bool:
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return False
    if (
        discord_test_origin_matches(value)
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith("/attachments/")
        and not parsed.fragment
    ):
        return True
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
        and port in {None, 443}
        and parsed.path.startswith("/attachments/")
        and not parsed.fragment
    )
