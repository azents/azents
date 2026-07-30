"""Bounded Discord conversation-history hydration primitives."""

import asyncio
import json
import time
from dataclasses import dataclass

import httpx

from azents.services.external_channel.conversation import (
    ExternalChannelHistoryCredentialsInvalid,
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPermissionDenied,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRange,
    ExternalChannelHistoryRangeIncomplete,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryResourceUnavailable,
    ExternalChannelHistoryTemporaryFailure,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
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
MAX_DISCORD_HISTORY_PAGES = 20
MAX_DISCORD_HISTORY_SCANNED_MESSAGES = 2_000
MAX_DISCORD_HISTORY_RETAINED_MESSAGES = 20


class DiscordHistoryRequestRejected(DiscordHistoryProviderError):
    """Discord rejected a syntactically valid history request."""


@dataclass(frozen=True)
class DiscordThreadPage:
    """One normalized bounded Discord history page."""

    messages: tuple[DiscordNormalizedMessage, ...]
    next_cursor: str | None


@dataclass(frozen=True)
class DiscordConversationHistoryTrigger:
    """Credential-free provider locator for one bounded Discord history range."""

    guild_id: str
    source_channel_id: str
    conversation_channel_id: str
    trigger_message_id: str
    connected_bot_user_id: str | None


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

    async def read_range(
        self,
        *,
        trigger: DiscordConversationHistoryTrigger,
        bot_token: str,
        exclusive_start_position: str | None,
        deadline: ExternalChannelOperationDeadline,
    ) -> ExternalChannelHistoryRange[DiscordNormalizedMessage]:
        """Read a bounded exclusive-start, inclusive-trigger Discord range."""
        started = time.monotonic()
        trigger_position = discord_provider_position(trigger.trigger_message_id)
        if exclusive_start_position is not None and not _valid_discord_position(
            exclusive_start_position
        ):
            raise ExternalChannelHistoryPositionInvalid(
                "Discord history range start position is invalid."
            )
        cursor: str | None = None
        pages = 0
        scanned = 0
        normalized_messages: list[DiscordNormalizedMessage] = []
        while True:
            if deadline.remaining_seconds() <= 0:
                raise ExternalChannelHistoryDeadlineExceeded(
                    "Discord history retrieval exceeded its deadline."
                )
            pages += 1
            if pages > MAX_DISCORD_HISTORY_PAGES:
                raise ExternalChannelHistoryRangeIncomplete(
                    "Discord history range exceeded the bounded page limit."
                )
            try:
                if cursor is None:
                    response = await self._request(
                        "GET",
                        f"/channels/{trigger.conversation_channel_id}/messages/"
                        f"{trigger.trigger_message_id}",
                        bot_token=bot_token,
                        deadline=deadline,
                    )
                    self._validate_response_size(response)
                    exact_payload = self._object_payload(response)
                    self._validate_message_size(exact_payload)
                    if exact_payload.get("id") != trigger.trigger_message_id:
                        raise ExternalChannelHistoryTriggerMissing(
                            "Discord history did not return the exact trigger."
                        )
                    self._validate_history_item(
                        exact_payload,
                        trigger=trigger,
                    )
                    exact_message = self._normalize(
                        guild_id=trigger.guild_id,
                        raw_message=exact_payload,
                        connected_bot_user_id=None,
                    )
                    if exact_message is None:
                        raise ExternalChannelHistoryTriggerMissing(
                            "Discord history trigger was authored by the connected Bot."
                        )
                    if (
                        trigger.connected_bot_user_id is not None
                        and exact_message.provider_user_id
                        == trigger.connected_bot_user_id
                    ):
                        raise ExternalChannelHistoryTriggerMissing(
                            "Discord history trigger was authored by the connected Bot."
                        )
                    normalized_messages.append(exact_message)
                    scanned = 1
                    cursor = trigger.trigger_message_id
                    continue
                params: dict[str, str | int] = {"limit": 100, "before": cursor}
                response = await self._request(
                    "GET",
                    f"/channels/{trigger.conversation_channel_id}/messages",
                    bot_token=bot_token,
                    params=params,
                    deadline=deadline,
                )
                self._validate_response_size(response)
                payload = self._array_payload(response)
                if len(payload) > 100:
                    raise ExternalChannelHistoryMalformed(
                        "Discord history response exceeded the requested limit."
                    )
                page_messages: list[DiscordNormalizedMessage] = []
                oldest_position: str | None = None
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    self._validate_message_size(item)
                    self._validate_history_item(item, trigger=trigger)
                    message = self._normalize(
                        guild_id=trigger.guild_id,
                        raw_message=item,
                        connected_bot_user_id=None,
                    )
                    if message is None:
                        continue
                    if (
                        trigger.connected_bot_user_id is not None
                        and message.provider_user_id == trigger.connected_bot_user_id
                    ):
                        continue
                    scanned += 1
                    if scanned > MAX_DISCORD_HISTORY_SCANNED_MESSAGES:
                        raise ExternalChannelHistoryRangeIncomplete(
                            "Discord history range exceeded the bounded message limit."
                        )
                    page_messages.append(message)
                    oldest_position = (
                        message.provider_position
                        if oldest_position is None
                        else min(oldest_position, message.provider_position)
                    )
                    eligible_count = sum(
                        1
                        for candidate in (*normalized_messages, *page_messages)
                        if (
                            exclusive_start_position is None
                            or candidate.provider_position > exclusive_start_position
                        )
                    )
                    if eligible_count >= MAX_DISCORD_HISTORY_RETAINED_MESSAGES + 1:
                        break
                normalized_messages.extend(page_messages)
                eligible_count = sum(
                    1
                    for message in normalized_messages
                    if (
                        exclusive_start_position is None
                        or message.provider_position > exclusive_start_position
                    )
                )
                reached_start = (
                    eligible_count >= MAX_DISCORD_HISTORY_RETAINED_MESSAGES + 1
                )
                if (
                    exclusive_start_position is not None
                    and oldest_position is not None
                    and oldest_position <= exclusive_start_position
                ):
                    reached_start = True
                if not payload or reached_start:
                    break
                last_item = payload[-1]
                if not isinstance(last_item, dict) or not isinstance(
                    last_item.get("id"), str
                ):
                    raise ExternalChannelHistoryRangeIncomplete(
                        "Discord history pagination cursor is invalid."
                    )
                cursor = last_item["id"]
            except DiscordHistoryCredentialsInvalid as error:
                raise ExternalChannelHistoryCredentialsInvalid(str(error)) from error
            except DiscordHistoryPermissionDenied as error:
                raise ExternalChannelHistoryPermissionDenied(str(error)) from error
            except DiscordHistoryResourceUnavailable as error:
                raise ExternalChannelHistoryResourceUnavailable(str(error)) from error
            except DiscordHistoryRateLimited as error:
                raise ExternalChannelHistoryRateLimited(
                    error.retry_after_seconds
                ) from error
            except DiscordHistoryResponseMalformed as error:
                raise ExternalChannelHistoryMalformed(str(error)) from error
            except DiscordHistoryRequestRejected as error:
                raise ExternalChannelHistoryTemporaryFailure(str(error)) from error
            except DiscordHistoryTemporaryError as error:
                raise ExternalChannelHistoryTemporaryFailure(str(error)) from error
            except TimeoutError as error:
                raise ExternalChannelHistoryDeadlineExceeded(
                    "Discord history retrieval exceeded its deadline."
                ) from error

        in_range = [
            message
            for message in normalized_messages
            if (
                (
                    exclusive_start_position is None
                    or message.provider_position > exclusive_start_position
                )
                and message.provider_position <= trigger_position
            )
        ]
        in_range.sort(key=lambda message: message.provider_position)
        trigger_messages = [
            message
            for message in in_range
            if message.message_id == trigger.trigger_message_id
        ]
        if not trigger_messages:
            raise ExternalChannelHistoryTriggerMissing(
                "Discord history did not contain the exact trigger."
            )
        context_omitted = len(in_range) > MAX_DISCORD_HISTORY_RETAINED_MESSAGES
        retained = tuple(in_range[-MAX_DISCORD_HISTORY_RETAINED_MESSAGES:])
        trigger_message = trigger_messages[0]
        if trigger_message not in retained:
            retained = tuple(
                sorted(
                    (*retained[:-1], trigger_message),
                    key=lambda message: message.provider_position,
                )
            )
        return ExternalChannelHistoryRange(
            messages=retained,
            trigger=trigger_message,
            context_omitted=context_omitted,
            range_start_position=exclusive_start_position,
            trigger_position=trigger_message.provider_position,
            provider_request_count=pages,
            scanned_message_count=scanned,
            elapsed_seconds=max(0.0, time.monotonic() - started),
        )

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
        deadline: ExternalChannelOperationDeadline | None = None,
    ) -> httpx.Response:
        try:
            remaining: float | None = None
            if deadline is not None:
                remaining = deadline.remaining_seconds()
                if remaining <= 0:
                    raise TimeoutError
            request = self.http_client.request(
                method,
                f"{discord_api_base_url()}{path}",
                headers={"Authorization": f"Bot {bot_token}"},
                params=params,
            )
            if deadline is None:
                response = await request
            else:
                assert remaining is not None
                async with asyncio.timeout(remaining):
                    response = await request
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
    def _validate_history_item(
        item: dict[str, object],
        *,
        trigger: DiscordConversationHistoryTrigger,
    ) -> None:
        """Validate one message remains inside the requested channel boundary."""
        if item.get("channel_id") != trigger.conversation_channel_id:
            raise ExternalChannelHistoryMalformed(
                "Discord history item crossed the requested channel."
            )
        raw_thread = item.get("thread")
        if (
            isinstance(raw_thread, dict)
            and trigger.conversation_channel_id != trigger.source_channel_id
            and (
                raw_thread.get("id") != trigger.conversation_channel_id
                or (
                    raw_thread.get("parent_id") is not None
                    and raw_thread.get("parent_id") != trigger.source_channel_id
                )
            )
        ):
            raise ExternalChannelHistoryMalformed(
                "Discord history item had an invalid thread boundary."
            )

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


def discord_provider_position(message_id: str) -> str:
    """Return a fixed-width lexically sortable Discord snowflake position."""
    if not message_id.isdigit():
        raise ExternalChannelHistoryPositionInvalid("Discord message ID is invalid.")
    return f"{int(message_id):020d}"


def _valid_discord_position(position: str) -> bool:
    return len(position) == 20 and position.isdigit()
