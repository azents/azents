"""Deterministic Discord provider fake contract tests."""

import threading
from collections.abc import Generator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from testcontainers.core.container import DockerContainer

from support.discord_provider_fake import (
    STATE,
    DiscordHTTPHandler,
)

_DISCORD_VERIFY_KEY = "233988c4fcf6ffd4dcf0590950d79671de856cfa36f65c16a2be13b1613875f0"
_SERVER_POLL_INTERVAL_SECONDS = 0.01


class _ImmediateBarrierExpiry:
    """Model one reached barrier whose bounded release wait expires."""

    def clear(self) -> None:
        """Keep the synthetic release unset."""

    def set(self) -> None:
        """Ignore releases because the modeled wait already expired."""

    def is_set(self) -> bool:
        """Report that no release was observed before expiry."""
        return False

    def wait(self, timeout: float | None = None) -> bool:
        """Expire immediately without using wall-clock delay."""
        del timeout
        return False


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


class _DeferredInteractionHandler(_SignedInteractionHandler):
    """Return one deferred component update for background completion tests."""

    def do_POST(self) -> None:
        """Verify the signed request and acknowledge before background work."""
        length = int(self.headers["Content-Length"])
        body = self.rfile.read(length)
        signature = bytes.fromhex(self.headers["X-Signature-Ed25519"])
        timestamp = self.headers["X-Signature-Timestamp"].encode()
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(_DISCORD_VERIFY_KEY)).verify(
            signature, timestamp + body
        )
        self.received_bodies.append(body)
        response = b'{"type":6}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


@pytest.fixture
def discord_fake_urls() -> Generator[tuple[str, str], None, None]:
    """Run one isolated SDK-facing/provider-gap fake with fresh global state."""
    STATE.reset()
    http_server = ThreadingHTTPServer(("127.0.0.1", 0), DiscordHTTPHandler)
    http_thread = threading.Thread(
        target=http_server.serve_forever,
        kwargs={"poll_interval": _SERVER_POLL_INTERVAL_SECONDS},
        daemon=True,
    )
    http_thread.start()
    try:
        http_host = http_server.server_address[0]
        http_port = http_server.server_address[1]
        yield (
            f"http://{http_host}:{http_port}",
            "",
        )
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=5)


def _sdk_call(
    base_url: str,
    operation: str,
    **arguments: object,
) -> requests.Response:
    """Invoke one credential-free SDK-facing fixture operation."""
    return requests.post(
        f"{base_url}/__testenv/sdk",
        json={"operation": operation, "arguments": arguments},
        timeout=5,
    )


def _configure_interaction_endpoint(
    base_url: str,
    endpoint_url: str,
) -> requests.Response:
    """Invoke the approved direct callback configuration gap."""
    return requests.patch(
        f"{base_url}/api/v10/applications/@me",
        json={"interactions_endpoint_url": endpoint_url},
        timeout=5,
    )


