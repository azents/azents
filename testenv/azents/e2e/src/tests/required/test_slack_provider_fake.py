"""Deterministic Slack provider fake contract tests."""

import base64
import hashlib
import json
import threading
import time
from collections.abc import Generator
from http.server import ThreadingHTTPServer
from typing import cast

import pytest
import requests
from websockets.sync.client import connect as websocket_connect

from support.slack_provider_fake import (
    FakeState,
    SlackHTTPHandler,
    SlackWebSocketHandler,
    ThreadingSocketServer,
)


@pytest.fixture
def slack_fake_url() -> Generator[str, None, None]:
    """Run an isolated HTTP fake with fresh state."""

    class IsolatedHandler(SlackHTTPHandler):
        state = FakeState()

    server = ThreadingHTTPServer(("127.0.0.1", 0), IsolatedHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = server.server_address[0]
        port = server.server_address[1]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_slack_fake_records_block_kit_approval_links_as_sanitized_evidence(
    slack_fake_url: str,
) -> None:
    """Recognize Block Kit approval buttons without retaining message content."""
    requests.post(
        f"{slack_fake_url}/api/auth.test",
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    ).raise_for_status()
    requests.post(
        f"{slack_fake_url}/api/chat.postMessage",
        headers={"Authorization": "Bearer xoxb-private-token"},
        json={
            "channel": "C-E2E",
            "thread_ts": "1721600000.000100",
            "text": (
                "Approval is required before this participant can invoke the Agent."
            ),
            "blocks": [
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Review access",
                            },
                            "url": (
                                "https://azents.example/external-channel/access/"
                                "request-1"
                            ),
                        }
                    ],
                }
            ],
        },
        timeout=5,
    ).raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert evidence["request_counts"] == {
        "auth.test": 1,
        "chat.postMessage": 1,
    }
    assert evidence["deliveries"][0]["approval_request_id"] == "request-1"
    assert "xoxb-private-token" not in rendered
    assert "Approval is required" not in rendered


def test_slack_fake_controls_membership_history_and_delivery_failure(
    slack_fake_url: str,
) -> None:
    """Configure deterministic provider states without external credentials."""
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "membership_scenario": "slack_connect",
            "history_scenario": "rate_limited",
            "delivery_scenarios": {"chat.update": "revoked"},
        },
        timeout=5,
    ).raise_for_status()

    membership = requests.get(
        f"{slack_fake_url}/api/conversations.info",
        params={"channel": "C-E2E"},
        timeout=5,
    ).json()
    history = requests.get(
        f"{slack_fake_url}/api/conversations.replies",
        params={"channel": "C-E2E", "ts": "1721600000.000100"},
        timeout=5,
    )
    update = requests.post(
        f"{slack_fake_url}/api/chat.update",
        json={
            "channel": "C-E2E",
            "ts": "1721600000.000100",
            "text": "content excluded from evidence",
        },
        timeout=5,
    ).json()

    assert membership["channel"]["is_ext_shared"] is True
    assert membership["channel"]["name"] == "e2e"
    assert history.status_code == 429
    assert history.headers["Retry-After"] == "1"
    assert update == {"ok": False, "error": "token_revoked"}


def test_slack_fake_records_sanitized_channel_and_thread_presence(
    slack_fake_url: str,
) -> None:
    """Expose native Work status evidence without retaining status text or users."""
    channel = requests.post(
        f"{slack_fake_url}/api/assistant.threads.setStatus",
        json={
            "channel_id": "C-E2E",
            "thread_ts": "1721600000.000100",
            "status": "Private work title",
            "username": "Private Agent",
        },
        timeout=5,
    )
    thread = requests.post(
        f"{slack_fake_url}/api/agents.sessions.setStatus",
        json={
            "channel_id": "C-E2E",
            "thread_ts": "1721600000.000200",
            "status": "processing",
            "initiator_user_id": "U-PRIVATE",
        },
        timeout=5,
    )

    channel.raise_for_status()
    thread.raise_for_status()
    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert evidence["presence"] == [
        {
            "operation": "assistant.threads.setStatus",
            "channel": "C-E2E",
            "thread_ts": "1721600000.000100",
            "desired_state": "processing",
            "has_initiator": False,
            "outcome": "delivered",
        },
        {
            "operation": "agents.sessions.setStatus",
            "channel": "C-E2E",
            "thread_ts": "1721600000.000200",
            "desired_state": "processing",
            "has_initiator": True,
            "outcome": "delivered",
        },
    ]
    assert "Private work title" not in rendered
    assert "Private Agent" not in rendered
    assert "U-PRIVATE" not in rendered


