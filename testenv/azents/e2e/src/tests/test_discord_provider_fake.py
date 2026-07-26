"""Deterministic Discord provider fake contract tests."""

import json
import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from testcontainers.core.container import DockerContainer
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as websocket_connect

from support.discord_provider_fake import (
    STATE,
    DiscordHTTPHandler,
    DiscordWebSocketHandler,
    ThreadingSocketServer,
)

_DISCORD_VERIFY_KEY = "233988c4fcf6ffd4dcf0590950d79671de856cfa36f65c16a2be13b1613875f0"


class _SignedInteractionHandler(BaseHTTPRequestHandler):
    """Verify the fake's real Ed25519 interaction signature in memory."""

    received_bodies: list[bytes] = []

    def do_POST(self) -> None:
        """Verify the exact timestamp-prefixed request body and acknowledge it."""
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        signature = bytes.fromhex(self.headers["X-Signature-Ed25519"])
        timestamp = self.headers["X-Signature-Timestamp"].encode()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_DISCORD_VERIFY_KEY)).verify(
            signature, timestamp + body
        )
        self.received_bodies.append(body)
        response = b'{"type":1}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        """Suppress test callback logs because they include request paths."""
        del format, args


@pytest.fixture
def discord_fake_urls() -> Generator[tuple[str, str], None, None]:
    """Run isolated fake HTTP and Gateway endpoints with fresh global state."""
    STATE.reset()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), DiscordHTTPHandler)
    websocket_server = ThreadingSocketServer(
        ("127.0.0.1", 0),
        DiscordWebSocketHandler,
    )
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    websocket_thread = threading.Thread(
        target=websocket_server.serve_forever,
        daemon=True,
    )
    http_thread.start()
    websocket_thread.start()
    try:
        http_host, http_port = http_server.server_address
        websocket_host, websocket_port = websocket_server.server_address
        yield (
            f"http://{http_host}:{http_port}",
            f"ws://{websocket_host}:{websocket_port}",
        )
    finally:
        http_server.shutdown()
        http_server.server_close()
        websocket_server.shutdown()
        websocket_server.server_close()
        http_thread.join(timeout=5)
        websocket_thread.join(timeout=5)


def test_discord_fake_redacts_rest_secrets_and_visible_provider_bodies(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Capture only provider operation identifiers and outcomes."""
    discord_fake_url, _ = discord_fake_urls
    requests.patch(
        f"{discord_fake_url}/api/v10/applications/100000000000000001",
        headers={"Authorization": "Bot discord-private-token"},
        json={"interactions_endpoint_url": "https://private.example/opaque-selector"},
        timeout=5,
    ).raise_for_status()
    created = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
        headers={"Authorization": "Bot discord-private-token"},
        json={
            "content": "Private Discord message body",
            "nonce": "nonce-private",
            "enforce_nonce": True,
        },
        timeout=5,
    ).json()
    duplicate = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
        json={
            "content": "Different private body",
            "nonce": "nonce-private",
            "enforce_nonce": True,
        },
        timeout=5,
    ).json()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    rendered = str(evidence)
    assert created["id"] == duplicate["id"]
    assert evidence["interaction_configurations"] == [
        {"application_id": "100000000000000001"}
    ]
    assert evidence["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "message_id": created["id"],
            "outcome": "created",
        },
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "message_id": created["id"],
            "outcome": "duplicate",
        },
    ]
    assert "discord-private-token" not in rendered
    assert "Private Discord message body" not in rendered
    assert "Different private body" not in rendered
    assert "private.example" not in rendered


def test_discord_fake_serves_gateway_identify_ready_dispatch_and_heartbeat(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Exercise the fake's minimal real Gateway protocol boundary."""
    discord_fake_url, websocket_url = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "gateway_dispatches": [
                {
                    "sequence": 2,
                    "event_type": "MESSAGE_CREATE",
                    "payload": {
                        "id": "500000000000000001",
                        "content": "Private gateway content",
                    },
                }
            ]
        },
        timeout=5,
    ).raise_for_status()
    with websocket_connect(websocket_url, open_timeout=5) as connection:
        hello = json.loads(connection.recv())
        assert hello == {"op": 10, "d": {"heartbeat_interval": 500}}
        connection.send(
            json.dumps(
                {
                    "op": 2,
                    "d": {
                        "token": "discord-private-token",
                        "intents": 0,
                        "properties": {},
                    },
                }
            )
        )
        ready = json.loads(connection.recv())
        dispatch = json.loads(connection.recv())
        connection.send(json.dumps({"op": 1, "d": 2}))
        acknowledgement = json.loads(connection.recv())

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    rendered = str(evidence)
    assert ready["t"] == "READY"
    assert dispatch["t"] == "MESSAGE_CREATE"
    assert acknowledgement == {"op": 11, "d": None}
    assert evidence["gateway"] == {
        "connections": 1,
        "initial_opcodes": [2],
        "heartbeats": [2],
        "dispatches": [{"event_type": "MESSAGE_CREATE", "sequence": 2}],
        "terminal_events": [],
    }
    assert "discord-private-token" not in rendered
    assert "Private gateway content" not in rendered