def test_discord_fake_serves_sdk_login_identity(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Model the public SDK login without accepting the Bot credential."""
    discord_fake_url, _ = discord_fake_urls

    login = _sdk_call(discord_fake_url, "login")

    login.raise_for_status()
    assert login.json() == {"bot_user_id": STATE.bot_user_id}


def test_discord_fake_redacts_rest_secrets_and_visible_provider_bodies(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Capture only provider operation identifiers and outcomes."""
    discord_fake_url, _ = discord_fake_urls
    _configure_interaction_endpoint(
        discord_fake_url,
        "https://private.example/opaque-selector",
    ).raise_for_status()
    created = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="Private Discord message body",
        nonce="nonce-private",
        components=None,
        embeds=None,
    ).json()
    duplicate = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="Different private body",
        nonce="nonce-private",
        components=None,
        embeds=None,
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
            "type": 1,
            "description": "Stale description.",
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
    for response in (unrelated, settings, message_action):
        assert response.json()["application_id"] == "100000000000000001"
        assert response.json()["guild_id"] == "200000000000000001"
    for response in (unrelated, message_action):
        assert response.json()["description"] == ""
    assert settings.json()["description"] == "Stale description."
    command_id = requests.get(
        f"{discord_fake_url}/__testenv/command-id",
        params={"role": "message_action"},
        timeout=5,
    )
    command_id.raise_for_status()
    assert command_id.json() == {"command_id": message_action.json()["id"]}

    listed = _sdk_call(
        discord_fake_url,
        "list_guild_commands",
        application_id=STATE.application_id,
        guild_id=STATE.guild_id,
    )
    listed.raise_for_status()
    assert listed.json()["commands"] == [
        unrelated.json(),
        settings.json(),
        message_action.json(),
    ]

    updated = _sdk_call(
        discord_fake_url,
        "update_guild_command",
        command_id=settings.json()["id"],
        name="Private updated settings command",
        command_type=1,
        description="Current description.",
    )
    updated.raise_for_status()
    assert updated.json()["id"] == settings.json()["id"]
    assert updated.json()["name"] == "Private updated settings command"
    assert updated.json()["type"] == 1
    assert updated.json()["application_id"] == "100000000000000001"
    assert updated.json()["guild_id"] == "200000000000000001"
    assert updated.json()["description"] == "Current description."

    deleted = _sdk_call(
        discord_fake_url,
        "delete_guild_command",
        command_id=settings.json()["id"],
    )
    assert deleted.status_code == 200
    remaining = _sdk_call(
        discord_fake_url,
        "list_guild_commands",
        application_id=STATE.application_id,
        guild_id=STATE.guild_id,
    )
    remaining.raise_for_status()
    assert remaining.json()["commands"] == [unrelated.json(), message_action.json()]

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert [
        (request["method"], request["operation"]) for request in evidence["requests"]
    ] == [
        ("POST", "create_guild_command"),
        ("POST", "create_guild_command"),
        ("POST", "create_guild_command"),
        ("POST", "list_guild_commands"),
        ("POST", "update_guild_command"),
        ("POST", "delete_guild_command"),
        ("POST", "list_guild_commands"),
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
    reset_commands = _sdk_call(
        discord_fake_url,
        "list_guild_commands",
        application_id=STATE.application_id,
        guild_id=STATE.guild_id,
    )
    reset_commands.raise_for_status()
    assert reset_commands.json() == {"commands": []}


def test_discord_fake_configures_bounded_command_reconciliation_state(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Seed duplicate, stale, and unrelated commands without evidence leakage."""
    discord_fake_url, _ = discord_fake_urls
    configured_names = [
        "Ask an Azents Agent",
        "Ask an Azents Agent",
        "azents",
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
    rendered = str(evidence)
    assert configured_names[0] not in rendered
    assert configured_names[3] not in rendered
    assert "Stale description." not in rendered


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
    callback_thread = threading.Thread(
        target=callback.serve_forever,
        kwargs={"poll_interval": _SERVER_POLL_INTERVAL_SECONDS},
        daemon=True,
    )
    callback_thread.start()
    try:
        callback_host = callback.server_address[0]
        callback_port = callback.server_address[1]
        _configure_interaction_endpoint(
            discord_fake_url,
            f"http://{callback_host}:{callback_port}/interaction",
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
    response = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="Private setup guidance.",
        nonce="component-handoff",
        components=[
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
        embeds=None,
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


def test_discord_fake_correlates_transient_components_by_channel(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Keep concurrent channel controls available for their matching callback."""
    discord_fake_url, _ = discord_fake_urls
    first_channel_id = "400000000000000011"
    second_channel_id = "400000000000000012"
    first_custom_id = "a:st:first:claim:1:1:signature"
    second_custom_id = "a:st:second:claim:1:1:signature"

    for channel_id, custom_id in (
        (first_channel_id, first_custom_id),
        (second_channel_id, second_custom_id),
    ):
        response = _sdk_call(
            discord_fake_url,
            "create_message",
            guild_id=STATE.guild_id,
            channel_id=channel_id,
            content="Private setup guidance.",
            nonce=f"component-handoff-{channel_id}",
            components=[
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
            embeds=None,
        )
        response.raise_for_status()

    second = requests.get(
        f"{discord_fake_url}/__testenv/transient-component",
        params={"scope": "settings", "channel_id": second_channel_id},
        timeout=5,
    )
    second.raise_for_status()
    assert second.json() == {"custom_id": second_custom_id}

    first = requests.get(
        f"{discord_fake_url}/__testenv/transient-component",
        params={"scope": "settings", "channel_id": first_channel_id},
        timeout=5,
    )
    first.raise_for_status()
    assert first.json() == {"custom_id": first_custom_id}


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

    def create() -> requests.Response:
        return _sdk_call(
            discord_fake_url,
            "create_message",
            guild_id=STATE.guild_id,
            channel_id="700",
            content="private",
            nonce="nonce-once",
            components=None,
            embeds=None,
        )

    first = create()
    assert first.status_code == 200
    assert first.content == b"{malformed"
    second = create()
    second.raise_for_status()
    assert second.json()["id"].isdigit()
    requests.post(
        f"{discord_fake_url}/__testenv/scenario",
        json={"api_scenarios": {"create_message": "response_shape_invalid"}},
        timeout=5,
    ).raise_for_status()
    third = create()
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


def test_discord_fake_serves_injected_gateway_dispatches(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Return bounded dispatches and sanitized evidence through fixture control I/O."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "gateway_dispatches": [
                {
                    "sequence": 2,
                    "event_type": "MESSAGE_CREATE",
                    "payload": {
                        "id": "message-1",
                        "channel_id": "channel-1",
                        "content": "Private gateway content",
                    },
                }
            ]
        },
        timeout=5,
    ).raise_for_status()
    response = requests.post(
        f"{discord_fake_url}/__testenv/gateway",
        json={"target_guild_id": STATE.guild_id, "resumed": False},
        timeout=5,
    )
    response.raise_for_status()

    assert response.json()["scenario"] == "open"
    assert response.json()["dispatches"][0]["event_type"] == "MESSAGE_CREATE"
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["gateway"] == {
        "connections": 1,
        "initial_opcodes": [2],
        "heartbeats": [],
        "dispatches": [{"event_type": "MESSAGE_CREATE", "sequence": 2}],
        "terminal_events": [],
    }
    assert "Private gateway content" not in str(evidence)


def test_discord_fake_records_redacted_typing_snapshots_and_pulses(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Store only safe active-target facts and explicit empty snapshots."""
    discord_fake_url, _ = discord_fake_urls
    targets = [
        {
            "guild_id": STATE.guild_id,
            "channel_id": "400000000000000001",
            "work_cycle_count": 2,
        },
        {
            "guild_id": STATE.guild_id,
            "channel_id": "400000000000000002",
            "work_cycle_count": 1,
        },
    ]
    active = requests.post(
        f"{discord_fake_url}/__testenv/typing",
        json={"targets": targets},
        timeout=5,
    )
    empty = requests.post(
        f"{discord_fake_url}/__testenv/typing",
        json={"targets": []},
        timeout=5,
    )

    assert active.status_code == 204
    assert empty.status_code == 204
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["typing"] == {
        "snapshots": [{"targets": targets}, {"targets": []}],
        "pulses": targets,
    }
    assert evidence["request_counts"]["typing"] == 2
    rendered = str(evidence)
    assert "work-cycle-private-id" not in rendered
    assert "typing-private-content" not in rendered


def test_discord_fake_typing_failures_do_not_record_targets_and_reset_evidence(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Apply typed failure controls without retaining failed typing snapshots."""
    discord_fake_url, _ = discord_fake_urls
    target = {
        "guild_id": STATE.guild_id,
        "channel_id": "400000000000000001",
        "work_cycle_count": 1,
    }
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"api_scenario_sequences": {"typing": ["server_error", "ok"]}},
        timeout=5,
    ).raise_for_status()

    failed = requests.post(
        f"{discord_fake_url}/__testenv/typing",
        json={"targets": [target]},
        timeout=5,
    )
    delivered = requests.post(
        f"{discord_fake_url}/__testenv/typing",
        json={"targets": [target]},
        timeout=5,
    )

    assert failed.status_code == 503
    assert delivered.status_code == 204
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["typing"] == {
        "snapshots": [{"targets": [target]}],
        "pulses": [target],
    }
    assert evidence["request_counts"]["typing"] == 2

    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={},
        timeout=5,
    ).raise_for_status()
    configured = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert configured["typing"] == {"snapshots": [], "pulses": []}
    assert "typing-private-content" not in str(configured)


