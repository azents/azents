"""Bounded Discord conversation-history hydration primitives."""

import json
from dataclasses import dataclass

import httpx

from azents.services.external_channel.discord_endpoint import discord_api_base_url
from azents.services.external_channel.discord_events import (
    DiscordEventExcluded,
    DiscordNormalizedMessage,
    normalize_projected_discord_event,
    project_discord_message,
)


class DiscordHistoryProviderError(RuntimeError):
    """Base class for controlled Discord history-hydration failures."""


class DiscordHistoryCredentialsInvalid(DiscordHistoryProviderError):
    """Discord rejected the configured Bot credential."""


class DiscordHistoryPermissionDenied(DiscordHistoryProviderError):
    """Discord denied access to the tracked conversation."""


class DiscordHistoryResourceUnavailable(DiscordHistoryProviderError):
    """Discord no longer exposes the tracked conversation."""


class DiscordHistoryRateLimited(DiscordHistoryProviderError):
    """Discord deferred one history request with a bounded retry delay."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Discord rate limited conversation history.")
        self.retry_after_seconds = retry_after_seconds


class DiscordHistoryTemporaryError(DiscordHistoryProviderError):
    """Discord did not provide a complete history response."""


class DiscordHistoryResponseMalformed(DiscordHistoryTemporaryError):
    """Discord returned a response outside the requested channel boundary."""


MAX_DISCORD_HISTORY_RESPONSE_BYTES = 256 * 1024
MAX_DISCORD_HISTORY_MESSAGE_BYTES = 64 * 1024


class DiscordHistoryRequestRejected(DiscordHistoryProviderError):
    """Discord rejected a syntactically valid history request."""


@dataclass(frozen=True)
class DiscordThreadPage:
    """One normalized bounded Discord history page."""

    messages: tuple[DiscordNormalizedMessage, ...]
    next_cursor: str | None


class DiscordConversationHistoryClient:
    """Fetch canonical Discord source/thread history without retaining raw pages."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def fetch_thread_page(
        self,
        *,
        bot_token: str,
        guild_id: str,
        source_channel_id: str,
        root_message_id: str,
        thread_channel_id: str | None,
        cursor: str | None,
        limit: int,
        connected_bot_user_id: str | None,
    ) -> DiscordThreadPage:
        """Fetch one page for a root source or an already-existing thread."""
        if thread_channel_id is None:
            if cursor is not None:
                return DiscordThreadPage(messages=(), next_cursor=None)
            response = await self._request(
                "GET",
                f"/channels/{source_channel_id}/messages/{root_message_id}",
                bot_token=bot_token,
            )
            self._validate_response_size(response)
            payload = self._object_payload(response)
            self._validate_message_size(payload)
            if (
                payload.get("id") != root_message_id
                or payload.get("channel_id") != source_channel_id
            ):
                raise DiscordHistoryResponseMalformed(
                    "Discord source message response did not match the request."
                )
            message = self._normalize(
                guild_id=guild_id,
                raw_message=payload,
                connected_bot_user_id=connected_bot_user_id,
            )
            return DiscordThreadPage(
                messages=() if message is None else (message,),
                next_cursor=None,
            )

        page_limit = min(max(limit, 1), 100)
        params: dict[str, str | int] = {"limit": page_limit}
        if cursor is not None:
            params["before"] = cursor
        response = await self._request(
            "GET",
            f"/channels/{thread_channel_id}/messages",
            bot_token=bot_token,
            params=params,
        )
        self._validate_response_size(response)
        payload = self._array_payload(response)
        if len(payload) > page_limit:
            raise DiscordHistoryResponseMalformed(
                "Discord history response exceeded the requested limit."
            )
        messages: list[DiscordNormalizedMessage] = []
        oldest_message_id: str | None = None
        for item in payload:
            if isinstance(item, dict):
                self._validate_message_size(item)
            if not isinstance(item, dict):
                continue
            if item.get("channel_id") != thread_channel_id:
                raise DiscordHistoryResponseMalformed(
                    "Discord thread history item crossed the requested channel."
                )
            raw_thread = item.get("thread")
            if isinstance(raw_thread, dict):
                if raw_thread.get("id") != thread_channel_id or (
                    raw_thread.get("parent_id") is not None
                    and raw_thread.get("parent_id") != source_channel_id
                ):
                    raise DiscordHistoryResponseMalformed(
                        "Discord thread history item had an invalid root relationship."
                    )
            message = self._normalize(
                guild_id=guild_id,
                raw_message=item,
                connected_bot_user_id=connected_bot_user_id,
            )
            if message is None:
                continue
            messages.append(message)
            if oldest_message_id is None or message.message_id < oldest_message_id:
                oldest_message_id = message.message_id
        next_cursor = oldest_message_id if len(payload) >= page_limit else None
        return DiscordThreadPage(messages=tuple(messages), next_cursor=next_cursor)

    def _normalize(
        self,
        *,
        guild_id: str,
        raw_message: dict[str, object],
        connected_bot_user_id: str | None,
    ) -> DiscordNormalizedMessage | None:
        try:
            projection = project_discord_message(message=raw_message, guild_id=guild_id)
            return normalize_projected_discord_event(
                event_type="discord_message_create",
                tenant_id=guild_id,
                envelope={"message": projection},
                connected_bot_user_id=connected_bot_user_id,
            )
        except DiscordEventExcluded:
            return None
        except (TypeError, ValueError) as error:
            raise DiscordHistoryTemporaryError(
                "Discord history response contained an invalid message."
            ) from error

    @staticmethod
    def _validate_response_size(response: httpx.Response) -> None:
        if len(response.content) > MAX_DISCORD_HISTORY_RESPONSE_BYTES:
            raise DiscordHistoryResponseMalformed(
                "Discord history response exceeded the size limit."
            )

    @staticmethod
    def _validate_message_size(message: dict[str, object]) -> None:
        try:
            serialized = json.dumps(
                message,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        except (TypeError, ValueError) as error:
            raise DiscordHistoryResponseMalformed(
                "Discord history message could not be bounded."
            ) from error
        if len(serialized) > MAX_DISCORD_HISTORY_MESSAGE_BYTES:
            raise DiscordHistoryResponseMalformed(
                "Discord history message exceeded the size limit."
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        bot_token: str,
        params: dict[str, str | int] | None = None,
    ) -> httpx.Response:
        try:
            response = await self.http_client.request(
                method,
                f"{discord_api_base_url()}{path}",
                headers={"Authorization": f"Bot {bot_token}"},
                params=params,
            )
        except httpx.RequestError as error:
            raise DiscordHistoryTemporaryError(
                "Discord history is temporarily unavailable."
            ) from error
        if response.status_code == 401:
            raise DiscordHistoryCredentialsInvalid(
                "Discord rejected the active Bot credential."
            )
        if response.status_code == 403:
            raise DiscordHistoryPermissionDenied(
                "Discord denied access to the tracked conversation."
            )
        if response.status_code == 404:
            raise DiscordHistoryResourceUnavailable(
                "Discord no longer exposes the tracked conversation."
            )
        if response.status_code == 429:
            raise DiscordHistoryRateLimited(_retry_after_seconds(response))
        if response.status_code >= 500:
            raise DiscordHistoryTemporaryError(
                "Discord history is temporarily unavailable."
            )
        if response.status_code >= 400:
            raise DiscordHistoryRequestRejected(
                "Discord rejected conversation history retrieval."
            )
        return response

    @staticmethod
    def _object_payload(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordHistoryTemporaryError(
                "Discord history response was invalid."
            ) from error
        if not isinstance(payload, dict):
            raise DiscordHistoryTemporaryError("Discord history response was invalid.")
        return payload

    @staticmethod
    def _array_payload(response: httpx.Response) -> list[object]:
        try:
            payload: object = response.json()
        except ValueError as error:
            raise DiscordHistoryTemporaryError(
                "Discord history response was invalid."
            ) from error
        if not isinstance(payload, list):
            raise DiscordHistoryTemporaryError("Discord history response was invalid.")
        return payload


def _retry_after_seconds(response: httpx.Response) -> int:
    """Return a bounded Discord retry delay without retaining provider detail."""
    try:
        payload: object = response.json()
    except ValueError:
        payload = None
    retry_after = payload.get("retry_after") if isinstance(payload, dict) else None
    if isinstance(retry_after, (int, float)) and not isinstance(retry_after, bool):
        return max(1, min(int(retry_after), 300))
    header = response.headers.get("Retry-After")
    try:
        return max(1, min(int(header or "1"), 300))
    except ValueError:
        return 1
