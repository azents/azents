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


class _SelectorInteractionHandler(_SignedInteractionHandler):
    """Return a selector-shaped response while keeping IDs request-local."""

    def do_POST(self) -> None:
        """Verify the signed request and return bounded selector components."""
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        signature = bytes.fromhex(self.headers["X-Signature-Ed25519"])
        timestamp = self.headers["X-Signature-Timestamp"].encode()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_DISCORD_VERIFY_KEY)).verify(
            signature, timestamp + body
        )
        self.received_bodies.append(body)
        response = (
            b'{"type":4,"data":{"flags":64,"content":"Select an Agent.",'
            b'"components":[{"type":1,"components":[{"type":3,'
            b'"custom_id":"azents-selector:select:admission:0:signature"}]}]}}'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


class _SettingsInteractionHandler(_SignedInteractionHandler):
    """Return settings-shaped controls while keeping signed IDs request-local."""

    def do_POST(self) -> None:
        """Verify the signed request and return bounded settings components."""
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        signature = bytes.fromhex(self.headers["X-Signature-Ed25519"])
        timestamp = self.headers["X-Signature-Timestamp"].encode()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_DISCORD_VERIFY_KEY)).verify(
            signature, timestamp + body
        )
        self.received_bodies.append(body)
        response = (
            b'{"type":4,"data":{"flags":64,"content":"Choose a location.",'
            b'"components":[{"type":1,"components":[{"type":2,'
            b'"custom_id":"a:sc:claim:1:1:signature"}]}]}}'
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


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
        http_host = http_server.server_address[0]
        http_port = http_server.server_address[1]
        websocket_host = websocket_server.server_address[0]
        websocket_port = websocket_server.server_address[1]
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
        f"{discord_fake_url}/api/v10/applications/@me",
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


def test_discord_fake_reconciles_guild_commands_without_body_evidence(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Provide deterministic command CRUD while retaining only operation evidence."""
    discord_fake_url, _ = discord_fake_urls
    commands_url = (
        f"{discord_fake_url}/api/v10/applications/100000000000000001/"
        "guilds/200000000000000001/commands"
    )
    unrelated = requests.post(
        commands_url,
        json={
            "name": "Private unrelated command",
            "type": 2,
        },
        timeout=5,
    )
    unrelated.raise_for_status()
    settings = requests.post(
        commands_url,
        json={
            "name": "Private Azents settings command",
            "type": 2,
        },
        timeout=5,
    )
    settings.raise_for_status()
    assert unrelated.json()["id"] == "500000000000000001"
    assert settings.json()["id"] == "500000000000000002"
    message_action = requests.post(
        commands_url,
        json={
            "name": "Ask an Azents Agent",
            "type": 3,
        },
        timeout=5,
    )
    message_action.raise_for_status()
    assert message_action.json()["id"] == "500000000000000003"
    command_id = requests.get(
        f"{discord_fake_url}/__testenv/command-id",
        params={"role": "message_action"},
        timeout=5,
    )
    command_id.raise_for_status()
    assert command_id.json() == {"command_id": message_action.json()["id"]}

    listed = requests.get(commands_url, timeout=5)
    listed.raise_for_status()
    assert listed.json() == [
        unrelated.json(),
        settings.json(),
        message_action.json(),
    ]

    updated = requests.patch(
        f"{commands_url}/{settings.json()['id']}",
        json={
            "name": "Private updated settings command",
            "type": 2,
        },
        timeout=5,
    )
    updated.raise_for_status()
    assert updated.json()["id"] == settings.json()["id"]
    assert updated.json()["name"] == "Private updated settings command"

    deleted = requests.delete(
        f"{commands_url}/{settings.json()['id']}",
        timeout=5,
    )
    assert deleted.status_code == 204
    remaining = requests.get(commands_url, timeout=5)
    remaining.raise_for_status()
    assert remaining.json() == [unrelated.json(), message_action.json()]

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert [
        (request["method"], request["operation"]) for request in evidence["requests"]
    ] == [
        ("POST", "create_guild_command"),
        ("POST", "create_guild_command"),
        ("POST", "create_guild_command"),
        ("GET", "list_guild_commands"),
        ("PATCH", "update_guild_command"),
        ("DELETE", "delete_guild_command"),
        ("GET", "list_guild_commands"),
    ]
    rendered = str(evidence)
    assert "Private unrelated command" not in rendered
    assert "Private Azents settings command" not in rendered
    assert "Private updated settings command" not in rendered
    assert evidence["guild_commands"] == [
        {"role": "message_action", "type": 3},
        {"role": "unrelated", "type": 2},
    ]

    requests.post(f"{discord_fake_url}/__testenv/reset", timeout=5).raise_for_status()
    reset_commands = requests.get(commands_url, timeout=5)
    reset_commands.raise_for_status()
    assert reset_commands.json() == []


def test_discord_fake_configures_bounded_command_reconciliation_state(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Seed duplicate, stale, and unrelated commands without evidence leakage."""
    discord_fake_url, _ = discord_fake_urls
    configured_names = [
        "Ask an Azents Agent",
        "Ask an Azents Agent",
        "Azents settings",
        "Private customer command",
    ]
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "guild_commands": [
                {
                    "id": "500000000000000101",
                    "name": configured_names[0],
                    "type": 3,
                },
                {
                    "id": "500000000000000102",
                    "name": configured_names[1],
                    "type": 3,
                },
                {
                    "id": "500000000000000103",
                    "name": configured_names[2],
                    "type": 1,
                    "description": "Stale description.",
                },
                {
                    "id": "500000000000000104",
                    "name": configured_names[3],
                    "type": 2,
                },
            ]
        },
        timeout=5,
    ).raise_for_status()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["guild_commands"] == [
        {"role": "azents_settings", "type": 1},
        {"role": "message_action", "type": 3},
        {"role": "message_action", "type": 3},
        {"role": "unrelated", "type": 2},
    ]
    assert all(name not in str(evidence) for name in configured_names)


