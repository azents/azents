"""Slack HTTP primitives for External Channel admission."""

import datetime
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import parse_qsl

import aiohttp
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.core.enums import (
    ExternalChannelEventEligibilityState,
    ExternalChannelEventStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelTransport,
)
from azents.core.external_channel_file import (
    MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH,
    MAX_EXTERNAL_CHANNEL_FILES,
)
from azents.repos.external_channel.data import (
    ExternalChannelEventCreate,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
)
from azents.services.external_channel.data import (
    ExternalChannelCapabilitySnapshot,
    ExternalChannelProviderIdentity,
)
from azents.services.external_channel.slack_blocks import projected_slack_blocks

MAX_SLACK_HTTP_BODY_BYTES = 256 * 1024
MAX_SLACK_URL_VERIFICATION_CHALLENGE_BYTES = 4 * 1024
SLACK_SIGNATURE_TOLERANCE_SECONDS = 5 * 60
SLACK_INTERACTION_TTL = datetime.timedelta(minutes=15)
_MAX_SLACK_INTERACTION_FORM_FIELDS = 8
SLACK_REQUIRED_BOT_SCOPES = (
    "app_mentions:read",
    "channels:history",
    "channels:read",
    "groups:history",
    "groups:read",
    "chat:write",
    "users:read",
)
SLACK_OPTIONAL_FILE_BOT_SCOPES = (
    "files:read",
    "files:write",
)


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
class SlackInteractionRouteIdentity:
    """Untrusted interaction identity used only to select an HMAC candidate."""

    app_id: str
    tenant_id: str


@dataclass(frozen=True)
class SlackEventCallback:
    """Authenticated ordinary Slack callback normalized for durable admission."""

    app_id: str
    tenant_id: str
    event: ExternalChannelEventCreate


def slack_event_is_normal_message_ingress(
    event: ExternalChannelEventCreate,
) -> bool:
    """Return whether quiesce should defer one new Slack message."""
    if event.event_type == "app_mention":
        return True
    if event.event_type != "message":
        return False
    payload = event.envelope.get("event")
    subtype = payload.get("subtype") if isinstance(payload, dict) else None
    return subtype not in {"message_changed", "message_deleted"}


@dataclass(frozen=True)
class SlackInteractionCallback:
    """Authenticated, bounded Slack interaction without raw provider content."""

    app_id: str
    tenant_id: str
    actor_user_id: str
    provider_interaction_key: str
    interaction_type: ExternalChannelInteractionType
    callback_id: str | None
    action_id: str | None
    trigger_id: str | None = field(repr=False)
    selector_admission_id: str | None = field(repr=False)
    resource_correlation_key: str | None
    projection: dict[str, object]
    expires_at: datetime.datetime
    selector_metadata: str | None = field(default=None, repr=False)
    selected_route_id: str | None = field(default=None, repr=False)
    selector_navigation: Literal["search", "previous", "next"] | None = field(
        default=None,
        repr=False,
    )
    selector_search: str | None = field(default=None, repr=False)
    selector_view_id: str | None = field(default=None, repr=False)
    selector_view_hash: str | None = field(default=None, repr=False)

    def requires_selector_processing(self) -> bool:
        """Return whether this callback belongs to the supported selector flow."""
        if self.interaction_type is ExternalChannelInteractionType.SHORTCUT:
            return self.trigger_id is not None
        if self.interaction_type is ExternalChannelInteractionType.BLOCK_ACTION:
            return (
                self.action_id == "azents_agent_selector_open"
                and self.trigger_id is not None
            ) or (
                self.selector_navigation is not None
                and self.selector_metadata is not None
                and self.selector_view_id is not None
            )
        if self.interaction_type is ExternalChannelInteractionType.VIEW_SUBMISSION:
            return (
                self.selector_metadata is not None
                and self.selected_route_id is not None
            )
        return False

    def interaction_create(
        self,
        *,
        connection_id: str,
        transport: ExternalChannelTransport,
    ) -> ExternalChannelInteractionCreate:
        """Build a durable interaction record without embedding provider authority."""
        return ExternalChannelInteractionCreate(
            connection_id=connection_id,
            transport=transport,
            provider_interaction_key=self.provider_interaction_key,
            interaction_type=self.interaction_type,
            callback_id=self.callback_id,
            action_id=self.action_id,
            principal_id=None,
            resource_correlation_key=self.resource_correlation_key,
            projection=self.projection,
            status=ExternalChannelInteractionStatus.ACCEPTED,
            expires_at=self.expires_at,
            error_kind=None,
            error_summary=None,
        )

    def principal_create(self) -> ExternalChannelPrincipalCreate:
        """Build the canonical provider actor record for this interaction."""
        return ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id=self.tenant_id,
            provider_user_id=self.actor_user_id,
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        )


