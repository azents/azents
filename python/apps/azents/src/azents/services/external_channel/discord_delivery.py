"""Bounded Discord message delivery through public SDK APIs and exact byte gaps."""

import asyncio
import contextlib
import json
import secrets
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass, replace
from typing import Literal, Protocol

import httpx

from azents.core.external_channel_title import normalize_discord_thread_title
from azents.services.external_channel.data import (
    DiscordThreadAutoArchiveDurationMinutes,
)
from azents.services.external_channel.discord_endpoint import discord_api_base_url
from azents.services.external_channel.discord_sdk import (
    DiscordSDKClientFactory,
    DiscordSDKCredentialsInvalid,
    DiscordSDKError,
    DiscordSDKMessage,
    DiscordSDKMessageForwardingSession,
    DiscordSDKPermissionDenied,
    DiscordSDKRateLimited,
    DiscordSDKRequestRejected,
    DiscordSDKResourceUnavailable,
    DiscordSDKSession,
    DiscordSDKThread,
    DiscordSDKUnavailable,
)
from azents.services.external_channel.provider_effect import ProviderOperationKey

DISCORD_DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DISCORD_CREATE_MESSAGE_MAX_REQUEST_BYTES = 25 * 1024 * 1024
_DISCORD_DELIVERY_TIMEOUT_SECONDS = 20.0


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


