"""Discord fixture ingress contracts without listeners or provider resources."""

import dataclasses
import json
from collections.abc import Mapping
from http.client import HTTPMessage
from typing import ClassVar

import pytest

from support import discord_provider_fake as fake


class _Handler(fake.DiscordHTTPHandler):
    """Exercise native dispatch with an in-memory wire body and response writer."""

    state: ClassVar[fake.FakeState]

    def __init__(self, state: fake.FakeState, path: str, payload: object) -> None:
        type(self).state = state
        self.path = path
        self.command = "POST"
        self.body = json.dumps(payload).encode()
        self.headers = HTTPMessage()
        self.recorded: list[tuple[int, object]] = []

    def _read_body(self) -> bytes:
        return self.body

    def _json_response(
        self,
        status: int,
        payload: object,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        del headers
        self.recorded.append((status, payload))


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _list(value: object) -> list[object]:
    assert isinstance(value, list)
    return value


def test_configuration_decodes_before_any_state_mutation() -> None:
    state = fake.FakeState()
    state.oauth.requests.append({"retained": True})
    original = state.evidence()
    with pytest.raises(ValueError, match="history_pages"):
        state.configure(
            {
                "application_id": "replacement",
                "oauth": {"user_id": "new-user"},
                "history_pages": "malformed",
            }
        )
    assert state.application_id == "100000000000000001"
    assert state.oauth.user_id == "710000000000000001"
    assert state.evidence() == original


def test_configuration_omitted_and_null_retain_existing_settings() -> None:
    state = fake.FakeState()
    state.configure(
        {
            "guild_id": "42",
            "allow_synthetic_roots": True,
            "oauth": {"username": "fixture", "delay_seconds": 2},
        }
    )
    state.configure(
        {
            "guild_id": None,
            "allow_synthetic_roots": None,
            "oauth": {"username": None, "delay_seconds": None},
        }
    )
    assert state.guild_id == "42"
    assert state.allow_synthetic_roots is True
    assert state.oauth.username == "fixture"
    assert state.oauth.delay_seconds == 2
    assert dataclasses.is_dataclass(fake._decode_fake_configuration({}))
    assert dataclasses.is_dataclass(fake._decode_oauth_configuration({}))


@pytest.mark.parametrize(
    "payload",
    [
        {"future": True},
        {"guild_id": 3},
        {"allow_synthetic_roots": 1},
        {"oauth": {"username": 3}},
        {"oauth": {"authorize_scenario": []}},
        {"oauth": {"token_scenario": {}}},
        {"oauth": {"delay_seconds": True}},
        {"api_scenarios": {"operation": "unsupported"}},
        {"retry_after_sequences": {"operation": [True]}},
        {
            "gateway_dispatches": [
                {"sequence": True, "event_type": "MESSAGE_CREATE", "payload": {}}
            ]
        },
    ],
)
def test_invalid_configuration_fails_without_changing_state(
    payload: dict[str, object],
) -> None:
    state = fake.FakeState()
    state.record_request("retained", method="GET")
    original = state.evidence()
    with pytest.raises(ValueError):
        state.configure(payload)
    assert state.evidence() == original


def test_scenario_update_is_atomic_and_does_not_reset_provider_state() -> None:
    state = fake.FakeState()
    created = state.create_message(channel_id="55", nonce="nonce")
    state.configure_scenarios({"api_scenarios": {"get_message": "not_found"}})
    before = state.evidence()
    with pytest.raises(ValueError):
        state.configure_scenarios(
            {
                "api_scenarios": {"get_message": "ok"},
                "retry_after_sequences": {"get_message": [False]},
            }
        )
    assert state.evidence() == before
    assert state.scenario("get_message") == "not_found"
    assert state.message_exists(channel_id="55", message_id=created.message_id)


@pytest.mark.parametrize(
    "operation,arguments,expected",
    [
        ("login", {}, fake._SdkEmpty),
        ("fetch_application", {}, fake._SdkEmpty),
        (
            "list_guild_commands",
            {"application_id": "1", "guild_id": "2"},
            fake._SdkIdentity,
        ),
        (
            "update_guild_command",
            {"command_id": "3", "name": "name", "command_type": 3},
            fake._SdkCommandUpdate,
        ),
        ("delete_guild_command", {"command_id": "3"}, fake._SdkCommandDelete),
        (
            "fetch_root_thread",
            {"guild_id": "2", "parent_channel_id": "4", "root_message_id": "5"},
            fake._SdkRoot,
        ),
        (
            "create_thread",
            {
                "guild_id": "2",
                "parent_channel_id": "4",
                "root_message_id": "5",
                "name": "name",
            },
            fake._SdkCreateThread,
        ),
        ("fetch_thread", {"guild_id": "2", "channel_id": "4"}, fake._SdkThreadTitle),
        (
            "update_thread_name",
            {"guild_id": "2", "channel_id": "4", "name": "name"},
            fake._SdkThreadTitle,
        ),
        (
            "create_message",
            {"guild_id": "2", "channel_id": "4", "nonce": "nonce"},
            fake._SdkMessage,
        ),
        (
            "update_message",
            {"guild_id": "2", "channel_id": "4", "message_id": "5"},
            fake._SdkMessage,
        ),
        (
            "delete_message",
            {"guild_id": "2", "channel_id": "4", "message_id": "5"},
            fake._SdkMessage,
        ),
        (
            "fetch_attachment",
            {
                "guild_id": "2",
                "channel_id": "4",
                "message_id": "5",
                "attachment_id": "6",
            },
            fake._SdkAttachment,
        ),
        (
            "fetch_message_projection",
            {"guild_id": "2", "channel_id": "4", "message_id": "5"},
            fake._SdkMessageIdentity,
        ),
        (
            "fetch_history_projections",
            {"guild_id": "2", "channel_id": "4", "before_message_id": "5", "limit": 10},
            fake._SdkHistory,
        ),
    ],
)
def test_every_sdk_operation_decodes_at_wire_ingress(
    operation: str,
    arguments: dict[str, object],
    expected: type[object],
) -> None:
    wire = json.loads(
        json.dumps(
            {
                "operation": operation,
                "arguments": arguments,
                "extension": {"opaque": True},
            }
        )
    )
    request = fake._decode_sdk_request(wire)
    assert request.operation == operation
    assert isinstance(request.arguments, expected)
    assert dataclasses.is_dataclass(request.arguments)


@pytest.mark.parametrize(
    "operation,arguments",
    [
        (
            "create_message",
            {"guild_id": "2", "channel_id": "4", "nonce": "n", "suppress_embeds": None},
        ),
        (
            "create_message",
            {"guild_id": "2", "channel_id": "4", "nonce": "n", "suppress_embeds": 1},
        ),
        (
            "fetch_history_projections",
            {
                "guild_id": "2",
                "channel_id": "4",
                "before_message_id": "5",
                "limit": True,
            },
        ),
        (
            "update_guild_command",
            {"command_id": "3", "name": "name", "command_type": True},
        ),
        (
            "create_thread",
            {
                "guild_id": "2",
                "parent_channel_id": "4",
                "root_message_id": "5",
                "name": "",
            },
        ),
    ],
)
def test_invalid_sdk_input_never_records_an_operation(
    operation: str,
    arguments: dict[str, object],
) -> None:
    state = fake.FakeState()
    handler = _Handler(
        state, "/__testenv/sdk", {"operation": operation, "arguments": arguments}
    )
    handler.do_POST()
    assert handler.recorded[0][0] == 400
    assert state.evidence()["requests"] == []
    assert state.evidence()["operations"] == []


def test_sdk_message_dispatch_uses_typed_redacted_projection() -> None:
    state = fake.FakeState()
    body = {
        "operation": "create_message",
        "arguments": {
            "guild_id": state.guild_id,
            "channel_id": "55",
            "nonce": "nonce",
            "content": "PRIVATE CONTENT",
            "provider_extension": {"secret": "PRIVATE EXTENSION"},
            "suppress_embeds": False,
            "components": [
                {
                    "components": [
                        {"custom_id": "a:transient-private", "label": "PRIVATE LABEL"},
                        {"url": "https://azents.example/w/workspace/session"},
                    ]
                }
            ],
        },
    }
    handler = _Handler(state, "/__testenv/sdk", body)
    handler.do_POST()
    assert handler.recorded[0][0] == 200
    delivery = state.evidence()["deliveries"]
    assert delivery == [
        {
            "operation": "create_message",
            "channel_id": "55",
            "message_id": "400000000000000001",
            "outcome": "created",
            "safe_category": "activity_tracker",
            "session_path": "/w/workspace/session",
            "action_ids": ["view_azents_session"],
            "suppress_embeds": False,
        }
    ]
    evidence = json.dumps(state.evidence())
    assert "PRIVATE" not in evidence
    assert "transient-private" not in evidence
    assert (
        state.consume_transient_component_custom_id("settings", channel_id="55")
        == "a:transient-private"
    )


def test_delete_preserves_ignored_suppress_embeds_compatibility() -> None:
    state = fake.FakeState()
    message = state.create_message(channel_id="55", nonce=None)
    handler = _Handler(
        state,
        "/__testenv/sdk",
        {
            "operation": "delete_message",
            "arguments": {
                "guild_id": state.guild_id,
                "channel_id": "55",
                "message_id": message.message_id,
                "suppress_embeds": "ignored",
            },
        },
    )
    handler.do_POST()
    assert handler.recorded == [(200, {})]
    assert not state.message_exists(channel_id="55", message_id=message.message_id)


def test_configured_provider_messages_remain_opaque_after_typed_selection() -> None:
    state = fake.FakeState()
    raw = {
        "id": "5",
        "channel_id": "55",
        "content": 17,
        "thread": {"id": "66", "name": False},
        "attachments": [
            {
                "id": "7",
                "filename": False,
                "size": "bad",
                "url": {"deliberate": "malformed"},
            }
        ],
        "future_provider_field": {"PRIVATE": True},
    }
    state.configure(
        {
            "root_messages": [raw],
            "history_pages": [[raw]],
            "gateway_dispatches": [
                {"sequence": 2, "event_type": "MESSAGE_CREATE", "payload": raw}
            ],
        }
    )
    assert state.root_message(parent_channel_id="55", root_message_id="5") == raw
    assert state.history_page(channel_id="55", before=None, limit=10).messages == [raw]
    assert state.get_root_thread(parent_channel_id="55", root_message_id="5") == "66"
    gateway = state.gateway_start(2)
    assert gateway.dispatches[0].wire()["payload"] == raw
    state.gateway_dispatch_sent(gateway.dispatches[0])
    assert "PRIVATE" not in json.dumps(state.evidence())
    handler = _Handler(
        state,
        "/__testenv/sdk",
        {
            "operation": "fetch_attachment",
            "arguments": {
                "guild_id": state.guild_id,
                "channel_id": "55",
                "message_id": "5",
                "attachment_id": "7",
            },
        },
    )
    handler.do_POST()
    assert handler.recorded == [
        (
            200,
            {
                "attachment_id": "7",
                "filename": False,
                "size": "bad",
                "content_type": None,
                "download_url": {"deliberate": "malformed"},
            },
        )
    ]


@pytest.mark.parametrize(
    "payload",
    [{"target_guild_id": "2", "resumed": 1}, {"target_guild_id": 2, "resumed": False}],
)
def test_gateway_control_rejects_primitive_coercion(payload: dict[str, object]) -> None:
    state = fake.FakeState()
    handler = _Handler(state, "/__testenv/gateway", payload)
    handler.do_POST()
    assert handler.recorded[0][0] == 400
    assert _mapping(state.evidence()["gateway"])["connections"] == 0


def test_typing_state_consumes_declared_redacted_target() -> None:
    state = fake.FakeState()
    handler = _Handler(
        state,
        "/__testenv/typing",
        {
            "targets": [
                {"guild_id": state.guild_id, "channel_id": "55", "work_cycle_count": 2}
            ]
        },
    )
    handler.do_POST()
    assert handler.recorded == [(204, None)]
    assert _mapping(state.evidence()["typing"])["pulses"] == [
        {"guild_id": state.guild_id, "channel_id": "55", "work_cycle_count": 2}
    ]


def test_deferred_response_projection_retains_no_content_or_token() -> None:
    state = fake.FakeState()
    state._interaction_tokens["PRIVATE TOKEN"] = ("id", "55")
    response = {
        "type": 4,
        "data": {"flags": 64, "content": "PRIVATE CONTENT", "components": []},
    }
    handler = _Handler(
        state,
        "/__testenv/interaction-response",
        {
            "application_id": state.application_id,
            "interaction_token": "PRIVATE TOKEN",
            "response": response,
        },
    )
    handler.do_POST()
    assert handler.recorded == [(200, {"status": "ok"})]
    assert state._interaction_completions["id"] == {
        "completed_response_type": 4,
        "completed_ephemeral": True,
        "completed_has_content": True,
        "completed_component_count": 0,
    }
    assert "PRIVATE" not in json.dumps(state.evidence())


def test_oauth_invalid_form_decodes_to_rejection_not_coerced_credentials() -> None:
    oauth = fake.DiscordOAuthState()
    result = oauth.exchange(
        {
            "client_id": 1,
            "client_secret": True,
            "code": [],
            "redirect_uri": None,
            "code_verifier": {},
        },
        "",
    )
    assert result.status == 400
    assert result.payload == {"error": "invalid_grant"}
    assert _mapping(_list(oauth.evidence()["requests"])[0])["client_valid"] is False
