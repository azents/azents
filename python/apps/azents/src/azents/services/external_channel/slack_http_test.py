"""Slack HTTP signature, parsing, and identity validation tests."""

import datetime
import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qs, urlencode

import aiohttp
import httpx
import pytest
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.web.async_slack_response import AsyncSlackResponse

from azents.core.enums import (
    ExternalChannelConversationLocation,
    ExternalChannelResponseMode,
    ExternalChannelTransport,
)
from azents.services.external_channel.slack_endpoint import (
    slack_api_base_url,
    slack_file_url_allowed,
    slack_insecure_websocket_allowed,
)
from azents.services.external_channel.slack_http import (
    MAX_SLACK_HTTP_BODY_BYTES,
    SlackEventCallback,
    SlackEventRouteIdentity,
    SlackHTTPPayloadTooLarge,
    SlackHTTPUnauthorized,
    SlackInteractionCallback,
    SlackInteractionRouteIdentity,
    SlackURLVerification,
    SlackWebAPIClient,
    parse_slack_callback,
    parse_slack_callback_route,
    parse_slack_interaction_payload,
    project_slack_shortcut_source_event,
    verify_slack_signature,
)
from azents.services.scheduled_task.control import (
    ScheduledTaskEditInput,
    build_scheduled_task_control_locator,
    build_scheduled_task_slack_edit_metadata,
)

_NOW = datetime.datetime(2026, 7, 22, 1, 0, tzinfo=datetime.UTC)
_SECRET = "signing-secret"
_CONTROL_TASK_ID = "01828d10-b4c3-7a12-94d6-8f43c4e195ce"
_CONTROL_BINDING_ID = "01828d10-b4c3-7a12-94d6-8f43c4e195cf"


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


def _validation_client(http_client: httpx.AsyncClient) -> SlackWebAPIClient:
    return SlackWebAPIClient(_MockSlackWebClient(http_client))


def test_scheduled_task_controls_project_only_bounded_locator_and_modal_input() -> None:
    """Scheduled Task control payloads remain request-local after admission."""
    edit_locator = build_scheduled_task_control_locator(
        secret=_SECRET,
        action="edit",
        task_id=_CONTROL_TASK_ID,
        binding_id=_CONTROL_BINDING_ID,
    )
    opened = parse_slack_interaction_payload(
        payload={
            "type": "block_actions",
            "api_app_id": "app-1",
            "team": {"id": "tenant-1"},
            "user": {"id": "user-1"},
            "channel": {"id": "channel-1"},
            "message": {"thread_ts": "1.000000"},
            "trigger_id": "trigger-1",
            "actions": [
                {
                    "action_id": "azents_scheduled_task_edit",
                    "value": edit_locator,
                }
            ],
        },
        provider_interaction_key="interaction-1",
        received_at=_NOW,
    )

    assert opened.handler == "scheduled_task_edit_open"
    assert opened.scheduled_task_locator == edit_locator
    assert opened.scheduled_task_edit is None

    edit_metadata = build_scheduled_task_slack_edit_metadata(
        secret=_SECRET,
        locator=edit_locator,
        origin_interaction_id="01828d10-b4c3-7a12-94d6-8f43c4e195d0",
    )
    assert len(edit_metadata) > 100
    submitted = parse_slack_interaction_payload(
        payload={
            "type": "view_submission",
            "api_app_id": "app-1",
            "team": {"id": "tenant-1"},
            "user": {"id": "user-1"},
            "trigger_id": "trigger-2",
            "view": {
                "callback_id": "azents_scheduled_task_edit",
                "private_metadata": edit_metadata,
                "state": {
                    "values": {
                        "azents_scheduled_task_title": {
                            "azents_scheduled_task_title": {"value": "Updated"}
                        },
                        "azents_scheduled_task_objective": {
                            "azents_scheduled_task_objective": {
                                "value": "Updated objective"
                            }
                        },
                        "azents_scheduled_task_at": {
                            "azents_scheduled_task_at": {"value": ""}
                        },
                        "azents_scheduled_task_cron": {
                            "azents_scheduled_task_cron": {"value": "0 9 * * *"}
                        },
                        "azents_scheduled_task_timezone": {
                            "azents_scheduled_task_timezone": {
                                "value": "America/Los_Angeles"
                            }
                        },
                    }
                },
            },
        },
        provider_interaction_key="interaction-2",
        received_at=_NOW,
    )

    assert submitted.handler == "scheduled_task_edit_submission"
    assert submitted.scheduled_task_locator == edit_metadata
    assert submitted.scheduled_task_edit == ScheduledTaskEditInput(
        title="Updated",
        objective="Updated objective",
        at=None,
        cron="0 9 * * *",
        timezone="America/Los_Angeles",
    )