def test_discord_fake_controls_gateway_reconnect_and_resume(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Request reconnect, then accept a Resume on the next Gateway connection."""
    discord_fake_url, websocket_url = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"gateway_scenarios": ["reconnect", "open"]},
        timeout=5,
    ).raise_for_status()

    with websocket_connect(websocket_url, open_timeout=5) as connection:
        assert json.loads(connection.recv())["op"] == 10
        connection.send(json.dumps({"op": 2, "d": {"token": "private"}}))
        assert json.loads(connection.recv())["t"] == "READY"
        assert json.loads(connection.recv()) == {"op": 7, "d": None}

    with websocket_connect(websocket_url, open_timeout=5) as connection:
        assert json.loads(connection.recv())["op"] == 10
        connection.send(
            json.dumps(
                {
                    "op": 6,
                    "d": {
                        "token": "private",
                        "session_id": "discord-e2e-session",
                        "seq": 1,
                    },
                }
            )
        )
        assert json.loads(connection.recv())["t"] == "RESUMED"
        connection.send(json.dumps({"op": 1, "d": 1}))
        assert json.loads(connection.recv()) == {"op": 11, "d": None}

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["gateway"] == {
        "connections": 2,
        "initial_opcodes": [2, 6],
        "heartbeats": [1],
        "dispatches": [],
        "terminal_events": ["reconnect"],
    }


def test_discord_fake_controls_invalid_sessions_and_intents_close(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose invalid-session and intents-disallowed outcomes without payload leaks."""
    discord_fake_url, websocket_url = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "gateway_scenarios": [
                "invalid_session_resumable",
                "invalid_session_fresh",
                "close_4014",
            ]
        },
        timeout=5,
    ).raise_for_status()

    for expected_resumable in (True, False):
        with websocket_connect(websocket_url, open_timeout=5) as connection:
            assert json.loads(connection.recv())["op"] == 10
            connection.send(json.dumps({"op": 2, "d": {"token": "private"}}))
            assert json.loads(connection.recv())["t"] == "READY"
            assert json.loads(connection.recv()) == {"op": 9, "d": expected_resumable}

    with websocket_connect(websocket_url, open_timeout=5) as connection:
        assert json.loads(connection.recv())["op"] == 10
        connection.send(json.dumps({"op": 2, "d": {"token": "private"}}))
        assert json.loads(connection.recv())["t"] == "READY"
        with pytest.raises(ConnectionClosed) as error:
            connection.recv()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert error.value.rcvd is not None
    assert error.value.rcvd.code == 4014
    assert evidence["gateway"]["terminal_events"] == [
        "invalid_session_resumable",
        "invalid_session_fresh",
        "close_4014",
    ]
    assert "private" not in str(evidence)


