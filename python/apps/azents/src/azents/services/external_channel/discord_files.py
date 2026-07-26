"""Current-source Discord attachment lookup and bounded download primitives."""

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


class DiscordChannelClient:
    """Fetch retained Discord source attachments without persisting current URLs."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def fetch_attachment_download_info(
        self,
        *,
        bot_token: str,
        channel_id: str,
        message_id: str,
        attachment_id: str,
    ) -> DiscordAttachmentDownloadInfo:
        """Revalidate one attachment from its current source message."""
        response = await self._request(
            "GET",
            f"/channels/{channel_id}/messages/{message_id}",
            bot_token=bot_token,
        )
        payload = self._object_payload(response)
        if payload.get("id") != message_id or payload.get("channel_id") != channel_id:
            raise DiscordFileTemporaryError(
                "Discord source message response did not match the requested source."
            )
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            raise DiscordFileTemporaryError(
                "Discord source message did not include attachment metadata."
            )
        for attachment in attachments:
            if (
                not isinstance(attachment, dict)
                or attachment.get("id") != attachment_id
            ):
                continue
            metadata = _attachment_metadata(attachment)
            url = attachment.get("url")
            if not isinstance(url, str) or not _download_url_allowed(url):
                url = None
            return DiscordAttachmentDownloadInfo(metadata=metadata, download_url=url)
        raise DiscordFileNotFound("Discord no longer exposes the requested attachment.")

    async def download_attachment(
        self,
        *,
        download_url: str,
        max_bytes: int,
    ) -> bytes:
        """Download one current attachment URL with a strict in-memory byte limit."""
        if max_bytes < 0:
            raise ValueError("Discord attachment limit must not be negative.")
        if not _download_url_allowed(download_url):
            raise DiscordFileRequestRejected(
                "Discord returned an invalid attachment download URL."
            )
        try:
            async with self.http_client.stream(
                "GET",
                download_url,
                follow_redirects=False,
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
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        declared_length = None
                    if declared_length is not None and declared_length > max_bytes:
                        raise DiscordFileTooLarge(
                            "Discord attachment exceeds the configured limit."
                        )
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > max_bytes:
                        raise DiscordFileTooLarge(
                            "Discord attachment exceeds the configured limit."
                        )
                    body.extend(chunk)
                return bytes(body)
        except httpx.RequestError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment download did not produce a complete response."
            ) from error

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bot_token: str,
    ) -> httpx.Response:
        try:
            response = await self.http_client.request(
                method,
                f"https://discord.com/api/v10{path}",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError as error:
            raise DiscordFileTemporaryError(
                "Discord attachment metadata is temporarily unavailable."
            ) from error
        if response.status_code == 401:
            raise DiscordFileCredentialsInvalid(
                "Discord rejected the active Bot credential."
            )
        if response.status_code == 403:
            raise DiscordFilePermissionDenied(
                "Discord denied access to the source message."
            )
        if response.status_code == 404:
            raise DiscordFileNotFound("Discord no longer exposes the source message.")
        if response.status_code == 429 or response.status_code >= 500:
            raise DiscordFileTemporaryError(
                "Discord attachment metadata is temporarily unavailable."
            )
        if response.status_code >= 400:
            raise DiscordFileRequestRejected(
                "Discord rejected source message retrieval."
            )
        return response

    @staticmethod
    def _object_payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordFileTemporaryError(
                "Discord source message response was invalid."
            ) from error
        if not isinstance(payload, dict):
            raise DiscordFileTemporaryError(
                "Discord source message response was invalid."
            )
        return payload


def _attachment_metadata(attachment: dict[str, object]) -> ExternalChannelFileMetadata:
    provider_file_id = _bounded_string(attachment.get("id"))
    declared_size = attachment.get("size")
    name = _bounded_string(attachment.get("filename"))
    media_type = _bounded_string(attachment.get("content_type"))
    if provider_file_id is None:
        return ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.DISCORD,
            provider_file_id=None,
            name=name,
            title=None,
            media_type=media_type,
            declared_size=declared_size if _valid_size(declared_size) else None,
            mode=None,
            external=False,
            file_access=None,
            supported=False,
            unsupported_reason=ExternalChannelFileUnsupportedReason.MISSING_FILE_ID,
        )
    if not _valid_size(declared_size):
        return ExternalChannelFileMetadata(
            provider=ExternalChannelProvider.DISCORD,
            provider_file_id=provider_file_id,
            name=name,
            title=None,
            media_type=media_type,
            declared_size=None,
            mode=None,
            external=False,
            file_access=None,
            supported=False,
            unsupported_reason=ExternalChannelFileUnsupportedReason.INVALID_SIZE,
        )
    return ExternalChannelFileMetadata(
        provider=ExternalChannelProvider.DISCORD,
        provider_file_id=provider_file_id,
        name=name,
        title=None,
        media_type=media_type,
        declared_size=declared_size,
        mode=None,
        external=False,
        file_access=None,
        supported=True,
        unsupported_reason=None,
    )


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
    return (
        parsed.scheme == "https"
        and parsed.username is None
        and parsed.password is None
        and parsed.hostname in {"cdn.discordapp.com", "media.discordapp.net"}
        and port in {None, 443}
        and parsed.path.startswith("/attachments/")
        and not parsed.fragment
    )