type SlackCallbackEnvelope = (
    SlackURLVerification | SlackEventCallback | SlackInteractionCallback
)
type SlackCallbackRoute = (
    SlackURLVerification | SlackEventRouteIdentity | SlackInteractionRouteIdentity
)


@dataclass(frozen=True)
class SlackConnectionValidation:
    """Sanitized Slack ``auth.test`` result with no credential material."""

    status: Literal["valid", "invalid", "unavailable"]
    code: str | None
    message: str | None
    action_hint: str | None
    identity: ExternalChannelProviderIdentity | None
    capabilities: ExternalChannelCapabilitySnapshot | None
    customize_messages: bool = False


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
    payload, is_interaction = _parse_callback_payload(raw_body)
    if is_interaction:
        return SlackInteractionRouteIdentity(
            app_id=_required_string(payload, "api_app_id"),
            tenant_id=_required_nested_string(payload, "team", "id"),
        )
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
    """Parse one verified Slack callback into a bounded event or interaction."""
    payload, is_interaction = _parse_callback_payload(raw_body)
    if is_interaction:
        return parse_slack_interaction_payload(
            payload=payload,
            provider_interaction_key=_http_interaction_key(raw_body),
            received_at=received_at,
        )

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


def parse_slack_interaction_payload(
    *,
    payload: dict[str, object],
    provider_interaction_key: str,
    received_at: datetime.datetime,
) -> SlackInteractionCallback:
    """Project one authenticated Socket or HTTP interaction into safe metadata."""
    interaction_type = _interaction_type(_required_string(payload, "type"))
    actor_user_id = _required_nested_string(payload, "user", "id")
    app_id = _required_string(payload, "api_app_id")
    tenant_id = _required_nested_string(payload, "team", "id")
    callback_id = _first_optional_string(
        payload,
        ("callback_id",),
        ("view", "callback_id"),
    )
    action_id = _interaction_action_id(payload)
    selector_metadata = _interaction_selector_metadata(
        payload,
        interaction_type=interaction_type,
        action_id=action_id,
    )
    selector_navigation = _interaction_selector_navigation(
        interaction_type=interaction_type,
        action_id=action_id,
    )
    selector_view = payload.get("view")
    selector_view_id = (
        _optional_string(selector_view, "id")
        if isinstance(selector_view, dict) and selector_navigation is not None
        else None
    )
    selector_view_hash = (
        _optional_string(selector_view, "hash")
        if isinstance(selector_view, dict) and selector_navigation is not None
        else None
    )
    return SlackInteractionCallback(
        app_id=app_id,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        provider_interaction_key=provider_interaction_key,
        interaction_type=interaction_type,
        callback_id=callback_id,
        action_id=action_id,
        trigger_id=_optional_string(payload, "trigger_id"),
        selector_admission_id=_interaction_selector_admission_id(
            payload,
            action_id=action_id,
        ),
        selector_metadata=selector_metadata,
        selected_route_id=_interaction_selected_route_id(
            payload,
            interaction_type=interaction_type,
        ),
        selector_navigation=selector_navigation,
        selector_search=_interaction_selector_search(
            payload,
            navigation=selector_navigation,
        ),
        selector_view_id=selector_view_id,
        selector_view_hash=selector_view_hash,
        resource_correlation_key=_interaction_resource_correlation_key(payload),
        projection={
            "interaction_type": interaction_type.value,
            "surface": _interaction_surface(payload),
        },
        expires_at=received_at + SLACK_INTERACTION_TTL,
    )