def test_discord_fake_rejects_non_redacted_typing_targets(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Reject work identifiers and visible content before they reach evidence."""
    discord_fake_url, _ = discord_fake_urls
    response = requests.post(
        f"{discord_fake_url}/__testenv/typing",
        json={
            "targets": [
                {
                    "guild_id": STATE.guild_id,
                    "channel_id": "400000000000000001",
                    "work_cycle_count": 1,
                    "work_cycle_id": "work-cycle-private-id",
                    "content": "typing-private-content",
                }
            ]
        },
        timeout=5,
    )

    assert response.status_code == 400
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["typing"] == {"snapshots": [], "pulses": []}
    assert "work-cycle-private-id" not in str(evidence)
    assert "typing-private-content" not in str(evidence)


def test_discord_fake_controls_injected_gateway_reconnect_and_resume(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Request reconnect, then accept a Resume through the injected runner API."""
    discord_fake_url, _ = discord_fake_urls
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"gateway_scenarios": ["reconnect", "open"]},
        timeout=5,
    ).raise_for_status()
    first = requests.post(
        f"{discord_fake_url}/__testenv/gateway",
        json={"target_guild_id": STATE.guild_id, "resumed": False},
        timeout=5,
    )
    second = requests.post(
        f"{discord_fake_url}/__testenv/gateway",
        json={"target_guild_id": STATE.guild_id, "resumed": True},
        timeout=5,
    )
    first.raise_for_status()
    second.raise_for_status()

    assert first.json() == {"scenario": "reconnect", "dispatches": []}
    assert second.json()["scenario"] == "open"
    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["gateway"] == {
        "connections": 2,
        "initial_opcodes": [2, 6],
        "heartbeats": [],
        "dispatches": [],
        "terminal_events": ["reconnect"],
    }


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
    response = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="controlled",
        nonce=f"nonce-{scenario}",
        components=None,
        embeds=None,
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


