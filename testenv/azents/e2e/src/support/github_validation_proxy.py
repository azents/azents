"""Deterministic GitHub App validation boundary for E2E tests."""

import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, cast
from urllib.parse import parse_qs, urlencode, urlsplit


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
                or not state.startswith("github_user.")
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
        content_length = int(self.headers.get("Content-Length", "0"))
        request_body = self.rfile.read(content_length)
        if self.path == "/__testenv/scenario":
            try:
                payload: object = json.loads(request_body)
            except UnicodeDecodeError:
                self._json_response(400, {"error": "invalid_json"})
                return
            except json.JSONDecodeError:
                self._json_response(400, {"error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._json_response(422, {"error": "unsupported_scenario"})
                return
            scenario = cast(dict[str, object], payload).get("scenario")
            if not isinstance(scenario, str) or scenario not in {
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
                self._json_response(422, {"error": "unsupported_scenario"})
                return
            with self.state_lock:
                type(self).scenario = scenario
                type(self).app_request_count = 0
                type(self).oauth_request_count = 0
                type(self).revocation_request_count = 0
                type(self).mcp_call_count = 0
                type(self).mcp_accounts = []
            self._json_response(200, {"scenario": scenario})
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
            payload: object = json.loads(request_body)
            if isinstance(payload, dict):
                code = payload.get("code")
                if isinstance(code, str) and code.startswith("e2e-user-"):
                    token = "synthetic-token-" + code
                    login = (
                        "replacement-user"
                        if "replacement" in code
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
        payload: object = json.loads(
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
        )
        with self.state_lock:
            type(self).revocation_request_count += 1
            fail = self.scenario == "user_cleanup_failure"
            if not fail and isinstance(payload, dict):
                token = payload.get("access_token")
                if isinstance(token, str):
                    type(self).user_tokens.pop(token, None)
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
        request: object = json.loads(request_body)
        if not isinstance(request, dict):
            self._json_response(400, {"message": "Invalid synthetic MCP request"})
            return
        method = request.get("method")
        identifier = request.get("id")
        if identifier is None:
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if method == "initialize":
            result: dict[str, object] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "synthetic-github", "version": "1"},
            }
        elif method == "tools/list":
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
        elif method == "tools/call":
            with self.state_lock:
                type(self).mcp_call_count += 1
                type(self).mcp_accounts.append(account)
            params = request.get("params")
            if isinstance(params, dict) and params.get("name") == "get_file_contents":
                arguments = params.get("arguments")
                if not isinstance(arguments, dict) or arguments.get("owner") not in {
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
        else:
            result = {}
        self._json_response(200, {"jsonrpc": "2.0", "id": identifier, "result": result})

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
