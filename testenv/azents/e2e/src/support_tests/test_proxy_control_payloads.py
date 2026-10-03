"""Typed fixture controls and provider projections without a listener or network."""

import json
from http.client import HTTPMessage
from pathlib import Path

import pytest

from support import image_generation_openai_proxy as proxy


class _ControlHandler(proxy._Handler):
    """Exercise only control dispatch; BaseHTTPRequestHandler is never initialized."""

    def __init__(self, path: str, body: bytes) -> None:
        self.path = path
        self.body = body
        self.headers = HTTPMessage()
        self.status: int | None = None
        self.value: object = None

    def _read_body(self) -> bytes:
        return self.body

    def _write_json(self, status: int, value: object) -> None:
        self.status = status
        self.value = value


def _oauth_body(provider: str) -> bytes:
    return json.dumps(
        {
            "provider": provider,
            "scenario": "fixture-account",
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
        }
    ).encode()


@pytest.mark.parametrize("provider", ["chatgpt", "xai"])
def test_oauth_scenario_decoder_returns_declared_account_fields(provider: str) -> None:
    scenario = proxy._decode_oauth_connection_scenario(_oauth_body(provider))
    assert scenario.provider == provider
    assert scenario.scenario == "fixture-account"
    assert scenario.access_token == "fixture-access"
    assert scenario.refresh_token == "fixture-refresh"


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"[]",
        b'{"provider":"unknown","scenario":"x","access_token":"x","refresh_token":"x"}',
        b'{"provider":"chatgpt","scenario":null,"access_token":"x","refresh_token":"x"}',
        b'{"provider":"chatgpt","scenario":"x","access_token":true,"refresh_token":"x"}',
        b'{"provider":"chatgpt","scenario":"x","access_token":"x","refresh_token":"x","extra":true}',
    ],
)
def test_invalid_local_oauth_control_never_mutates_queue(
    monkeypatch: pytest.MonkeyPatch, body: bytes
) -> None:
    monkeypatch.setattr(
        proxy._State, "oauth_connection_queues", {"chatgpt": [], "xai": []}
    )
    handler = _ControlHandler("/v1/_oauth_connection_scenarios", body)
    handler.do_POST()
    assert handler.status == 400
    assert handler.value == {"error": "invalid request"}
    assert proxy._State.oauth_connection_queues == {"chatgpt": [], "xai": []}


def test_device_authorization_reads_typed_queue_state_and_preserves_wire_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        proxy._State, "oauth_connection_queues", {"chatgpt": [], "xai": []}
    )
    monkeypatch.setattr(proxy._State, "oauth_connection_sessions", {})
    monkeypatch.setattr(proxy._State, "oauth_connection_sequence", 0)
    queue = _ControlHandler("/v1/_oauth_connection_scenarios", _oauth_body("chatgpt"))
    queue.do_POST()
    assert queue.status == 201
    connection_id = proxy._Handler._start_oauth_connection("chatgpt")
    assert connection_id == "chatgpt-1"
    account = proxy._Handler._oauth_connection(connection_id)
    assert isinstance(account, proxy._OAuthConnectionScenario)
    assert account.access_token == "fixture-access"
    handler = _ControlHandler(
        "/chatgpt/device/token",
        json.dumps(
            {"device_auth_id": connection_id, "user_code": "SDK-owned field"}
        ).encode(),
    )
    handler.do_POST()
    assert handler.status == 200
    assert handler.value == {
        "authorization_code": "chatgpt-1",
        "code_verifier": "deterministic-code-verifier",
    }


