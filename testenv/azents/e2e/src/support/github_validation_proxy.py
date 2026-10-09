"""Deterministic GitHub App validation boundary for E2E tests."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, assert_never
from urllib.parse import parse_qs, urlencode, urlsplit


class _InvalidPayload(ValueError):
    """Reject synthetic wire input without exposing its contents."""


@dataclass(frozen=True)
class _ScenarioRequest:
    scenario: str


@dataclass(frozen=True)
class _OAuthRequest:
    code: str


@dataclass(frozen=True)
class _RevocationRequest:
    access_token: str


@dataclass(frozen=True)
class _Initialize:
    pass


@dataclass(frozen=True)
class _Initialized:
    pass


@dataclass(frozen=True)
class _ListTools:
    pass


@dataclass(frozen=True)
class _Ping:
    pass


@dataclass(frozen=True)
class _GetMe:
    pass


@dataclass(frozen=True)
class _GetFile:
    owner: str
    repo: str
    path: str


type _McpOperation = _Initialize | _Initialized | _ListTools | _Ping | _GetMe | _GetFile


@dataclass(frozen=True)
class _McpRequest:
    identifier: str | int | None
    operation: _McpOperation


def _object(value: object, allowed: set[str] | None) -> dict[str, object]:
    """Validate object keys; open objects are reserved for MCP extension metadata."""
    if not isinstance(value, dict):
        raise _InvalidPayload("Expected a synthetic request object.")
    result: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str) or (allowed is not None and key not in allowed):
            raise _InvalidPayload("Unknown synthetic request field.")
        result[key] = item
    return result


def _load(body: bytes, allowed: set[str]) -> dict[str, object]:
    try:
        value: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _InvalidPayload("Invalid synthetic request JSON.") from error
    return _object(value, allowed)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _InvalidPayload("Expected a nonempty synthetic request string.")
    return value


def _argument(value: object) -> str:
    """Retain the tool schema's string contract, including an empty file path."""
    if not isinstance(value, str):
        raise _InvalidPayload("Expected a synthetic tool argument string.")
    return value


def _metadata(value: object) -> None:
    """Validate opaque MCP extension metadata, which does not control dispatch."""
    _object(value, None)


def _decode_scenario(body: bytes) -> _ScenarioRequest:
    payload = _load(body, {"scenario"})
    scenario = _string(payload.get("scenario"))
    if scenario not in {
        "valid",
        "invalid_app",
        "invalid_oauth",
        "mismatched_app",
        "rate_limited",
        "unavailable",
        "user_success",
        "user_cleanup_failure",
        "user_expiring",
        "user_revoked",
    }:
        raise _InvalidPayload("Unsupported synthetic scenario.")
    return _ScenarioRequest(scenario)


def _decode_oauth(body: bytes) -> _OAuthRequest:
    optional = {"client_id", "client_secret", "redirect_uri", "code_verifier"}
    payload = _load(body, {"code", *optional})
    code = _string(payload.get("code"))
    for key in optional & payload.keys():
        _string(payload[key])
    return _OAuthRequest(code)


def _decode_revocation(body: bytes) -> _RevocationRequest:
    payload = _load(body, {"access_token"})
    return _RevocationRequest(_string(payload.get("access_token")))