@pytest.mark.parametrize(
    ("handler", "scope", "expected_custom_id"),
    [
        (
            _SelectorInteractionHandler,
            "selector",
            "azents-selector:select:admission:0:signature",
        ),
        (
            _SettingsInteractionHandler,
            "settings",
            "a:sc:claim:1:1:signature",
        ),
    ],
)
def test_discord_fake_keeps_component_ids_outside_persistent_evidence(
    discord_fake_urls: tuple[str, str],
    handler: type[_SignedInteractionHandler],
    scope: str,
    expected_custom_id: str,
) -> None:
    """Keep selector and settings control IDs in transient handoff state only."""
    discord_fake_url, _ = discord_fake_urls
    callback = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    callback_thread = threading.Thread(target=callback.serve_forever, daemon=True)
    callback_thread.start()
    try:
        callback_host = callback.server_address[0]
        callback_port = callback.server_address[1]
        requests.patch(
            f"{discord_fake_url}/api/v10/applications/@me",
            json={
                "interactions_endpoint_url": (
                    f"http://{callback_host}:{callback_port}/interaction"
                )
            },
            timeout=5,
        ).raise_for_status()
        delivered = requests.post(
            f"{discord_fake_url}/__testenv/interactions",
            json={"id": "700000000000000099", "type": 2},
            timeout=5,
        )
        delivered.raise_for_status()
        assert delivered.json() == {"status": 200, "response_type": 4}
        transient = requests.get(
            f"{discord_fake_url}/__testenv/transient-component",
            params={"scope": scope},
            timeout=5,
        )
        transient.raise_for_status()
        assert transient.json() == {"custom_id": expected_custom_id}
        evidence = requests.get(
            f"{discord_fake_url}/__testenv/state",
            timeout=5,
        ).json()
        assert expected_custom_id not in str(evidence)
    finally:
        callback.shutdown()
        callback.server_close()
        callback_thread.join(timeout=5)


