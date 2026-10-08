"""Typed synthetic GitHub ingress without sockets, Docker or provider calls."""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from http.client import HTTPMessage
from io import BytesIO

import pytest

from support import github_validation_proxy as proxy


@dataclass(frozen=True)
class _Response:
    status: int
    payload: Mapping[str, object] | None


class _WireHandler(proxy.Handler):
    """Exercise handler dispatch with in-memory request and response streams."""

    def __init__(self, path: str, body: bytes, token: str | None) -> None:
        self.path = path
        self.headers = HTTPMessage()
        self.headers["Content-Length"] = str(len(body))
        if token is not None:
            self.headers["Authorization"] = "Bearer " + token
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.response: _Response | None = None

    def _json_response(self, status: int, payload: Mapping[str, object]) -> None:
        self.response = _Response(status, payload)

    def send_response(self, code: int, message: str | None = None) -> None:
        self.response = _Response(code, None)

    def send_header(self, keyword: str, value: str) -> None:
        pass

    def end_headers(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _isolated_state() -> Iterator[None]:
    _WireHandler.scenario = "user_success"
    _WireHandler.app_request_count = 0
    _WireHandler.oauth_request_count = 0
    _WireHandler.revocation_request_count = 0
    _WireHandler.mcp_call_count = 0
    _WireHandler.mcp_accounts = []
    _WireHandler.user_tokens = {"synthetic-existing": "connected-user"}
    yield
    _WireHandler.user_tokens = {}
    _WireHandler.mcp_accounts = []


def _body(value: object) -> bytes:
    return json.dumps(value).encode()


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"\xff",
        b"null",
        b"[]",
        b"{}",
        b'{"scenario":null}',
        b'{"scenario":42}',
        b'{"scenario":"unknown"}',
        b'{"scenario":"user_success","unexpected":true}',
    ],
)
def test_invalid_scenario_does_not_mutate_state(body: bytes) -> None:
    handler = _WireHandler("/__testenv/scenario", body, None)
    handler.do_POST()
    assert handler.response == _Response(422, {"error": "unsupported_scenario"})
    assert _WireHandler.scenario == "user_success"
    assert _WireHandler.user_tokens == {"synthetic-existing": "connected-user"}


def test_scenario_decoder_and_reset_preserve_saved_tokens() -> None:
    request = proxy._decode_scenario(_body({"scenario": "user_cleanup_failure"}))
    assert request.scenario == "user_cleanup_failure"
    _WireHandler.mcp_call_count = 2
    handler = _WireHandler(
        "/__testenv/scenario", _body({"scenario": request.scenario}), None
    )
    handler.do_POST()
    assert handler.response == _Response(200, {"scenario": request.scenario})
    assert _WireHandler.mcp_call_count == 0
    assert _WireHandler.user_tokens == {"synthetic-existing": "connected-user"}


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"null",
        b"[]",
        b"{}",
        b'{"code":null}',
        b'{"code":42}',
        b'{"code":""}',
        b'{"code":"e2e-user-main","client_id":null}',
        b'{"code":"e2e-user-main","unexpected":"secret"}',
    ],
)
def test_invalid_oauth_never_issues_token(body: bytes) -> None:
    handler = _WireHandler("/login/oauth/access_token", body, None)
    handler.do_POST()
    assert handler.response == _Response(400, {"error": "invalid_synthetic_request"})
    assert _WireHandler.user_tokens == {"synthetic-existing": "connected-user"}


@pytest.mark.parametrize(
    ("code", "scenario", "account"),
    [
        ("e2e-user-main", "user_success", "connected-user"),
        ("e2e-user-replacement", "user_success", "replacement-user"),
        ("e2e-user-expiring", "user_expiring", "connected-user"),
    ],
)
def test_oauth_accepts_actual_sdk_envelope(
    code: str, scenario: str, account: str
) -> None:
    _WireHandler.scenario = scenario
    body = _body(
        {
            "code": code,
            "client_id": "synthetic-client",
            "client_secret": "synthetic-secret",
            "redirect_uri": "https://web.example/oauth/github/callback",
            "code_verifier": "synthetic-pkce",
        }
    )
    handler = _WireHandler("/login/oauth/access_token", body, None)
    handler.do_POST()
    token = "synthetic-token-" + code
    expected: dict[str, object] = {"access_token": token, "token_type": "bearer"}
    if scenario == "user_expiring":
        expected.update(
            expires_in=28800, refresh_token="synthetic-refresh-not-supported"
        )
    assert handler.response == _Response(200, expected)
    assert _WireHandler.user_tokens[token] == account


