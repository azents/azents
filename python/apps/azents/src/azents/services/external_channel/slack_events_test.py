"""Slack External Channel event normalization and API adapter tests."""

import datetime
import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs

import aiohttp
import httpx
import pytest
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.core.enums import (
    ExternalChannelPrincipalAuthorType,
)
from azents.services.external_channel.conversation import (
    ExternalChannelHistoryDeadlineExceeded,
    ExternalChannelHistoryMalformed,
    ExternalChannelHistoryPositionInvalid,
    ExternalChannelHistoryRateLimited,
    ExternalChannelHistoryTriggerMissing,
    ExternalChannelOperationDeadline,
)
from azents.services.external_channel.slack_endpoint import slack_api_base_url
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackConversationClient,
    SlackConversationHistoryTrigger,
    SlackEventExcluded,
    SlackExternalUploadTransport,
    SlackInteractionView,
    SlackNormalizedMessage,
    SlackOutboundFile,
    SlackOutboundFileContentError,
    SlackPrivateFileTransport,
    SlackProviderCredentialsInvalid,
    SlackProviderFileNotFound,
    SlackProviderFileTooLarge,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    SlackProviderRequestRejected,
    SlackProviderTemporaryError,
    normalize_projected_slack_event,
    normalize_slack_event,
    slack_message_reference_ids,
    slack_provider_position,
)
from azents.testing.types import is_string_object_dict