def project_slack_shortcut_source_event(
    *,
    connection_id: str,
    payload: dict[str, object],
    provider_interaction_key: str,
    received_at: datetime.datetime,
) -> ExternalChannelEventCreate:
    """Project a verified message shortcut source into the canonical event inbox."""
    if _interaction_type(_required_string(payload, "type")) is not (
        ExternalChannelInteractionType.SHORTCUT
    ):
        raise SlackHTTPInvalidPayload("Slack interaction is not a message shortcut.")
    app_id = _required_string(payload, "api_app_id")
    tenant_id = _required_nested_string(payload, "team", "id")
    actor_user_id = _required_nested_string(payload, "user", "id")
    channel = payload.get("channel")
    message = payload.get("message")
    if not isinstance(channel, dict) or not isinstance(message, dict):
        raise SlackHTTPInvalidPayload("Slack shortcut source is missing.")
    channel_id = _required_string(channel, "id")
    message_ts = _required_string(message, "ts")
    thread_ts = _optional_string(message, "thread_ts") or message_ts
    source = {
        "type": "app_mention",
        "channel": channel_id,
        "user": _optional_string(message, "user") or actor_user_id,
        "ts": message_ts,
        "thread_ts": thread_ts,
        "text": _optional_string(message, "text") or "",
        **(
            {"blocks": _project_slack_blocks(message["blocks"])}
            if "blocks" in message
            else {}
        ),
        **(
            {"files": _project_slack_files(message["files"])}
            if "files" in message
            else {}
        ),
    }
    return ExternalChannelEventCreate(
        connection_id=connection_id,
        provider_event_id=f"shortcut-{provider_interaction_key}",
        transport_envelope_id=None,
        event_type="app_mention",
        provider_app_id=app_id,
        provider_tenant_id=tenant_id,
        provider_enterprise_id=None,
        resource_correlation_key=f"{channel_id}:{thread_ts}",
        eligibility_state=ExternalChannelEventEligibilityState.UNCLASSIFIED,
        envelope={"event": source},
        status=ExternalChannelEventStatus.ACCEPTED,
        provider_occurred_at=_provider_occurred_at_from_slack_ts(message_ts),
        received_at=received_at,
    )


def project_slack_shortcut_source_event_from_callback_body(
    *,
    connection_id: str,
    raw_body: bytes,
    provider_interaction_key: str,
    received_at: datetime.datetime,
) -> ExternalChannelEventCreate | None:
    """Project a verified shortcut body, or return no source for other callbacks."""
    payload, is_interaction = _parse_callback_payload(raw_body)
    if not is_interaction:
        return None
    if _interaction_type(_required_string(payload, "type")) is not (
        ExternalChannelInteractionType.SHORTCUT
    ):
        return None
    return project_slack_shortcut_source_event(
        connection_id=connection_id,
        payload=payload,
        provider_interaction_key=provider_interaction_key,
        received_at=received_at,
    )


def _parse_callback_payload(raw_body: bytes) -> tuple[dict[str, object], bool]:
    """Parse either an Events API JSON payload or an interaction form payload."""
    if len(raw_body) > MAX_SLACK_HTTP_BODY_BYTES:
        raise SlackHTTPPayloadTooLarge("Slack callback body exceeds the size limit.")
    if raw_body.lstrip().startswith(b"{"):
        return _parse_payload(raw_body), False
    return _parse_interaction_form_payload(raw_body), True