def test_oauth_optional_fields_and_bad_code_contract() -> None:
    assert proxy._decode_oauth(_body({"code": "ordinary-code"})).code == "ordinary-code"
    handler = _WireHandler(
        "/login/oauth/access_token", _body({"code": "ordinary-code"}), None
    )
    handler.do_POST()
    assert handler.response == _Response(200, {"error": "bad_verification_code"})


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"null",
        b"[]",
        b"{}",
        b'{"access_token":null}',
        b'{"access_token":5}',
        b'{"access_token":""}',
        b'{"access_token":"synthetic-existing","unknown":true}',
    ],
)
def test_invalid_revocation_never_removes_or_counts_token(body: bytes) -> None:
    handler = _WireHandler("/applications/client/token", body, None)
    handler.do_DELETE()
    assert handler.response == _Response(400, {"error": "invalid_synthetic_request"})
    assert _WireHandler.revocation_request_count == 0
    assert _WireHandler.user_tokens == {"synthetic-existing": "connected-user"}


@pytest.mark.parametrize("failure", [False, True])
def test_revocation_targets_only_the_validated_token(failure: bool) -> None:
    _WireHandler.user_tokens["synthetic-replacement"] = "replacement-user"
    if failure:
        _WireHandler.scenario = "user_cleanup_failure"
    handler = _WireHandler(
        "/applications/client/token",
        _body({"access_token": "synthetic-existing"}),
        None,
    )
    handler.do_DELETE()
    assert _WireHandler.revocation_request_count == 1
    assert _WireHandler.user_tokens["synthetic-replacement"] == "replacement-user"
    assert ("synthetic-existing" in _WireHandler.user_tokens) is failure
    assert handler.response == (
        _Response(503, {"message": "Synthetic cleanup unavailable"})
        if failure
        else _Response(204, None)
    )


def _rpc(method: str, identifier: str | int | None, params: object) -> bytes:
    return _body(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
    )


def test_initialize_accepts_mcp_client_capabilities_and_metadata() -> None:
    handler = _WireHandler(
        "/mcp",
        _rpc(
            "initialize",
            1,
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {"roots": {"listChanged": True}},
                "clientInfo": {
                    "name": "mcp",
                    "version": "2.2.0",
                    "title": "SDK client",
                    "future": {"extension": True},
                },
                "_meta": {"trace": "fixture"},
            },
        ),
        "synthetic-existing",
    )
    handler.do_POST()
    assert handler.response == _Response(
        200,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic-github", "version": "1"},
            },
        },
    )
    assert _WireHandler.mcp_call_count == 0


@pytest.mark.parametrize("identifier", [None, "fixture-id", 7])
def test_ping_preserves_ids_and_explicit_null_acknowledgement(
    identifier: str | int | None,
) -> None:
    handler = _WireHandler("/mcp", _rpc("ping", identifier, {}), "synthetic-existing")
    handler.do_POST()
    assert handler.response == (
        _Response(202, None)
        if identifier is None
        else _Response(200, {"jsonrpc": "2.0", "id": identifier, "result": {}})
    )