def test_testenv_endpoint_overrides_are_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use Slack defaults unless deterministic test boundaries are configured."""
    monkeypatch.delenv("AZ_TESTENV_SLACK_API_BASE_URL", raising=False)
    monkeypatch.delenv(
        "AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET",
        raising=False,
    )
    assert slack_api_base_url() == "https://slack.com/api"
    assert slack_insecure_websocket_allowed() is False

    monkeypatch.setenv(
        "AZ_TESTENV_SLACK_API_BASE_URL",
        "http://slack-fake:8083/api/",
    )
    monkeypatch.setenv(
        "AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET",
        "true",
    )
    assert slack_api_base_url() == "http://slack-fake:8083/api"
    assert slack_insecure_websocket_allowed() is True


def test_slack_file_url_allows_https_and_exact_test_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Insecure file URLs remain limited to the explicit deterministic origin."""
    monkeypatch.setenv(
        "AZ_TESTENV_SLACK_API_BASE_URL",
        "http://slack-fake:8083/api",
    )

    assert slack_file_url_allowed("https://files.slack.com/files/F1")
    assert slack_file_url_allowed("http://slack-fake:8083/files/F1")
    assert not slack_file_url_allowed("http://other-fake:8083/files/F1")
    assert not slack_file_url_allowed("file:///tmp/F1")


def _signature(body: bytes, timestamp: int | None = None) -> tuple[str, str]:
    request_timestamp = timestamp if timestamp is not None else int(_NOW.timestamp())
    timestamp_header = str(request_timestamp)
    base = b"v0:" + timestamp_header.encode() + b":" + body
    signature = "v0=" + hmac.new(_SECRET.encode(), base, hashlib.sha256).hexdigest()
    return timestamp_header, signature


def _event_body() -> bytes:
    return json.dumps(
        {
            "type": "event_callback",
            "event_id": "Ev-1",
            "event_time": int(_NOW.timestamp()),
            "api_app_id": "A-1",
            "team_id": "T-1",
            "enterprise_id": "E-1",
            "authorizations": [
                {
                    "is_bot": True,
                    "team_id": "T-1",
                    "user_id": "UBOT",
                    "unexpected": "not retained",
                }
            ],
            "token": "deprecated-token-must-not-be-stored",
            "event": {
                "type": "app_mention",
                "channel": "C-1",
                "user": "U-1",
                "text": "Please investigate",
                "ts": "100.0002",
                "thread_ts": "100.0001",
                "unexpected": "not retained",
            },
        }
    ).encode()


def _interaction_body(*, interaction_type: str = "message_action") -> bytes:
    """Build one URL-encoded Slack interaction body with excluded secret fields."""
    payload: dict[str, object] = {
        "type": interaction_type,
        "api_app_id": "A-1",
        "team": {"id": "T-1"},
        "user": {"id": "U-1"},
        "trigger_id": "trigger-secret-must-not-persist",
        "response_url": "https://hooks.slack.com/actions/private",
        "channel": {"id": "C-1"},
        "message": {
            "ts": "100.0001",
            "thread_ts": "100.0001",
            "text": "private source text",
        },
    }
    if interaction_type != "view_submission":
        payload["callback_id"] = "azents_ask_agent"
    if interaction_type in {"block_actions", "block_suggestion"}:
        payload["actions"] = [
            {"action_id": "azents_agent_selector_open", "value": "route-1"}
        ]
    if interaction_type == "view_submission":
        payload["view"] = {
            "callback_id": "azents_agent_selector",
            "private_metadata": "signed-selector-metadata",
            "state": {
                "values": {
                    "azents_agent_selector_route": {
                        "azents_agent_selector_route": {
                            "selected_option": {"value": "route-1"}
                        }
                    }
                }
            },
        }
    return urlencode({"payload": json.dumps(payload)}).encode()


def test_signature_verification_uses_exact_raw_body() -> None:
    """Accept the signed bytes and reject a semantically equal reserialization."""
    body = b'{"type":"url_verification","challenge":"abc"}'
    timestamp, signature = _signature(body)

    verify_slack_signature(
        raw_body=body,
        timestamp_header=timestamp,
        signature_header=signature,
        signing_secret=_SECRET,
        now=_NOW,
    )

    with pytest.raises(SlackHTTPUnauthorized):
        verify_slack_signature(
            raw_body=b'{"challenge":"abc","type":"url_verification"}',
            timestamp_header=timestamp,
            signature_header=signature,
            signing_secret=_SECRET,
            now=_NOW,
        )