def _decode_mcp(body: bytes) -> _McpRequest:
    payload = _load(body, {"jsonrpc", "id", "method", "params"})
    if payload.get("jsonrpc") != "2.0":
        raise _InvalidPayload("Invalid synthetic JSON-RPC version.")
    identifier = payload.get("id")
    if not (
        identifier is None
        or isinstance(identifier, str)
        or (isinstance(identifier, int) and not isinstance(identifier, bool))
    ):
        raise _InvalidPayload("Invalid synthetic JSON-RPC identifier.")
    method = _string(payload.get("method"))
    if method == "initialize":
        params = _object(
            payload.get("params"),
            {"protocolVersion", "capabilities", "clientInfo", "_meta"},
        )
        _string(params.get("protocolVersion"))
        # MCP capabilities and implementation metadata are extensible protocol
        # objects. Validate their shape but do not interpret extensions as policy.
        _metadata(params.get("capabilities"))
        client = _object(params.get("clientInfo"), None)
        _string(client.get("name"))
        _string(client.get("version"))
        if "_meta" in params:
            _metadata(params["_meta"])
        operation: _McpOperation = _Initialize()
    elif method in {"notifications/initialized", "tools/list", "ping"}:
        params = (
            _object(
                payload["params"],
                {"cursor", "_meta"} if method == "tools/list" else {"_meta"},
            )
            if "params" in payload
            else {}
        )
        if "cursor" in params:
            _string(params["cursor"])
        if "_meta" in params:
            _metadata(params["_meta"])
        if method == "notifications/initialized":
            operation = _Initialized()
        elif method == "ping":
            operation = _Ping()
        else:
            operation = _ListTools()
    elif method == "tools/call":
        params = _object(payload.get("params"), {"name", "arguments", "_meta"})
        if "_meta" in params:
            _metadata(params["_meta"])
        name = _string(params.get("name"))
        arguments = params["arguments"] if "arguments" in params else {}
        if name == "get_me":
            _object(arguments, set())
            operation = _GetMe()
        elif name == "get_file_contents":
            fields = _object(arguments, {"owner", "repo", "path"})
            operation = _GetFile(
                _argument(fields.get("owner")),
                _argument(fields.get("repo")),
                _argument(fields.get("path")),
            )
        else:
            raise _InvalidPayload("Unknown synthetic MCP tool.")
    else:
        raise _InvalidPayload("Unknown synthetic MCP method.")
    # Preserve this fixture's existing acknowledgement contract for omitted
    # and explicit-null IDs; neither is counted as a tool execution.
    return _McpRequest(identifier, operation)


