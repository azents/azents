"""Slack External Channel event normalization and API adapter tests."""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

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
    SlackInteractionView,
    SlackNormalizedMessage,
    SlackOutboundFile,
    SlackOutboundFileContentError,
    SlackProviderCredentialsInvalid,
    SlackProviderFileNotFound,
    SlackProviderFileTooLarge,
    SlackProviderPermissionDenied,
    SlackProviderRateLimited,
    SlackProviderTemporaryError,
    normalize_projected_slack_event,
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
        "blocks": {
            "block_count": 1,
            "block_types": ["section"],
            "truncated": False,
        }
    }


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
    assert projected[0]["supported"] is True
    assert projected[0]["unsupported_reason"] is None
    assert projected[1]["unsupported_reason"] == "external_file"
    assert projected[2]["unsupported_reason"] == "slack_connect_file"
    assert projected[3]["unsupported_reason"] == "sparse_file"
    assert projected[4]["unsupported_reason"] == "unsupported_mode"
    assert projected[5]["unsupported_reason"] == "invalid_size"
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
    assert page.messages[0].attachment_metadata is not None
    files = page.messages[0].attachment_metadata["files"]
    assert isinstance(files, list)
    assert files[0]["provider_file_id"] == "F1"
    assert files[0]["supported"] is True
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
        page = await SlackConversationClient(http).fetch_thread_page(
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
        info = await SlackConversationClient(http).fetch_file_download_info(
            bot_token="xoxb-secret",
            provider_file_id="F123",
        )

    assert info.metadata.provider_file_id == "F123"
    assert info.metadata.supported is True
    assert info.private_url == "https://files.slack.test/download/F123"
    assert requests[0].url.path == "/api/files.info"
    assert requests[0].url.params["file"] == "F123"
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
            await SlackConversationClient(http).fetch_file_download_info(
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
            await SlackConversationClient(http).fetch_file_download_info(
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
        client = SlackConversationClient(http)
        async with client.open_private_file_stream(
            bot_token="xoxb-secret",
            private_url="https://files.slack.test/private/F123",
            max_bytes=8,
            maximum_chunk_size=4,
        ) as stream:
            body = b"".join([chunk async for chunk in stream])
        with pytest.raises(SlackProviderFileTooLarge):
            async with client.open_private_file_stream(
                bot_token="xoxb-secret",
                private_url="https://files.slack.test/private/F123",
                max_bytes=7,
                maximum_chunk_size=4,
            ) as stream:
                async for _ in stream:
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
            async with SlackConversationClient(http).open_private_file_stream(
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
        result = await SlackConversationClient(http).post_approval_control_message(
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
        result = await SlackConversationClient(http).post_approval_control_message(
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
        client = SlackConversationClient(http)
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
    payload = json.loads(requests[0].content)
    if operation == "post":
        assert payload["markdown_text"] == "Reply"
        assert "text" not in payload
        assert "blocks" not in payload
    elif operation == "update":
        assert payload["parse"] == "none"
        assert payload["link_names"] is False


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
        result = await SlackConversationClient(http).open_interaction_view(
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
        result = await SlackConversationClient(http).update_interaction_view(
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
        SlackConversationClient._validate_interaction_view(view)  # pyright: ignore[reportPrivateUsage]  # Validate the provider payload boundary directly.


async def test_missing_update_target_is_reported_as_confirmed_deletion() -> None:
    """Slack message absence is recoverable rather than an ambiguous outcome."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "message_not_found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).update_message(
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
        result = await SlackConversationClient(http).update_message(
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
        result = await SlackConversationClient(http).post_approval_control_message(
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
        result = await SlackConversationClient(http).post_approval_control_message(
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
        result = await SlackConversationClient(http).post_message(
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
        result = await SlackConversationClient(http).post_message(
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
        result = await SlackConversationClient(http).post_message(
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
async def test_file_reply_does_not_start_after_logical_deadline() -> None:
    """A Runtime delivery deadline overrides the client's ordinary timeout."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("Slack must not receive an expired delivery request")

    async def content() -> AsyncIterator[bytes]:
        yield b"abc"

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await SlackConversationClient(http).post_file_message(
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
            deadline_at=datetime.now(UTC) - timedelta(seconds=1),
        )

    assert calls == 0
    assert result.status == "unknown"
    assert result.error_kind == "provider_ambiguous"


@pytest.mark.asyncio
async def test_file_reply_streams_in_order_and_completes_once() -> None:
    """Slack receives ordered known-length streams before one visible completion."""
    requests: list[tuple[str, str, dict[str, str], bytes]] = []
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
        result = await SlackConversationClient(http).post_file_message(
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
    assert [path for _, path, _, _ in requests] == [
        "/api/files.getUploadURLExternal",
        "/upload/1",
        "/api/files.getUploadURLExternal",
        "/upload/2",
        "/api/files.completeUploadExternal",
    ]
    assert requests[0][2]["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    first_acquisition = parse_qs(requests[0][3].decode(), strict_parsing=True)
    assert first_acquisition == {"filename": ["first.txt"], "length": ["3"]}
    assert requests[1][3] == b"abc"
    assert requests[1][2]["content-length"] == "3"
    assert "authorization" not in requests[1][2]
    assert requests[2][2]["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    second_acquisition = parse_qs(requests[2][3].decode(), strict_parsing=True)
    assert second_acquisition == {"filename": ["second.txt"], "length": ["4"]}
    assert requests[3][3] == b"1234"
    assert requests[3][2]["content-length"] == "4"
    assert requests[4][2]["content-type"].startswith(
        "application/x-www-form-urlencoded"
    )
    completion = parse_qs(requests[4][3].decode(), strict_parsing=True)
    assert completion == {
        "files": [
            json.dumps(
                [
                    {"id": "F1", "title": "first.txt"},
                    {"id": "F2", "title": "second.txt"},
                ],
                separators=(",", ":"),
            )
        ],
        "channel_id": ["C1"],
        "thread_ts": ["1721600000.000100"],
        "initial_comment": ["Attached reports"],
    }
    assert requests[4][2]["authorization"] == "Bearer xoxb-secret"


@pytest.mark.asyncio
async def test_file_reply_stops_without_completion_when_runtime_stream_fails() -> None:
    """A changed Runtime source never reaches Slack's publication boundary."""
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
        result = await SlackConversationClient(http).post_file_message(
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

    assert result.status == "failed"
    assert result.error_kind == "runtime_file_unavailable"
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
        result = await SlackConversationClient(http).post_file_message(
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
        result = await SlackConversationClient(http).post_file_message(
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
        result = await SlackConversationClient(http).post_file_message(
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
            result = await SlackConversationClient(http).post_file_message(
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
    assert record_extra["slack_api_path"] == "/api/files.completeUploadExternal"
    assert record_extra["slack_api_method"] == "POST"
    assert record_extra["slack_http_status_code"] == 200
    assert record_extra["slack_request_id"] == "REQ1"
    assert record_extra["slack_request_content_type"].startswith(
        "application/x-www-form-urlencoded"
    )
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