@pytest.mark.parametrize("offset_seconds", [-301, 301])
def test_signature_verification_rejects_replay_window(offset_seconds: int) -> None:
    """Reject both stale and excessively future-dated requests."""
    body = b"{}"
    timestamp, signature = _signature(
        body,
        int(_NOW.timestamp()) + offset_seconds,
    )

    with pytest.raises(SlackHTTPUnauthorized):
        verify_slack_signature(
            raw_body=body,
            timestamp_header=timestamp,
            signature_header=signature,
            signing_secret=_SECRET,
            now=_NOW,
        )


def test_url_verification_does_not_require_app_identity() -> None:
    """Return the challenge because Slack omits ``api_app_id`` from this shape."""
    result = parse_slack_callback_route(
        json.dumps({"type": "url_verification", "challenge": "challenge-1"}).encode()
    )

    assert result == SlackURLVerification(challenge="challenge-1")


def test_event_callback_exposes_untrusted_routing_identity() -> None:
    """Extract only App and tenant identity before HMAC authentication."""
    result = parse_slack_callback_route(_event_body())

    assert result == SlackEventRouteIdentity(app_id="A-1", tenant_id="T-1")


def test_interaction_callback_exposes_only_untrusted_routing_identity() -> None:
    """Read the interaction App and Team before HMAC verification."""
    result = parse_slack_callback_route(_interaction_body())

    assert result == SlackInteractionRouteIdentity(app_id="A-1", tenant_id="T-1")


def test_slash_settings_command_projects_explicit_settings_handler() -> None:
    """Route the exact settings command without retaining arbitrary command text."""
    body = urlencode(
        {
            "api_app_id": "A-1",
            "team_id": "T-1",
            "user_id": "U-1",
            "channel_id": "C-1",
            "command": "/azents",
            "text": "settings",
            "trigger_id": "trigger-secret",
        }
    ).encode()

    route = parse_slack_callback_route(body)
    callback = parse_slack_callback(
        connection_id="connection-1",
        raw_body=body,
        received_at=_NOW,
    )

    assert route == SlackInteractionRouteIdentity(app_id="A-1", tenant_id="T-1")
    assert isinstance(callback, SlackInteractionCallback)
    assert callback.handler == "settings_open"
    assert callback.provider_parent_channel_id == "C-1"
    assert callback.projection == {
        "interaction_type": "management_action",
        "handler": "settings_open",
        "surface": "command",
    }
    assert "trigger-secret" not in repr(callback)


def test_settings_modal_projects_only_typed_signed_scope_and_selections() -> None:
    """Keep opaque scope and known enum selections only in transient handoff state."""
    callback = parse_slack_interaction_payload(
        payload={
            "type": "view_submission",
            "api_app_id": "A-1",
            "team": {"id": "T-1"},
            "user": {"id": "U-1"},
            "view": {
                "callback_id": "azents_conversation_settings",
                "private_metadata": "signed-settings-scope",
                "state": {
                    "values": {
                        "azents_conversation_location": {
                            "azents_conversation_location": {
                                "selected_option": {"value": "channel"}
                            }
                        },
                        "azents_conversation_response_mode": {
                            "azents_conversation_response_mode": {
                                "selected_option": {"value": "mention_only"}
                            }
                        },
                    }
                },
            },
        },
        provider_interaction_key="http-settings",
        received_at=_NOW,
    )

    assert callback.handler == "settings_submission"
    assert callback.settings_metadata == "signed-settings-scope"
    assert callback.settings_location is ExternalChannelConversationLocation.CHANNEL
    assert callback.settings_response_mode is ExternalChannelResponseMode.MENTION_ONLY
    assert "signed-settings-scope" not in repr(callback)


def test_settings_button_projects_modal_open_callback() -> None:
    """Route one setup control button through the settings modal processor."""
    callback = parse_slack_interaction_payload(
        payload={
            "type": "block_actions",
            "api_app_id": "A-1",
            "team": {"id": "T-1"},
            "user": {"id": "U-1"},
            "trigger_id": "trigger-secret",
            "channel": {"id": "C-1"},
            "message": {"ts": "100.0001", "thread_ts": "100.0001"},
            "actions": [
                {
                    "action_id": "azents_conversation_settings_open",
                    "value": "signed-settings-locator",
                }
            ],
        },
        provider_interaction_key="http-settings-open",
        received_at=_NOW,
    )

    assert callback.handler == "settings_open"
    assert callback.settings_metadata == "signed-settings-locator"
    assert callback.trigger_id == "trigger-secret"
    assert "signed-settings-locator" not in repr(callback)
    assert "trigger-secret" not in repr(callback)