def test_slack_fake_sequences_retry_after_and_blocks_exact_history(
    slack_fake_url: str,
) -> None:
    """Sequence bounded rate limits and release one exact provider operation."""
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "history_scenario_sequence": ["rate_limited", "rate_limited", "ok"],
            "history_retry_after_seconds": [3, 7],
            "history_pages": [[]],
        },
        timeout=5,
    ).raise_for_status()

    first = requests.get(
        f"{slack_fake_url}/api/conversations.history",
        params={"channel": "C-E2E"},
        timeout=5,
    )
    second = requests.get(
        f"{slack_fake_url}/api/conversations.history",
        params={"channel": "C-E2E"},
        timeout=5,
    )
    third = requests.get(
        f"{slack_fake_url}/api/conversations.history",
        params={"channel": "C-E2E"},
        timeout=5,
    )

    assert first.status_code == 429
    assert first.headers["Retry-After"] == "3"
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "7"
    assert third.status_code == 200

    requests.post(
        f"{slack_fake_url}/__testenv/barrier",
        json={"operation": "conversations.replies", "occurrence": 1},
        timeout=5,
    ).raise_for_status()
    responses: list[requests.Response] = []

    def request_history() -> None:
        responses.append(
            requests.get(
                f"{slack_fake_url}/api/conversations.replies",
                params={"channel": "C-E2E", "ts": "1721600000.000100"},
                timeout=10,
            )
        )

    thread = threading.Thread(target=request_history)
    thread.start()
    for _ in range(50):
        barrier = requests.get(
            f"{slack_fake_url}/__testenv/barrier",
            timeout=5,
        ).json()
        if barrier["reached"]:
            break
        time.sleep(0.02)
    else:
        pytest.fail("Slack history barrier was not reached.")
    assert responses == []
    assert barrier == {
        "operation": "conversations.replies",
        "occurrence": 1,
        "request_count": 1,
        "reached": True,
        "released": False,
    }
    requests.post(
        f"{slack_fake_url}/__testenv/barrier/release",
        timeout=5,
    ).raise_for_status()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert responses[0].status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"history_scenario_sequence": []},
        {"history_scenario_sequence": ["ok"] * 11},
        {"history_retry_after_seconds": []},
        {"history_retry_after_seconds": [1] * 11},
        {"history_retry_after_seconds": [0]},
        {"history_retry_after_seconds": [301]},
    ],
)
def test_slack_fake_rejects_unbounded_history_sequences(
    payload: dict[str, object],
) -> None:
    """Reject fixture sequences that exceed deterministic test bounds."""
    with pytest.raises(ValueError):
        FakeState().configure(payload)


def test_slack_fake_serves_bounded_parent_and_thread_history_pages(
    slack_fake_url: str,
) -> None:
    """Serve the same bounded history fixture through both Slack range APIs."""
    messages = [
        {
            "user": "U-EXTERNAL",
            "ts": "1721600000.000100",
            "text": "Private provider history",
        }
    ]
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={"history_pages": [messages]},
        timeout=5,
    ).raise_for_status()

    parent = requests.get(
        f"{slack_fake_url}/api/conversations.history",
        params={
            "channel": "C-E2E",
            "latest": "1721600000.000100",
            "inclusive": "true",
            "limit": "100",
        },
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    )
    thread = requests.get(
        f"{slack_fake_url}/api/conversations.replies",
        params={
            "channel": "C-E2E",
            "ts": "1721600000.000100",
            "inclusive": "true",
            "limit": "100",
        },
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    )

    assert parent.json()["messages"] == messages
    assert thread.json()["messages"] == messages
    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert evidence["request_counts"] == {
        "conversations.history": 1,
        "conversations.replies": 1,
    }
    assert "xoxb-private-token" not in rendered
    assert "Private provider history" not in rendered