def _encoded_sdk_params(
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    """Mirror the SDK's safe top-level query normalization for HTTP scenarios."""
    return {
        key: (
            "1"
            if value is True
            else "0"
            if value is False
            else json.dumps(value, separators=(",", ":"))
            if isinstance(value, dict | list)
            else value
        )
        for key, value in (params or {}).items()
        if value is not None
    }


class _MockSlackWebClient(AsyncWebClient):
    """Route public SDK calls through one deterministic HTTPX transport."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        super().__init__(retry_handlers=[])
        self.http_client = http_client

    async def api_call(
        self,
        api_method: str,
        *,
        http_verb: str = "POST",
        files: dict[str, Any] | None = None,
        data: dict[str, Any] | aiohttp.FormData | None = None,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth: dict[str, str] | None = None,
    ) -> AsyncSlackResponse:
        del files, auth
        request_headers = dict(headers or {})
        request_params = _encoded_sdk_params(params)
        request_json = dict(json or {}) if json is not None else None
        if isinstance(data, aiohttp.FormData):
            raise AssertionError("Slack test double does not support multipart forms.")
        request_data = dict(data) if isinstance(data, dict) else None
        token = request_params.pop("token", None)
        if request_json is not None:
            token = request_json.pop("token", token)
        if isinstance(request_data, dict):
            token = request_data.pop("token", token)
        if isinstance(token, str):
            request_headers["Authorization"] = f"Bearer {token}"
        try:
            response = await self.http_client.request(
                http_verb,
                f"{slack_api_base_url()}/{api_method}",
                params=request_params or None,
                json=request_json,
                data=request_data,
                headers=request_headers,
            )
        except httpx.RequestError as error:
            raise aiohttp.ClientError("Slack test transport failed.") from error
        try:
            payload: object = response.json()
        except ValueError:
            payload = {}
        sdk_response = AsyncSlackResponse(
            client=self,
            http_verb=http_verb,
            api_url=str(response.request.url),
            req_args={},
            data=payload if isinstance(payload, dict | bytes) else {},
            headers=dict(response.headers),
            status_code=response.status_code,
        )
        return sdk_response.validate()


def _client(http_client: httpx.AsyncClient) -> SlackConversationClient:
    return SlackConversationClient(
        web_client=_MockSlackWebClient(http_client),
        private_file_transport=SlackPrivateFileTransport(http_client),
        external_upload_transport=SlackExternalUploadTransport(http_client),
    )


def _envelope(event: dict[str, object]) -> dict[str, object]:
    return {"event": event}


def _history_message(
    *,
    timestamp: str,
    user_id: str,
    text: str | None = None,
    app_id: str | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "type": "message",
        "channel": "C1",
        "channel_type": "channel",
        "user": user_id,
        "ts": timestamp,
        "text": text or f"message-{timestamp}",
    }
    if app_id is not None:
        message["app_id"] = app_id
    return message


def test_normalizes_human_app_mention_as_invocation_candidate() -> None:
    """A human mention establishes the thread resource and invocation identity."""
    normalized = normalize_slack_event(
        event_type="app_mention",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "app_mention",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000200",
                "text": "<@B1> investigate",
                "blocks": [{"type": "section"}],
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.invocation is True
    assert normalized.author_type is ExternalChannelPrincipalAuthorType.HUMAN
    assert normalized.provider_resource_key == "slack:T1:C1:1721600000.000200"
    assert normalized.provider_message_key == "slack:T1:C1:1721600000.000200"
    assert normalized.correlation_key == "C1:1721600000.000200"
    assert normalized.attachment_metadata == {
        "blocks": {
            "block_count": 1,
            "block_types": ["section"],
            "truncated": False,
        }
    }


@pytest.mark.parametrize(
    ("authorizations", "connected_bot_user_id"),
    [
        (
            [{"is_bot": True, "team_id": "T1", "user_id": "UAUTH"}],
            "BOLD",
        ),
        ([], "UAUTH"),
    ],
)
def test_projected_human_message_targeting_authorized_bot_is_invocation(
    authorizations: list[dict[str, object]],
    connected_bot_user_id: str,
) -> None:
    """A signed message callback may carry the App mention as a message event."""
    normalized = normalize_projected_slack_event(
        event_type="message",
        tenant_id="T1",
        connected_bot_user_id=connected_bot_user_id,
        envelope={
            "authorizations": authorizations,
            "event": {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000200",
                "text": "<@UAUTH> investigate",
            },
        },
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.author_type is ExternalChannelPrincipalAuthorType.HUMAN
    assert normalized.invocation is True


@pytest.mark.parametrize(
    ("text", "authorizations", "connected_bot_user_id"),
    [
        (
            "<@UOTHER> investigate",
            [{"is_bot": True, "team_id": "T1", "user_id": "UAUTH"}],
            "BOLD",
        ),
        ("no mention", [], "UAUTH"),
        (
            "<@UAUTH> investigate",
            [{"is_bot": True, "team_id": "T2", "user_id": "UAUTH"}],
            "BOLD",
        ),
    ],
)
def test_projected_human_message_without_connected_bot_target_is_context(
    text: str,
    authorizations: list[dict[str, object]],
    connected_bot_user_id: str,
) -> None:
    """Only the connected bot identity may promote a message callback."""
    normalized = normalize_projected_slack_event(
        event_type="message",
        tenant_id="T1",
        connected_bot_user_id=connected_bot_user_id,
        envelope={
            "authorizations": authorizations,
            "event": {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000200",
                "text": text,
            },
        },
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.invocation is False


def test_projected_bot_message_cannot_invoke_through_self_mention() -> None:
    """Connected-App output remains context even when it mentions the App."""
    normalized = normalize_projected_slack_event(
        event_type="message",
        tenant_id="T1",
        connected_bot_user_id="UAUTH",
        envelope={
            "authorizations": [
                {
                    "is_bot": True,
                    "team_id": "T1",
                    "user_id": "UAUTH",
                }
            ],
            "event": {
                "type": "message",
                "subtype": "bot_message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "UAUTH",
                "bot_id": "B1",
                "ts": "1721600000.000200",
                "text": "<@UAUTH> generated output",
            },
        },
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.author_type is ExternalChannelPrincipalAuthorType.BOT
    assert normalized.invocation is False


def test_normalizes_bounded_file_metadata_and_fail_closed_modes() -> None:
    """Retain decision metadata while classifying unsupported Slack file modes."""
    files: list[object] = [
        {
            "id": "F1",
            "name": "report.csv",
            "title": "Report",
            "mimetype": "text/csv",
            "size": 42,
            "mode": "hosted",
            "is_external": False,
            "url_private": "https://files.slack.test/private/F1",
            "body": "must not survive",
        },
        {
            "id": "F2",
            "name": "remote.pdf",
            "size": 43,
            "mode": "hosted",
            "is_external": True,
        },
        {
            "id": "F3",
            "name": "connect.txt",
            "size": 44,
            "mode": "hosted",
            "file_access": "check_file_info",
        },
        {
            "id": "F4",
            "name": "sparse.txt",
            "mode": "hosted",
        },
        {
            "id": "F5",
            "name": "snippet.txt",
            "size": 45,
            "mode": "snippet",
        },
        {
            "id": "F6",
            "name": "invalid.txt",
            "size": -1,
            "mode": "hosted",
        },
        *[
            {
                "id": f"F{index}",
                "name": f"file-{index}.txt",
                "size": index,
                "mode": "hosted",
            }
            for index in range(7, 22)
        ],
    ]
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "subtype": "file_share",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": "Review files",
                "files": files,
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.attachment_metadata is not None
    projected = normalized.attachment_metadata["files"]
    assert isinstance(projected, list)
    assert len(projected) == 20
    assert normalized.attachment_metadata["files_truncated"] is True
    first_six = projected[:6]
    first, second, third, fourth, fifth, sixth = first_six
    assert is_string_object_dict(first)
    assert is_string_object_dict(second)
    assert is_string_object_dict(third)
    assert is_string_object_dict(fourth)
    assert is_string_object_dict(fifth)
    assert is_string_object_dict(sixth)
    assert first["supported"] is True
    assert first["unsupported_reason"] is None
    assert second["unsupported_reason"] == "external_file"
    assert third["unsupported_reason"] == "slack_connect_file"
    assert fourth["supported"] is True
    assert fourth["declared_size"] is None
    assert fourth["unsupported_reason"] is None
    assert fifth["unsupported_reason"] == "unsupported_mode"
    assert sixth["supported"] is True
    assert sixth["declared_size"] is None
    assert sixth["unsupported_reason"] is None
    assert "url_private" not in repr(projected)
    assert "must not survive" not in repr(projected)


@pytest.mark.parametrize(
    "subtype",
    ["channel_join", "thread_broadcast", "reply_broadcast"],
)
def test_normalizes_all_user_visible_message_subtypes(subtype: str) -> None:
    """User-visible Slack message subtypes remain available to the Agent."""
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "subtype": subtype,
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": "Visible Slack message",
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.normalized_body == "Visible Slack message"
    assert normalized.invocation is False


def test_normalizes_nested_user_visible_message_subtype() -> None:
    """Subtypes with a nested visible message retain its canonical identity."""
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "subtype": "message_replied",
                "channel": "C1",
                "channel_type": "channel",
                "message": {
                    "user": "U1",
                    "ts": "1721600000.000100",
                    "text": "Visible threaded reply",
                },
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.provider_message_key == "slack:T1:C1:1721600000.000100"
    assert normalized.normalized_body == "Visible threaded reply"


def test_bot_mention_remains_a_route_policy_candidate() -> None:
    """Route policy, not Slack normalization, decides whether a bot may invoke."""
    normalized = normalize_slack_event(
        event_type="app_mention",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "app_mention",
                "subtype": "bot_message",
                "channel": "G1",
                "channel_type": "group",
                "bot_id": "B9",
                "ts": "1721600000.000300",
                "text": "bot context",
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.invocation is True
    assert normalized.author_type is ExternalChannelPrincipalAuthorType.BOT
    assert normalized.provider_user_id == "bot:B9"


@pytest.mark.parametrize(
    "event",
    [
        {
            "type": "message",
            "channel": "D1",
            "channel_type": "im",
            "user": "U1",
            "ts": "1721600000.000100",
        },
        {
            "type": "message",
            "channel": "C1",
            "channel_type": "channel",
            "is_ext_shared_channel": True,
            "user": "U1",
            "ts": "1721600000.000100",
        },
    ],
)
def test_excludes_dm_and_slack_connect_scope(event: dict[str, object]) -> None:
    """Unsupported conversation scopes never normalize into external messages."""
    with pytest.raises(SlackEventExcluded):
        normalize_slack_event(
            event_type="message",
            tenant_id="T1",
            envelope=_envelope(event),
        )


@pytest.mark.parametrize("subtype", ("message_changed", "message_deleted"))
def test_excludes_edit_and_delete_events(subtype: str) -> None:
    """Provider mutations do not create a secondary inbound lifecycle path."""
    with pytest.raises(SlackEventExcluded):
        normalize_slack_event(
            event_type="message",
            tenant_id="T1",
            envelope=_envelope(
                {
                    "type": "message",
                    "subtype": subtype,
                    "channel": "C1",
                    "channel_type": "channel",
                    "ts": "1721600000.000100",
                }
            ),
        )


def test_normalizes_connection_revocation_without_message_identity() -> None:
    """Uninstall and token events terminate connection state, not conversations."""
    uninstall = normalize_slack_event(
        event_type="app_uninstalled",
        tenant_id="T1",
        envelope=_envelope({"type": "app_uninstalled"}),
    )
    revoked = normalize_slack_event(
        event_type="tokens_revoked",
        tenant_id="T1",
        envelope=_envelope({"type": "tokens_revoked"}),
    )

    assert uninstall == SlackConnectionRevocation(kind="app_uninstalled")
    assert revoked == SlackConnectionRevocation(kind="tokens_revoked")


def test_provider_position_orders_variable_width_slack_timestamps() -> None:
    """Canonical positions do not depend on provider string width."""
    assert slack_provider_position("9.2") < slack_provider_position("10.000001")
    assert slack_provider_position("10.1") == "00000000000000000010.100000"


def test_extracts_bounded_user_and_channel_reference_ids() -> None:
    """Provider reference mapping preserves actionable IDs for the Agent."""
    users, channels = slack_message_reference_ids(
        "<@U1> asks @W2 to check <#C1|incidents> and #G2."
    )

    assert users == {"U1", "W2"}
    assert channels == {"C1", "G2"}


def test_normalizes_block_only_rich_text_and_reference_ids() -> None:
    """Use supported rich-text elements when Slack fallback text is empty."""
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": "",
                "blocks": [
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {"type": "text", "text": "Ask "},
                                    {"type": "user", "user_id": "U2"},
                                    {"type": "text", "text": " in "},
                                    {"type": "channel", "channel_id": "G2"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.normalized_body == "Ask <@U2> in <#G2>"
    assert slack_message_reference_ids(normalized.normalized_body) == (
        {"U2"},
        {"G2"},
    )


def test_long_blank_fallback_does_not_hide_block_only_content() -> None:
    """Check blankness before truncation adds a visible fallback marker."""
    normalized = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": " " * (70 * 1024),
                "blocks": [
                    {
                        "type": "rich_text",
                        "elements": [
                            {
                                "type": "rich_text_section",
                                "elements": [
                                    {"type": "text", "text": "Readable from blocks"}
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
    )

    assert isinstance(normalized, SlackNormalizedMessage)
    assert normalized.normalized_body == "Readable from blocks"


def test_raw_provider_normalization_ignores_spoofed_normalized_text() -> None:
    """Only the authenticated admission projection may supply normalized text."""
    raw = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": "",
                "blocks": [
                    {
                        "type": "unsupported_provider_block",
                        "normalized_text": "Spoofed trusted content",
                    }
                ],
            }
        ),
    )
    projected = normalize_projected_slack_event(
        event_type="message",
        tenant_id="T1",
        connected_bot_user_id=None,
        envelope=_envelope(
            {
                "type": "message",
                "channel": "C1",
                "channel_type": "channel",
                "user": "U1",
                "ts": "1721600000.000100",
                "text": "",
                "blocks": [
                    {
                        "type": "rich_text",
                        "normalized_text": "Admission-projected content",
                    }
                ],
            }
        ),
    )

    assert isinstance(raw, SlackNormalizedMessage)
    assert raw.normalized_body == ""
    assert isinstance(projected, SlackNormalizedMessage)
    assert projected.normalized_body == "Admission-projected content"


async def test_conversation_access_requires_membership_and_exposes_connect() -> None:
    """First-mention validation distinguishes membership and Slack Connect."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "channel": {
                    "name": "incidents",
                    "is_member": False,
                    "is_channel": True,
                    "is_group": False,
                    "is_ext_shared": True,
                    "is_im": False,
                    "is_mpim": False,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        access = await _client(http).fetch_conversation_access(
            bot_token="xoxb-secret",
            channel_id="C1",
        )

    assert access.app_member is False
    assert access.external_shared is True
    assert access.public_or_private_channel is True
    assert access.display_name == "#incidents"


async def test_resolves_slack_user_and_channel_display_names() -> None:
    """Identity enrichment prefers the provider's human-readable labels."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/users.info":
            assert request.url.params["user"] == "U1"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "user": {
                        "profile": {"display_name": "Alice"},
                        "real_name": "Alice Example",
                    },
                },
            )
        assert request.url.path == "/api/conversations.info"
        assert request.url.params["channel"] == "C1"
        return httpx.Response(
            200,
            json={"ok": True, "channel": {"name": "incidents"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http)
        user = await client.fetch_user_display_name(
            bot_token="xoxb-secret",
            provider_user_id="U1",
        )
        channel = await client.fetch_channel_display_name(
            bot_token="xoxb-secret",
            channel_id="C1",
        )

    assert user == "Alice"
    assert channel == "#incidents"


async def test_thread_page_uses_cursor_and_normalizes_messages() -> None:
    """Hydration consumes cursor pages without retaining arbitrary response data."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {
                        "user": "U1",
                        "ts": "1721600000.000100",
                        "text": "root",
                        "files": [
                            {
                                "id": "F1",
                                "name": "report.csv",
                                "mimetype": "text/csv",
                                "size": 42,
                                "mode": "hosted",
                                "url_private": "https://files.slack.test/private/F1",
                            }
                        ],
                    }
                ],
                "response_metadata": {"next_cursor": "cursor-2"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await _client(http).fetch_thread_page(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            root_thread_ts="1721600000.000100",
            cursor="cursor-1",
            limit=100,
        )

    assert page.next_cursor == "cursor-2"
    assert len(page.messages) == 1
    assert page.messages[0].normalized_body == "root"
    assert page.messages[0].attachment_metadata is not None
    files = page.messages[0].attachment_metadata["files"]
    assert isinstance(files, list)
    first_file = files[0]
    assert is_string_object_dict(first_file)
    assert first_file["provider_file_id"] == "F1"
    assert first_file["supported"] is True
    assert "url_private" not in repr(files)
    assert requests[0].url.params["cursor"] == "cursor-1"
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"


async def test_thread_page_includes_all_user_visible_history_subtypes() -> None:
    """Hydration preserves user-visible history regardless of subtype."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [
                    {
                        "subtype": "channel_join",
                        "user": "U2",
                        "ts": "1721600000.000050",
                        "text": "joined",
                    },
                    {
                        "user": "U1",
                        "ts": "1721600000.000100",
                        "text": "root",
                    },
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await _client(http).fetch_thread_page(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            root_thread_ts="1721600000.000100",
            cursor=None,
            limit=100,
        )

    assert [message.normalized_body for message in page.messages] == ["joined", "root"]


async def test_thread_page_surfaces_rate_limit_for_inbound_retry() -> None:
    """Hydration rate limits carry the provider retry interval."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderRateLimited) as raised:
            await _client(http).fetch_thread_page(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                root_thread_ts="1721600000.000100",
                cursor=None,
                limit=100,
            )

    assert raised.value.retry_after_seconds == 17


async def test_thread_page_maps_revoked_token_to_connection_failure() -> None:
    """Credential revocation is distinct from temporary hydration failure."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "token_revoked"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderCredentialsInvalid):
            await _client(http).fetch_thread_page(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                root_thread_ts="1721600000.000100",
                cursor=None,
                limit=100,
            )


async def test_thread_page_maps_missing_scope_to_connection_failure() -> None:
    """Missing Slack scopes remain distinct from invalid credentials."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "missing_scope"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderPermissionDenied):
            await _client(http).fetch_thread_page(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                root_thread_ts="1721600000.000100",
                cursor=None,
                limit=100,
            )


async def test_file_info_returns_current_metadata_and_private_download_target() -> None:
    """The file read adapter keeps provider URLs inside the server-only result."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {
                    "id": "F123",
                    "name": "report.csv",
                    "title": "Report",
                    "mimetype": "text/csv",
                    "size": 7,
                    "mode": "hosted",
                    "url_private": "https://files.slack.test/private/F123",
                    "url_private_download": ("https://files.slack.test/download/F123"),
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        info = await _client(http).fetch_file_download_info(
            bot_token="xoxb-secret",
            provider_file_id="F123",
        )

    assert info.metadata.provider_file_id == "F123"
    assert info.metadata.supported is True
    assert info.private_url == "https://files.slack.test/download/F123"
    assert requests[0].url.path == "/api/files.info"
    assert requests[0].url.params["file"] == "F123"
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"


@pytest.mark.parametrize("declared_size", (None, -1, "7", True))
async def test_file_info_treats_invalid_metadata_size_as_advisory(
    declared_size: object,
) -> None:
    """Fresh hosted-file identity remains supported without a Slack size."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {
                    "id": "F123",
                    "name": "report.csv",
                    "size": declared_size,
                    "mode": "hosted",
                    "url_private": "https://files.slack.test/private/F123",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        info = await _client(http).fetch_file_download_info(
            bot_token="xoxb-secret",
            provider_file_id="F123",
        )

    assert info.metadata.declared_size is None
    assert info.metadata.supported is True
    assert info.metadata.unsupported_reason is None


async def test_private_file_content_length_uses_authenticated_final_url() -> None:
    """The authenticated private URL HEAD exclusively declares transfer size."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"Content-Length": "7"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        size = await _client(http).fetch_private_file_content_length(
            bot_token="xoxb-secret",
            private_url="https://files.slack.test/private/F123",
            max_bytes=10,
        )

    assert size == 7
    assert len(requests) == 1
    assert requests[0].method == "HEAD"
    assert requests[0].url == "https://files.slack.test/private/F123"
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"


async def test_file_info_rejects_deleted_file() -> None:
    """A currently deleted Slack file cannot be materialized."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {
                    "id": "F123",
                    "deleted": True,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderFileNotFound):
            await _client(http).fetch_file_download_info(
                bot_token="xoxb-secret",
                provider_file_id="F123",
            )