def _parse_interaction_form_payload(raw_body: bytes) -> dict[str, object]:
    """Read the single URL-encoded Slack interaction payload without retaining it."""
    try:
        fields = parse_qsl(
            raw_body.decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            max_num_fields=_MAX_SLACK_INTERACTION_FORM_FIELDS,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise SlackHTTPInvalidPayload(
            "Slack interaction callback form is invalid."
        ) from error
    payload_values = [value for key, value in fields if key == "payload"]
    if len(payload_values) != 1:
        raise SlackHTTPInvalidPayload(
            "Slack interaction callback form must contain one payload."
        )
    try:
        payload: object = json.loads(payload_values[0])
    except json.JSONDecodeError as error:
        raise SlackHTTPInvalidPayload(
            "Slack interaction callback payload is not valid JSON."
        ) from error
    if not isinstance(payload, dict):
        raise SlackHTTPInvalidPayload(
            "Slack interaction callback payload must be a JSON object."
        )
    return payload


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

    def __init__(self, web_client: AsyncWebClient) -> None:
        self.web_client = web_client

    async def validate_connection(
        self,
        *,
        bot_token: str,
        app_id: str,
        transport: ExternalChannelTransport,
    ) -> SlackConnectionValidation:
        """Validate a bot token and return only sanitized identity state."""
        try:
            response = await self.web_client.auth_test(token=bot_token)
        except SlackApiError as error:
            response = error.response
            if isinstance(response, AsyncSlackResponse) and (
                response.status_code == 429 or response.status_code >= 500
            ):
                return self._unavailable()
            error_code = _slack_api_error_code(error)
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
        except aiohttp.ClientError, TimeoutError:
            return self._unavailable()
        payload = _slack_response_payload(response)
        if payload is None:
            return self._unavailable(code="slack_auth_test_response_invalid")

        granted_scopes_header = _slack_response_header(
            response,
            "x-oauth-scopes",
        )
        granted_scopes: set[str] | None = None
        if granted_scopes_header:
            granted_scopes = {
                scope.strip()
                for scope in granted_scopes_header.split(",")
                if scope.strip()
            }
            missing_scopes = [
                scope
                for scope in SLACK_REQUIRED_BOT_SCOPES
                if scope not in granted_scopes
            ]
            if missing_scopes:
                return SlackConnectionValidation(
                    status="invalid",
                    code="slack_bot_scopes_missing",
                    message=(
                        "Slack Bot Token Scopes are missing: "
                        + ", ".join(missing_scopes)
                        + "."
                    ),
                    action_hint=(
                        "Update the App manifest, reinstall the App, and validate "
                        "the connection again."
                    ),
                    identity=None,
                    capabilities=None,
                )

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
            bot_response = await self.web_client.bots_info(
                bot=bot_id,
                token=bot_token,
            )
        except SlackApiError as error:
            response = error.response
            if isinstance(response, AsyncSlackResponse) and (
                response.status_code == 429 or response.status_code >= 500
            ):
                return self._unavailable()
            error_code = _slack_api_error_code(error)
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
        except aiohttp.ClientError, TimeoutError:
            return self._unavailable()
        bot_payload = _slack_response_payload(bot_response)
        if bot_payload is None:
            return self._unavailable(code="slack_bot_identity_response_invalid")
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
                download_files=(
                    granted_scopes is not None and "files:read" in granted_scopes
                ),
                upload_files=(
                    granted_scopes is not None and "files:write" in granted_scopes
                ),
            ),
            customize_messages=(
                granted_scopes is not None and "chat:write.customize" in granted_scopes
            ),
        )

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


def _slack_response_payload(
    response: AsyncSlackResponse,
) -> dict[str, object] | None:
    data = response.data
    return data if isinstance(data, dict) else None


def _slack_api_error_code(error: SlackApiError) -> str | None:
    response = error.response
    if not isinstance(response, AsyncSlackResponse):
        return None
    payload = _slack_response_payload(response)
    error_code = payload.get("error") if payload is not None else None
    return error_code if isinstance(error_code, str) else None


def _slack_response_header(
    response: AsyncSlackResponse,
    name: str,
) -> str | None:
    """Read one SDK response header without relying on provider casing."""
    normalized_name = name.lower()
    for header_name, value in response.headers.items():
        if header_name.lower() == normalized_name and isinstance(value, str):
            return value
    return None


def _required_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SlackHTTPInvalidPayload(f"Slack callback field '{key}' is missing.")
    return value


def _optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _required_nested_string(
    payload: dict[str, object],
    parent_key: str,
    key: str,
) -> str:
    """Read one required bounded nested Slack identifier."""
    parent = payload.get(parent_key)
    if not isinstance(parent, dict):
        raise SlackHTTPInvalidPayload(
            f"Slack callback field '{parent_key}.{key}' is missing."
        )
    return _required_string(parent, key)