def test_slack_fake_configures_installation_identity_and_captures_selector_view(
    slack_fake_url: str,
) -> None:
    """Represent distinct Apps and retain only opaque selector state."""
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "provider_app_id": "A-MULTI",
            "provider_team_id": "T-MULTI",
            "provider_bot_user_id": "U-BOT-MULTI",
        },
        timeout=5,
    ).raise_for_status()

    auth = requests.post(
        f"{slack_fake_url}/api/auth.test",
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    ).json()
    bot = requests.get(
        f"{slack_fake_url}/api/bots.info",
        params={"bot": "B-E2E"},
        timeout=5,
    ).json()
    opened = requests.post(
        f"{slack_fake_url}/api/views.open",
        json={
            "trigger_id": "trigger-secret",
            "view": {
                "type": "modal",
                "callback_id": "azents_agent_selector",
                "private_metadata": "signed-opaque-metadata",
                "title": {"type": "plain_text", "text": "Select an Agent"},
                "blocks": [
                    {
                        "type": "input",
                        "element": {
                            "type": "static_select",
                            "options": [
                                {
                                    "text": {
                                        "type": "plain_text",
                                        "text": "Private Agent Name",
                                    },
                                    "value": "route-1",
                                }
                            ],
                        },
                    }
                ],
                "submit": {"type": "plain_text", "text": "Select"},
            },
        },
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    )
    opened.raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert auth["team_id"] == "T-MULTI"
    assert auth["user_id"] == "U-BOT-MULTI"
    assert bot["bot"]["app_id"] == "A-MULTI"
    assert evidence["views"] == [
        {
            "operation": "views.open",
            "control_scope": "selector",
            "route_count": 1,
            "has_submit": True,
            "outcome": "delivered",
        }
    ]
    transient = requests.get(
        f"{slack_fake_url}/__testenv/transient-view",
        params={"scope": "selector"},
        timeout=5,
    ).json()
    assert transient["view_id"] == "V-E2E-1"
    assert transient["view_hash"] == "hash-1"
    assert transient["private_metadata"] == "signed-opaque-metadata"
    assert transient["route_ids"] == ["route-1"]
    assert "trigger-secret" not in rendered
    assert "xoxb-private-token" not in rendered
    assert "Private Agent Name" not in rendered
    assert "signed-opaque-metadata" not in rendered


def test_slack_fake_captures_selector_control_without_visible_copy(
    slack_fake_url: str,
) -> None:
    """Expose only the opaque admission needed to drive the next callback."""
    requests.post(
        f"{slack_fake_url}/api/chat.postMessage",
        json={
            "channel": "C-E2E",
            "thread_ts": "1721600000.000100",
            "text": "Private selector instructions",
            "blocks": [
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": "Private button label",
                            },
                            "action_id": "azents_agent_selector_open",
                            "value": "admission-1",
                        }
                    ],
                }
            ],
        },
        timeout=5,
    ).raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert evidence["deliveries"][0]["action_ids"] == ["azents_agent_selector_open"]
    assert evidence["deliveries"][0]["selector_admission_id"] == "admission-1"
    assert "Private selector instructions" not in rendered
    assert "Private button label" not in rendered