async def test_file_info_rejects_mismatched_response_identity() -> None:
    """Slack must return the exact file object selected by files.info."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "file": {
                    "id": "F-OTHER",
                    "name": "other.csv",
                    "size": 7,
                    "mode": "hosted",
                    "url_private": "https://files.slack.test/private/F-OTHER",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(
            SlackProviderTemporaryError,
            match="identity does not match",
        ):
            await _client(http).fetch_file_download_info(
                bot_token="xoxb-secret",
                provider_file_id="F123",
            )


async def test_private_file_stream_authenticates_and_enforces_actual_limit() -> None:
    """Private stream uses bearer auth and enforces its actual-byte limit."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"12345678")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http)
        async with client.open_private_file_stream(
            bot_token="xoxb-secret",
            private_url="https://files.slack.test/private/F123",
            max_bytes=8,
            maximum_chunk_size=4,
        ) as stream:
            body = b"".join([chunk async for chunk in stream.chunks])
        with pytest.raises(SlackProviderFileTooLarge):
            async with client.open_private_file_stream(
                bot_token="xoxb-secret",
                private_url="https://files.slack.test/private/F123",
                max_bytes=7,
                maximum_chunk_size=4,
            ) as stream:
                async for _ in stream.chunks:
                    pass

    assert body == b"12345678"
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"
    assert requests[0].url == "https://files.slack.test/private/F123"