class DiscordFileMessageTransport:
    """G2 direct transport for streamed Discord multipart file messages only."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def create_file_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        files: tuple[DiscordOutboundFile, ...],
        nonce: str,
    ) -> DiscordDeliveryResult:
        """Create one exact-length multipart message through approved gap G2."""
        if not files:
            return _rejected_result()
        try:
            stream = _DiscordMultipartStream(
                payload={
                    "content": content,
                    "nonce": nonce,
                    "enforce_nonce": True,
                    "attachments": [
                        {"id": str(index), "filename": file.filename}
                        for index, file in enumerate(files)
                    ],
                },
                files=files,
            )
            response = await self.http_client.post(
                f"{discord_api_base_url()}/channels/{channel_id}/messages",
                headers={"Authorization": f"Bot {bot_token}", **stream.headers},
                content=stream,
            )
        except DiscordOutboundFileContentError:
            return DiscordDeliveryResult(
                status="unknown",
                provider_message_key=None,
                error_kind="provider_ambiguous",
                error_summary=(
                    "Discord file delivery outcome is unknown after the source changed."
                ),
            )
        except httpx.RequestError:
            return _unknown_result(
                error_kind="transport_unknown",
                error_summary="Discord file delivery outcome is unknown.",
            )
        failure = _response_failure(response)
        if failure is not None:
            return failure
        return _created_message_result(
            response=response,
            guild_id=guild_id,
            channel_id=channel_id,
        )


class DiscordFileMessageTransportProtocol(Protocol):
    """One exact G2 multipart file-message operation."""

    async def create_file_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        files: tuple[DiscordOutboundFile, ...],
        nonce: str,
    ) -> DiscordDeliveryResult:
        """Create one streamed multipart file message."""
        ...


class DiscordDeliveryClient:
    """Perform Discord mutations through one authenticated SDK session."""

    def __init__(
        self,
        sdk_factory: DiscordSDKClientFactory,
        file_transport: DiscordFileMessageTransportProtocol,
    ) -> None:
        self.sdk_factory = sdk_factory
        self.file_transport = file_transport

    def open(
        self,
        *,
        bot_token: str,
    ) -> AbstractAsyncContextManager["DiscordDeliveryClient"]:
        """Open one SDK login and return a workflow-bound delivery client."""
        return self._open(bot_token=bot_token)

    @contextlib.asynccontextmanager
    async def _open(
        self,
        *,
        bot_token: str,
    ) -> AsyncIterator["DiscordDeliveryClient"]:
        stack = AsyncExitStack()
        try:
            async with asyncio.timeout(_DISCORD_DELIVERY_TIMEOUT_SECONDS):
                sdk = await stack.enter_async_context(
                    self.sdk_factory.open(bot_token=bot_token)
                )
            yield DiscordDeliveryClient(
                _BoundDiscordSDKClientFactory(
                    session=sdk,
                    bot_token=bot_token,
                ),
                self.file_transport,
            )
        finally:
            await stack.aclose()

    async def ensure_thread(
        self,
        *,
        bot_token: str,
        guild_id: str,
        parent_channel_id: str,
        root_message_id: str,
        name: str | None,
        auto_archive_duration: DiscordThreadAutoArchiveDurationMinutes,
    ) -> DiscordDeliveryResult:
        """Return only after the root Discord message has a usable Thread."""
        thread_name = _discord_thread_name(name)
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                existing = await sdk.fetch_root_thread(
                    guild_id=guild_id,
                    parent_channel_id=parent_channel_id,
                    root_message_id=root_message_id,
                )
                if existing is not None:
                    return _thread_result(
                        existing,
                        guild_id=guild_id,
                        parent_channel_id=parent_channel_id,
                    )
                try:
                    created = await sdk.create_thread(
                        guild_id=guild_id,
                        parent_channel_id=parent_channel_id,
                        root_message_id=root_message_id,
                        name=thread_name,
                        auto_archive_duration=auto_archive_duration,
                    )
                except DiscordSDKError as error:
                    result = _sdk_delivery_failure(error)
                    reconciled = await sdk.fetch_root_thread(
                        guild_id=guild_id,
                        parent_channel_id=parent_channel_id,
                        root_message_id=root_message_id,
                    )
                    if reconciled is not None:
                        return _thread_result(
                            reconciled,
                            guild_id=guild_id,
                            parent_channel_id=parent_channel_id,
                        )
                    return result
                return replace(
                    _thread_result(
                        created,
                        guild_id=guild_id,
                        parent_channel_id=parent_channel_id,
                    ),
                    created_thread_name=thread_name,
                )
        except DiscordSDKError as error:
            return _sdk_delivery_failure(error)
        except TimeoutError:
            return _sdk_timeout_result()

    async def read_thread_title(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
    ) -> DiscordThreadTitleReadResult:
        """Read one exact Discord Thread title without retry."""
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                thread = await sdk.fetch_thread(
                    guild_id=guild_id,
                    channel_id=channel_id,
                )
        except DiscordSDKResourceUnavailable:
            return DiscordThreadTitleReadResult(
                status="missing", name=None, error_kind="thread_not_found"
            )
        except DiscordSDKError as error:
            failure = _sdk_delivery_failure(error)
            return DiscordThreadTitleReadResult(
                status="failed" if failure.status == "failed" else "unknown",
                name=None,
                error_kind=failure.error_kind,
            )
        except TimeoutError:
            return DiscordThreadTitleReadResult(
                status="unknown",
                name=None,
                error_kind="transport_unknown",
            )
        return DiscordThreadTitleReadResult(
            status="present", name=thread.name, error_kind=None
        )

    async def update_thread_title(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        name: str,
    ) -> DiscordDeliveryResult:
        """Apply one name-only Discord Thread update without retry."""
        normalized = normalize_discord_thread_title(name)
        if normalized is None:
            return _rejected_result()
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                thread = await sdk.update_thread_name(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    name=normalized,
                )
        except DiscordSDKError as error:
            return _sdk_delivery_failure(error)
        except TimeoutError:
            return _sdk_timeout_result()
        if thread.name != normalized:
            return _unknown_result(
                error_kind="response_shape_invalid",
                error_summary="Discord Thread update response was invalid.",
            )
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=f"discord-thread:{channel_id}",
            error_kind=None,
            error_summary=None,
        )

    async def create_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        operation_key: ProviderOperationKey,
        suppress_notifications: bool,
        components: list[dict[str, object]] | None = None,
        embeds: list[dict[str, object]] | None = None,
        forward_to_parent: bool = False,
        parent_channel_id: str | None = None,
    ) -> DiscordDeliveryResult:
        """Create once and optionally forward the exact Message to its parent."""
        if forward_to_parent and parent_channel_id is None:
            return _rejected_result()
        created_result: DiscordDeliveryResult | None = None
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                message = await sdk.create_message(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    content=content,
                    nonce=discord_delivery_nonce(operation_key),
                    suppress_notifications=suppress_notifications,
                    components=components,
                    embeds=embeds,
                )
                created_result = _sdk_message_result(
                    message,
                    guild_id=guild_id,
                    channel_id=channel_id,
                )
                if created_result.status != "delivered" or not forward_to_parent:
                    return created_result
                assert parent_channel_id is not None
                if not isinstance(sdk, DiscordSDKMessageForwardingSession):
                    return _forwarding_result(
                        created_result,
                        _unknown_result(
                            error_kind="provider_ambiguous",
                            error_summary=(
                                "Discord native message forwarding is unavailable."
                            ),
                        ),
                    )
                try:
                    forwarded = await sdk.forward_message(
                        message=message,
                        destination_channel_id=parent_channel_id,
                    )
                except DiscordSDKError as error:
                    return _forwarding_result(
                        created_result,
                        _sdk_delivery_failure(error),
                    )
                return _forwarding_result(
                    created_result,
                    _sdk_message_result(
                        forwarded,
                        guild_id=guild_id,
                        channel_id=parent_channel_id,
                    ),
                )
        except DiscordSDKError as error:
            return _sdk_delivery_failure(error)
        except TimeoutError:
            if created_result is not None:
                return _forwarding_result(created_result, _sdk_timeout_result())
            return _sdk_timeout_result()

    async def create_file_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        content: str,
        files: tuple[DiscordOutboundFile, ...],
        operation_key: ProviderOperationKey,
        forward_to_parent: bool,
        parent_channel_id: str | None,
    ) -> DiscordDeliveryResult:
        """Create one multipart message and optionally forward it to its parent."""
        if forward_to_parent and parent_channel_id is None:
            return _rejected_result()
        created = await self.file_transport.create_file_message(
            bot_token=bot_token,
            guild_id=guild_id,
            channel_id=channel_id,
            content=content,
            files=files,
            nonce=discord_delivery_nonce(operation_key),
        )
        if created.status != "delivered" or not forward_to_parent:
            return created
        message = _file_message_identity(
            created,
            guild_id=guild_id,
            channel_id=channel_id,
        )
        if message is None:
            return _forwarding_result(
                created,
                _unknown_result(
                    error_kind="response_shape_invalid",
                    error_summary="Discord file message identity was invalid.",
                ),
            )
        assert parent_channel_id is not None
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                if not isinstance(sdk, DiscordSDKMessageForwardingSession):
                    return _forwarding_result(
                        created,
                        _unknown_result(
                            error_kind="provider_ambiguous",
                            error_summary=(
                                "Discord native message forwarding is unavailable."
                            ),
                        ),
                    )
                forwarded = await sdk.forward_message(
                    message=message,
                    destination_channel_id=parent_channel_id,
                )
        except DiscordSDKError as error:
            return _forwarding_result(created, _sdk_delivery_failure(error))
        except TimeoutError:
            return _forwarding_result(created, _sdk_timeout_result())
        return _forwarding_result(
            created,
            _sdk_message_result(
                forwarded,
                guild_id=guild_id,
                channel_id=parent_channel_id,
            ),
        )

    async def update_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        message_id: str,
        content: str | None,
        components: list[dict[str, object]] | None = None,
        embeds: list[dict[str, object]] | None = None,
    ) -> DiscordDeliveryResult:
        """Update one currently owned Discord message through the SDK."""
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                message = await sdk.update_message(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=message_id,
                    content=content,
                    components=components,
                    embeds=embeds,
                )
        except DiscordSDKError as error:
            return _sdk_delivery_failure(error)
        except TimeoutError:
            return _sdk_timeout_result()
        return _sdk_message_result(message, guild_id=guild_id, channel_id=channel_id)

    async def delete_message(
        self,
        *,
        bot_token: str,
        guild_id: str,
        channel_id: str,
        message_id: str,
    ) -> DiscordDeliveryResult:
        """Delete one currently owned Discord message through the SDK."""
        try:
            async with self._open_sdk(bot_token=bot_token) as sdk:
                await sdk.delete_message(
                    guild_id=guild_id,
                    channel_id=channel_id,
                    message_id=message_id,
                )
        except DiscordSDKError as error:
            return _sdk_delivery_failure(error)
        except TimeoutError:
            return _sdk_timeout_result()
        return DiscordDeliveryResult(
            status="delivered",
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
        )

    @contextlib.asynccontextmanager
    async def _open_sdk(
        self,
        *,
        bot_token: str,
    ) -> AsyncIterator[DiscordSDKSession]:
        async with asyncio.timeout(_DISCORD_DELIVERY_TIMEOUT_SECONDS):
            async with self.sdk_factory.open(bot_token=bot_token) as sdk:
                yield sdk


class _BoundDiscordSDKClientFactory:
    """Yield one existing operation-scoped SDK session without another login."""

    def __init__(
        self,
        *,
        session: DiscordSDKSession,
        bot_token: str,
    ) -> None:
        self.session = session
        self.bot_token = bot_token

    def open(
        self,
        *,
        bot_token: str,
    ) -> AbstractAsyncContextManager[DiscordSDKSession]:
        """Return the existing authenticated session for the same credential."""
        if bot_token != self.bot_token:
            raise DiscordSDKRequestRejected(
                "Discord workflow credential changed during delivery."
            )
        return self._open()

    @contextlib.asynccontextmanager
    async def _open(self) -> AsyncIterator[DiscordSDKSession]:
        yield self.session


def _discord_thread_name(name: str | None) -> str:
    """Return one bounded valid Discord Thread name."""
    normalized = "" if name is None else " ".join(name.split())
    return (normalized or "Azents")[:100]


def discord_delivery_nonce(operation_key: ProviderOperationKey) -> str:
    """Return the bounded duplicate nonce for one live create operation."""
    return operation_key.value


def _sdk_message_result(
    message: DiscordSDKMessage,
    *,
    guild_id: str,
    channel_id: str,
) -> DiscordDeliveryResult:
    if message.guild_id != guild_id or message.channel_id != channel_id:
        return _unknown_result(
            error_kind="response_channel_mismatch",
            error_summary="Discord message response targeted another channel.",
        )
    if not message.message_id.isdigit():
        return _unknown_result(
            error_kind="response_shape_invalid",
            error_summary="Discord message response contained an invalid identity.",
        )
    return DiscordDeliveryResult(
        status="delivered",
        provider_message_key=f"discord:{guild_id}:{message.message_id}",
        error_kind=None,
        error_summary=None,
    )


def _forwarding_result(
    created: DiscordDeliveryResult,
    forwarded: DiscordDeliveryResult,
) -> DiscordDeliveryResult:
    """Retain the created Thread message identity with the surfacing outcome."""
    return replace(
        forwarded,
        provider_message_key=created.provider_message_key,
    )


def _file_message_identity(
    created: DiscordDeliveryResult,
    *,
    guild_id: str,
    channel_id: str,
) -> DiscordSDKMessage | None:
    prefix = f"discord:{guild_id}:"
    provider_message_key = created.provider_message_key
    if provider_message_key is None or not provider_message_key.startswith(prefix):
        return None
    message_id = provider_message_key.removeprefix(prefix)
    if not message_id.isdigit():
        return None
    return DiscordSDKMessage(
        message_id=message_id,
        channel_id=channel_id,
        guild_id=guild_id,
    )


def _thread_result(
    thread: DiscordSDKThread,
    *,
    guild_id: str,
    parent_channel_id: str,
) -> DiscordDeliveryResult:
    if (
        thread.guild_id != guild_id
        or thread.parent_id != parent_channel_id
        or not thread.thread_id.isdigit()
    ):
        return _unknown_result(
            error_kind="thread_response_invalid",
            error_summary="Discord Thread response had an invalid relationship.",
        )
    return DiscordDeliveryResult(
        status="delivered",
        provider_message_key=f"discord-thread:{thread.thread_id}",
        error_kind=None,
        error_summary=None,
    )


def _sdk_delivery_failure(error: DiscordSDKError) -> DiscordDeliveryResult:
    if isinstance(error, DiscordSDKCredentialsInvalid):
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="credentials_invalid",
            error_summary="Discord rejected the active Bot credential.",
        )
    if isinstance(error, DiscordSDKPermissionDenied):
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="permission_denied",
            error_summary="Discord denied access to the target conversation.",
        )
    if isinstance(error, DiscordSDKResourceUnavailable):
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="message_not_found",
            error_summary="Discord no longer exposes the target message.",
        )
    if isinstance(error, DiscordSDKRateLimited):
        return DiscordDeliveryResult(
            status="failed",
            provider_message_key=None,
            error_kind="rate_limited",
            error_summary="Discord rate limited the provider operation.",
        )
    if isinstance(error, DiscordSDKRequestRejected):
        return _rejected_result()
    if isinstance(error, DiscordSDKUnavailable):
        return _unknown_result(
            error_kind="provider_ambiguous",
            error_summary="Discord delivery outcome is unknown.",
        )
    return _unknown_result()


def _response_failure(response: httpx.Response) -> DiscordDeliveryResult | None:
    """Map one G2 HTTP response into a sanitized delivery outcome."""
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


def _sdk_timeout_result() -> DiscordDeliveryResult:
    return _unknown_result(
        error_kind="transport_unknown",
        error_summary="Discord delivery exceeded its provider deadline.",
    )


def _rejected_result() -> DiscordDeliveryResult:
    return DiscordDeliveryResult(
        status="failed",
        provider_message_key=None,
        error_kind="provider_rejected",
        error_summary="Discord rejected the provider operation.",
    )


class _DiscordMultipartStream(httpx.AsyncByteStream):
    """Encode one bounded G2 multipart request while yielding chunks lazily."""

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