def test_discord_fake_publishes_failure_evidence_before_response(
    discord_fake_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publish controlled failure evidence before the SDK observes its response."""
    discord_fake_url, _ = discord_fake_urls
    evidence_started = threading.Event()
    release_evidence = threading.Event()
    original_record_message_failure = STATE.record_message_failure

    def record_message_failure_after_release(
        *,
        operation: str,
        channel_id: str,
        message_id: str | None,
        outcome: str,
        file_count: int = 0,
        file_bytes: int = 0,
        safe_category: str | None,
    ) -> None:
        evidence_started.set()
        if not release_evidence.wait(timeout=5):
            raise TimeoutError("controlled failure evidence was not released")
        original_record_message_failure(
            operation=operation,
            channel_id=channel_id,
            message_id=message_id,
            outcome=outcome,
            file_count=file_count,
            file_bytes=file_bytes,
            safe_category=safe_category,
        )

    monkeypatch.setattr(
        STATE,
        "record_message_failure",
        record_message_failure_after_release,
    )
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"api_scenario_sequences": {"create_message": ["forbidden"]}},
        timeout=5,
    ).raise_for_status()
    responses: list[requests.Response] = []

    def create_message() -> None:
        responses.append(
            requests.post(
                f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
                data={"payload_json": '{"content":"controlled"}'},
                files={
                    "files[0]": (
                        "evidence.txt",
                        b"evidence-order",
                        "text/plain",
                    )
                },
                timeout=5,
            )
        )

    request_thread = threading.Thread(target=create_message)
    request_thread.start()
    try:
        assert evidence_started.wait(timeout=5)
        assert responses == []
    finally:
        release_evidence.set()
        request_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert len(responses) == 1
    assert responses[0].status_code == 403

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert evidence["operations"] == [
        {
            "sequence": 1,
            "event": "message",
            "operation": "create_message",
            "outcome": "failed",
            "channel_id": "400000000000000001",
            "safe_category": "permission_denied",
        }
    ]
    assert evidence["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "outcome": "failed",
            "file_count": 1,
            "file_bytes": len(b"evidence-order"),
            "safe_category": "permission_denied",
        }
    ]


@pytest.mark.parametrize(
    ("scenario", "boundary_method"),
    [
        ("transport_unknown", "_close_connection"),
        ("timeout", "_wait_for_controlled_timeout"),
    ],
)
def test_discord_fake_publishes_failure_evidence_before_transport_boundary(
    discord_fake_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    boundary_method: str,
) -> None:
    """Publish unknown failure evidence before closing or delaying transport."""
    discord_fake_url, _ = discord_fake_urls
    original_boundary = (
        DiscordHTTPHandler._close_connection
        if boundary_method == "_close_connection"
        else DiscordHTTPHandler._wait_for_controlled_timeout
    )
    boundary_evidence: list[dict[str, object]] = []

    def observe_boundary(handler: DiscordHTTPHandler) -> None:
        boundary_evidence.append(
            requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
        )
        if boundary_method == "_close_connection":
            original_boundary(handler)

    monkeypatch.setattr(DiscordHTTPHandler, boundary_method, observe_boundary)
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={"api_scenario_sequences": {"create_message": [scenario]}},
        timeout=5,
    ).raise_for_status()

    with pytest.raises(requests.ConnectionError):
        requests.post(
            f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
            data={"payload_json": '{"content":"controlled"}'},
            files={
                "files[0]": (
                    "transport.txt",
                    b"transport-boundary",
                    "text/plain",
                )
            },
            timeout=5,
        )

    assert len(boundary_evidence) == 1
    assert boundary_evidence[0]["operations"] == [
        {
            "sequence": 1,
            "event": "message",
            "operation": "create_message",
            "outcome": "unknown",
            "channel_id": "400000000000000001",
            "message_id": "400000000000000001",
            "safe_category": "transport_unknown",
        }
    ]
    assert boundary_evidence[0]["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "message_id": "400000000000000001",
            "outcome": "unknown",
            "file_count": 1,
            "file_bytes": len(b"transport-boundary"),
            "safe_category": "transport_unknown",
        }
    ]


def test_discord_fake_records_message_evidence_before_barrier_expiry_close(
    discord_fake_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Record an ambiguous committed message before barrier expiry closes transport."""
    discord_fake_url, _ = discord_fake_urls
    original_close = DiscordHTTPHandler._close_connection
    boundary_evidence: list[dict[str, object]] = []

    def observe_close(handler: DiscordHTTPHandler) -> None:
        boundary_evidence.append(
            requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
        )
        original_close(handler)

    monkeypatch.setattr(DiscordHTTPHandler, "_close_connection", observe_close)
    requests.post(
        f"{discord_fake_url}/__testenv/barrier",
        json={"operation": "create_message", "occurrence": 1},
        timeout=5,
    ).raise_for_status()
    monkeypatch.setattr(
        STATE,
        "_delivery_barrier_release",
        _ImmediateBarrierExpiry(),
    )

    with pytest.raises(requests.ConnectionError):
        requests.post(
            f"{discord_fake_url}/api/v10/channels/400000000000000001/messages",
            data={"payload_json": '{"content":"controlled"}'},
            files={
                "files[0]": (
                    "barrier.txt",
                    b"barrier-expiry",
                    "text/plain",
                )
            },
            timeout=5,
        )

    assert len(boundary_evidence) == 1
    assert boundary_evidence[0]["operations"] == [
        {
            "sequence": 1,
            "event": "message",
            "operation": "create_message",
            "outcome": "unknown",
            "channel_id": "400000000000000001",
            "message_id": "400000000000000001",
            "safe_category": "transport_unknown",
        }
    ]
    assert boundary_evidence[0]["deliveries"] == [
        {
            "operation": "create_message",
            "channel_id": "400000000000000001",
            "message_id": "400000000000000001",
            "outcome": "unknown",
            "file_count": 1,
            "file_bytes": len(b"barrier-expiry"),
            "safe_category": "transport_unknown",
        }
    ]


@pytest.mark.parametrize(
    ("barrier_operation", "sdk_operation", "arguments", "expected_metadata"),
    [
        (
            "create_thread",
            "create_thread",
            {
                "guild_id": STATE.guild_id,
                "parent_channel_id": "400000000000000001",
                "root_message_id": "400000000000000101",
                "name": "private-thread-name",
                "auto_archive_duration": 60,
            },
            {
                "channel_id": "400000000000000001",
                "message_id": "400000000000000101",
            },
        ),
        (
            "get_message",
            "fetch_message_projection",
            {
                "guild_id": STATE.guild_id,
                "channel_id": "400000000000000001",
                "message_id": "400000000000000101",
            },
            {
                "channel_id": "400000000000000001",
                "message_id": "400000000000000101",
            },
        ),
        (
            "get_history",
            "fetch_history_projections",
            {
                "guild_id": STATE.guild_id,
                "channel_id": "400000000000000001",
                "before_message_id": "999999999999999999",
                "limit": 100,
            },
            {
                "channel_id": "400000000000000001",
                "limit": 100,
                "cursor": "999999999999999999",
            },
        ),
    ],
)
def test_discord_fake_records_operation_evidence_before_barrier_expiry_close(
    discord_fake_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
    barrier_operation: str,
    sdk_operation: str,
    arguments: dict[str, object],
    expected_metadata: dict[str, object],
) -> None:
    """Record the expired provider operation before closing its transport."""
    discord_fake_url, _ = discord_fake_urls
    original_close = DiscordHTTPHandler._close_connection
    boundary_evidence: list[dict[str, object]] = []

    def observe_close(handler: DiscordHTTPHandler) -> None:
        boundary_evidence.append(
            requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
        )
        original_close(handler)

    monkeypatch.setattr(DiscordHTTPHandler, "_close_connection", observe_close)
    requests.post(
        f"{discord_fake_url}/__testenv/barrier",
        json={"operation": barrier_operation, "occurrence": 1},
        timeout=5,
    ).raise_for_status()
    monkeypatch.setattr(
        STATE,
        "_delivery_barrier_release",
        _ImmediateBarrierExpiry(),
    )

    with pytest.raises(requests.ConnectionError):
        _sdk_call(discord_fake_url, sdk_operation, **arguments)

    assert len(boundary_evidence) == 1
    assert boundary_evidence[0]["deliveries"] == []
    assert boundary_evidence[0]["operations"] == [
        {
            "sequence": 1,
            "event": "delivery_barrier",
            "operation": barrier_operation,
            "outcome": "unknown",
            "safe_category": "transport_unknown",
            **expected_metadata,
        }
    ]


def test_discord_fake_sequences_retry_after_and_blocks_provider_work(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Sequence Retry-After and release exact-read and thread-create barriers."""
    discord_fake_url, _ = discord_fake_urls
    channel_id = "400000000000000001"
    message_id = "400000000000000101"
    requests.post(
        f"{discord_fake_url}/__testenv/configure",
        json={
            "api_scenario_sequences": {
                "get_history": ["rate_limited", "rate_limited", "ok"]
            },
            "retry_after_sequences": {"get_history": [4, 8]},
            "history_pages": [
                [
                    {
                        "id": message_id,
                        "channel_id": channel_id,
                        "content": "provider content excluded from evidence",
                    }
                ]
            ],
            "root_messages": [
                {
                    "id": message_id,
                    "channel_id": channel_id,
                    "content": "provider content excluded from evidence",
                }
            ],
        },
        timeout=5,
    ).raise_for_status()

    history_arguments = {
        "guild_id": STATE.guild_id,
        "channel_id": channel_id,
        "before_message_id": "999999999999999999",
        "limit": 100,
    }
    first = _sdk_call(
        discord_fake_url,
        "fetch_history_projections",
        **history_arguments,
    )
    second = _sdk_call(
        discord_fake_url,
        "fetch_history_projections",
        **history_arguments,
    )
    third = _sdk_call(
        discord_fake_url,
        "fetch_history_projections",
        **history_arguments,
    )
    assert first.status_code == 429
    assert first.headers["Retry-After"] == "4"
    assert second.status_code == 429
    assert second.headers["Retry-After"] == "8"
    assert third.status_code == 200

    requests.post(
        f"{discord_fake_url}/__testenv/barrier",
        json={"operation": "get_message", "occurrence": 1},
        timeout=5,
    ).raise_for_status()
    responses: list[requests.Response] = []

    def request_message() -> None:
        responses.append(
            _sdk_call(
                discord_fake_url,
                "fetch_message_projection",
                guild_id=STATE.guild_id,
                channel_id=channel_id,
                message_id=message_id,
            )
        )

    thread = threading.Thread(target=request_message)
    thread.start()
    for _ in range(50):
        barrier = requests.get(
            f"{discord_fake_url}/__testenv/barrier",
            timeout=5,
        ).json()
        if barrier["reached"]:
            break
        threading.Event().wait(0.02)
    else:
        pytest.fail("Discord exact-message barrier was not reached.")
    assert responses == []
    assert barrier == {
        "operation": "get_message",
        "occurrence": 1,
        "request_count": 1,
        "reached": True,
        "released": False,
    }
    requests.post(
        f"{discord_fake_url}/__testenv/barrier/release",
        timeout=5,
    ).raise_for_status()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert responses[0].status_code == 200
    evidence = requests.get(
        f"{discord_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    assert "provider content excluded from evidence" not in str(evidence)

    requests.post(
        f"{discord_fake_url}/__testenv/barrier",
        json={"operation": "create_thread", "occurrence": 1},
        timeout=5,
    ).raise_for_status()
    thread_responses: list[requests.Response] = []

    def request_thread_creation() -> None:
        thread_responses.append(
            _sdk_call(
                discord_fake_url,
                "create_thread",
                guild_id=STATE.guild_id,
                parent_channel_id=channel_id,
                root_message_id=message_id,
                name="content-free-thread-name",
                auto_archive_duration=60,
            )
        )

    create_thread = threading.Thread(target=request_thread_creation)
    create_thread.start()
    for _ in range(50):
        barrier = requests.get(
            f"{discord_fake_url}/__testenv/barrier",
            timeout=5,
        ).json()
        if barrier["reached"]:
            break
        threading.Event().wait(0.02)
    else:
        pytest.fail("Discord thread-create barrier was not reached.")
    assert thread_responses == []
    assert barrier == {
        "operation": "create_thread",
        "occurrence": 1,
        "request_count": 1,
        "reached": True,
        "released": False,
    }
    requests.post(
        f"{discord_fake_url}/__testenv/barrier/release",
        timeout=5,
    ).raise_for_status()
    create_thread.join(timeout=5)
    assert not create_thread.is_alive()
    assert thread_responses[0].status_code == 200
    evidence = requests.get(
        f"{discord_fake_url}/__testenv/state",
        timeout=5,
    ).json()
    assert "content-free-thread-name" not in str(evidence)


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
    first = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="first",
        nonce="retry-nonce",
        components=None,
        embeds=None,
    )
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
    second = _sdk_call(
        discord_fake_url,
        "create_message",
        guild_id=STATE.guild_id,
        channel_id="400000000000000001",
        content="second",
        nonce="retry-nonce",
        components=None,
        embeds=None,
    )
    second.raise_for_status()

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    assert "message_id" not in evidence["deliveries"][0]
    assert evidence["deliveries"][1]["outcome"] == "created"
    assert evidence["deliveries"][1]["message_id"] == second.json()["id"]
    assert "retry-nonce" not in str(evidence)


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


def test_discord_fake_controls_rest_rate_limit_rejection_and_ambiguous_write(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Return controlled provider outcomes while retaining only safe evidence."""
    discord_fake_url, _ = discord_fake_urls
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
        response = _sdk_call(
            discord_fake_url,
            "create_message",
            guild_id=STATE.guild_id,
            channel_id="400000000000000001",
            content="Private controlled outcome body",
            nonce=f"nonce-{scenario}",
            components=None,
            embeds=None,
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
        kwargs={"poll_interval": _SERVER_POLL_INTERVAL_SECONDS},
        daemon=True,
    )
    callback_thread.start()
    try:
        host = callback_server.server_address[0]
        port = callback_server.server_address[1]
        _configure_interaction_endpoint(
            discord_fake_url,
            f"http://{host}:{port}/callback",
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
        kwargs={"poll_interval": _SERVER_POLL_INTERVAL_SECONDS},
        daemon=True,
    )
    callback_thread.start()
    try:
        host = callback_server.server_address[0]
        port = callback_server.server_address[1]
        _configure_interaction_endpoint(
            discord_fake_url,
            f"http://{host}:{port}/callback",
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


def test_discord_fake_records_deferred_interaction_completion_without_token(
    discord_fake_urls: tuple[str, str],
) -> None:
    """Expose ACK/completion ordering while discarding transient response data."""
    discord_fake_url, _ = discord_fake_urls
    _DeferredInteractionHandler.received_bodies = []
    callback_server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _DeferredInteractionHandler,
    )
    callback_thread = threading.Thread(
        target=callback_server.serve_forever,
        kwargs={"poll_interval": _SERVER_POLL_INTERVAL_SECONDS},
        daemon=True,
    )
    callback_thread.start()
    try:
        host = callback_server.server_address[0]
        port = callback_server.server_address[1]
        _configure_interaction_endpoint(
            discord_fake_url,
            f"http://{host}:{port}/callback",
        ).raise_for_status()
        delivered = requests.post(
            f"{discord_fake_url}/__testenv/interactions",
            json={
                "id": "700000000000000003",
                "type": 3,
                "application_id": STATE.application_id,
                "guild_id": STATE.guild_id,
                "channel_id": "400000000000000001",
                "token": "private-interaction-token",
                "member": {"user": {"id": "600000000000000001"}},
                "data": {"custom_id": "a:sc:claim:1:1:signature"},
            },
            timeout=5,
        )
        delivered.raise_for_status()
        completed = requests.post(
            f"{discord_fake_url}/__testenv/interaction-response",
            json={
                "application_id": STATE.application_id,
                "interaction_token": "private-interaction-token",
                "response": {
                    "type": 7,
                    "data": {
                        "content": "Private completion content.",
                        "components": [],
                    },
                },
            },
            timeout=5,
        )
        completed.raise_for_status()
    finally:
        callback_server.shutdown()
        callback_server.server_close()
        callback_thread.join(timeout=5)

    evidence = requests.get(f"{discord_fake_url}/__testenv/state", timeout=5).json()
    rendered = str(evidence)
    assert delivered.json() == {"status": 200, "response_type": 6}
    assert evidence["interactions"] == [
        {
            "interaction_id": "700000000000000003",
            "interaction_type": 3,
            "response_status": 200,
            "response_type": 6,
            "completed_response_type": 7,
            "completed_has_content": True,
            "completed_component_count": 0,
        }
    ]
    assert "private-interaction-token" not in rendered
    assert "Private completion content." not in rendered


def test_discord_fake_container_uses_the_azents_server_image(
    discord_provider_fake_container: DockerContainer,
    discord_provider_fake_url: str,
) -> None:
    """Start the fake in the same Python image used by Azents E2E processes."""
    del discord_provider_fake_container
    response = requests.get(f"{discord_provider_fake_url}/health", timeout=5)
    application = _sdk_call(
        discord_provider_fake_url,
        "fetch_application",
    )

    assert response.json() == {"status": "ok"}
    assert application.json()["verify_key"] == _DISCORD_VERIFY_KEY
    assert application.json()["bot_user_id"].isdigit()