def test_slack_fake_captures_plan_after_agent_identity_block(
    slack_fake_url: str,
) -> None:
    """Retain the native Plan when current Agent attribution precedes it."""
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Incident Agent*",
            },
        },
        {
            "type": "plan",
            "title": "Investigating…",
            "tasks": [
                {
                    "task_id": "inspect",
                    "title": "Inspect logs",
                    "status": "in_progress",
                }
            ],
        },
    ]
    requests.post(
        f"{slack_fake_url}/api/chat.update",
        json={
            "channel": "C-E2E",
            "ts": "1721600000.000100",
            "text": "Incident Agent\nInvestigating…",
            "blocks": blocks,
        },
        timeout=5,
    ).raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    assert evidence["deliveries"] == [
        {
            "operation": "chat.update",
            "channel": "C-E2E",
            "thread_ts": None,
            "message_ts": "1721600000.000100",
            "outcome": "delivered",
            "approval_request_id": None,
            "text": "Incident Agent\nInvestigating…",
            "blocks": blocks,
        }
    ]


def test_slack_fake_serves_private_file_without_leaking_content_evidence(
    slack_fake_url: str,
) -> None:
    """Expose selected file bytes while retaining only sanitized request metadata."""
    content = b"private input body"
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "files": [
                {
                    "id": "F-IN-1",
                    "name": "input-private.txt",
                    "title": "Private input",
                    "mimetype": "text/plain",
                    "mode": "hosted",
                    "is_external": False,
                    "content_base64": base64.b64encode(content).decode(),
                }
            ]
        },
        timeout=5,
    ).raise_for_status()

    info = requests.get(
        f"{slack_fake_url}/api/files.info",
        params={"file": "F-IN-1"},
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    ).json()
    download = requests.get(
        info["file"]["url_private_download"],
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    )
    download.raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert info["file"]["size"] == len(content)
    assert download.content == content
    assert evidence["request_counts"] == {
        "files.info": 1,
        "file.download": 1,
    }
    assert "xoxb-private-token" not in rendered
    assert "private input body" not in rendered
    assert "input-private.txt" not in rendered
    assert "url_private_download" not in rendered


def test_slack_fake_collects_ordered_external_upload_evidence(
    slack_fake_url: str,
) -> None:
    """Acquire, stream, and complete ordered files without retaining their bodies."""
    first_target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        json={"filename": "first-private.txt", "length": 3},
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    ).json()
    second_target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        json={"filename": "second-private.txt", "length": 4},
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    ).json()
    requests.post(
        first_target["upload_url"],
        data=b"abc",
        headers={"Content-Type": "application/octet-stream"},
        timeout=5,
    ).raise_for_status()
    requests.post(
        second_target["upload_url"],
        data=b"defg",
        headers={"Content-Type": "application/octet-stream"},
        timeout=5,
    ).raise_for_status()
    completion = requests.post(
        f"{slack_fake_url}/api/files.completeUploadExternal",
        json={
            "files": [
                {"id": first_target["file_id"], "title": "first-private.txt"},
                {"id": second_target["file_id"], "title": "second-private.txt"},
            ],
            "channel_id": "C-E2E",
            "thread_ts": "1721600000.000100",
            "initial_comment": "Private completion text",
        },
        headers={"Authorization": "Bearer xoxb-private-token"},
        timeout=5,
    )
    completion.raise_for_status()

    evidence = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    rendered = str(evidence)
    assert completion.json()["ok"] is True
    assert evidence["request_counts"] == {
        "files.getUploadURLExternal": 2,
        "file.upload": 2,
        "files.completeUploadExternal": 1,
    }
    assert evidence["deliveries"] == [
        {
            "operation": "files.completeUploadExternal",
            "channel": "C-E2E",
            "thread_ts": "1721600000.000100",
            "file_ids": [
                first_target["file_id"],
                second_target["file_id"],
            ],
            "file_count": 2,
            "total_bytes": 7,
            "has_initial_comment": True,
            "outcome": "delivered",
        }
    ]
    uploads = [
        request
        for request in evidence["requests"]
        if request["operation"] == "file.upload"
    ]
    assert uploads == [
        {
            "operation": "file.upload",
            "method": "POST",
            "file": first_target["file_id"],
            "content_length": 3,
            "received_length": 3,
            "content_sha256": hashlib.sha256(b"abc").hexdigest(),
        },
        {
            "operation": "file.upload",
            "method": "POST",
            "file": second_target["file_id"],
            "content_length": 4,
            "received_length": 4,
            "content_sha256": hashlib.sha256(b"defg").hexdigest(),
        },
    ]
    assert "xoxb-private-token" not in rendered
    assert "first-private.txt" not in rendered
    assert "Private completion text" not in rendered
    assert "abcdefg" not in rendered


