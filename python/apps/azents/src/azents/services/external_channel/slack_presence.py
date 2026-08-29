"""Lease-owned Slack Work presence projection."""

import asyncio
import dataclasses
import logging
import re
from collections.abc import Awaitable
from typing import Literal

import aiohttp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.repos.external_channel.data import SlackWorkPresenceTarget
from azents.services.external_channel.presentation import normalize_slack_agent_name

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class SlackPresenceOutcome:
    """Sanitized result of one Slack presence mutation."""

    status: Literal["delivered", "failed", "unknown"]
    error_kind: str | None


class SlackWorkPresenceClient:
    """Public Slack SDK adapter for channel and thread Work presence."""

    def __init__(self, web_client: AsyncWebClient) -> None:
        """Create one presence client with an SDK-owned HTTP session."""
        self.web_client = web_client

    async def set_presence(
        self,
        *,
        bot_token: str,
        target: SlackWorkPresenceTarget,
    ) -> SlackPresenceOutcome:
        """Apply one target-appropriate desired Work presence state."""
        username = (
            normalize_slack_agent_name(target.agent_name)
            if target.customize_messages
            else None
        )
        if target.kind == "channel_loading":
            request = self.web_client.assistant_threads_setStatus(
                channel_id=target.channel_id,
                thread_ts=target.thread_ts,
                status=(
                    target.status_text
                    if target.desired_state == "processing"
                    and target.status_text is not None
                    else ""
                ),
                username=username,
                token=bot_token,
            )
            return await self._attempt(
                api_method="assistant.threads.setStatus",
                request=request,
            )
        request = self.web_client.agents_sessions_setStatus(
            channel_id=target.channel_id,
            thread_ts=target.thread_ts,
            status=("processing" if target.desired_state == "processing" else "active"),
            initiator_user_id=(
                target.initiator_user_id
                if target.desired_state == "processing"
                else None
            ),
            username=username,
            token=bot_token,
        )
        return await self._attempt(
            api_method="agents.sessions.setStatus",
            request=request,
        )

    async def _attempt(
        self,
        *,
        api_method: str,
        request: Awaitable[AsyncSlackResponse],
    ) -> SlackPresenceOutcome:
        """Classify one bounded SDK presence call without provider content."""
        try:
            async with asyncio.timeout(20):
                await request
        except SlackApiError as error:
            return _slack_api_outcome(error, api_method=api_method)
        except TimeoutError, aiohttp.ClientError:
            return SlackPresenceOutcome(
                status="unknown",
                error_kind="provider_ambiguous",
            )
        return SlackPresenceOutcome(status="delivered", error_kind=None)


def _slack_api_outcome(
    error: SlackApiError,
    *,
    api_method: str,
) -> SlackPresenceOutcome:
    """Map one Slack API rejection into a sanitized presence outcome."""
    response = error.response
    if not isinstance(response, AsyncSlackResponse):
        return SlackPresenceOutcome(
            status="unknown",
            error_kind="provider_ambiguous",
        )
    payload = response.data if isinstance(response.data, dict) else {}
    error_code = payload.get("error")
    normalized = (
        error_code
        if isinstance(error_code, str) and re.fullmatch(r"[a-z0-9_]{1,80}", error_code)
        else "provider_rejected"
    )
    if response.status_code >= 500:
        return SlackPresenceOutcome(
            status="unknown",
            error_kind="provider_ambiguous",
        )
    if response.status_code == 429:
        return SlackPresenceOutcome(status="failed", error_kind="rate_limited")
    if normalized == "missing_scope":
        return SlackPresenceOutcome(status="failed", error_kind="missing_scope")
    if normalized == "feature_disabled":
        return SlackPresenceOutcome(status="failed", error_kind="feature_disabled")
    if normalized in {
        "account_inactive",
        "invalid_auth",
        "not_authed",
        "not_allowed_token_type",
        "token_revoked",
    }:
        return SlackPresenceOutcome(
            status="failed",
            error_kind="credentials_invalid",
        )
    if normalized in {
        "app_not_authorized",
        "channel_not_found",
        "is_archived",
        "not_in_channel",
        "thread_not_found",
    }:
        return SlackPresenceOutcome(
            status="failed",
            error_kind="resource_unavailable",
        )
    logger.warning(
        "Slack Work presence was rejected",
        extra={
            "slack_api_method": api_method,
            "slack_error_code": normalized,
        },
    )
    return SlackPresenceOutcome(status="failed", error_kind=normalized)
