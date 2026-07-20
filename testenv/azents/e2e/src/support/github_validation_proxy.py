"""Deterministic GitHub App validation boundary for E2E tests."""

import json
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock
from typing import ClassVar, cast


class Handler(BaseHTTPRequestHandler):
    """Serve controllable sanitized GitHub App and OAuth responses."""

    scenario: ClassVar[str] = "valid"
    app_request_count: ClassVar[int] = 0
    oauth_request_count: ClassVar[int] = 0
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
            self._json_response(200, payload)
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
            }:
                self._json_response(422, {"error": "unsupported_scenario"})
                return
            with self.state_lock:
                type(self).scenario = scenario
                type(self).app_request_count = 0
                type(self).oauth_request_count = 0
            self._json_response(200, {"scenario": scenario})
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
        self._json_response(200, {"error": "bad_verification_code"})

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
