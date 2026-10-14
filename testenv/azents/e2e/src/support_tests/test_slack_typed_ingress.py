"""Listener-free contracts for Slack fake ingress and private evidence."""

import base64
import io
import json
import subprocess
import sys
from collections.abc import Mapping
from email.message import Message
from pathlib import Path
from typing import NamedTuple

import pytest
from pydantic import ValidationError

from support import slack_provider_fake as fake
from support.slack_fake_observations import (
    BarrierObservation,
    FakeEvidenceObservation,
    OAuthTokenObservation,
    UploadTargetObservation,
)


class _Reply(NamedTuple):
    status: int
    body: dict[str, object]


class _CaptureHandler(fake.SlackHTTPHandler):
    """Call the real POST routes without initializing a server or socket."""

    def __init__(
        self, state: fake.FakeState, path: str, raw: bytes, content_type: str
    ) -> None:
        _CaptureHandler.state = state
        self.path = path
        self.rfile = io.BytesIO(raw)
        self.headers = Message()
        self.headers["Content-Length"] = str(len(raw))
        self.headers["Content-Type"] = content_type
        self.reply: _Reply | None = None

    def _json_response(
        self,
        status: int,
        payload: Mapping[str, object],
        *,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self.reply = _Reply(status, dict(payload))


def _post(state: fake.FakeState, path: str, payload: object) -> _Reply:
    handler = _CaptureHandler(
        state, path, json.dumps(payload).encode(), "application/json"
    )
    handler.do_POST()
    assert handler.reply is not None
    return handler.reply


@pytest.mark.parametrize(
    "payload",
    [
        {"oauth": {"unknown": "private-secret"}},
        {"oauth": {"client_id": 1}},
        {"oauth": {"client_secret": ""}},
        {"oauth": {"delay_seconds": True}},
        {"oauth": {"delay_seconds": 6}},
        {"oauth": {"token_scenario": ["success"]}},
        {"history_retry_after_seconds": [True]},
        {"delivery_scenario_sequences": {"chat.update": []}},
        {"socket_sessions": []},
        {"socket_sessions": [{"envelopes": [], "extra": "private-secret"}]},
        {"socket_sessions": [{"envelopes": [False]}]},
        {"files": [{"id": "F", "content_base64": "%%"}]},
        {"provider_app_id": False},
        {"unknown": "private-secret"},
    ],
)
def test_private_configuration_rejects_invalid_input_without_echo_or_partial_state(
    payload: object,
) -> None:
    state = fake.FakeState()
    with pytest.raises(ValueError) as caught:
        state.configure(payload)
    assert "private-secret" not in str(caught.value)
    assert state.provider_app_id == "A-E2E"
    assert state.oauth.client_id == "slack-oauth-client"
    assert _post(state, "/__testenv/configure", payload) == _Reply(
        422, {"error": "invalid_configuration"}
    )


def test_config_preserves_nulls_coercion_and_malformed_provider_metadata() -> None:
    state = fake.FakeState()
    state.configure(
        {"provider_app_id": "A-custom", "oauth": {"client_id": "private-client"}}
    )
    state.configure(
        {
            "provider_app_id": None,
            "oauth": {"client_id": None},
            "delivery_scenarios": {"chat.update": 1},
        }
    )
    assert state.provider_app_id == "A-custom"
    assert state.oauth.client_id == "private-client"
    assert state.delivery_scenarios == {"chat.update": "1"}
    state.configure(
        {
            "files": [
                {
                    "id": "F",
                    "name": None,
                    "size": "intentionally-invalid",
                    "content_base64": base64.b64encode(b"private-bytes").decode(),
                }
            ]
        }
    )
    file = state.files["F"]
    assert file.content == b"private-bytes"
    assert file.metadata == {"id": "F", "name": None, "size": "intentionally-invalid"}
    assert "private-bytes" not in json.dumps(state.evidence())


@pytest.mark.parametrize(
    "value",
    [
        None,
        [],
        False,
        {"operation": [], "occurrence": 1},
        {"operation": "chat.update", "occurrence": True},
        {"operation": "chat.update", "occurrence": 0},
    ],
)
def test_barrier_ingress_rejects_malformed_control(value: object) -> None:
    assert _post(fake.FakeState(), "/__testenv/barrier", value) == _Reply(
        422, {"error": "invalid_barrier"}
    )


def test_barrier_preserves_ignored_extensions_and_declared_state() -> None:
    state = fake.FakeState()
    state.configure_operation_barrier(
        {"operation": "chat.update", "occurrence": 2, "future": "private-secret"}
    )
    barrier = BarrierObservation.model_validate(state.operation_barrier_evidence())
    assert barrier.operation == "chat.update" and barrier.occurrence == 2
    assert not barrier.reached and not barrier.released
    assert "private-secret" not in json.dumps(barrier.model_dump())


@pytest.mark.parametrize(
    "blocks", [None, False, "blocks", [], [None], [{"elements": [None]}]]
)
def test_malformed_optional_block_shapes_decode_once_to_empty_controls(
    blocks: object,
) -> None:
    message = fake.decode_message(
        {"text": 1, "channel": None, "blocks": blocks, "provider_extra": "opaque"}
    )
    assert message.text is None and message.channel is None
    assert fake._approval_request_id(message) is None
    assert fake._block_action_handoffs(message) == []


def test_typed_message_control_capture_preserves_private_handoffs_and_plan_wire() -> (
    None
):
    state = fake.FakeState()
    blocks = [
        {
            "type": "actions",
            "block_id": "B",
            "elements": [
                {
                    "type": "button",
                    "action_id": "azents_agent_selector_open",
                    "value": "signed-private-value",
                },
                {
                    "type": "button",
                    "action_id": "azents_agent_selector_open",
                    "value": None,
                },
                {
                    "type": "button",
                    "url": "https://example.invalid/external-channel/access/approval-1",
                },
            ],
        }
    ]
    assert _post(
        state,
        "/api/chat.postMessage",
        {"channel": "C", "text": "private-copy", "blocks": blocks},
    ) == _Reply(200, {"ok": True, "ts": "1721600100.000001"})
    evidence = FakeEvidenceObservation.model_validate(state.evidence())
    assert evidence.deliveries[0]["selector_admission_id"] == "signed-private-value"
    assert evidence.deliveries[0]["approval_request_id"] == "approval-1"
    # Current selector admission evidence is durable; signed model/action
    # values stay transient.
    transient = state.transient_action("azents_agent_selector_open")
    assert transient == {"action_id": "azents_agent_selector_open", "block_id": "B"}
    assert "private-copy" not in json.dumps(evidence.model_dump())
    plan = [{"type": "plan", "provider_extra": {"opaque": True}}, None]
    assert fake.decode_message({"blocks": plan}).has_plan
    _post(state, "/api/chat.update", {"blocks": plan, "text": "current-plan"})
    assert state.deliveries[-1]["blocks"] == plan


def test_view_control_tree_is_typed_and_private_metadata_never_becomes_evidence() -> (
    None
):
    state = fake.FakeState()
    payload = {
        "trigger_id": "private-trigger",
        "view": {
            "callback_id": "azents_model_apply",
            "private_metadata": "private-metadata",
            "submit": {},
            "blocks": [
                {
                    "block_id": "block",
                    "element": {
                        "type": "static_select",
                        "action_id": "choose",
                        "options": [
                            {"value": "signed-option", "text": {"text": "Option"}},
                        ],
                        "initial_option": {"value": "signed-initial"},
                    },
                }
            ],
        },
    }
    assert _post(state, "/api/views.open", payload).status == 200
    handoff = state.transient_view("model")
    assert handoff is not None
    assert handoff["option_values"] == {"choose": ["signed-option", "signed-initial"]}
    assert handoff["option_labels"] == {"choose": {"signed-option": "Option"}}
    wire = json.dumps(state.evidence())
    for secret in (
        "private-trigger",
        "private-metadata",
        "signed-option",
        "signed-initial",
        "Option",
    ):
        assert secret not in wire
    assert state.views[0]["control_count"] == 1
    assert state.views[0]["option_count"] == 2


def test_upload_lifecycle_and_oauth_basic_preserve_sdk_form_contract() -> None:
    state = fake.FakeState()
    handler = _CaptureHandler(
        state,
        "/api/files.getUploadURLExternal",
        b"length=3&filename=opaque.txt",
        "application/x-www-form-urlencoded",
    )
    handler.do_POST()
    assert handler.reply is not None
    target = UploadTargetObservation.model_validate(handler.reply.body)
    assert state.record_upload(
        file_id=target.file_id, received_length=3, content_sha256="digest"
    )
    assert _post(
        state,
        "/api/files.completeUploadExternal",
        {"files": [{"id": target.file_id}], "channel_id": "C"},
    ) == _Reply(200, {"ok": True, "files": []})
    assert state.deliveries[-1]["total_bytes"] == 3
    request = fake.decode_oauth_exchange(
        {"client_id": "", "client_secret": "", "code_verifier": False}
    )
    basic = "Basic " + base64.b64encode(b"basic-client:basic-secret").decode()
    assert fake._oauth_client_credentials(
        request, basic
    ) == fake._OAuthClientCredentials("", "")
    assert request.pkce_present
    fallback = fake.decode_oauth_exchange({"client_id": 1, "client_secret": None})
    assert fake._oauth_client_credentials(
        fallback, basic
    ) == fake._OAuthClientCredentials("basic-client", "basic-secret")


def test_socket_projection_keeps_provider_wire_opaque_and_ack_identity_validated() -> (
    None
):
    state = fake.FakeState()
    envelope = {
        "envelope_id": "Env",
        "payload": ["intentionally malformed provider event"],
        "extension": None,
    }
    state.configure({"socket_sessions": [{"envelopes": [envelope]}]})
    session = state.socket_sessions[0]
    assert session.envelopes[0].envelope_id == "Env"
    assert session.envelopes[0].wire == envelope
    assert fake.decode_acknowledgement({"envelope_id": "", "extension": True}) == ""
    assert fake.decode_acknowledgement({"envelope_id": 1}) is None


@pytest.mark.parametrize(
    "model,payload",
    [
        (UploadTargetObservation, {"ok": True, "upload_url": 1, "file_id": "F"}),
        (
            BarrierObservation,
            {
                "operation": "chat.update",
                "occurrence": 1,
                "request_count": 1,
                "reached": "true",
                "released": False,
            },
        ),
        (
            OAuthTokenObservation,
            {"ok": True, "access_token": None, "token_type": "Bearer"},
        ),
    ],
)
def test_response_decision_fields_validate_at_ingress(
    model: type[UploadTargetObservation]
    | type[BarrierObservation]
    | type[OAuthTokenObservation],
    payload: object,
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_fake_imports_as_an_isolated_stdlib_only_standalone_script() -> None:
    """Mirror the single-script Python alpine runtime without site packages."""
    script = Path(fake.__file__).resolve()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            "import runpy,sys; module=runpy.run_path(sys.argv[1]); "
            "module['FakeState']().configure({})",
            str(script),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