async def test_private_file_stream_rejects_partial_response_status() -> None:
    """A ranged or empty success is not accepted as the complete Slack file."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(206, content=b"partial")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderTemporaryError, match="incomplete"):
            async with _client(http).open_private_file_stream(
                bot_token="xoxb-secret",
                private_url="https://files.slack.test/private/F123",
                max_bytes=100,
                maximum_chunk_size=4,
            ):
                pass


@pytest.mark.parametrize("content_length", ("", "invalid", "-1"))
async def test_private_file_stream_requires_valid_content_length(
    content_length: str,
) -> None:
    """A complete Slack response must contain one non-negative decimal size."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Length": content_length},
            content=b"content",
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderRequestRejected):
            async with _client(http).open_private_file_stream(
                bot_token="xoxb-secret",
                private_url="https://files.slack.test/private/F123",
                max_bytes=100,
                maximum_chunk_size=4,
            ):
                pass


async def test_control_message_reports_ambiguous_network_outcome_without_retry() -> (
    None
):
    """A transport failure remains unknown instead of fabricated as delivered."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="Alice",
            participant_provider_user_id="U1",
            agent_name=None,
            agent_markdown_line=None,
            icon_url=None,
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"


async def test_control_message_reports_confirmed_provider_rejection() -> None:
    """A Slack validation response is failed rather than transport-ambiguous."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_blocks"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="Alice",
            participant_provider_user_id="U1",
            agent_name=None,
            agent_markdown_line=None,
            icon_url=None,
        )

    assert result.status == "failed"
    assert result.error_kind == "provider_rejected"
    assert result.error_summary == (
        "Slack rejected the provider operation (invalid_blocks)."
    )