@pytest.mark.parametrize(
    ("interaction_type", "expected_type", "expected_handler", "expected_surface"),
    [
        ("message_action", "shortcut", "selector_open", "unknown"),
        ("block_actions", "block_action", "selector_open", "unknown"),
        ("block_suggestion", "options", "unsupported", "unknown"),
        ("view_submission", "view_submission", "selector_submission", "modal"),
    ],
)
def test_interaction_callback_projects_only_bounded_safe_metadata(
    interaction_type: str,
    expected_type: str,
    expected_handler: str,
    expected_surface: str,
) -> None:
    """Do not retain form text, trigger IDs, response URLs, or action values."""
    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=_interaction_body(interaction_type=interaction_type),
        received_at=_NOW,
    )

    assert isinstance(result, SlackInteractionCallback)
    assert result.interaction_type.value == expected_type
    assert result.actor_user_id == "U-1"
    assert result.resource_correlation_key == "C-1:100.0001"
    assert result.provider_interaction_key.startswith("http-")
    assert result.projection == {
        "interaction_type": expected_type,
        "handler": expected_handler,
        "surface": expected_surface,
    }
    if interaction_type == "view_submission":
        assert result.selector_metadata == "signed-selector-metadata"
        assert result.selected_route_id == "route-1"
    persisted = repr(result)
    assert "trigger-secret" not in persisted
    assert "hooks.slack.com" not in persisted
    assert "private source text" not in persisted
    assert "route-1" not in persisted


def test_selector_navigation_projects_only_transient_bounded_modal_state() -> None:
    """Keep page/search controls in memory without persisting their values."""
    result = parse_slack_interaction_payload(
        payload={
            "type": "block_actions",
            "api_app_id": "A-1",
            "team": {"id": "T-1"},
            "user": {"id": "U-1"},
            "actions": [{"action_id": "azents_agent_selector_next"}],
            "view": {
                "id": "V-1",
                "hash": "hash-1",
                "callback_id": "azents_agent_selector",
                "private_metadata": "signed-selector-metadata",
                "state": {
                    "values": {
                        "azents_agent_selector_search": {
                            "azents_agent_selector_search": {"value": "  operations  "}
                        }
                    }
                },
            },
        },
        provider_interaction_key="http-navigation",
        received_at=_NOW,
    )

    assert result.requires_selector_processing()
    assert result.selector_navigation == "next"
    assert result.selector_search == "operations"
    assert result.selector_view_id == "V-1"
    assert result.selector_view_hash == "hash-1"
    assert result.selector_metadata == "signed-selector-metadata"
    assert "operations" not in repr(result)
    assert "signed-selector-metadata" not in repr(result)


def test_message_shortcut_source_projects_to_stable_canonical_event() -> None:
    """Retain only canonical source content and stable retry identity."""
    payload = json.loads(
        parse_qs(_interaction_body(interaction_type="message_action").decode())[
            "payload"
        ][0]
    )
    source = project_slack_shortcut_source_event(
        connection_id="connection-1",
        payload=payload,
        provider_interaction_key="http-abc",
        received_at=_NOW,
    )
    retry = project_slack_shortcut_source_event(
        connection_id="connection-1",
        payload=payload,
        provider_interaction_key="http-abc",
        received_at=_NOW,
    )

    assert source.provider_event_id == retry.provider_event_id == "shortcut-http-abc"
    assert source.resource_correlation_key == "C-1:100.0001"
    assert source.envelope["event"] == {
        "type": "app_mention",
        "channel": "C-1",
        "user": "U-1",
        "ts": "100.0001",
        "thread_ts": "100.0001",
        "text": "private source text",
    }
    persisted = repr(source)
    assert "trigger-secret" not in persisted
    assert "hooks.slack.com" not in persisted