@pytest.mark.parametrize("value", [None, True, 3, "unknown-device"])
def test_missing_or_unknown_device_identity_preserves_404(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    monkeypatch.setattr(proxy._State, "oauth_connection_sessions", {})
    handler = _ControlHandler(
        "/chatgpt/device/token", json.dumps({"device_auth_id": value}).encode()
    )
    handler.do_POST()
    assert handler.status == 404
    assert handler.value == {"error": "unknown device authorization"}


def test_image_projection_keeps_provider_extra_fields_for_opaque_journal_egress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image = tmp_path / "fixture-image"
    image.write_bytes(b"fixture image")
    monkeypatch.setattr(proxy, "_IMAGE_PATH", image)
    monkeypatch.setattr(proxy._State, "openai_image_requests", [])
    payload = {
        "prompt": proxy._OPENAI_IMAGE_PROMPT,
        "model": "provider-owned-model",
        "size": "provider-owned-size",
    }
    request = proxy._decode_image_generation_request(json.dumps(payload).encode())
    assert request.prompt == proxy._OPENAI_IMAGE_PROMPT
    assert proxy._image_request_egress(request) == payload
    handler = _ControlHandler("/v1/images/generations", json.dumps(payload).encode())
    handler.do_POST()
    assert handler.status == 200
    assert proxy._State.openai_image_requests == [payload]


@pytest.mark.parametrize(
    "payload",
    [
        {"operation": "unknown", "path": "/tmp/example"},
        {"operation": "read", "path": None},
        {"operation": "read", "path": "/tmp/example", "nonce": True},
        {"operation": "read", "path": "/tmp/example", "unknown": 1},
    ],
)
def test_historical_control_rejects_invalid_or_unknown_fields(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        proxy._decode_historical_inspection_control(json.dumps(payload))


def test_historical_control_declares_omitted_and_null_nonce_behavior() -> None:
    without_nonce = proxy._decode_historical_inspection_control(
        '{"operation":"read","path":"/tmp/example"}'
    )
    nullable = proxy._decode_historical_inspection_control(
        '{"operation":"read","path":"/tmp/example","nonce":null}'
    )
    assert without_nonce == nullable
    assert without_nonce.operation == "read"
    assert without_nonce.path == "/tmp/example"
    assert without_nonce.nonce is None


def test_quiet_work_control_is_exact_and_keeps_scalar_compatibility_view() -> None:
    body = b'{"binding":"binding-quiet-123"}'
    control = proxy._decode_quiet_work_barrier_control(body)
    assert control is not None
    assert control.binding == "binding-quiet-123"
    assert proxy._external_channel_quiet_work_barrier_binding(body) == control.binding
    assert (
        proxy._decode_quiet_work_barrier_control(
            b'{"binding":"binding-quiet-123","unknown":true}'
        )
        is None
    )


def test_model_request_projects_fields_once_and_preserves_opaque_provider_extras() -> (
    None
):
    payload: dict[str, object] = {
        "model": "fixture-model",
        "stream": True,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Current "},
                    {"type": "input_image", "image_url": "provider-owned-image"},
                    {"type": "text", "text": "question"},
                ],
            },
            {
                "type": "function_call_output",
                "call_id": "call-1",
                "output": "completed",
            },
        ],
        "tools": [{"name": "fixture_tool", "type": "function", "provider_extra": True}],
        "provider_extra": {"future": "provider-owned value"},
    }
    request = proxy._decode_model_request(payload)
    assert request.model == "fixture-model"
    assert request.stream is True
    assert request.context is None
    assert request.input_items is not None and len(request.input_items) == 2
    assert proxy._last_user_text(request) == "Current question"
    assert proxy._request_has_named_tool_type(
        request, name="fixture_tool", tool_type="function"
    )
    assert proxy.has_current_tool_output(request, "call-1")
    assert proxy._model_request_egress(request) == payload
    assert request.matching_text == json.dumps(payload, ensure_ascii=False)
    payload["model"] = "mutated-after-ingress"
    assert request.model == "fixture-model"
    assert proxy._model_request_egress(request)["model"] == "fixture-model"


def test_model_projection_preserves_missing_null_and_optional_type_tolerance() -> None:
    request = proxy._decode_model_request(
        {
            "model": 3,
            "stream": 1,
            "previous_response_id": False,
            "input": None,
            "messages": [{"role": "user", "content": "Null input suppresses fallback"}],
        }
    )
    assert request.model is None
    assert request.stream is False
    assert request.previous_response_id is None
    assert request.input_items is None
    assert proxy._last_user_text(request) is None
    messages = proxy._decode_model_request(
        {"messages": [{"role": "user", "content": "Fallback input"}]}
    )
    assert proxy._last_user_text(messages) == "Fallback input"
    assert messages.responses_input_present is False


class _TypedDispatchHandler(_ControlHandler):
    """Observe only the typed application handoff, not a provider or transport."""

    def __init__(self, body: bytes) -> None:
        super().__init__("/v1/responses", body)
        self.captured: proxy._ModelRequest | None = None
        self.original_body: bytes | None = None

    def _dispatch_model_request(
        self, request: proxy._ModelRequestInput, body: bytes
    ) -> None:
        assert isinstance(request, proxy._ModelRequest)
        self.captured = request
        self.original_body = body

    def _proxy(self, body: bytes | None = None) -> None:
        raise AssertionError("This contract must not acquire a transport.")


def test_model_http_ingress_hands_typed_request_and_original_body_to_dispatch() -> None:
    body = json.dumps(
        {
            "model": "fixture-model",
            "input": [{"role": "user", "content": "Ordinary fixture handoff"}],
            "provider_extra": True,
        }
    ).encode()
    handler = _TypedDispatchHandler(body)
    handler.do_POST()
    assert handler.captured is not None
    assert handler.captured.model == "fixture-model"
    assert handler.original_body == body
    assert proxy._model_request_egress(handler.captured)["provider_extra"] is True


@pytest.mark.parametrize("body", [b"{", b"[]", b"\xff"])
def test_invalid_model_ingress_fails_before_state_or_transport(body: bytes) -> None:
    handler = _TypedDispatchHandler(body)
    handler.do_POST()
    assert handler.status == 400
    assert handler.value == {"error": {"message": "invalid request"}}
    assert handler.captured is None
    assert handler.original_body is None
