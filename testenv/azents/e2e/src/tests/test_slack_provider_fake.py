"""Deterministic Slack provider fake contract tests."""

import base64
import threading
from collections.abc import Generator
from http.server import ThreadingHTTPServer

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
        host, port = server.server_address
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
    """Serve a real WebSocket handshake and retain only sanitized ACK evidence."""
    state = FakeState()
    state.configure(
        {
            "socket_envelopes": [
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
            "socket_disconnect_reason": "link_disabled",
        }
    )

    class IsolatedWebSocketHandler(SlackWebSocketHandler):
        pass

    IsolatedWebSocketHandler.state = state
    server = ThreadingSocketServer(("127.0.0.1", 0), IsolatedWebSocketHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        with websocket_connect(f"ws://{host}:{port}/socket") as connection:
            hello = connection.recv()
            envelope = connection.recv()
            assert isinstance(hello, str)
            assert isinstance(envelope, str)
            assert '"type": "hello"' in hello
            assert '"envelope_id":"Env-1"' in envelope
            connection.send('{"envelope_id":"Env-1"}')
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
    assert socket_evidence["connections"] == 1
    assert socket_evidence["envelope_ids"] == ["Env-1"]
    assert socket_evidence["acknowledgements"] == ["Env-1"]
    assert "content excluded from evidence" not in str(evidence)