def test_discord_fake_hands_off_delivered_message_components_transiently(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose a delivered settings control once without retaining its signed ID."""
    discord_fake_url, _ = discord_fake_urls
    custom_id = "a:st:interaction:claim:1:1:signature"
    response = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
        json={
            "content": "Private setup guidance.",
            "components": [
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 2,
                            "label": "Answer in threads",
                            "custom_id": custom_id,
                        }
                    ],
                }
            ],
        },
        timeout=5,
    )
    response.raise_for_status()

    transient = requests.get(
        f"{discord_fake_url}/__testenv/transient-component",
        params={"scope": "settings"},
        timeout=5,
    )
    transient.raise_for_status()
    assert transient.json() == {"custom_id": custom_id}
    consumed = requests.get(
        f"{discord_fake_url}/__testenv/transient-component",
        params={"scope": "settings"},
        timeout=5,
    )
    consumed.raise_for_status()
    assert consumed.json() == {"custom_id": None}
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert custom_id not in str(evidence)
    assert "Private setup guidance." not in str(evidence)


def test_discord_fake_serves_bounded_history_and_thread_ordering_evidence(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose history pages and one root-thread boundary without content evidence."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "root_messages": [
                {
                    "id": "500000000000000001",
                    "channel_id": "400000000000000001",
                    "content": "Private root source",
                    "author": {"id": "600000000000000001"},
                    "timestamp": "2026-07-28T00:00:00.000000+00:00",
                }
            ],
            "history_pages": [
                [
                    {"id": "300", "channel_id": "700", "content": "Private later"},
                    {"id": "200", "channel_id": "700", "content": "Private earlier"},
                ],
                [{"id": "100", "channel_id": "700", "content": "Private oldest"}],
            ],
        },
        timeout=5,
    ).raise_for_status()
    root = requests.get(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/500000000000000001",
        timeout=5,
    )
    root.raise_for_status()
    assert root.json()["id"] == "500000000000000001"
    first_page = requests.get(
        f"{discord_fake_url}/api/v10/channels/700/messages",
        params={"limit": 2},
        timeout=5,
    )
    first_page.raise_for_status()
    assert [item["id"] for item in first_page.json()] == ["300", "200"]
    second_page = requests.get(
        f"{discord_fake_url}/api/v10/channels/700/messages",
        params={"limit": 2, "before": "200"},
        timeout=5,
    )
    second_page.raise_for_status()
    assert [item["id"] for item in second_page.json()] == ["100"]
    thread = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/500000000000000001/threads",
        json={"name": "Azents"},
        timeout=5,
    )
    thread.raise_for_status()
    assert thread.json()["parent_id"] == "400000000000000001"
    reused_root = requests.get(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/500000000000000001",
        timeout=5,
    )
    reused_root.raise_for_status()
    assert reused_root.json()["thread"]["id"] == thread.json()["id"]

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    events = evidence["operations"]
    assert [event["event"] for event in events] == [
        "thread_read",
        "history_page",
        "history_page",
        "thread_create",
        "thread_read",
    ]
    assert events[0]["outcome"] == "missing"
    assert events[3]["thread_channel_id"] == thread.json()["id"]
    assert events[4]["outcome"] == "reused"
    rendered = str(evidence)
    assert "Private root source" not in rendered
    assert "Private later" not in rendered
    assert "Private earlier" not in rendered
    assert "Private oldest" not in rendered


def test_discord_fake_reads_and_updates_thread_titles_without_name_evidence(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Serve thread title GET/PATCH while keeping both names out of evidence."""
    discord_fake_url, _ = discord_fake_urls
    thread = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/"
        "500000000000000001/threads",
        json={"name": "Private provisional title"},
        timeout=5,
    )
    thread.raise_for_status()
    channel_url = f"{discord_fake_url}/api/v10/channels/{thread.json()['id']}"
    initial = requests.get(channel_url, timeout=5)
    initial.raise_for_status()
    assert initial.json()["name"] == "Private provisional title"

    updated = requests.patch(
        channel_url,
        json={"name": "Private final title"},
        timeout=5,
    )
    updated.raise_for_status()
    assert updated.json()["name"] == "Private final title"
    current = requests.get(channel_url, timeout=5)
    current.raise_for_status()
    assert current.json()["name"] == "Private final title"

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert [event["operation"] for event in evidence["operations"]] == [
        "create_thread",
        "get_channel",
        "update_channel",
        "get_channel",
    ]
    assert evidence["request_counts"]["get_channel"] == 2
    assert evidence["request_counts"]["update_channel"] == 1
    rendered = str(evidence)
    assert "Private provisional title" not in rendered
    assert "Private final title" not in rendered