def test_initialized_notification_without_id_is_acknowledged() -> None:
    handler = _WireHandler(
        "/mcp",
        _body({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        "synthetic-existing",
    )
    handler.do_POST()
    assert handler.response == _Response(202, None)
    assert _WireHandler.mcp_call_count == 0


def test_tools_list_accepts_optional_metadata_and_exposes_original_schemas() -> None:
    handler = _WireHandler(
        "/mcp", _rpc("tools/list", 1, {"_meta": {}}), "synthetic-existing"
    )
    handler.do_POST()
    assert handler.response is not None
    assert handler.response.status == 200
    assert handler.response.payload is not None
    result = handler.response.payload["result"]
    assert isinstance(result, dict)
    tools = result["tools"]
    assert [item["name"] for item in tools] == ["get_me", "get_file_contents"]
    assert tools[1]["inputSchema"]["required"] == ["owner", "repo", "path"]


@pytest.mark.parametrize(
    "params",
    [
        {"name": "get_me"},
        {"name": "get_me", "arguments": {}, "_meta": {"progressToken": 1}},
        {
            "name": "get_file_contents",
            "arguments": {"owner": "connected-user", "repo": "fixture", "path": ""},
        },
        {
            "name": "get_file_contents",
            "arguments": {
                "owner": "research-team",
                "repo": "fixture",
                "path": "README.md",
            },
        },
    ],
)
def test_mcp_valid_calls_use_typed_dispatch(params: dict[str, object]) -> None:
    handler = _WireHandler(
        "/mcp", _rpc("tools/call", "call", params), "synthetic-existing"
    )
    handler.do_POST()
    assert handler.response is not None
    assert handler.response.status == 200
    assert _WireHandler.mcp_call_count == 1
    assert _WireHandler.mcp_accounts == ["connected-user"]


def test_denied_target_does_not_invalidate_account() -> None:
    handler = _WireHandler(
        "/mcp",
        _rpc(
            "tools/call",
            1,
            {
                "name": "get_file_contents",
                "arguments": {
                    "owner": "restricted-team",
                    "repo": "fixture",
                    "path": "README.md",
                },
            },
        ),
        "synthetic-existing",
    )
    handler.do_POST()
    assert handler.response == _Response(
        403, {"message": "Synthetic repository permission denied"}
    )
    assert _WireHandler.user_tokens["synthetic-existing"] == "connected-user"


@pytest.mark.parametrize(
    "body",
    [
        b"invalid",
        b"null",
        b"[]",
        b"{}",
        _rpc("tools/call", True, {"name": "get_me"}),
        _rpc("tools/call", 1, None),
        _rpc("tools/call", 1, {"name": "unknown"}),
        _rpc("tools/call", 1, {"name": "get_me", "arguments": None}),
        _rpc("tools/call", 1, {"name": "get_me", "arguments": {"extra": 1}}),
        _rpc("tools/call", 1, {"name": "get_me", "unknown": "secret"}),
        _rpc("tools/call", 1, {"name": "get_file_contents", "arguments": {"owner": 1}}),
        _rpc("initialize", 1, {"protocolVersion": "2025-06-18", "capabilities": None}),
        _rpc("tools/list", 1, None),
        _rpc("tools/list", 1, {"cursor": None}),
        _rpc("unknown", 1, {}),
        b'{"jsonrpc":"2.0","method":"ping","id":1,"unknown":true}',
        b'{"jsonrpc":"1.0","method":"ping","id":1}',
    ],
)
def test_malformed_mcp_does_not_count_or_execute(body: bytes) -> None:
    handler = _WireHandler("/mcp", body, "synthetic-existing")
    handler.do_POST()
    assert handler.response == _Response(
        400, {"message": "Invalid synthetic MCP request"}
    )
    assert _WireHandler.mcp_call_count == 0
    assert _WireHandler.mcp_accounts == []


@pytest.mark.parametrize("length", ["-1", "invalid"])
def test_invalid_body_length_is_rejected(length: str) -> None:
    handler = _WireHandler("/login/oauth/access_token", b"secret", None)
    handler.headers.replace_header("Content-Length", length)
    handler.do_POST()
    assert handler.response == _Response(400, {"error": "invalid_synthetic_request"})
    assert _WireHandler.oauth_request_count == 0


def test_revoked_account_keeps_authentication_failure_boundary() -> None:
    _WireHandler.scenario = "user_revoked"
    handler = _WireHandler(
        "/mcp", _rpc("tools/call", 1, {"name": "get_me"}), "synthetic-existing"
    )
    handler.do_POST()
    assert handler.response == _Response(401, {"message": "Bad synthetic credentials"})
    assert _WireHandler.mcp_call_count == 0
