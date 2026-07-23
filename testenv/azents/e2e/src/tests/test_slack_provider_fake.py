"""Deterministic Slack provider fake contract tests."""

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