def test_event_callback_projects_bounded_routing_and_message_fields() -> None:
    """Normalize identity and correlation while dropping unrelated top-level data."""
    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=_event_body(),
        received_at=_NOW,
    )

    assert isinstance(result, SlackEventCallback)
    assert result.app_id == "A-1"
    assert result.tenant_id == "T-1"
    assert result.event.provider_event_id == "Ev-1"
    assert result.event.event_type == "app_mention"
    assert result.event.resource_correlation_key == "C-1:100.0001"
    assert result.event.provider_enterprise_id == "E-1"
    assert "token" not in result.event.envelope
    assert result.event.envelope["authorizations"] == [
        {
            "is_bot": True,
            "team_id": "T-1",
            "user_id": "UBOT",
        }
    ]
    event = result.event.envelope["event"]
    assert isinstance(event, dict)
    assert event["text"] == "Please investigate"
    assert "unexpected" not in event


def test_event_callback_projects_bounded_rich_text_content() -> None:
    """Retain readable block-only content without arbitrary Block Kit fields."""
    payload = json.loads(_event_body())
    event = payload["event"]
    event["text"] = ""
    event["blocks"] = [
        {
            "type": "rich_text",
            "block_id": "untrusted-provider-block-id",
            "normalized_text": "Spoofed provider projection",
            "elements": [
                {
                    "type": "rich_text_section",
                    "elements": [
                        {"type": "text", "text": "Ask "},
                        {"type": "user", "user_id": "U2"},
                        {"type": "text", "text": " in "},
                        {"type": "channel", "channel_id": "C2"},
                    ],
                }
            ],
        }
    ]

    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=json.dumps(payload).encode(),
        received_at=_NOW,
    )

    assert isinstance(result, SlackEventCallback)
    projected_event = result.event.envelope["event"]
    assert isinstance(projected_event, dict)
    assert projected_event["blocks"] == [
        {
            "type": "rich_text",
            "normalized_text": "Ask <@U2> in <#C2>",
        }
    ]
    assert "untrusted-provider-block-id" not in repr(projected_event)


def test_event_callback_projects_bounded_files_without_private_fields() -> None:
    """Retain safe file metadata while dropping URLs, bodies, and excess entries."""
    payload = json.loads(_event_body())
    event = payload["event"]
    event["files"] = [
        {
            "id": f"F{index}",
            "name": "x" * 300,
            "title": f"File {index}",
            "mimetype": "text/plain",
            "size": index,
            "mode": "hosted",
            "is_external": False,
            "url_private": f"https://files.slack.test/private/F{index}",
            "thumb_1024": "https://files.slack.test/thumb",
            "body": "must not survive",
        }
        for index in range(21)
    ]

    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=json.dumps(payload).encode(),
        received_at=_NOW,
    )

    assert isinstance(result, SlackEventCallback)
    projected_event = result.event.envelope["event"]
    assert isinstance(projected_event, dict)
    files = projected_event["files"]
    assert isinstance(files, list)
    assert len(files) == 20
    assert projected_event["files_truncated"] is True
    assert files[0] == {
        "id": "F0",
        "name": "x" * 255,
        "title": "File 0",
        "mimetype": "text/plain",
        "mode": "hosted",
        "size": 0,
        "is_external": False,
    }
    assert "url_private" not in repr(files)
    assert "thumb_1024" not in repr(files)
    assert "must not survive" not in repr(files)


def test_event_callback_projects_nested_edited_message_files() -> None:
    """Edited and deleted message variants use the same safe file projection."""
    payload = json.loads(_event_body())
    event = payload["event"]
    event["type"] = "message"
    event["subtype"] = "message_changed"
    event["message"] = {
        "user": "U-1",
        "ts": "100.0002",
        "text": "updated",
        "files": [
            {
                "id": "F1",
                "name": "report.csv",
                "size": 42,
                "mode": "hosted",
                "url_private": "https://files.slack.test/private/F1",
            }
        ],
    }

    result = parse_slack_callback(
        connection_id="connection-1",
        raw_body=json.dumps(payload).encode(),
        received_at=_NOW,
    )

    assert isinstance(result, SlackEventCallback)
    projected_event = result.event.envelope["event"]
    assert isinstance(projected_event, dict)
    nested = projected_event["message"]
    assert isinstance(nested, dict)
    assert nested["files"] == [
        {
            "id": "F1",
            "name": "report.csv",
            "mode": "hosted",
            "size": 42,
        }
    ]
    assert nested["files_truncated"] is False
    assert "url_private" not in repr(nested)


def test_event_callback_rejects_oversized_body() -> None:
    """Bound the provider inbox before JSON normalization."""
    with pytest.raises(SlackHTTPPayloadTooLarge):
        parse_slack_callback(
            connection_id="connection-1",
            raw_body=b"x" * (MAX_SLACK_HTTP_BODY_BYTES + 1),
            received_at=_NOW,
        )