class Handler(BaseHTTPRequestHandler):
    """Serve controllable sanitized GitHub App and OAuth responses."""

    scenario: ClassVar[str] = "valid"
    app_request_count: ClassVar[int] = 0
    oauth_request_count: ClassVar[int] = 0
    revocation_request_count: ClassVar[int] = 0
    mcp_call_count: ClassVar[int] = 0
    mcp_accounts: ClassVar[list[str]] = []
    user_tokens: ClassVar[dict[str, str]] = {}
    state_lock: ClassVar[Lock] = Lock()

    def do_GET(self) -> None:
        """Handle readiness, state inspection, and GitHub App lookup."""
        if self.path == "/health":
            self._json_response(200, {"status": "ok"})
            return
        if self.path == "/__testenv/state":
            with self.state_lock:
                payload = {
                    "scenario": self.scenario,
                    "app_request_count": self.app_request_count,
                    "oauth_request_count": self.oauth_request_count,
                }
                if self.scenario.startswith("user_"):
                    payload.update(
                        revocation_request_count=self.revocation_request_count,
                        mcp_call_count=self.mcp_call_count,
                        mcp_accounts=list(self.mcp_accounts),
                    )
            self._json_response(200, payload)
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/login/oauth/authorize":
            query = parse_qs(parsed.query)
            redirect_uri = query.get("redirect_uri", [""])[0]
            state = query.get("state", [""])[0]
            callback = urlsplit(redirect_uri)
            if (
                not self.scenario.startswith("user_")
                or callback.scheme not in {"http", "https"}
                or callback.path != "/oauth/github/callback"
                or not state.startswith(("github_user.", "github_user_create."))
            ):
                self._json_response(400, {"error": "invalid_synthetic_authorization"})
                return
            self.send_response(302)
            self.send_header(
                "Location",
                redirect_uri
                + "?"
                + urlencode(
                    {"code": "e2e-user-browser-" + state.split(".")[1], "state": state}
                ),
            )
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if urlsplit(self.path).path.startswith("/user"):
            self._user_get()
            return
        if self.path != "/app":
            self._json_response(404, {"error": "not_found"})
            return

        with self.state_lock:
            type(self).app_request_count += 1
            scenario = self.scenario
        if scenario == "unavailable":
            self._json_response(503, {"message": "provider diagnostics are private"})
            return
        if scenario == "rate_limited":
            self._json_response(429, {"message": "provider rate limit details"})
            return
        if scenario == "invalid_app":
            self._json_response(401, {"message": "provider credential details"})
            return
        if scenario == "mismatched_app":
            self._json_response(
                200,
                {"id": 999, "client_id": "Iv1.other", "slug": "other-app"},
            )
            return
        self._json_response(
            200,
            {"id": 123, "client_id": "Iv1.azents-test", "slug": "azents-test"},
        )

    def do_POST(self) -> None:
        """Handle scenario control and OAuth credential validation."""
        try:
            request_body = self._request_body()
        except _InvalidPayload:
            self._json_response(400, {"error": "invalid_synthetic_request"})
            return
        if self.path == "/__testenv/scenario":
            try:
                request = _decode_scenario(request_body)
            except _InvalidPayload:
                self._json_response(422, {"error": "unsupported_scenario"})
                return
            with self.state_lock:
                type(self).scenario = request.scenario
                type(self).app_request_count = 0
                type(self).oauth_request_count = 0
                type(self).revocation_request_count = 0
                type(self).mcp_call_count = 0
                type(self).mcp_accounts = []
            self._json_response(200, {"scenario": request.scenario})
            return
        if self.path == "/mcp":
            self._mcp_request(request_body)
            return
        if self.path != "/login/oauth/access_token":
            self._json_response(404, {"error": "not_found"})
            return

        with self.state_lock:
            type(self).oauth_request_count += 1
            scenario = self.scenario
        if scenario == "unavailable":
            self._json_response(503, {"message": "provider diagnostics are private"})
            return
        if scenario == "rate_limited":
            self._json_response(429, {"message": "provider rate limit details"})
            return
        if scenario == "invalid_oauth":
            self._json_response(
                200,
                {
                    "error": "incorrect_client_credentials",
                    "error_description": "provider credential details are private",
                },
            )
            return
        if scenario.startswith("user_"):
            try:
                request = _decode_oauth(request_body)
            except _InvalidPayload:
                self._json_response(400, {"error": "invalid_synthetic_request"})
                return
            if request.code.startswith("e2e-user-"):
                token = "synthetic-token-" + request.code
                login = (
                    "replacement-user"
                    if "replacement" in request.code
                    else "connected-user"
                )
                with self.state_lock:
                    type(self).user_tokens[token] = login
                response: dict[str, object] = {
                    "access_token": token,
                    "token_type": "bearer",
                }
                if scenario == "user_expiring":
                    response["expires_in"] = 28800
                    response["refresh_token"] = "synthetic-refresh-not-supported"
                self._json_response(200, response)
                return
        self._json_response(200, {"error": "bad_verification_code"})

    def _account(self) -> str | None:
        token = self.headers.get("Authorization", "").removeprefix("Bearer ")
        with self.state_lock:
            if self.scenario == "user_revoked":
                return None
            return self.user_tokens.get(token)

    def _user_get(self) -> None:
        """Serve only issued synthetic accounts and personal/two-org observations."""
        account = self._account()
        if account is None:
            self._json_response(401, {"message": "Bad synthetic credentials"})
            return
        parsed = urlsplit(self.path)
        if parsed.path == "/user":
            self._json_response(
                200,
                {
                    "id": 42 if account == "connected-user" else 43,
                    "login": account,
                    "avatar_url": None,
                },
            )
            return
        if parsed.path == "/user/installations":
            self._json_response(
                200,
                {
                    "total_count": 4,
                    "installations": [
                        {
                            "id": 501 + index,
                            "app_id": 123,
                            "account": {
                                "login": owner,
                                "type": "User" if index == 0 else "Organization",
                                "avatar_url": None,
                            },
                            "permissions": {"contents": "read", "issues": "write"},
                        }
                        for index, owner in enumerate(
                            (account, "research-team", "ops-team", "restricted-team")
                        )
                    ],
                },
            )
            return
        if parsed.path == "/user/installations/504/repositories":
            self._json_response(403, {"message": "Synthetic target permission denied"})
            return
        owners = {
            "/user/installations/501/repositories": account,
            "/user/installations/502/repositories": "research-team",
            "/user/installations/503/repositories": "ops-team",
        }
        owner = owners.get(parsed.path)
        if owner is None:
            self._json_response(404, {"message": "Unknown synthetic target"})
            return
        page = parse_qs(parsed.query).get("page", ["1"])[0]
        name = (
            "personal-notes"
            if owner == account
            else ("shared-project" if page == "1" else "second-project")
        )
        repo = {
            "id": (
                1001
                if owner == account
                else (3001 if owner == "ops-team" else (2001 if page == "1" else 2002))
            ),
            "name": name,
            "full_name": f"{owner}/{name}",
            "owner": {"login": owner},
            "private": True,
            "permissions": {"pull": True, "push": False, "admin": False},
        }
        body = json.dumps({"repositories": [repo]}, separators=(",", ":")).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if owner == "research-team" and page == "1":
            self.send_header(
                "Link",
                "<https://api.github.com/user/installations/502/repositories"
                '?page=2&per_page=100>; rel="next"',
            )
        self.end_headers()
        self.wfile.write(body)

    def do_DELETE(self) -> None:
        """Attempt only the captured synthetic token, with controllable failure."""
        if not self.path.startswith("/applications/") or not self.path.endswith(
            "/token"
        ):
            self._json_response(404, {"message": "Unknown revocation target"})
            return
        try:
            request = _decode_revocation(self._request_body())
        except _InvalidPayload:
            self._json_response(400, {"error": "invalid_synthetic_request"})
            return
        with self.state_lock:
            type(self).revocation_request_count += 1
            fail = self.scenario == "user_cleanup_failure"
            if not fail:
                type(self).user_tokens.pop(request.access_token, None)
        if fail:
            self._json_response(503, {"message": "Synthetic cleanup unavailable"})
        else:
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _mcp_request(self, request_body: bytes) -> None:
        """Support the real MCP client protocol using the supplied account token."""
        account = self._account()
        if account is None:
            self._json_response(401, {"message": "Bad synthetic credentials"})
            return
        try:
            request = _decode_mcp(request_body)
        except _InvalidPayload:
            self._json_response(400, {"message": "Invalid synthetic MCP request"})
            return
        if request.identifier is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if isinstance(request.operation, _Initialize):
            result: dict[str, object] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic-github", "version": "1"},
            }
        elif isinstance(request.operation, _ListTools):
            result = {
                "tools": [
                    {
                        "name": "get_me",
                        "description": "Read the current GitHub account.",
                        "inputSchema": {"type": "object", "properties": {}},
                    },
                    {
                        "name": "get_file_contents",
                        "description": "Read a permitted repository file.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "owner": {"type": "string"},
                                "repo": {"type": "string"},
                                "path": {"type": "string"},
                            },
                            "required": ["owner", "repo", "path"],
                        },
                    },
                ]
            }
        elif isinstance(request.operation, (_GetMe, _GetFile)):
            with self.state_lock:
                type(self).mcp_call_count += 1
                type(self).mcp_accounts.append(account)
            if isinstance(request.operation, _GetFile):
                if request.operation.owner not in {
                    account,
                    "research-team",
                    "ops-team",
                }:
                    self._json_response(
                        403, {"message": "Synthetic repository permission denied"}
                    )
                    return
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "account": account,
                                "owners": [account, "research-team", "ops-team"],
                                "fixture": "github-user-product",
                            }
                        ),
                    }
                ]
            }
        elif isinstance(request.operation, (_Initialized, _Ping)):
            result = {}
        else:
            assert_never(request.operation)
        self._json_response(
            200, {"jsonrpc": "2.0", "id": request.identifier, "result": result}
        )

    def _request_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise _InvalidPayload("Invalid synthetic request length.") from error
        if length < 0:
            raise _InvalidPayload("Invalid synthetic request length.")
        return self.rfile.read(length)

    def log_message(self, format: str, *args: object) -> None:
        """Avoid logging headers or request bodies that contain test secrets."""
        del format, args

    def _json_response(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8082), Handler).serve_forever()
