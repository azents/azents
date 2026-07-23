"""Slack External Channel event normalization and API adapter tests."""

import json

import httpx
import pytest

from azents.core.enums import (
    ExternalChannelMessageLifecycle,
    ExternalChannelMessageRevisionKind,
    ExternalChannelPrincipalAuthorType,
)
from azents.services.external_channel.slack_events import (
    SlackConnectionRevocation,
    SlackConversationClient,
    SlackEventExcluded,
    SlackNormalizedMessage,
    SlackProviderCredentialsInvalid,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    normalize_slack_event,
    slack_message_reference_ids,
    slack_provider_position,
)


def _envelope(event: dict[str, object]) -> dict[str, object]:
    return {"event": event}


def test_normalizes_human_app_mention_as_authorized_invocation_candidate() -> None:
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
        "block_count": 1,
        "block_types": ["section"],
        "truncated": False,
    }


def test_bot_mention_is_context_only_and_never_invokes() -> None:
    """Bot-authored mentions remain context even when Slack labels them mentions."""
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
    assert normalized.invocation is False
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


def test_normalizes_edit_and_delete_with_distinct_lifecycle_identity() -> None:
    """Edits and deletes preserve message identity while creating new revisions."""
    edited = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "subtype": "message_changed",
                "channel": "C1",
                "channel_type": "channel",
                "event_ts": "1721600002.000100",
                "message": {
                    "user": "U1",
                    "ts": "1721600000.000100",
                    "thread_ts": "1721599999.000100",
                    "text": "updated",
                    "edited": {"ts": "1721600002.000000"},
                },
            }
        ),
    )
    deleted = normalize_slack_event(
        event_type="message",
        tenant_id="T1",
        envelope=_envelope(
            {
                "type": "message",
                "subtype": "message_deleted",
                "channel": "C1",
                "channel_type": "channel",
                "event_ts": "1721600003.000000",
                "deleted_ts": "1721600000.000100",
                "previous_message": {
                    "user": "U1",
                    "ts": "1721600000.000100",
                    "thread_ts": "1721599999.000100",
                },
            }
        ),
    )

    assert isinstance(edited, SlackNormalizedMessage)
    assert isinstance(deleted, SlackNormalizedMessage)
    assert edited.provider_message_key == deleted.provider_message_key
    assert edited.revision_kind is ExternalChannelMessageRevisionKind.EDIT
    assert edited.lifecycle is ExternalChannelMessageLifecycle.EDITED
    assert edited.revision_key.startswith("edit:1721600002.000000:")
    assert deleted.revision_kind is ExternalChannelMessageRevisionKind.DELETE
    assert deleted.lifecycle is ExternalChannelMessageLifecycle.DELETED
    assert deleted.normalized_body is None


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


def test_rich_text_edit_revision_identity_uses_normalized_body() -> None:
    """Changing block-only content creates a distinct edit revision key."""

    def edited(text: str) -> SlackNormalizedMessage:
        normalized = normalize_slack_event(
            event_type="message",
            tenant_id="T1",
            envelope=_envelope(
                {
                    "type": "message",
                    "subtype": "message_changed",
                    "channel": "C1",
                    "channel_type": "channel",
                    "event_ts": "1721600002.000100",
                    "message": {
                        "user": "U1",
                        "ts": "1721600000.000100",
                        "text": "",
                        "edited": {"ts": "1721600002.000000"},
                        "blocks": [
                            {
                                "type": "rich_text",
                                "elements": [
                                    {
                                        "type": "rich_text_section",
                                        "elements": [{"type": "text", "text": text}],
                                    }
                                ],
                            }
                        ],
                    },
                }
            ),
        )
        assert isinstance(normalized, SlackNormalizedMessage)
        return normalized

    first = edited("First")
    second = edited("Second")

    assert first.normalized_body == "First"
    assert second.normalized_body == "Second"
    assert first.revision_key != second.revision_key


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
        access = await SlackConversationClient(http).fetch_conversation_access(
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
        client = SlackConversationClient(http)
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
                    }
                ],
                "response_metadata": {"next_cursor": "cursor-2"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        page = await SlackConversationClient(http).fetch_thread_page(
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
    assert requests[0].url.params["cursor"] == "cursor-1"
    assert requests[0].headers["Authorization"] == "Bearer xoxb-secret"


async def test_thread_page_skips_unsupported_history_subtypes() -> None:
    """One unsupported history item does not block the remaining thread."""

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
        page = await SlackConversationClient(http).fetch_thread_page(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            root_thread_ts="1721600000.000100",
            cursor=None,
            limit=100,
        )

    assert len(page.messages) == 1
    assert page.messages[0].normalized_body == "root"


async def test_thread_page_surfaces_rate_limit_for_inbound_retry() -> None:
    """Hydration rate limits carry the provider retry interval."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "17"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(SlackProviderRateLimited) as raised:
            await SlackConversationClient(http).fetch_thread_page(
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
            await SlackConversationClient(http).fetch_thread_page(
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
            await SlackConversationClient(http).fetch_thread_page(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                root_thread_ts="1721600000.000100",
                cursor=None,
                limit=100,
            )


async def test_control_message_reports_ambiguous_network_outcome_without_retry() -> (
    None
):
    """A transport failure remains unknown instead of fabricated as delivered."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="Alice",
            participant_provider_user_id="U1",
        )

    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"


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
        client = SlackConversationClient(http)
        if operation == "post":
            result = await client.post_message(
                bot_token="xoxb-secret",
                tenant_id="T1",
                channel_id="C1",
                thread_ts="1721600000.000100",
                markdown_text="Reply",
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
    payload = json.loads(requests[0].content)
    if operation == "post":
        assert payload["markdown_text"] == "Reply"
        assert "text" not in payload
        assert "blocks" not in payload


async def test_operational_blocks_include_accessible_fallback_text() -> None:
    """Operational Slack messages use Block Kit without losing notification text."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).post_blocks(
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
        result = await SlackConversationClient(http).post_approval_control_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            approval_url="https://azents.example/access/request-1",
            participant_label="Alice",
            participant_provider_user_id="U1",
        )

    assert result.status == "delivered"
    payload = json.loads(requests[0].content)
    assert payload["text"] == (
        "Approval is required before Alice (U1) can invoke the Agent."
    )
    assert "Alice" in payload["blocks"][0]["text"]["text"]
    assert "U1" in payload["blocks"][0]["text"]["text"]
    button = payload["blocks"][1]["elements"][0]
    assert button["type"] == "button"
    assert button["url"] == "https://azents.example/access/request-1"


async def test_channel_action_rate_limit_is_terminal_failed_without_retry() -> None:
    """Outbound rate limiting is one failed attempt rather than inbound retry."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"}, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="Reply",
        )

    assert calls == 1
    assert result.status == "failed"
    assert result.error_kind == "rate_limited"


async def test_channel_action_rejects_over_limit_markdown_without_request() -> None:
    """The delivery boundary rejects invalid provider text before mutation."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"ok": True, "ts": "1721600001.000100"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).post_message(
            bot_token="xoxb-secret",
            tenant_id="T1",
            channel_id="C1",
            thread_ts="1721600000.000100",
            markdown_text="x" * 12_001,
        )

    assert calls == 0
    assert result.status == "failed"
    assert result.error_kind == "provider_payload_invalid"