def test_discord_fake_preserves_state_for_one_shot_scenarios(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Scenario changes do not erase nonce identities or ordered evidence."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "api_scenario_sequences": {"create_message": ["response_malformed", "ok"]}
        },
        timeout=5,
    ).raise_for_status()
    message_url = f"{discord_fake_url}/api/v10/channels/700/messages"
    first = requests.post(message_url, json={"nonce": "nonce-once"}, timeout=5)
    assert first.status_code == 200
    assert first.content == b"{malformed"
    second = requests.post(message_url, json={"nonce": "nonce-once"}, timeout=5)
    second.raise_for_status()
    assert second.json()["id"].isdigit()
    requests.post(
        f"{discord_fake_url}/__testenv/scenario",
        json={"api_scenarios": {"create_message": "response_shape_invalid"}},
        timeout=5,
    ).raise_for_status()
    third = requests.post(message_url, json={"nonce": "nonce-once"}, timeout=5)
    assert third.status_code == 200
    assert third.json() == {"channel_id": "700"}

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert len(evidence["operations"]) == 3
    assert [item.get("safe_category") for item in evidence["operations"]] == [
        "response_malformed",
        None,
        "response_shape_invalid",
    ]
    assert evidence["deliveries"][0]["outcome"] == "duplicate"
    assert "nonce-once" not in str(evidence)


def test_discord_fake_controls_thread_response_mismatch_and_transport_unknown(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose malformed thread success and transport ambiguity as safe evidence."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "api_scenario_sequences": {
                "create_thread": ["thread_response_invalid", "transport_unknown"]
            }
        },
        timeout=5,
    ).raise_for_status()
    thread_url = (
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/"
        "500000000000000001/threads"
    )
    invalid = requests.post(thread_url, json={"name": "Azents"}, timeout=5)
    assert invalid.status_code == 201
    assert invalid.json() == {"id": "bad", "parent_id": "0"}
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.post(thread_url, json={"name": "Azents"}, timeout=5)
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert [item["safe_category"] for item in evidence["operations"]] == [
        "thread_response_invalid",
        "transport_unknown",
    ]
    assert "Azents" not in str(evidence)