def test_discord_fake_controls_rest_rate_limit_rejection_and_ambiguous_write(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Return controlled provider outcomes while retaining only safe evidence."""
    discord_fake_url, _ = discord_fake_urls
    message_url = f"{discord_fake_url}/api/v10/channels/400000000000000001/messages"

    for scenario, expected_status in (
        ("rate_limited", 429),
        ("rejected", 400),
        ("ambiguous", 503),
    ):
        requests.post(
            f"{discord_fake_url}/__testenv/configure",
            json={"api_scenarios": {"create_message": scenario}},
            timeout=5,
        ).raise_for_status()
        response = requests.post(
            message_url,
            json={
                "content": "Private controlled outcome body",
                "nonce": f"nonce-{scenario}",
                "enforce_nonce": True,
            },
            timeout=5,
        )
        assert response.status_code == expected_status
        if scenario == "rate_limited":
            assert response.headers["Retry-After"] == "1"

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["request_counts"] == {"create_message": 1}
    assert evidence["deliveries"][0]["outcome"] == "created"
    assert "Private controlled outcome body" not in str(evidence)


def test_discord_fake_relays_a_real_signed_interaction_without_body_evidence(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Sign the exact relay body while preserving only interaction metadata."""
    discord_fake_url, _ = discord_fake_urls
    _SignedInteractionHandler.received_bodies = []
    callback_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _SignedInteractionHandler,
    )
    callback_thread = threading.Thread(
        target=callback_server.serve_forever,
        daemon=True,
    )
    callback_thread.start()
    try:
        host, port = callback_server.server_address
        requests.patch(
            f"{discord_fake_url}/api/v10/applications/100000000000000001",
            json={"interactions_endpoint_url": f"http://{host}:{port}/callback"},
            timeout=5,
        ).raise_for_status()
        response = requests.post(
            f"{discord_fake_url}/__testenv/interactions",
            json={
                "id": "700000000000000001",
                "type": 1,
                "application_id": "100000000000000001",
            },
            timeout=5,
        )
        response.raise_for_status()
    finally:
        callback_server.shutdown()
        callback_server.server_close()
        callback_thread.join(timeout=5)

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    rendered = str(evidence)
    assert response.json() == {"status": 200, "response_type": 1}
    assert _SignedInteractionHandler.received_bodies
    assert evidence["interactions"] == [
        {
            "interaction_id": "700000000000000001",
            "interaction_type": 1,
            "response_status": 200,
        }
    ]
    assert "/callback" not in rendered


def test_discord_fake_records_multipart_file_sizes_without_file_bodies(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose bounded file evidence while discarding filename and content."""
    discord_fake_url, _ = discord_fake_urls
    private_file_body = b"private-discord-file-content"
    response = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
        data={"payload_json": '{"content":"Private visible content"}'},
        files={
            "files[0]": (
                "private-report.csv",
                private_file_body,
                "text/csv",
            )
        },
        timeout=5,
    )
    response.raise_for_status()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    rendered = str(evidence)
    assert evidence["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "message_id": response.json()["id"],
            "outcome": "created",
            "file_count": 1,
            "file_bytes": len(private_file_body),
        }
    ]
    assert "Private visible content" not in rendered
    assert "private-report.csv" not in rendered
    assert "private-discord-file-content" not in rendered


def test_discord_fake_container_uses_the_azents_server_image(
    discord_provider_fake_container: DockerContainer,
    discord_provider_fake_url: str,
) -> None:
    """Start the fake in the same Python image used by Azents E2E processes."""
    del discord_provider_fake_container
    response = requests.get(f"{discord_provider_fake_url}/health", timeout=5)
    application = requests.get(
        f"{discord_provider_fake_url}/api/v10/oauth2/applications/@me",
        timeout=5,
    )

    assert response.json() == {"status": "ok"}
    assert application.json()["verify_key"] == _DISCORD_VERIFY_KEY