def test_slack_fake_controls_file_scope_and_size_rejection(
    slack_fake_url: str,
) -> None:
    """Expose optional scopes and deterministic upload rejection scenarios."""
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "granted_scopes": [
                "app_mentions:read",
                "channels:history",
                "channels:read",
                "groups:history",
                "groups:read",
                "chat:write",
                "users:read",
                "files:read",
            ],
            "file_scenarios": {"file.upload": "size_mismatch"},
        },
        timeout=5,
    ).raise_for_status()

    auth = requests.post(
        f"{slack_fake_url}/api/auth.test",
        timeout=5,
    )
    target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        json={"filename": "size.txt", "length": 4},
        timeout=5,
    ).json()
    upload = requests.post(
        target["upload_url"],
        data=b"abc",
        timeout=5,
    )

    assert "files:read" in auth.headers["X-OAuth-Scopes"]
    assert "files:write" not in auth.headers["X-OAuth-Scopes"]
    assert upload.status_code == 400


def test_slack_fake_accepts_url_encoded_file_upload_requests(
    slack_fake_url: str,
) -> None:
    """Match Slack's form-encoded external upload API request format."""
    target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        data={"filename": "encoded.txt", "length": "3"},
        timeout=5,
    ).json()
    assert target["ok"] is True

    upload = requests.post(
        target["upload_url"],
        data=b"abc",
        timeout=5,
    )
    assert upload.status_code == 200

    completion = requests.post(
        f"{slack_fake_url}/api/files.completeUploadExternal",
        data={
            "files": json.dumps(
                [{"id": target["file_id"], "title": "encoded.txt"}],
                separators=(",", ":"),
            ),
            "channel_id": "C-E2E",
            "thread_ts": "1721600000.000001",
            "initial_comment": "Encoded upload",
        },
        timeout=5,
    ).json()
    assert completion["ok"] is True
    state = requests.get(
        f"{slack_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    assert state["deliveries"] == [
        {
            "operation": "files.completeUploadExternal",
            "channel": "C-E2E",
            "thread_ts": "1721600000.000001",
            "file_ids": [target["file_id"]],
            "file_count": 1,
            "total_bytes": 3,
            "has_initial_comment": True,
            "outcome": "delivered",
        }
    ]


def test_slack_fake_accepts_query_encoded_upload_target_requests(
    slack_fake_url: str,
) -> None:
    """Match slack_sdk's query-encoded upload target request format."""
    target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        params={"filename": "query.txt", "length": "3"},
        timeout=5,
    ).json()

    assert target["ok"] is True


@pytest.mark.parametrize(
    ("operation", "scenario", "expected_status", "expected_error"),
    [
        ("files.info", "missing", 200, "file_not_found"),
        ("files.info", "rejected", 200, "file_not_found"),
        ("files.info", "missing_scope", 200, "missing_scope"),
        ("file.download", "missing", 404, "file_not_found"),
        ("file.download", "rejected", 400, "file_not_found"),
        ("file.download", "missing_scope", 403, "missing_scope"),
    ],
)
def test_slack_fake_controls_inbound_file_failures(
    slack_fake_url: str,
    operation: str,
    scenario: str,
    expected_status: int,
    expected_error: str,
) -> None:
    """Return deterministic missing, rejected, and scope failures by phase."""
    content = b"private input body"
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "file_scenarios": {operation: scenario},
            "files": [
                {
                    "id": "F-IN-FAILURE",
                    "name": "private-input.txt",
                    "mimetype": "text/plain",
                    "mode": "hosted",
                    "is_external": False,
                    "content_base64": base64.b64encode(content).decode(),
                }
            ],
        },
        timeout=5,
    ).raise_for_status()

    if operation == "files.info":
        response = requests.get(
            f"{slack_fake_url}/api/files.info",
            params={"file": "F-IN-FAILURE"},
            timeout=5,
        )
    else:
        response = requests.get(
            f"{slack_fake_url}/files/F-IN-FAILURE",
            timeout=5,
        )

    assert response.status_code == expected_status
    assert response.json()["error"] == expected_error