def test_discord_fake_reconciles_committed_unknown_thread_creation(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Reconcile a committed thread after the create response is lost."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "api_scenario_sequences": {
                "create_thread": ["thread_create_committed_unknown"]
            },
            "allow_synthetic_roots": True,
        },
        timeout=5,
    ).raise_for_status()
    thread_url = (
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/"
        "500000000000000001/threads"
    )
    with pytest.raises(requests.exceptions.ConnectionError):
        requests.post(thread_url, json={"name": "Private thread name"}, timeout=5)

    reconciled = requests.get(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/"
        "500000000000000001",
        timeout=5,
    )
    reconciled.raise_for_status()
    thread_id = reconciled.json()["thread"]["id"]

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert [event["event"] for event in evidence["operations"]] == [
        "thread_create",
        "thread_reconcile",
    ]
    assert evidence["operations"][0] == {
        "sequence": 1,
        "event": "thread_create",
        "operation": "create_thread",
        "outcome": "unknown",
        "safe_category": "transport_unknown",
        "parent_channel_id": "400000000000000001",
        "root_message_id": "500000000000000001",
        "thread_channel_id": thread_id,
    }
    assert evidence["operations"][1]["outcome"] == "reused"
    rendered = str(evidence)
    assert "Private thread name" not in rendered


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


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("credentials_invalid", 401),
        ("forbidden", 403),
        ("not_found", 404),
        ("rate_limited", 429),
        ("rejected", 400),
        ("provider_5xx_unknown", 503),
    ],
)
def test_discord_fake_controls_confirmed_and_unknown_http_categories(
    discord_fake_urls: tuple[str, str],
    scenario: str,
    expected_status: int,
) -> None:
    """Expose each bounded REST category without retaining provider response bodies."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"api_scenario_sequences": {"create_message": [scenario]}},
        timeout=5,
    ).raise_for_status()
    response = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
        json={"nonce": f"nonce-{scenario}"},
        timeout=5,
    )
    assert response.status_code == expected_status
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["operations"][0]["event"] == "message"
    assert evidence["operations"][0]["safe_category"] in {
        "credentials_invalid",
        "permission_denied",
        "message_not_found",
        "rate_limited",
        "provider_rejected",
        "provider_5xx_unknown",
    }
    assert "nonce-" not in str(evidence)


def test_discord_fake_confirmed_create_failure_does_not_consume_nonce_identity(
    discord_fake_urls: tuple[str, str],
) -> None:
    """A confirmed rejection leaves the nonce available for a real retry."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"api_scenario_sequences": {"create_message": ["rejected", "ok"]}},
        timeout=5,
    ).raise_for_status()
    message_url = f"{discord_fake_url}/api/v10/channels/400000000000000001/messages"
    first = requests.post(message_url, json={"nonce": "retry-nonce"}, timeout=5)
    assert first.status_code == 400
    failed_evidence = requests.get(
        f"{discord_fake_url}/__testenv/state", timeout=5
    ).json()
    assert failed_evidence["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "outcome": "failed",
            "safe_category": "provider_rejected",
        }
    ]
    second = requests.post(message_url, json={"nonce": "retry-nonce"}, timeout=5)
    second.raise_for_status()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert "message_id" not in evidence["deliveries"][0]
    assert evidence["deliveries"][1]["outcome"] == "created"
    assert evidence["deliveries"][1]["message_id"] == second.json()["id"]
    assert "retry-nonce" not in str(evidence)


def test_discord_fake_history_is_channel_scoped_and_cursor_bounded(
    discord_fake_urls: tuple[str, str],
) -> None:
    """History pages enforce target channel, requested limit, and cursor evidence."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {"id": "300", "channel_id": "channel-a"},
                    {"id": "200", "channel_id": "channel-a"},
                ]
            ]
        },
        timeout=5,
    ).raise_for_status()
    wrong_channel = requests.get(
        f"{discord_fake_url}/api/v10/channels/channel-b/messages",
        params={"limit": 100},
        timeout=5,
    )
    wrong_channel.raise_for_status()
    assert wrong_channel.json() == []
    first = requests.get(
        f"{discord_fake_url}/api/v10/channels/channel-a/messages",
        params={"limit": 1},
        timeout=5,
    )
    first.raise_for_status()
    assert [item["id"] for item in first.json()] == ["300"]
    second = requests.get(
        f"{discord_fake_url}/api/v10/channels/channel-a/messages",
        params={"limit": 1, "before": "300"},
        timeout=5,
    )
    second.raise_for_status()
    assert [item["id"] for item in second.json()] == ["200"]

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    history_events = [
        item for item in evidence["operations"] if item["event"] == "history_page"
    ]
    assert history_events[0]["channel_id"] == "channel-b"
    assert history_events[0]["limit"] == 100
    assert history_events[1]["channel_id"] == "channel-a"
    assert history_events[1]["limit"] == 1
    assert history_events[2]["cursor"] == "300"


def test_discord_fake_root_reads_require_configured_or_explicit_synthetic_mode(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Absent roots are 404 unless the bounded synthetic fixture mode is enabled."""
    discord_fake_url, _ = discord_fake_urls
    root_url = f"{discord_fake_url}/api/v10/channels/channel-a/messages/root-a"
    missing = requests.get(root_url, timeout=5)
    assert missing.status_code == 404
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"allow_synthetic_roots": True},
        timeout=5,
    ).raise_for_status()
    synthetic = requests.get(root_url, timeout=5)
    synthetic.raise_for_status()
    assert synthetic.json()["id"] == "root-a"