@pytest.mark.parametrize(
    ("operation", "expected_path", "expected_ts"),
    [
        ("post", "/api/chat.postMessage", "1721600001.000100"),
        ("update", "/api/chat.update", "1721600000.000100"),
        ("delete", "/api/chat.delete", "1721600000.000100"),
    ],
)
async def test_channel_action_message_mutations_are_single_provider_requests(
    operation: str,
    expected_path: str,
    expected_ts: str,
) -> None:
    """Reply and progress mutations issue one bounded Slack request each."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": expected_ts})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http)
        if operation == "post":
            result = await client.post_message(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                thread_ts="1721600000.000100",
                markdown_text="Reply",
                icon_url=None,
            )
        elif operation == "update":
            result = await client.update_message(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                message_ts="1721600000.000100",
                text="Progress",
            )
        else:
            result = await client.delete_message(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                message_ts="1721600000.000100",
            )

    assert result.status == "delivered"
    assert result.provider_message_key == f"slack:T1:C1:{expected_ts}"
    assert len(requests) == 1
    assert requests[0].url.path == expected_path
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"
    payload = (
        json.loads(requests[0].content)
        if requests[0].content
        else dict(requests[0].url.params)
    )
    if operation == "post":
        assert payload["markdown_text"] == "Reply"
        assert "text" not in payload
        assert "blocks" not in payload
    elif operation == "update":
        assert payload["parse"] == "none"
        assert payload["link_names"] is False
    else:
        assert payload == {
            "channel": "C1",
            "ts": "1721600000.000100",
        }


async def test_interaction_view_open_uses_bounded_safe_payload() -> None:
    """Modal mutation retains only opaque metadata and never returns a trigger."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "view": {"id": "V1"}})

    view = SlackInteractionView(
        callback_id="agent-selector",
        title="Choose Agent",
        private_metadata="interaction-1",
        blocks=[
            {
                "type": "section",
                "text": {"type": "plain_text", "text": "Choose an Agent."},
            }
        ],
        submit_title="Select",
        close_title="Cancel",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).open_interaction_view(
            bot_token="xoxb-secret",
            trigger_id="trigger-secret",
            view=view,
        )

    assert result.status == "opened"
    assert result.error_kind is None
    assert len(requests) == 1
    assert requests[0].url.path == "/api/views.open"
    payload = json.loads(requests[0].content)
    assert payload == {
        "trigger_id": "trigger-secret",
        "view": {
            "type": "modal",
            "callback_id": "agent-selector",
            "private_metadata": "interaction-1",
            "title": {"type": "plain_text", "text": "Choose Agent"},
            "blocks": view.blocks,
            "submit": {"type": "plain_text", "text": "Select"},
            "close": {"type": "plain_text", "text": "Cancel"},
        },
    }
    assert "trigger-secret" not in repr(result)


@pytest.mark.parametrize(
    ("error_code", "expected_status", "expected_kind"),
    [
        ("trigger_expired", "expired", "trigger_expired"),
        ("invalid_hash", "conflict", "view_hash_conflict"),
        ("invalid_arguments", "rejected", "provider_rejected"),
    ],
)
async def test_interaction_view_provider_outcomes_are_explicit(
    error_code: str,
    expected_status: str,
    expected_kind: str,
) -> None:
    """Provider responses never look like a successful selector mutation."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": error_code})

    view = SlackInteractionView(
        callback_id="agent-selector",
        title="Choose Agent",
        private_metadata="interaction-1",
        blocks=[],
        submit_title=None,
        close_title=None,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).update_interaction_view(
            bot_token="xoxb-secret",
            view_id="V1",
            view_hash="hash-1",
            view=view,
        )

    assert result.status == expected_status
    assert result.error_kind == expected_kind


def test_interaction_view_rejects_oversized_private_metadata_without_request() -> None:
    """Oversized opaque state cannot produce a Slack modal request."""
    view = SlackInteractionView(
        callback_id="agent-selector",
        title="Choose Agent",
        private_metadata="x" * 3_001,
        blocks=[],
        submit_title=None,
        close_title=None,
    )

    with pytest.raises(ValueError, match="private metadata is too long"):
        SlackConversationClient._validate_interaction_view(
            view
        )  # Validate the provider payload boundary directly.


async def test_missing_update_target_is_reported_as_confirmed_deletion() -> None:
    """Slack message absence is recoverable rather than an ambiguous outcome."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "message_not_found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).update_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            message_ts="1721600000.000100",
            text="Agent is working",
            blocks=[],
        )

    assert result.status == "failed"
    assert result.error_kind == "message_not_found"


async def test_invalid_update_blocks_are_reported_as_confirmed_rejection() -> None:
    """A Slack validation response is failed rather than transport-ambiguous."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "invalid_blocks"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).update_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            message_ts="1721600000.000100",
            text="Agent is working",
            blocks=[],
        )

    assert result.status == "failed"
    assert result.error_kind == "provider_rejected"
    assert result.error_summary == (
        "Slack rejected the provider operation (invalid_blocks)."
    )


async def test_operational_blocks_include_accessible_fallback_text() -> None:
    """Operational Slack messages use Block Kit without losing notification text."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_blocks(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            text="Agent work is in progress.",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*Working*"},
                }
            ],
            icon_url=None,
        )

    assert result.status == "delivered"
    assert json.loads(requests[0].content) == {
        "channel": "C1",
        "thread_ts": "1721600000.000100",
        "text": "Agent work is in progress.",
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Working*"},
            }
        ],
        "mrkdwn": False,
        "parse": "none",
        "link_names": False,
        "unfurl_links": False,
        "unfurl_media": False,
    }