def _first_optional_string(
    payload: dict[str, object],
    *paths: tuple[str, ...],
) -> str | None:
    """Return the first non-empty bounded identifier among known Slack paths."""
    for path in paths:
        current: object = payload
        for key in path:
            if not isinstance(current, dict):
                break
            current = current.get(key)
        if isinstance(current, str) and current:
            return current
    return None


def _interaction_type(value: str) -> ExternalChannelInteractionType:
    """Map only supported Slack interaction payload categories."""
    mapping = {
        "message_action": ExternalChannelInteractionType.SHORTCUT,
        "block_actions": ExternalChannelInteractionType.BLOCK_ACTION,
        "block_suggestion": ExternalChannelInteractionType.OPTIONS,
        "view_submission": ExternalChannelInteractionType.VIEW_SUBMISSION,
    }
    interaction_type = mapping.get(value)
    if interaction_type is None:
        raise SlackHTTPInvalidPayload("Slack interaction type is not supported.")
    return interaction_type


def _interaction_action_id(payload: dict[str, object]) -> str | None:
    """Return one action identifier without retaining arbitrary action values."""
    direct = _optional_string(payload, "action_id")
    if direct is not None:
        return direct
    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return None
    action = actions[0]
    return _optional_string(action, "action_id") if isinstance(action, dict) else None


def _interaction_selector_admission_id(
    payload: dict[str, object],
    *,
    action_id: str | None,
) -> str | None:
    """Keep one opaque selector admission reference only for the live handoff."""
    if action_id != "azents_agent_selector_open":
        return None
    actions = payload.get("actions")
    if not isinstance(actions, list) or len(actions) != 1:
        return None
    action = actions[0]
    if not isinstance(action, dict):
        return None
    value = _optional_string(action, "value")
    return value if value is not None and len(value) <= 64 else None


def _interaction_selector_metadata(
    payload: dict[str, object],
    *,
    interaction_type: ExternalChannelInteractionType,
    action_id: str | None,
) -> str | None:
    """Keep signed selector metadata transiently for submission or navigation."""
    selector_submission = (
        interaction_type is ExternalChannelInteractionType.VIEW_SUBMISSION
    )
    selector_navigation = (
        interaction_type is ExternalChannelInteractionType.BLOCK_ACTION
        and _interaction_selector_navigation(
            interaction_type=interaction_type,
            action_id=action_id,
        )
        is not None
    )
    if not selector_submission and not selector_navigation:
        return None
    view = payload.get("view")
    if not isinstance(view, dict):
        raise SlackHTTPInvalidPayload("Slack selector submission view is missing.")
    if _optional_string(view, "callback_id") != "azents_agent_selector":
        return None
    metadata = _optional_string(view, "private_metadata")
    if metadata is None or len(metadata) > 3_000:
        raise SlackHTTPInvalidPayload("Slack selector metadata is invalid.")
    return metadata


def _interaction_selector_navigation(
    *,
    interaction_type: ExternalChannelInteractionType,
    action_id: str | None,
) -> Literal["search", "previous", "next"] | None:
    """Map only shared-selector modal navigation actions."""
    if interaction_type is not ExternalChannelInteractionType.BLOCK_ACTION:
        return None
    mapping: dict[str, Literal["search", "previous", "next"]] = {
        "azents_agent_selector_search": "search",
        "azents_agent_selector_previous": "previous",
        "azents_agent_selector_next": "next",
    }
    return None if action_id is None else mapping.get(action_id)


def _interaction_selector_search(
    payload: dict[str, object],
    *,
    navigation: Literal["search", "previous", "next"] | None,
) -> str | None:
    """Read one bounded transient catalog query from modal state."""
    if navigation is None:
        return None
    view = payload.get("view")
    state = view.get("state") if isinstance(view, dict) else None
    values = state.get("values") if isinstance(state, dict) else None
    block = (
        values.get("azents_agent_selector_search") if isinstance(values, dict) else None
    )
    action = (
        block.get("azents_agent_selector_search") if isinstance(block, dict) else None
    )
    value = action.get("value") if isinstance(action, dict) else None
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 100:
        raise SlackHTTPInvalidPayload("Slack selector search query is invalid.")
    normalized = value.strip()
    return normalized or None