def test_slack_fake_can_make_completion_ambiguous(
    slack_fake_url: str,
) -> None:
    """Close the completion connection after successful temporary upload."""
    requests.post(
        f"{slack_fake_url}/__testenv/configure",
        json={
            "file_scenarios": {
                "files.completeUploadExternal": "ambiguous",
            }
        },
        timeout=5,
    ).raise_for_status()
    target = requests.post(
        f"{slack_fake_url}/api/files.getUploadURLExternal",
        json={"filename": "ambiguous.txt", "length": 3},
        timeout=5,
    ).json()
    requests.post(
        target["upload_url"],
        data=b"abc",
        timeout=5,
    ).raise_for_status()

    with pytest.raises(requests.exceptions.ConnectionError):
        requests.post(
            f"{slack_fake_url}/api/files.completeUploadExternal",
            json={
                "files": [{"id": target["file_id"], "title": "ambiguous.txt"}],
                "channel_id": "C-E2E",
                "thread_ts": "1721600000.000100",
                "initial_comment": "Ambiguous completion",
            },
            timeout=5,
        )


def test_slack_fake_websocket_captures_acknowledgement_after_envelope() -> None:
    """Retain a delayed ACK without imposing an artificial provider timeout."""
    state = FakeState()
    state.configure(
        {
            "socket_sessions": [
                {
                    "envelopes": [
                        {
                            "envelope_id": "Env-1",
                            "type": "events_api",
                            "payload": {
                                "type": "event_callback",
                                "event_id": "Ev-1",
                                "api_app_id": "A-E2E",
                                "team_id": "T-E2E",
                                "event": {
                                    "type": "app_mention",
                                    "channel": "C-E2E",
                                    "user": "U-E2E",
                                    "text": "content excluded from evidence",
                                    "ts": "1721600000.000100",
                                },
                            },
                        }
                    ],
                    "disconnect_reason": "link_disabled",
                }
            ],
        }
    )

    class IsolatedWebSocketHandler(SlackWebSocketHandler):
        socket_timeout_seconds = 0.01

    IsolatedWebSocketHandler.state = state
    server = ThreadingSocketServer(("127.0.0.1", 0), IsolatedWebSocketHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host = server.server_address[0]
    port = server.server_address[1]
    try:
        with websocket_connect(f"ws://{host}:{port}/socket") as connection:
            hello = connection.recv()
            envelope = connection.recv()
            assert isinstance(hello, str)
            assert isinstance(envelope, str)
            assert '"type": "hello"' in hello
            assert '"envelope_id":"Env-1"' in envelope
            pong_received = connection.ping(b"sdk-ping-pong:test")
            connection.send('{"envelope_id":"Env-1"}')
            assert pong_received.wait(timeout=5)
            disconnect = connection.recv()
            assert isinstance(disconnect, str)
            assert "link_disabled" in disconnect
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    evidence = state.evidence()
    socket_evidence = evidence["socket"]
    assert isinstance(socket_evidence, dict)
    socket_evidence_object = cast(dict[str, object], socket_evidence)
    assert socket_evidence_object["connections"] == 1
    assert socket_evidence_object["envelope_ids"] == ["Env-1"]
    assert socket_evidence_object["acknowledgements"] == ["Env-1"]
    assert "content excluded from evidence" not in str(evidence)
