"""Bounded Discord message delivery primitives."""

import json
import secrets
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, replace
from typing import Literal

import httpx

from azents.core.external_channel_title import normalize_discord_thread_title
from azents.services.external_channel.discord_endpoint import discord_api_base_url
from azents.services.external_channel.provider_effect import ProviderOperationKey

_DISCORD_MIN_AUTO_ARCHIVE_MINUTES = 60
DISCORD_DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DISCORD_CREATE_MESSAGE_MAX_REQUEST_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class DiscordDeliveryResult:
    """Sanitized result of one at-most-once Discord message mutation."""

    status: Literal["delivered", "failed", "unknown"]
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None
    created_thread_name: str | None = None


@dataclass(frozen=True)
class DiscordThreadTitleReadResult:
    """Sanitized result of one Discord thread-title read."""

    status: Literal["present", "missing", "failed", "unknown"]
    name: str | None
    error_kind: str | None


class DiscordOutboundFileContentError(Exception):
    """One Runtime or Exchange source became unavailable during upload."""


@dataclass(frozen=True)
class DiscordOutboundFile:
    """One streamed Discord multipart attachment without retained file bytes."""

    filename: str
    media_type: str
    length: int
    content: Callable[[], AsyncIterator[bytes]]


class DiscordDeliveryClient:
    """Perform one Discord message mutation without retrying ambiguous outcomes."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def ensure_thread(
        self,
        *,
        bot_token: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str | None,
    ) -> DiscordDeliveryResult:
        """Return only after the root Discord message has a usable thread."""
        existing = await self._read_root_thread(
            bot_token=bot_token,
            parent_channel_id=parent_channel_id,
            root_message_id=root_message_id,
        )
        if existing is not None:
            return existing
        thread_name = _discord_thread_name(name)
        response = await self._request(
            "POST",
            f"/channels/{parent_channel_id}/messages/{root_message_id}/threads",
            bot_token=bot_token,
            json_body={
                "name": thread_name,
                "auto_archive_duration": _DISCORD_MIN_AUTO_ARCHIVE_MINUTES,
            },
        )
        if isinstance(response, DiscordDeliveryResult):
            result = response
        else:
            result = _thread_result(
                response=response,
                parent_channel_id=parent_channel_id,
                root_message_id=root_message_id,
            )
        if result.status == "delivered":
            return replace(result, created_thread_name=thread_name)
        reconciled = await self._read_root_thread(
            bot_token=bot_token,
            parent_channel_id=parent_channel_id,
            root_message_id=root_message_id,
        )
        if reconciled is not None:
            return reconciled
        return result

    async def read_thread_title(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
    ) -> DiscordThreadTitleReadResult:
        """Read one exact Discord thread title without retry."""
        try:
            response = await self.http_client.get(
                f"{discord_api_base_url()}/channels/{channel_id}",
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError:
            return DiscordThreadTitleReadResult(
                status="unknown",
                name=None,
                error_kind="transport_unknown",
            )
        if response.status_code == 404:
            return DiscordThreadTitleReadResult(
                status="missing",
                name=None,
                error_kind="thread_not_found",
            )
        failure = _response_failure(response)
        if failure is not None:
            return DiscordThreadTitleReadResult(
                status=("failed" if failure.status == "failed" else "unknown"),
                name=None,
                error_kind=failure.error_kind,
            )
        try:
            payload: object = response.json()
        except ValueError:
            return DiscordThreadTitleReadResult(
                status="unknown",
                name=None,
                error_kind="response_malformed",
            )
        if not isinstance(payload, dict):
            return DiscordThreadTitleReadResult(
                status="unknown",
                name=None,
                error_kind="response_shape_invalid",
            )
        name = payload.get("name")
        if (
            payload.get("id") != channel_id
            or payload.get("guild_id") != guild_id
            or not isinstance(name, str)
            or not name.strip()
        ):
            return DiscordThreadTitleReadResult(
                status="unknown",
                name=None,
                error_kind="response_shape_invalid",
            )
        return DiscordThreadTitleReadResult(
            status="present",
            name=name,
            error_kind=None,
        )

    async def update_thread_title(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordDeliveryResult:
        """Apply one name-only Discord thread update without retry."""
        normalized = normalize_discord_thread_title(name)
        if normalized is None:
            return _rejected_result()
        response = await self._request(
            "PATCH",
            f"/channels/{channel_id}",
            bot_token=bot_token,
            json_body={"name": normalized},
        )
        if isinstance(response, DiscordDeliveryResult):
            return response
        failure = _response_failure(response)
        if failure is not None:
            return failure
        try:
            payload: object = response.json()
        except ValueError:
            return _unknown_result(
                error_kind="response_malformed",
                error_summary="Discord thread update response was malformed.",
            )
        if (
            not isinstance(payload, dict)
            or payload.get("id") != channel_id
            or payload.get("guild_id") != guild_id
            or payload.get("name") != normalized
        ):
            return _unknown_result(
                error_kind="response_shape_invalid",
                error_summary="Discord thread update response was invalid.",
            )
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=f"discord-thread:{channel_id}",
            error_kind=None,
            error_summary=None,
        )

    async def _read_root_thread(
        self,
        *,
        bot_token: str,
        parent_channel_id: str,
        root_message_id: str,
    ) -> DiscordDeliveryResult | None:
        """Read the root once to reconcile an existing or ambiguous thread create."""
        try:
            response = await self.http_client.get(
                (
                    f"{discord_api_base_url()}/channels/{parent_channel_id}/messages/"
                    f"{root_message_id}"
                ),
                headers={"Authorization": f"Bot {bot_token}"},
            )
        except httpx.RequestError:
            return _unknown_result(
                error_kind="transport_unknown",
                error_summary="Discord thread reconciliation transport failed.",
            )
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            return _response_failure(response) or _unknown_result(
                error_kind="response_shape_invalid",
                error_summary="Discord thread reconciliation response was invalid.",
            )
        try:
            payload: object = response.json()
        except ValueError:
            return _unknown_result(
                error_kind="response_malformed",
                error_summary="Discord thread reconciliation response was malformed.",
            )
        if not isinstance(payload, dict):
            return _unknown_result(
                error_kind="response_shape_invalid",
                error_summary="Discord thread reconciliation response was invalid.",
            )
        if "thread" not in payload:
            return None
        return _thread_result(
            response=response,
            parent_channel_id=parent_channel_id,
            root_message_id=root_message_id,
        )

    async def create_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        operation_key: ProviderOperationKey,
        components: list[dict[str, object]] | None = None,
        embeds: list[dict[str, object]] | None = None,
    ) -> DiscordDeliveryResult:
        """Create one message with a live-operation duplicate nonce."""
        payload: dict[str, object] = {
            "content": content,
            "nonce": discord_delivery_nonce(operation_key),
            "enforce_nonce": True,
        }
        if components is not None:
            payload["components"] = components
        if embeds is not None:
            payload["embeds"] = embeds
        response = await self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            bot_token=bot_token,
            json_body=payload,
        )
        if isinstance(response, DiscordDeliveryResult):
            return response
        return _created_message_result(
            response=response,
            guild_id=guild_id,
            channel_id=channel_id,
        )

    async def create_file_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        files: tuple[DiscordOutboundFile, ...],
        operation_key: ProviderOperationKey,
    ) -> DiscordDeliveryResult:
        """Create one nonce-fenced multipart message from streaming file sources."""
        if not files:
            return _rejected_result()
        try:
            stream = _DiscordMultipartStream(
                payload={
                    "content": content,
                    "nonce": discord_delivery_nonce(operation_key),
                    "enforce_nonce": True,
                    "attachments": [
                        {"id": str(index), "filename": file.filename}
                        for index, file in enumerate(files)
                    ],
                },
                files=files,
            )
            response = await self._request(
                "POST",
                f"/channels/{channel_id}/messages",
                bot_token=bot_token,
                json_body=None,
                content=stream,
                content_headers=stream.headers,
            )
        except DiscordOutboundFileContentError:
            return DiscordDeliveryResult(
                status="failed",
                provider_message_key=None,
                error_kind="file_source_invalid",
                error_summary="The outbound file source changed before upload.",
            )
        if isinstance(response, DiscordDeliveryResult):
            return response
        return _created_message_result(
            response=response,
            guild_id=guild_id,
            channel_id=channel_id,
        )

    async def update_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        message_id: str,
        content: str,
        components: list[dict[str, object]] | None = None,
        embeds: list[dict[str, object]] | None = None,
    ) -> DiscordDeliveryResult:
        """Update one currently owned Discord message."""
        response = await self._request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            bot_token=bot_token,
            json_body={
                "content": content,
                **({"components": components} if components is not None else {}),
                **({"embeds": embeds} if embeds is not None else {}),
            },
        )
        if isinstance(response, DiscordDeliveryResult):
            return response
        return _created_message_result(
            response=response,
            guild_id=guild_id,
            channel_id=channel_id,
        )

    async def delete_message(
        self,
        *,
        bot_token: str,
        channel_id: str,
        message_id: str,
    ) -> DiscordDeliveryResult:
        """Delete one currently owned Discord message."""
        response = await self._request(
            "DELETE",
            f"/channels/{channel_id}/messages/{message_id}",
            bot_token=bot_token,
            json_body=None,
        )
        if isinstance(response, DiscordDeliveryResult):
            return response
        if response.status_code not in {200, 202, 204}:
            return _rejected_result()
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bot_token: str,
        json_body: dict[str, object] | None,
        content: httpx.AsyncByteStream | None = None,
        content_headers: dict[str, str] | None = None,
    ) -> httpx.Response | DiscordDeliveryResult:
        try:
            response = await self.http_client.request(
                method,
                f"{discord_api_base_url()}{path}",
                headers={
                    "Authorization": f"Bot {bot_token}",
                    **(content_headers or {}),
                },
                json=json_body,
                content=content,
            )
        except httpx.RequestError:
            return _unknown_result(
                error_kind="transport_unknown",
                error_summary="Discord delivery transport outcome is unknown.",
            )
        return _response_failure(response) or response


def _discord_thread_name(name: str | None) -> str:
    """Return one bounded valid Discord thread name."""
    normalized = "" if name is None else " ".join(name.split())
    return (normalized or "Azents")[:100]


def _response_failure(response: httpx.Response) -> DiscordDeliveryResult | None:
    """Map a non-success Discord response into a sanitized delivery outcome."""
    if response.status_code in {401, 403}:
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind=(
                "credentials_invalid"
                if response.status_code == 401
                else "permission_denied"
            ),
            error_summary=(
                "Discord rejected the active Bot credential."
                if response.status_code == 401
                else "Discord denied access to the target conversation."
            ),
        )
    if response.status_code == 404:
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="message_not_found",
            error_summary="Discord no longer exposes the target message.",
        )
    if response.status_code == 429:
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="rate_limited",
            error_summary="Discord rate limited the provider operation.",
        )
    if response.status_code >= 500:
        return _unknown_result(
            error_kind="provider_5xx_unknown",
            error_summary="Discord returned a server error with an unknown outcome.",
        )
    if response.status_code >= 400:
        return _rejected_result()
    return None


def discord_delivery_nonce(operation_key: ProviderOperationKey) -> str:
    """Return the bounded duplicate nonce for one live create operation."""
    return operation_key.value


def _created_message_result(
    *,
    response: httpx.Response,
    guild_id: str,
    channel_id: str,
) -> DiscordDeliveryResult:
    try:
        payload: object = response.json()
    except ValueError:
        return _unknown_result(
            error_kind="response_malformed",
            error_summary="Discord message response was malformed.",
        )
    message_id = payload.get("id") if isinstance(payload, dict) else None
    response_channel_id = (
        payload.get("channel_id") if isinstance(payload, dict) else None
    )
    if response_channel_id != channel_id:
        return _unknown_result(
            error_kind="response_channel_mismatch",
            error_summary="Discord message response targeted another channel.",
        )
    if message_id is None:
        return _unknown_result(
            error_kind="response_shape_invalid",
            error_summary="Discord message response omitted its identity.",
        )
    if not isinstance(message_id, str) or not message_id.isdigit():
        return _unknown_result(
            error_kind="response_shape_invalid",
            error_summary="Discord message response contained an invalid identity.",
        )
    return DiscordDeliveryResult(
        status="delivered",
        provider_message_key=f"discord:{guild_id}:{message_id}",
        error_kind=None,
        error_summary=None,
    )


def _thread_result(
    *,
    response: httpx.Response,
    parent_channel_id: str,
    root_message_id: str,
) -> DiscordDeliveryResult:
    """Validate that Discord returned the expected thread channel."""
    try:
        payload: object = response.json()
    except ValueError:
        return _unknown_result(
            error_kind="response_malformed",
            error_summary="Discord thread response was malformed.",
        )
    if not isinstance(payload, dict):
        return _unknown_result(
            error_kind="response_shape_invalid",
            error_summary="Discord thread response was invalid.",
        )
    thread = payload.get("thread") if "thread" in payload else payload
    if not isinstance(thread, dict):
        return _unknown_result(
            error_kind="thread_response_invalid",
            error_summary="Discord thread response omitted its thread object.",
        )
    thread_id = thread.get("id")
    if thread.get("parent_id") != parent_channel_id:
        return _unknown_result(
            error_kind="thread_response_invalid",
            error_summary="Discord thread response had the wrong parent channel.",
        )
    if not isinstance(thread_id, str) or not thread_id.isdigit():
        return _unknown_result(
            error_kind="thread_response_invalid",
            error_summary="Discord thread response contained an invalid identity.",
        )
    return DiscordDeliveryResult(
        status="delivered",
        provider_message_key=f"discord-thread:{thread_id}",
        error_kind=None,
        error_summary=None,
    )


def _unknown_result(
    *,
    error_kind: str = "provider_ambiguous",
    error_summary: str = "Discord delivery outcome is unknown.",
) -> DiscordDeliveryResult:
    return DiscordDeliveryResult(
        status="unknown",
        provider_message_key=None,
        error_kind=error_kind,
        error_summary=error_summary,
    )


def _rejected_result() -> DiscordDeliveryResult:
    return DiscordDeliveryResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_rejected",
        error_summary="Discord rejected the provider operation.",
    )


class _DiscordMultipartStream(httpx.AsyncByteStream):
    """Encode a bounded multipart request while yielding file chunks lazily."""

    def __init__(
        self,
        *,
        payload: dict[str, object],
        files: tuple[DiscordOutboundFile, ...],
    ) -> None:
        self._boundary = secrets.token_hex(16)
        self._payload = json.dumps(payload, separators=(",", ":")).encode()
        self._files = files
        self.headers = {
            "Content-Type": f"multipart/form-data; boundary={self._boundary}",
            "Content-Length": str(self._content_length()),
        }

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._opening("payload_json")
        yield b"Content-Type: application/json\r\n\r\n"
        yield self._payload
        yield b"\r\n"
        for index, file in enumerate(self._files):
            yield self._opening(f"files[{index}]", filename=file.filename)
            yield f"Content-Type: {file.media_type}\r\n\r\n".encode()
            emitted = 0
            async for chunk in file.content():
                emitted += len(chunk)
                if emitted > file.length:
                    raise DiscordOutboundFileContentError
                yield chunk
            if emitted != file.length:
                raise DiscordOutboundFileContentError
            yield b"\r\n"
        yield f"--{self._boundary}--\r\n".encode()

    async def aclose(self) -> None:
        """The source iterators are owned and finalized by their producer."""

    def _content_length(self) -> int:
        length = (
            len(self._opening("payload_json"))
            + len(b"Content-Type: application/json\r\n\r\n")
            + len(self._payload)
            + len(b"\r\n")
        )
        for index, file in enumerate(self._files):
            length += (
                len(self._opening(f"files[{index}]", filename=file.filename))
                + len(f"Content-Type: {file.media_type}\r\n\r\n".encode())
                + file.length
                + len(b"\r\n")
            )
        return length + len(f"--{self._boundary}--\r\n".encode())

    def _opening(self, name: str, *, filename: str | None = None) -> bytes:
        disposition = f'Content-Disposition: form-data; name="{name}"'
        if filename is not None:
            safe_filename = filename.replace("\\", "\\\\").replace('"', '\\"')
            disposition += f'; filename="{safe_filename}"'
        return f"--{self._boundary}\r\n{disposition}\r\n".encode()