def test_discord_fake_rejects_unbounded_history_root_and_command_fixtures(
    discord_fake_urls: tuple[str, str],
) -> None:
    """History, root, and command fixture state remains explicitly bounded."""
    discord_fake_url, _ = discord_fake_urls
    oversized = requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [
                    {
                        "id": "1",
                        "channel_id": "channel-a",
                        "content": "x" * 20_000,
                    }
                ]
            ]
        },
        timeout=5,
    )
    assert oversized.status_code == 400
    too_many_pages = requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "history_pages": [
                [{"id": str(index), "channel_id": "channel-a"}] for index in range(33)
            ]
        },
        timeout=5,
    )
    assert too_many_pages.status_code == 400
    oversized_root = requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "root_messages": [
                {
                    "id": "root-a",
                    "channel_id": "channel-a",
                    "content": "x" * 20_000,
                }
            ]
        },
        timeout=5,
    )
    assert oversized_root.status_code == 400
    too_many_commands = requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "guild_commands": [
                {
                    "id": str(500000000000001000 + index),
                    "name": f"command-{index}",
                    "type": 1,
                }
                for index in range(101)
            ]
        },
        timeout=5,
    )
    assert too_many_commands.status_code == 400
    oversized_command = requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "guild_commands": [
                {
                    "id": "500000000000002000",
                    "name": "x" * 101,
                    "type": 1,
                }
            ]
        },
        timeout=5,
    )
    assert oversized_command.status_code == 400
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "guild_commands": [
                {
                    "id": str(500000000000003000 + index),
                    "name": f"command-{index}",
                    "type": 1,
                }
                for index in range(100)
            ]
        },
        timeout=5,
    ).raise_for_status()
    command_collection_url = (
        f"{discord_fake_url}/api/v10/applications/100000000000000001/"
        "guilds/200000000000000001/commands"
    )
    overflow_create = requests.post(
        command_collection_url,
        json={"name": "overflow", "type": 1},
        timeout=5,
    )
    assert overflow_create.status_code == 400


