"""Slack HTTP primitives for External Channel admission."""

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Literal

import httpx

from azents.core.enums import (
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.repos.external_channel.data import ExternalChannelEventCreate
from azents.services.external_channel.data import (
    ExternalChannelCapabilitySnapshot,
    ExternalChannelProviderIdentity,
)
from azents.services.external_channel.slack_endpoint import slack_api_base_url

MAX_SLACK_HTTP_BODY_BYTES = 256 * 1024
MAX_SLACK_URL_VERIFICATION_CHALLENGE_BYTES = 4 * 1024
SLACK_SIGNATURE_TOLERANCE_SECONDS = 5 * 60


class SlackHTTPError(ValueError):
    """Base class for controlled Slack callback rejection."""


class SlackHTTPUnauthorized(SlackHTTPError):
    """The callback could not be authenticated for the selected connection."""


class SlackHTTPInvalidPayload(SlackHTTPError):
    """The authenticated callback payload is malformed or unsupported."""


class SlackHTTPPayloadTooLarge(SlackHTTPError):
    """The callback body exceeds the bounded provider-inbox limit."""


@dataclass(frozen=True)
class SlackURLVerification:
    """Bounded Slack URL-verification challenge with no durable side effects."""

    challenge: str


@dataclass(frozen=True)
class SlackEventRouteIdentity:
    """Untrusted provider identity used only to select an HMAC candidate."""

    app_id: str
    tenant_id: str


@dataclass(frozen=True)
class SlackEventCallback:
    """Authenticated ordinary Slack callback normalized for durable admission."""

    app_id: str
    tenant_id: str
    event: ExternalChannelEventCreate


type SlackCallbackEnvelope = SlackURLVerification | SlackEventCallback
type SlackCallbackRoute = SlackURLVerification | SlackEventRouteIdentity


@dataclass(frozen=True)
class SlackConnectionValidation:
    """Sanitized Slack ``auth.test`` result with no credential material."""

    status: Literal["valid", "invalid", "unavailable"]
    code: str | None
    message: str | None
    action_hint: str | None
    identity: ExternalChannelProviderIdentity | None
    capabilities: ExternalChannelCapabilitySnapshot | None


def verify_slack_signature(
    *,
    raw_body: bytes,
    timestamp_header: str | None,
    signature_header: str | None,
    signing_secret: str,
    now: datetime.datetime,
) -> None:
    """Verify Slack's raw-body ``v0`` HMAC and bounded timestamp window."""
    if timestamp_header is None or signature_header is None:
        raise SlackHTTPUnauthorized("Slack signature headers are missing.")
    try:
        timestamp = int(timestamp_header)
    except ValueError as error:
        raise SlackHTTPUnauthorized("Slack request timestamp is invalid.") from error
    if now.tzinfo is None:
        raise ValueError("Signature verification requires a timezone-aware clock.")
    age_seconds = abs(now.timestamp() - timestamp)
    if age_seconds > SLACK_SIGNATURE_TOLERANCE_SECONDS:
        raise SlackHTTPUnauthorized(
            "Slack request timestamp is outside the replay window."
        )
    if not signature_header.startswith("v0="):
        raise SlackHTTPUnauthorized("Slack request signature is malformed.")
    signing_base = b"v0:" + timestamp_header.encode() + b":" + raw_body
    expected = (
        "v0="
        + hmac.new(
            signing_secret.encode(),
            signing_base,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, signature_header):
        raise SlackHTTPUnauthorized("Slack request signature is invalid.")


def parse_slack_callback_route(raw_body: bytes) -> SlackCallbackRoute:
    """Parse only the bounded fields required before signature verification."""
    payload = _parse_payload(raw_body)
    callback_type = _required_string(payload, "type")
    if callback_type == "url_verification":
        challenge = _required_string(payload, "challenge")
        if len(challenge.encode()) > MAX_SLACK_URL_VERIFICATION_CHALLENGE_BYTES:
            raise SlackHTTPPayloadTooLarge(
                "Slack URL verification challenge exceeds the size limit."
            )
        return SlackURLVerification(challenge=challenge)
    if callback_type != "event_callback":
        raise SlackHTTPInvalidPayload("Slack callback type is not supported.")
    return SlackEventRouteIdentity(
        app_id=_required_string(payload, "api_app_id"),
        tenant_id=_required_string(payload, "team_id"),
    )


def parse_slack_callback(
    *,
    connection_id: str,
    raw_body: bytes,
    received_at: datetime.datetime,
) -> SlackCallbackEnvelope:
    """Parse one verified Slack callback into a bounded provider event."""
    payload = _parse_payload(raw_body)

    callback_type = _required_string(payload, "type")
    if callback_type == "url_verification":
        return SlackURLVerification(challenge=_required_string(payload, "challenge"))
    if callback_type != "event_callback":
        raise SlackHTTPInvalidPayload("Slack callback type is not supported.")

    event_id = _required_string(payload, "event_id")
    app_id = _required_string(payload, "api_app_id")
    tenant_id = _required_string(payload, "team_id")
    event_payload = payload.get("event")
    if not isinstance(event_payload, dict):
        raise SlackHTTPInvalidPayload(
            "Slack event callback is missing its event object."
        )
    event_type = _required_string(event_payload, "type")
    provider_enterprise_id = _optional_string(payload, "enterprise_id")
    occurred_at = _provider_occurred_at(payload.get("event_time"))
    projected_payload = _project_envelope(payload, event_payload)
    resource_correlation_key = _resource_correlation_key(event_payload)

    return SlackEventCallback(
        app_id=app_id,
        tenant_id=tenant_id,
        event=ExternalChannelEventCreate(
            connection_id=connection_id,
            provider_event_id=event_id,
            transport_envelope_id=event_id,
            event_type=event_type,
            provider_app_id=app_id,
            provider_tenant_id=tenant_id,
            provider_enterprise_id=provider_enterprise_id,
            resource_correlation_key=resource_correlation_key,
            eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
            envelope=projected_payload,
            status=ExternalChannelEventStatus.ACCEPTED,
            provider_occurred_at=occurred_at,
            received_at=received_at,
        ),
    )


def _parse_payload(raw_body: bytes) -> dict[str, object]:
    if len(raw_body) > MAX_SLACK_HTTP_BODY_BYTES:
        raise SlackHTTPPayloadTooLarge("Slack callback body exceeds the size limit.")
    try:
        payload: object = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SlackHTTPInvalidPayload(
            "Slack callback body is not valid JSON."
        ) from error
    if not isinstance(payload, dict):
        raise SlackHTTPInvalidPayload("Slack callback body must be a JSON object.")
    return payload


class SlackWebAPIClient:
    """Bounded Slack Web API client used for connection identity validation."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def validate_connection(
        self,
        *,
        bot_token: str,
        app_id: str,
        transport: ExternalChannelTransport,
    ) -> SlackConnectionValidation:
        """Validate a bot token and return only sanitized identity state."""
        try:
            response = await self.http_client.post(
                f"{slack_api_base_url()}/auth.test",
                headers={"Authorization": f"Bearer {bot_token}"},
            )
        except httpx.RequestError:
            return self._unavailable()
        if response.status_code == 429 or response.status_code >= 500:
            return self._unavailable()
        payload = self._json_object(response)
        if response.status_code >= 400 or payload.get("ok") is not True:
            error_code = payload.get("error")
            if error_code in {
                "account_inactive",
                "invalid_auth",
                "not_authed",
                "token_revoked",
            }:
                return SlackConnectionValidation(
                    status="invalid",
                    code="slack_credentials_invalid",
                    message="Slack rejected the configured bot token.",
                    action_hint=(
                        "Replace the bot token and validate the connection again."
                    ),
                    identity=None,
                    capabilities=None,
                )
            return self._unavailable(code="slack_auth_test_unavailable")

        team_id = payload.get("team_id")
        user_id = payload.get("user_id")
        bot_id = payload.get("bot_id")
        if not isinstance(team_id, str) or not team_id:
            return self._unavailable(code="slack_auth_test_response_invalid")
        if not isinstance(user_id, str) or not user_id:
            return self._unavailable(code="slack_auth_test_response_invalid")
        if not isinstance(bot_id, str) or not bot_id:
            return self._unavailable(code="slack_auth_test_response_invalid")
        try:
            bot_response = await self.http_client.get(
                f"{slack_api_base_url()}/bots.info",
                headers={"Authorization": f"Bearer {bot_token}"},
                params={"bot": bot_id},
            )
        except httpx.RequestError:
            return self._unavailable()
        if bot_response.status_code == 429 or bot_response.status_code >= 500:
            return self._unavailable()
        bot_payload = self._json_object(bot_response)
        if bot_response.status_code >= 400 or bot_payload.get("ok") is not True:
            error_code = bot_payload.get("error")
            if error_code in {
                "account_inactive",
                "invalid_auth",
                "not_authed",
                "token_revoked",
            }:
                return SlackConnectionValidation(
                    status="invalid",
                    code="slack_credentials_invalid",
                    message="Slack rejected the configured bot token.",
                    action_hint=(
                        "Replace the bot token and validate the connection again."
                    ),
                    identity=None,
                    capabilities=None,
                )
            if error_code == "missing_scope":
                return SlackConnectionValidation(
                    status="invalid",
                    code="slack_bot_identity_scope_missing",
                    message=(
                        "Slack cannot verify the App identity because the bot token "
                        "does not have users:read."
                    ),
                    action_hint=(
                        "Add users:read, reinstall the App, replace the bot token, "
                        "and validate again."
                    ),
                    identity=None,
                    capabilities=None,
                )
            return self._unavailable(code="slack_bot_identity_unavailable")
        bot = bot_payload.get("bot")
        if not isinstance(bot, dict):
            return self._unavailable(code="slack_bot_identity_response_invalid")
        actual_app_id = bot.get("app_id")
        if not isinstance(actual_app_id, str) or not actual_app_id:
            return self._unavailable(code="slack_bot_identity_response_invalid")
        if actual_app_id != app_id:
            return SlackConnectionValidation(
                status="invalid",
                code="slack_app_id_mismatch",
                message="The Slack App ID does not own the configured bot token.",
                action_hint=(
                    "Copy the App ID and Bot User OAuth Token from the same Slack App."
                ),
                identity=None,
                capabilities=None,
            )
        return SlackConnectionValidation(
            status="valid",
            code=None,
            message=None,
            action_hint=None,
            identity=ExternalChannelProviderIdentity(
                provider=ExternalChannelProvider.SLACK,
                app_id=actual_app_id,
                tenant_id=team_id,
                bot_user_id=bot_id,
            ),
            capabilities=ExternalChannelCapabilitySnapshot(
                provider=ExternalChannelProvider.SLACK,
                transport=transport,
                inbound_events=True,
                thread_history=True,
                post_messages=True,
                update_messages=True,
                delete_messages=True,
            ),
        )

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, object]:
        try:
            payload: object = response.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _unavailable(
        *,
        code: str = "slack_unavailable",
    ) -> SlackConnectionValidation:
        return SlackConnectionValidation(
            status="unavailable",
            code=code,
            message="Slack connection validation is temporarily unavailable.",
            action_hint="Retry validation after Slack recovers.",
            identity=None,
            capabilities=None,
        )


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SlackHTTPInvalidPayload(f"Slack callback field '{key}' is missing.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _provider_occurred_at(value: object) -> datetime.datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        return datetime.datetime.fromtimestamp(value, datetime.UTC)
    except OverflowError, OSError, ValueError:
        return None


def _resource_correlation_key(event: dict[str, object]) -> str | None:
    channel = event.get("channel")
    message = event.get("message")
    previous_message = event.get("previous_message")
    nested = (
        message
        if isinstance(message, dict)
        else previous_message
        if isinstance(previous_message, dict)
        else None
    )
    timestamp = event.get("thread_ts") or event.get("ts")
    if timestamp is None and nested is not None:
        timestamp = nested.get("thread_ts") or nested.get("ts")
    if timestamp is None:
        timestamp = event.get("deleted_ts")
    if not isinstance(channel, str) or not channel:
        return None
    if not isinstance(timestamp, str) or not timestamp:
        return None
    return f"{channel}:{timestamp}"


def _project_envelope(
    payload: dict[str, object],
    event: dict[str, object],
) -> dict[str, object]:
    top_level_keys = (
        "type",
        "event_id",
        "event_time",
        "event_context",
        "api_app_id",
        "team_id",
        "enterprise_id",
        "authorizations",
    )
    event_keys = (
        "type",
        "subtype",
        "channel",
        "channel_type",
        "context_team_id",
        "is_ext_shared_channel",
        "user",
        "bot_id",
        "app_id",
        "ts",
        "thread_ts",
        "event_ts",
        "client_msg_id",
        "text",
        "deleted_ts",
        "hidden",
    )
    projected: dict[str, object] = {
        key: payload[key] for key in top_level_keys if key in payload
    }
    projected_event = {key: event[key] for key in event_keys if key in event}
    if "blocks" in event:
        projected_event["blocks"] = _project_slack_blocks(event["blocks"])
    for key in ("message", "previous_message"):
        value = event.get(key)
        if isinstance(value, dict):
            projected_event[key] = _project_slack_message(value)
    projected["event"] = projected_event
    serialized = json.dumps(projected, separators=(",", ":")).encode()
    if len(serialized) > MAX_SLACK_HTTP_BODY_BYTES:
        raise SlackHTTPPayloadTooLarge(
            "Slack callback projection exceeds the size limit."
        )
    return projected


def _project_slack_message(message: dict[str, object]) -> dict[str, object]:
    """Retain only bounded fields required for lifecycle normalization."""
    keys = (
        "type",
        "subtype",
        "user",
        "bot_id",
        "app_id",
        "ts",
        "thread_ts",
        "text",
        "edited",
    )
    projected = {key: message[key] for key in keys if key in message}
    if "blocks" in message:
        projected["blocks"] = _project_slack_blocks(message["blocks"])
    return projected


def _project_slack_blocks(value: object) -> list[dict[str, str]]:
    """Reduce Slack blocks to bounded attachment-type metadata."""
    if not isinstance(value, list):
        return []
    projected: list[dict[str, str]] = []
    for block in value[:32]:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if isinstance(block_type, str) and block_type:
            projected.append({"type": block_type})
    return projected
