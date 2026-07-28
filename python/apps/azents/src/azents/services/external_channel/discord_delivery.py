"""Bounded Discord message delivery primitives for durable Channel Actions."""

import hashlib
import json
import secrets
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Literal

import httpx

from azents.services.external_channel.discord_endpoint import discord_api_base_url

_DISCORD_NONCE_MAX_LENGTH = 25
DISCORD_DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DISCORD_CREATE_MESSAGE_MAX_REQUEST_BYTES = 25 * 1024 * 1024


@dataclass(frozen=True)
class DiscordDeliveryResult:
    """Sanitized result of one at-most-once Discord message mutation."""

    status: Literal["delivered", "failed", "unknown"]
    provider_message_key: str | None
    error_kind: str | None
    error_summary: str | None


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
    ) -> DiscordDeliveryResult:
        """Return only after the root Discord message has a usable thread."""
        existing = await self._read_root_thread(
            bot_token=bot_token,
            parent_channel_id=parent_channel_id,
            root_message_id=root_message_id,
        )
        if existing is not None:
            return existing
        response = await self._request(
            "POST",
            f"/channels/{parent_channel_id}/messages/{root_message_id}/threads",
            bot_token=bot_token,
            json_body={"name": "Azents"},
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
            return result
        reconciled = await self._read_root_thread(
            bot_token=bot_token,
            parent_channel_id=parent_channel_id,
            root_message_id=root_message_id,
        )
        if reconciled is not None:
            return reconciled
        return result

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
        delivery_attempt_id: str,
        components: list[dict[str, object]] | None = None,
        embeds: list[dict[str, object]] | None = None,
    ) -> DiscordDeliveryResult:
        """Create one message with a durable-attempt-derived duplicate nonce."""
        payload: dict[str, object] = {
            "content": content,
            "nonce": discord_delivery_nonce(delivery_attempt_id),
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
        delivery_attempt_id: str,
    ) -> DiscordDeliveryResult:
        """Create one nonce-fenced multipart message from streaming file sources."""
        if not files:
            return _rejected_result()
        try:
            stream = _DiscordMultipartStream(
                payload={
                    "content": content,
                    "nonce": discord_delivery_nonce(delivery_attempt_id),
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
        embeds: list[dict[str, object]] | None = None,
    ) -> DiscordDeliveryResult:
        """Update one currently owned Discord message."""
        response = await self._request(
            "PATCH",
            f"/channels/{channel_id}/messages/{message_id}",
            bot_token=bot_token,
            json_body={
                "content": content,
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


def discord_delivery_nonce(delivery_attempt_id: str) -> str:
    """Return a bounded deterministic nonce for one durable create attempt."""
    return hashlib.sha256(delivery_attempt_id.encode()).hexdigest()[
        :_DISCORD_NONCE_MAX_LENGTH
    ]


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