def _interaction_selected_route_id(
    payload: dict[str, object],
    *,
    interaction_type: ExternalChannelInteractionType,
) -> str | None:
    """Read exactly one opaque selector route value from a modal submission."""
    if interaction_type is not ExternalChannelInteractionType.VIEW_SUBMISSION:
        return None
    view = payload.get("view")
    if not isinstance(view, dict):
        raise SlackHTTPInvalidPayload("Slack selector submission view is missing.")
    if _optional_string(view, "callback_id") != "azents_agent_selector":
        return None
    state = view.get("state")
    values = state.get("values") if isinstance(state, dict) else None
    if not isinstance(values, dict):
        raise SlackHTTPInvalidPayload("Slack selector submission state is missing.")
    block = values.get("azents_agent_selector_route")
    action = (
        block.get("azents_agent_selector_route") if isinstance(block, dict) else None
    )
    selected = action.get("selected_option") if isinstance(action, dict) else None
    route_id = selected.get("value") if isinstance(selected, dict) else None
    if not isinstance(route_id, str) or not route_id or len(route_id) > 64:
        raise SlackHTTPInvalidPayload("Slack selector route selection is invalid.")
    return route_id


def _interaction_resource_correlation_key(
    payload: dict[str, object],
) -> str | None:
    """Project the interaction's visible source conversation without its content."""
    channel_id = _first_optional_string(
        payload,
        ("channel", "id"),
        ("container", "channel_id"),
    )
    message_ts = _first_optional_string(
        payload,
        ("message", "thread_ts"),
        ("message", "ts"),
        ("container", "thread_ts"),
        ("container", "message_ts"),
    )
    if channel_id is None or message_ts is None:
        return None
    return f"{channel_id}:{message_ts}"


def _interaction_surface(payload: dict[str, object]) -> str:
    """Return the categorical interaction surface without raw payload retention."""
    container_type = _first_optional_string(payload, ("container", "type"))
    if container_type is not None:
        return container_type
    return "modal" if isinstance(payload.get("view"), dict) else "unknown"


def _http_interaction_key(raw_body: bytes) -> str:
    """Derive a non-reversible HTTP retry key without persisting the raw form."""
    return "http-" + hashlib.sha256(raw_body).hexdigest()


def _provider_occurred_at_from_slack_ts(value: str) -> datetime.datetime | None:
    """Convert a canonical Slack timestamp for event ordering only."""
    try:
        return datetime.datetime.fromtimestamp(float(value), datetime.UTC)
    except ValueError, OverflowError, OSError:
        return None


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
    if "files" in event:
        files = event["files"]
        projected_event["files"] = _project_slack_files(files)
        projected_event["files_truncated"] = (
            isinstance(files, list) and len(files) > MAX_EXTERNAL_CHANNEL_FILES
        )
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
    if "files" in message:
        files = message["files"]
        projected["files"] = _project_slack_files(files)
        projected["files_truncated"] = (
            isinstance(files, list) and len(files) > MAX_EXTERNAL_CHANNEL_FILES
        )
    return projected


def _project_slack_blocks(value: object) -> list[dict[str, str]]:
    """Reduce Slack blocks to bounded readable projection data."""
    return projected_slack_blocks(value)


def _project_slack_files(value: object) -> list[dict[str, object]]:
    """Retain only bounded non-secret Slack file metadata."""
    if not isinstance(value, list):
        return []
    projected: list[dict[str, object]] = []
    string_keys = (
        "id",
        "name",
        "title",
        "mimetype",
        "mode",
        "external_type",
        "file_access",
    )
    for item in value[:MAX_EXTERNAL_CHANNEL_FILES]:
        if not isinstance(item, dict):
            continue
        file_projection: dict[str, object] = {}
        for key in string_keys:
            field = item.get(key)
            if isinstance(field, str) and field:
                file_projection[key] = field[:MAX_EXTERNAL_CHANNEL_FILE_TEXT_LENGTH]
        size = item.get("size")
        if isinstance(size, int) and not isinstance(size, bool):
            file_projection["size"] = size
        if isinstance(item.get("is_external"), bool):
            file_projection["is_external"] = item["is_external"]
        projected.append(file_projection)
    return projected