async def test_approval_control_message_uses_block_kit_button() -> None:
    """Approval delivery renders a Slack button rather than a raw URL."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="Alice",
            participant_provider_user_id="U1",
            agent_name=None,
            agent_markdown_line=None,
            icon_url=None,
        )

    assert result.status == "delivered"
    payload = json.loads(requests[0].content)
    assert payload["text"] == (
        "Approval is required before Alice (U1) can invoke the Agent."
    )
    assert payload["blocks"][0] == {
        "type": "header",
        "text": {"type": "plain_text", "text": "Approval required"},
    }
    assert payload["blocks"][1]["text"] == {
        "type": "plain_text",
        "text": (
            "Participant: Alice (U1)\n"
            "Approve this participant before the Agent can respond."
        ),
    }
    button = payload["blocks"][2]["elements"][0]
    assert button["type"] == "button"
    assert button["url"] == "https://azents.example/access/request-1"


async def test_approval_participant_identity_is_not_interpreted_as_mrkdwn() -> None:
    """Provider labels remain literal even when they contain Slack markup."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="<@U999> *Admin* & _owner_",
            participant_provider_user_id="U1",
            agent_name=None,
            agent_markdown_line=None,
            icon_url=None,
        )

    assert result.status == "delivered"
    payload = json.loads(requests[0].content)
    participant_text = payload["blocks"][1]["text"]
    assert participant_text["type"] == "plain_text"
    assert participant_text["text"] == (
        "Participant: <@U999> *Admin* & _owner_ (U1)\n"
        "Approve this participant before the Agent can respond."
    )
    assert all(
        block.get("text", {}).get("type") != "mrkdwn"
        for block in payload["blocks"]
        if isinstance(block, dict)
    )


async def test_channel_action_rate_limit_is_terminal_failed_without_retry() -> None:
    """Outbound rate limiting is one failed attempt rather than inbound retry."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Reply",
            icon_url=None,
        )

    assert calls == 1
    assert result.status == "failed"
    assert result.error_kind == "rate_limited"


async def test_thread_reply_broadcast_is_opt_in() -> None:
    """Only an explicit terminal reply is surfaced to the parent channel."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = _client(http)
        default = await client.post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Interim",
            icon_url=None,
        )
        broadcast = await client.post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Terminal",
            icon_url=None,
            reply_broadcast=True,
        )

    assert default.status == broadcast.status == "delivered"
    default_payload = json.loads(requests[0].content)
    broadcast_payload = json.loads(requests[1].content)
    assert "reply_broadcast" not in default_payload
    assert broadcast_payload["reply_broadcast"] is True


async def test_custom_icon_rejection_falls_back_without_replaying_content() -> None:
    """A confirmed icon failure retries the same logical post with bot identity."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"ok": False, "error": "missing_scope"},
            )
        return httpx.Response(
            200,
            json={"ok": True, "ts": "1721600001.000100"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="*Agent*\nReply",
            icon_url="https://cdn.example/agent.png",
        )

    assert result.status == "delivered"
    assert len(requests) == 2
    first = json.loads(requests[0].content)
    fallback = json.loads(requests[1].content)
    assert first["icon_url"] == "https://cdn.example/agent.png"
    assert "icon_url" not in fallback
    assert first["markdown_text"] == fallback["markdown_text"] == "*Agent*\nReply"


async def test_channel_action_rejects_over_limit_markdown_without_request() -> None:
    """The delivery boundary rejects invalid provider text before mutation."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="x" * 12_001,
            icon_url=None,
        )

    assert calls == 0
    assert result.status == "failed"
    assert result.error_kind == "provider_payload_invalid"


@pytest.mark.asyncio
async def test_file_reply_streams_in_order_and_completes_once() -> None:
    """Slack receives ordered known-length streams before one visible completion."""
    requests: list[tuple[str, str, dict[str, str], bytes, str]] = []
    acquisition_index = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal acquisition_index
        body = await request.aread()
        requests.append(
            (
                request.url.host or "",
                request.url.path,
                dict(request.headers),
                body,
                request.url.query.decode(),
            )
        )
        if request.url.path == "/api/files.getUploadURLExternal":
            acquisition_index += 1
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": (
                        f"https://upload.slack.test/upload/{acquisition_index}"
                    ),
                    "file_id": f"F{acquisition_index}",
                },
            )
        if request.url.host == "upload.slack.test":
            return httpx.Response(200, text="OK")
        assert request.url.path == "/api/files.completeUploadExternal"
        return httpx.Response(200, json={"ok": True, "files": []})

    async def first_content() -> AsyncIterator[bytes]:
        yield b"ab"
        yield b"c"

    async def second_content() -> AsyncIterator[bytes]:
        yield b"1234"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_file_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Attached reports",
            files=[
                SlackOutboundFile(
                    filename="first.txt",
                    length=3,
                    content=first_content,
                ),
                SlackOutboundFile(
                    filename="second.txt",
                    length=4,
                    content=second_content,
                ),
            ],
        )

    assert result.status == "delivered"
    assert [path for _, path, _, _, _ in requests] == [
        "/api/files.getUploadURLExternal",
        "/upload/1",
        "/api/files.getUploadURLExternal",
        "/upload/2",
        "/api/files.completeUploadExternal",
    ]
    first_acquisition = parse_qs(requests[0][4], strict_parsing=True)
    assert first_acquisition == {"filename": ["first.txt"], "length": ["3"]}
    assert requests[1][3] == b"abc"
    assert requests[1][2]["content-length"] == "3"
    assert "authorization" not in requests[1][2]
    second_acquisition = parse_qs(requests[2][4], strict_parsing=True)
    assert second_acquisition == {"filename": ["second.txt"], "length": ["4"]}
    assert requests[3][3] == b"1234"
    assert requests[3][2]["content-length"] == "4"
    completion = parse_qs(requests[4][4], strict_parsing=True)
    serialized_files = completion.pop("files")
    assert len(serialized_files) == 1
    assert json.loads(serialized_files[0]) == [
        {"id": "F1", "title": "first.txt"},
        {"id": "F2", "title": "second.txt"},
    ]
    assert completion == {
        "channel_id": ["C1"],
        "thread_ts": ["1721600000.000100"],
        "initial_comment": ["Attached reports"],
    }
    assert requests[4][2]["authorization"] == "Bearer xoxb-secret"