@pytest.mark.asyncio
async def test_auth_test_returns_sanitized_identity() -> None:
    """Verify App ownership and expose only sanitized identity state."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer xoxb-secret"
        if request.url.path.endswith("/auth.test"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "team_id": "T-1",
                    "user_id": "U-BOT",
                    "bot_id": "B-1",
                },
            )
        assert request.url.path.endswith("/bots.info")
        assert request.url.params["bot"] == "B-1"
        return httpx.Response(
            200,
            json={"ok": True, "bot": {"id": "B-1", "app_id": "A-1"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _validation_client(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert result.status == "valid"
    assert result.identity is not None
    assert result.identity.app_id == "A-1"
    assert result.identity.tenant_id == "T-1"
    assert result.identity.bot_user_id == "U-BOT"
    assert result.capabilities is not None
    assert result.capabilities.download_files is False
    assert result.capabilities.upload_files is False
    assert "xoxb-secret" not in repr(result)


@pytest.mark.parametrize(
    ("optional_scopes", "download_files", "upload_files", "customize_messages"),
    [
        ("files:read", True, False, False),
        ("files:write", False, True, False),
        ("files:read,files:write", True, True, False),
        ("chat:write.customize", False, False, True),
        ("files:read invalid", False, False, False),
    ],
)
@pytest.mark.asyncio
async def test_auth_test_derives_optional_internal_capabilities_independently(
    optional_scopes: str,
    download_files: bool,
    upload_files: bool,
    customize_messages: bool,
) -> None:
    """Optional scopes never gate unrelated text connection behavior."""
    required_scopes = (
        "assistant:write,app_mentions:read,channels:history,channels:read,"
        "groups:history,groups:read,chat:write,commands,users:read"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth.test"):
            return httpx.Response(
                200,
                headers={
                    "x-oauth-scopes": f"{required_scopes},{optional_scopes}",
                },
                json={
                    "ok": True,
                    "team_id": "T-1",
                    "user_id": "U-BOT",
                    "bot_id": "B-1",
                },
            )
        return httpx.Response(
            200,
            json={"ok": True, "bot": {"id": "B-1", "app_id": "A-1"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _validation_client(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert result.status == "valid"
    assert result.capabilities is not None
    assert result.capabilities.download_files is download_files
    assert result.capabilities.upload_files is upload_files
    assert result.customize_messages is customize_messages


@pytest.mark.asyncio
async def test_app_id_must_own_the_configured_bot_token() -> None:
    """Reject an App ID copied from a different Slack App."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth.test"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "team_id": "T-1",
                    "user_id": "U-BOT",
                    "bot_id": "B-1",
                },
            )
        return httpx.Response(
            200,
            json={"ok": True, "bot": {"id": "B-1", "app_id": "A-ACTUAL"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _validation_client(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-WRONG",
            transport=ExternalChannelTransport.HTTP,
        )

    assert result.status == "invalid"
    assert result.code == "slack_app_id_mismatch"
    assert result.identity is None


@pytest.mark.asyncio
async def test_auth_test_rejects_missing_required_bot_scopes() -> None:
    """Validation catches incomplete App permissions before event processing."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/auth.test")
        return httpx.Response(
            200,
            headers={
                "x-oauth-scopes": (
                    "app_mentions:read,channels:history,groups:history,"
                    "chat:write,users:read"
                )
            },
            json={
                "ok": True,
                "team_id": "T-1",
                "user_id": "U-BOT",
                "bot_id": "B-1",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _validation_client(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert result.status == "invalid"
    assert result.code == "slack_bot_scopes_missing"
    assert result.message is not None
    assert "channels:read" in result.message
    assert "groups:read" in result.message
    assert result.identity is None


@pytest.mark.asyncio
async def test_auth_test_distinguishes_invalid_and_unavailable() -> None:
    """Map rejected credentials separately from transient provider failure."""

    def invalid_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json={"ok": False, "error": "invalid_auth"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(invalid_handler)
    ) as client:
        invalid = await _validation_client(client).validate_connection(
            bot_token="xoxb-invalid",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    def unavailable_handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(unavailable_handler)
    ) as client:
        unavailable = await _validation_client(client).validate_connection(
            bot_token="xoxb-secret",
            app_id="A-1",
            transport=ExternalChannelTransport.HTTP,
        )

    assert invalid.status == "invalid"
    assert invalid.code == "slack_credentials_invalid"
    assert unavailable.status == "unavailable"
    assert unavailable.code == "slack_unavailable"