def test_discord_fake_update_delete_track_missing_and_deleted_messages(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Update/delete paths expose real missing and deleted identity behavior."""
    discord_fake_url, _ = discord_fake_urls
    message_url = f"{discord_fake_url}/api/v10/channels/channel-a/messages"
    created = requests.post(message_url, json={"nonce": "lifecycle"}, timeout=5)
    created.raise_for_status()
    message_id = created.json()["id"]
    update_url = f"{message_url}/{message_id}"
    updated = requests.patch(update_url, json={"content": "new"}, timeout=5)
    updated.raise_for_status()
    deleted = requests.delete(update_url, timeout=5)
    assert deleted.status_code == 204
    assert (
        requests.patch(update_url, json={"content": "again"}, timeout=5).status_code
        == 404
    )
    assert requests.delete(update_url, timeout=5).status_code == 404


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
    assert evidence["deliveries"][0] == {
        "operation": "create_message",
        "channel_id": "400000000000000001",
        "outcome": "unknown",
        "message_id": evidence["deliveries"][0]["message_id"],
        "safe_category": "provider_5xx_unknown",
    }
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
        host = callback_server.server_address[0]
        port = callback_server.server_address[1]
        requests.patch(
            f"{discord_fake_url}/api/v10/applications/@me",
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
            "response_type": 1,
        }
    ]
    assert "/callback" not in rendered


def test_discord_fake_keeps_selector_ids_transient_and_redacted(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Selector component IDs are usable once but absent from durable evidence."""
    discord_fake_url, _ = discord_fake_urls
    _SelectorInteractionHandler.received_bodies = []
    callback_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _SelectorInteractionHandler,
    )
    callback_thread = threading.Thread(
        target=callback_server.serve_forever,
        daemon=True,
    )
    callback_thread.start()
    try:
        host = callback_server.server_address[0]
        port = callback_server.server_address[1]
        requests.patch(
            f"{discord_fake_url}/api/v10/applications/@me",
            json={"interactions_endpoint_url": f"http://{host}:{port}/callback"},
            timeout=5,
        ).raise_for_status()
        response = requests.post(
            f"{discord_fake_url}/__testenv/interactions",
            json={
                "id": "700000000000000002",
                "type": 2,
                "application_id": "100000000000000001",
                "guild_id": "200000000000000001",
                "channel_id": "400000000000000001",
                "member": {"user": {"id": "600000000000000001"}},
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
    selector = requests.get(
        f"{discord_fake_url}/__testenv/transient-selector",
        timeout=5,
    )
    selector.raise_for_status()
    assert response.json() == {"status": 200, "response_type": 4}
    assert selector.json()["custom_id"].startswith("azents-selector:")
    assert requests.get(
        f"{discord_fake_url}/__testenv/transient-selector",
        timeout=5,
    ).json() == {"custom_id": None}
    assert "azents-selector:select:admission:0:signature" not in rendered
    assert "Select an Agent." not in rendered


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


def test_discord_fake_preserves_canonical_thread_progress_and_file_order(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Cover one thread's progress page mutations, confirmed delete, and file output."""
    discord_fake_url, _ = discord_fake_urls
    thread = requests.post(
        f"{discord_fake_url}/api/v10/channels/400000000000000001/messages/500000000000000003/threads",
        json={"name": "Private thread title"},
        timeout=5,
    )
    thread.raise_for_status()
    thread_id = thread.json()["id"]
    first = requests.post(
        f"{discord_fake_url}/api/v10/channels/{thread_id}/messages",
        json={"content": "Private checking page", "nonce": "progress-page-1"},
        timeout=5,
    )
    first.raise_for_status()
    second = requests.post(
        f"{discord_fake_url}/api/v10/channels/{thread_id}/messages",
        json={"content": "Private progress page 2", "nonce": "progress-page-2"},
        timeout=5,
    )
    second.raise_for_status()
    update = requests.patch(
        f"{discord_fake_url}/api/v10/channels/{thread_id}/messages/{first.json()['id']}",
        json={"content": "Private updated progress page"},
        timeout=5,
    )
    update.raise_for_status()
    deleted = requests.delete(
        f"{discord_fake_url}/api/v10/channels/{thread_id}/messages/{second.json()['id']}",
        timeout=5,
    )
    assert deleted.status_code == 204
    file_delivery = requests.post(
        f"{discord_fake_url}/api/v10/channels/{thread_id}/messages",
        data={"payload_json": '{"content":"Private file output"}'},
        files={
            "files[0]": (
                "private.txt",
                b"private-file-bytes",
                "text/plain",
            )
        },
        timeout=5,
    )
    file_delivery.raise_for_status()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    operations = [
        item
        for item in evidence["operations"]
        if item["event"] in {"thread_create", "message"}
    ]
    assert [item["operation"] for item in operations] == [
        "create_thread",
        "create_message",
        "create_message",
        "update_message",
        "delete_message",
        "create_message",
    ]
    assert [item["outcome"] for item in operations] == [
        "delivered",
        "created",
        "created",
        "delivered",
        "delivered",
        "created",
    ]
    assert evidence["deliveries"][-1]["file_count"] == 1
    rendered = str(evidence)
    assert "Private checking page" not in rendered
    assert "Private progress page 2" not in rendered
    assert "Private updated progress page" not in rendered
    assert "private-file-bytes" not in rendered
    assert "private.txt" not in rendered


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
    assert application.json()["owner"]["id"].isdigit()