@pytest.mark.asyncio
async def test_file_reply_stops_without_completion_when_runtime_stream_fails() -> None:
    """A midstream source failure is ambiguous and never reaches completion."""
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/upload/1",
                    "file_id": "F1",
                },
            )
        await request.aread()
        return httpx.Response(200, text="OK")

    async def failed_content() -> AsyncIterator[bytes]:
        yield b"partial"
        raise SlackOutboundFileContentError

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_file_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Attached report",
            files=[
                SlackOutboundFile(
                    filename="report.txt",
                    length=10,
                    content=failed_content,
                )
            ],
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"
    assert paths == ["/api/files.getUploadURLExternal"]
    assert "/api/files.completeUploadExternal" not in paths


@pytest.mark.asyncio
async def test_file_reply_completion_transport_failure_is_unknown() -> None:
    """Completion ambiguity is terminal and never fabricated as delivered."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/upload/1",
                    "file_id": "F1",
                },
            )
        if request.url.host == "upload.slack.test":
            await request.aread()
            return httpx.Response(200, text="OK")
        raise httpx.ReadTimeout("timeout", request=request)

    async def content() -> AsyncIterator[bytes]:
        yield b"abc"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_file_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Attached report",
            files=[
                SlackOutboundFile(
                    filename="report.txt",
                    length=3,
                    content=content,
                )
            ],
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"


@pytest.mark.asyncio
async def test_file_reply_upload_server_failure_is_unknown_without_completion() -> None:
    """A server failure after streaming bytes is treated as ambiguous."""
    paths: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/upload/1",
                    "file_id": "F1",
                },
            )
        await request.aread()
        return httpx.Response(503, text="unavailable")

    async def content() -> AsyncIterator[bytes]:
        yield b"abc"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_file_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Attached report",
            files=[
                SlackOutboundFile(
                    filename="report.txt",
                    length=3,
                    content=content,
                )
            ],
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"
    assert paths == [
        "/api/files.getUploadURLExternal",
        "/upload/1",
    ]


@pytest.mark.asyncio
async def test_file_reply_completion_file_rejection_is_terminal_failed() -> None:
    """Slack rejecting a temporary file ID is a controlled failed outcome."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/upload/1",
                    "file_id": "F1",
                },
            )
        if request.url.host == "upload.slack.test":
            await request.aread()
            return httpx.Response(200, text="OK")
        return httpx.Response(
            200,
            json={"ok": False, "error": "file_not_found"},
        )

    async def content() -> AsyncIterator[bytes]:
        yield b"abc"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await _client(http).post_file_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Attached report",
            files=[
                SlackOutboundFile(
                    filename="report.txt",
                    length=3,
                    content=content,
                )
            ],
        )

    assert result.status == "failed"
    assert result.error_kind == "provider_rejected"


@pytest.mark.asyncio
async def test_file_reply_completion_rejection_logs_safe_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Slack rejection logs request shape without file or message contents."""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/files.getUploadURLExternal":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "upload_url": "https://upload.slack.test/upload/1",
                    "file_id": "F1",
                },
            )
        if request.url.host == "upload.slack.test":
            await request.aread()
            return httpx.Response(200, text="OK")
        return httpx.Response(
            200,
            headers={"x-slack-req-id": "REQ1"},
            json={
                "ok": False,
                "error": "invalid_arguments",
                "response_metadata": {
                    "messages": [
                        "invalid initial_comment: confidential outbound message",
                    ],
                },
            },
        )

    async def content() -> AsyncIterator[bytes]:
        yield b"private file content"

    with caplog.at_level("ERROR"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            result = await _client(http).post_file_message(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                thread_ts="1721600000.000100",
                markdown_text="confidential outbound message",
                files=[
                    SlackOutboundFile(
                        filename="private-report.txt",
                        length=20,
                        content=content,
                    )
                ],
            )

    assert result.status == "failed"
    assert result.error_kind == "provider_rejected"
    record = next(
        record
        for record in caplog.records
        if record.message == "Slack outbound operation failed"
    )
    record_extra = record.__dict__
    assert record_extra["slack_operation"] == "file_reply"
    assert record_extra["slack_api_method"] == "files.completeUploadExternal"
    assert record_extra["slack_http_status_code"] == 200
    assert record_extra["slack_request_id"] == "REQ1"
    assert record_extra["slack_request_field_names"] == [
        "channel_id",
        "files",
        "initial_comment",
        "thread_ts",
    ]
    assert record_extra["slack_response_error_code"] == "invalid_arguments"
    assert record_extra["slack_response_diagnostic_argument_names"] == [
        "initial_comment"
    ]
    assert record.exc_info is not None
    assert "confidential outbound message" not in caplog.text
    assert "private file content" not in caplog.text
    assert "private-report.txt" not in caplog.text


@pytest.mark.asyncio
async def test_read_range_orders_messages_and_excludes_connected_app_before_bound() -> (
    None
):
    """Slack ranges retain the newest twenty eligible messages in provider order."""
    raw_messages = [
        _history_message(
            timestamp=f"100.{index:06d}",
            user_id="B1" if index == 1 else f"U{index}",
            app_id="A1" if index == 1 else None,
        )
        for index in range(22, 0, -1)
    ]

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"ok": True, "messages": raw_messages})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _client(client).read_range(
            trigger=SlackConversationHistoryTrigger(
                tenant_id="T1",
                channel_id="C1",
                trigger_message_ts="100.000022",
                root_thread_ts=None,
                connected_bot_user_id="B1",
                connected_app_id="A1",
            ),
            bot_token="xoxb-secret",
            exclusive_start_position=None,
            deadline=deadline,
        )

    assert result.context_omitted is True
    assert len(result.messages) == 20
    assert result.messages[0].message_ts == "100.000003"
    assert result.messages[-1].message_ts == "100.000022"
    assert all(message.provider_user_id != "bot:B1" for message in result.messages)
    assert [message.provider_position for message in result.messages] == sorted(
        message.provider_position for message in result.messages
    )
    assert result.scanned_message_count == 21


@pytest.mark.asyncio
async def test_read_range_continues_after_connected_identity_dominated_page() -> None:
    """Connected App messages do not make an otherwise incomplete range terminal."""
    first_page = [
        _history_message(timestamp="100.000200", user_id="U-trigger"),
        *[
            _history_message(
                timestamp=f"100.{index:06d}",
                user_id="B1",
                app_id="A1",
            )
            for index in range(199, 100, -1)
        ],
    ]
    second_page = [
        _history_message(timestamp=f"100.{index:06d}", user_id=f"U{index}")
        for index in range(100, 79, -1)
    ]
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.params.get("cursor") is None:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "messages": first_page,
                    "response_metadata": {"next_cursor": "next"},
                },
            )
        return httpx.Response(200, json={"ok": True, "messages": second_page})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _client(client).read_range(
            trigger=SlackConversationHistoryTrigger(
                tenant_id="T1",
                channel_id="C1",
                trigger_message_ts="100.000200",
                root_thread_ts=None,
                connected_bot_user_id="B1",
                connected_app_id="A1",
            ),
            bot_token="xoxb-secret",
            exclusive_start_position=None,
            deadline=deadline,
        )

    assert len(calls) == 2
    assert calls[1].url.params["cursor"] == "next"
    assert result.context_omitted is True
    assert len(result.messages) == 20
    assert result.messages[-1].message_ts == "100.000200"
    assert all(message.provider_user_id != "bot:B1" for message in result.messages)


@pytest.mark.asyncio
async def test_read_range_applies_exclusive_start_and_requires_trigger() -> None:
    """Slack ranges exclude the cursor and include the exact trigger."""
    raw_messages = [
        _history_message(timestamp="100.000003", user_id="U3"),
        _history_message(timestamp="100.000002", user_id="U2"),
        _history_message(timestamp="100.000001", user_id="U1"),
    ]

    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "messages": raw_messages})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _client(client).read_range(
            trigger=SlackConversationHistoryTrigger(
                tenant_id="T1",
                channel_id="C1",
                trigger_message_ts="100.000003",
                root_thread_ts=None,
                connected_bot_user_id="B1",
                connected_app_id=None,
            ),
            bot_token="xoxb-secret",
            exclusive_start_position=slack_provider_position("100.000001"),
            deadline=deadline,
        )

    assert [message.message_ts for message in result.messages] == [
        "100.000002",
        "100.000003",
    ]
    assert calls[0].url.params["oldest"] == "100.000001"
    assert calls[0].url.params["latest"] == "100.000003"
    assert calls[0].headers["Authorization"] == "Bearer xoxb-secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("root_thread_ts", "raw_scope"),
    [
        (None, {"channel": "C-other"}),
        ("100.000001", {"thread_ts": "100.999999"}),
    ],
)
async def test_read_range_rejects_cross_conversation_items(
    root_thread_ts: str | None,
    raw_scope: dict[str, object],
) -> None:
    """Slack range items must retain the requested channel and thread identity."""
    raw_message = _history_message(timestamp="100.000003", user_id="U3")
    raw_message.update(raw_scope)

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"ok": True, "messages": [raw_message]})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryMalformed):
            await _client(client).read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id="T1",
                    channel_id="C1",
                    trigger_message_ts="100.000003",
                    root_thread_ts=root_thread_ts,
                    connected_bot_user_id=None,
                    connected_app_id=None,
                ),
                bot_token="xoxb-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )


@pytest.mark.asyncio
async def test_thread_range_sends_oldest_latest_boundaries() -> None:
    """Slack thread reads bound every request to the requested range."""
    raw_messages = [
        {
            **_history_message(timestamp="100.000003", user_id="U3"),
            "thread_ts": "100.000000",
        },
        {
            **_history_message(timestamp="100.000002", user_id="U2"),
            "thread_ts": "100.000000",
        },
    ]
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "messages": raw_messages})

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _client(client).read_range(
            trigger=SlackConversationHistoryTrigger(
                tenant_id="T1",
                channel_id="C1",
                trigger_message_ts="100.000003",
                root_thread_ts="100.000000",
                connected_bot_user_id=None,
                connected_app_id=None,
            ),
            bot_token="xoxb-secret",
            exclusive_start_position=slack_provider_position("100.000001"),
            deadline=deadline,
        )

    assert calls[0].url.path.endswith("/conversations.replies")
    assert calls[0].url.params["oldest"] == "100.000001"
    assert calls[0].url.params["latest"] == "100.000003"


@pytest.mark.asyncio
async def test_read_range_maps_invalid_start_position() -> None:
    """Slack timestamps use the typed invalid-position failure."""
    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))
    ) as client:
        with pytest.raises(ExternalChannelHistoryPositionInvalid):
            await _client(client).read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id="T1",
                    channel_id="C1",
                    trigger_message_ts="100.000003",
                    root_thread_ts=None,
                    connected_bot_user_id=None,
                    connected_app_id=None,
                ),
                bot_token="xoxb-secret",
                exclusive_start_position="not-a-slack-position",
                deadline=deadline,
            )


@pytest.mark.asyncio
async def test_read_range_checks_expired_deadline_before_request() -> None:
    """An expired range budget does not construct a Slack request."""
    calls: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise AssertionError("expired history must not reach the provider")

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryDeadlineExceeded):
            await _client(client).read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id="T1",
                    channel_id="C1",
                    trigger_message_ts="100.000003",
                    root_thread_ts=None,
                    connected_bot_user_id=None,
                    connected_app_id=None,
                ),
                bot_token="xoxb-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )

    assert calls == []


@pytest.mark.asyncio
async def test_read_range_maps_provider_rate_limit() -> None:
    """Slack range provider failures retain the typed retry classification."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            429,
            json={"ok": False, "error": "ratelimited"},
            headers={"Retry-After": "2"},
        )

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryRateLimited) as raised:
            await _client(client).read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id="T1",
                    channel_id="C1",
                    trigger_message_ts="100.000003",
                    root_thread_ts=None,
                    connected_bot_user_id=None,
                    connected_app_id=None,
                ),
                bot_token="xoxb-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )

    assert raised.value.retry_after_seconds == 2


@pytest.mark.asyncio
async def test_read_range_maps_missing_trigger() -> None:
    """Slack history without the exact trigger is rejected."""

    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json={
                "ok": True,
                "messages": [_history_message(timestamp="100.000001", user_id="U1")],
            },
        )

    deadline = ExternalChannelOperationDeadline(
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=1)
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ExternalChannelHistoryTriggerMissing):
            await _client(client).read_range(
                trigger=SlackConversationHistoryTrigger(
                    tenant_id="T1",
                    channel_id="C1",
                    trigger_message_ts="100.000002",
                    root_thread_ts=None,
                    connected_bot_user_id="B1",
                    connected_app_id=None,
                ),
                bot_token="xoxb-secret",
                exclusive_start_position=None,
                deadline=deadline,
            )
