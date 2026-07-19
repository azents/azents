"""Deterministic model, hosted-tool, Imagine, and xAI OAuth proxy."""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar, cast
from urllib.parse import parse_qs, urlsplit

_PROMPT = "Provider image generation handoff"
_FOLLOW_UP_PROMPT = "Provider image generation follow-up"
_SEMANTIC_PROMPT = "Provider semantic web search handoff"
_SEMANTIC_SAME_NATIVE_PROMPT = "Provider semantic same-native follow-up"
_SEMANTIC_CROSS_NATIVE_PROMPT = "Provider semantic cross-native follow-up"
_SEMANTIC_POST_COMPACTION_PROMPT = "Provider semantic post-compaction follow-up"
_SEMANTIC_QUERY = "Azents provider semantic transcript"
_SEMANTIC_SOURCE_URL = "https://example.com/provider-semantic-transcript"
_SEMANTIC_RESPONSE = "PROVIDER_SEMANTIC_WEB_SEARCH_COMPLETED"
_SEMANTIC_SAME_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_SAME_NATIVE_COMPLETED"
_SEMANTIC_CROSS_NATIVE_RESPONSE = "PROVIDER_SEMANTIC_CROSS_NATIVE_COMPLETED"
_SEMANTIC_POST_COMPACTION_RESPONSE = "PROVIDER_SEMANTIC_POST_COMPACTION_COMPLETED"
_SEMANTIC_ITEM_ID = "search_provider_semantic"
_COMPACTION_SYSTEM_PREFIX = (
    "You are a context compaction engine for a long-running coding agent."
)
_COMPACTION_SUMMARY = f"""## Goal
Preserve provider-hosted tool semantics across compaction.

## Current State
- Web search query: {_SEMANTIC_QUERY}
- Source: {_SEMANTIC_SOURCE_URL}
- Assistant answer: {_SEMANTIC_RESPONSE}

## Pending Work
- Continue the deterministic provider semantic transcript verification.
"""
_SEMANTIC_FOLLOW_UP_RESPONSES = {
    _SEMANTIC_SAME_NATIVE_PROMPT: _SEMANTIC_SAME_NATIVE_RESPONSE,
    _SEMANTIC_CROSS_NATIVE_PROMPT: _SEMANTIC_CROSS_NATIVE_RESPONSE,
    _SEMANTIC_POST_COMPACTION_PROMPT: _SEMANTIC_POST_COMPACTION_RESPONSE,
}
_UPSTREAM = os.environ.get("AIMOCK_UPSTREAM", "http://mock-openai:8080")
_IMAGE_PATH = Path(
    os.environ.get(
        "IMAGE_GENERATION_FIXTURE",
        "/fixtures/provider-image-generation.png",
    )
)
_JOURNAL_PATH = "/v1/_image_generation_requests"
_XAI_IMAGINE_JOURNAL_PATH = "/v1/_xai_imagine_requests"
_XAI_OAUTH_JOURNAL_PATH = "/v1/_xai_oauth_requests"
_SUBSCRIPTION_USAGE_JOURNAL_PATH = "/v1/_subscription_usage_requests"
_CHATGPT_USAGE_PATH = "/backend-api/wham/usage"
_CHATGPT_TOKEN_PATH = "/chatgpt/oauth/token"
_XAI_SETTINGS_PATH = "/v1/settings"
_XAI_BILLING_PATH = "/v1/billing"
_XAI_AUTO_TOP_UP_PATH = "/v1/auto-topup-rule"
_CHATGPT_SCENARIOS = {
    "test-chatgpt-normal": "chatgpt_normal",
    "test-chatgpt-exhausted": "chatgpt_exhausted",
    "test-chatgpt-refresh": "chatgpt_refresh",
    "test-chatgpt-transport": "chatgpt_transport",
    "test-chatgpt-rate-limited": "chatgpt_rate_limited",
    "test-chatgpt-unavailable": "chatgpt_unavailable",
    "test-chatgpt-malformed": "chatgpt_malformed",
    "test-chatgpt-stale": "chatgpt_stale",
}
_XAI_USAGE_SCENARIOS = {
    "test-xai-normal": "xai_normal",
    "test-xai-external": "xai_external",
    "test-xai-invalid-redirect": "xai_invalid_redirect",
    "test-xai-billing-denied": "xai_billing_denied",
    "test-xai-settings-failure": "xai_settings_failure",
    "test-xai-transport": "xai_transport",
    "test-xai-unavailable": "xai_unavailable",
    "test-xai-malformed": "xai_malformed",
}
_XAI_API_KEY_IMAGE_PROMPT = "A deterministic xAI API-key aurora"
_XAI_OAUTH_IMAGE_PROMPT = "A deterministic xAI OAuth aurora"
_XAI_OAUTH_REFRESH_IMAGE_PROMPT = "A deterministic xAI OAuth refresh aurora"
_XAI_OAUTH_REJECTED_IMAGE_PROMPT = "A deterministic rejected xAI OAuth aurora"
_CAPTURED_MODEL_PROMPTS = {
    _PROMPT,
    _FOLLOW_UP_PROMPT,
    "xAI API-key image generation",
    "xAI OAuth image generation",
    "xAI OAuth image generation after 401",
    "xAI OAuth image generation repeated 401",
    "xAI image generation disabled",
}


def _last_user_text(request: dict[str, object]) -> str | None:
    """Return the text from the last user input or message item."""
    input_value = request.get("input", request.get("messages"))
    if isinstance(input_value, str):
        return input_value
    if not isinstance(input_value, list):
        return None
    input_items = cast(list[object], input_value)
    for raw_item in reversed(input_items):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, object], raw_item)
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return None
        text_parts: list[str] = []
        for raw_part in cast(list[object], content):
            if not isinstance(raw_part, dict):
                continue
            part = cast(dict[str, object], raw_part)
            text = part.get("text")
            if part.get("type") in {"input_text", "text"} and isinstance(text, str):
                text_parts.append(text)
        return "".join(text_parts)
    return None


def _is_semantic_compaction_request(request: dict[str, object]) -> bool:
    """Return whether compaction belongs to the semantic transcript scenario."""
    instructions = request.get("instructions")
    user_text = _last_user_text(request)
    return (
        isinstance(instructions, str)
        and instructions.startswith(_COMPACTION_SYSTEM_PREFIX)
        and user_text is not None
        and _SEMANTIC_QUERY in user_text
        and _SEMANTIC_SOURCE_URL in user_text
        and _SEMANTIC_RESPONSE in user_text
    )


class _State:
    requests: ClassVar[list[dict[str, object]]] = []
    imagine_requests: ClassVar[list[dict[str, object]]] = []
    oauth_requests: ClassVar[list[dict[str, object]]] = []
    subscription_usage_requests: ClassVar[list[dict[str, object]]] = []
    subscription_usage_sequences: ClassVar[dict[tuple[str, str], int]] = {}
    lock: ClassVar[threading.Lock] = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        """Return a local journal, deterministic usage, or proxied response."""
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                payload = list(journal)
            self._write_json(200, payload)
            return
        if self._write_subscription_usage_get():
            return
        self._proxy()

    def do_DELETE(self) -> None:
        """Clear a local journal or proxy the request."""
        journal = self._journal_for_path()
        if journal is not None:
            with _State.lock:
                journal.clear()
                if journal is _State.subscription_usage_requests:
                    _State.subscription_usage_sequences.clear()
            self._write_json(200, {"cleared": True})
            return
        self._proxy()

    def do_POST(self) -> None:
        """Handle deterministic image, hosted-tool, and OAuth boundaries."""
        body = self._read_body()
        if self.path == _CHATGPT_TOKEN_PATH:
            self._write_chatgpt_oauth_token_response(body)
            return
        if self.path == "/v1/images/generations":
            self._write_xai_imagine_response(body)
            return
        if self.path == "/oauth2/token":
            self._write_xai_oauth_token_response(body)
            return
        if self.path not in {"/v1/responses", "/v1/chat/completions"}:
            self._proxy(body)
            return
        request_value: object = json.loads(body)
        if not isinstance(request_value, dict):
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        request = cast(dict[str, object], request_value)
        user_text = _last_user_text(request)
        compaction_request = _is_semantic_compaction_request(request)
        captured_prompts = _CAPTURED_MODEL_PROMPTS | {
            _SEMANTIC_PROMPT,
            *_SEMANTIC_FOLLOW_UP_RESPONSES,
        }
        if user_text in captured_prompts or compaction_request:
            with _State.lock:
                _State.requests.append(request)
        if self.path == "/v1/responses" and user_text == _PROMPT:
            self._write_image_generation_response(request)
            return
        if user_text == _SEMANTIC_PROMPT:
            self._write_semantic_web_search_response(request)
            return
        if user_text in _SEMANTIC_FOLLOW_UP_RESPONSES:
            self._write_text_response(
                request,
                _SEMANTIC_FOLLOW_UP_RESPONSES[user_text],
                response_id=f"resp_{user_text.lower().replace(' ', '_')}",
            )
            return
        if compaction_request:
            self._write_text_response(
                request,
                _COMPACTION_SUMMARY,
                response_id="resp_provider_semantic_compaction",
            )
            return
        self._proxy(body)

    def _journal_for_path(self) -> list[dict[str, object]] | None:
        """Return the journal selected by the current request path."""
        if self.path == _JOURNAL_PATH:
            return _State.requests
        if self.path == _XAI_IMAGINE_JOURNAL_PATH:
            return _State.imagine_requests
        if self.path == _XAI_OAUTH_JOURNAL_PATH:
            return _State.oauth_requests
        if self.path == _SUBSCRIPTION_USAGE_JOURNAL_PATH:
            return _State.subscription_usage_requests
        return None

    def _write_subscription_usage_get(self) -> bool:
        """Handle deterministic subscription-usage provider reads."""
        path = urlsplit(self.path).path
        if path == _CHATGPT_USAGE_PATH:
            self._write_chatgpt_usage(path=path)
            return True
        if path in {_XAI_SETTINGS_PATH, _XAI_BILLING_PATH, _XAI_AUTO_TOP_UP_PATH}:
            self._write_xai_usage(path=path)
            return True
        return False

    def _write_chatgpt_usage(self, *, path: str) -> None:
        """Return one deterministic ChatGPT usage outcome."""
        account_id = self.headers.get("ChatGPT-Account-Id")
        scenario = _CHATGPT_SCENARIOS.get(account_id or "", "unknown")
        sequence = self._next_subscription_sequence(scenario=scenario, path=path)
        authorization = self.headers.get("Authorization")
        headers = {
            "authorization": authorization is not None,
            "account": account_id is not None,
            "originator": self.headers.get("originator") is not None,
            "user_agent": self.headers.get("user-agent") is not None,
        }

        status: int | str
        payload: object
        if scenario == "chatgpt_normal":
            status, payload = 200, self._chatgpt_usage_payload(used_percent=42)
        elif scenario == "chatgpt_exhausted":
            status, payload = 200, self._chatgpt_usage_payload(used_percent=100)
        elif scenario == "chatgpt_refresh":
            if authorization == "Bearer test-chatgpt-refresh-initial":
                status, payload = 401, {"error": "expired"}
            elif authorization == "Bearer test-chatgpt-refreshed":
                status, payload = 200, self._chatgpt_usage_payload(used_percent=35)
            else:
                status, payload = 401, {"error": "invalid"}
        elif scenario == "chatgpt_transport":
            status, payload = "transport_close", None
        elif scenario == "chatgpt_rate_limited":
            status, payload = 429, {"error": "rate_limited"}
        elif scenario == "chatgpt_unavailable":
            status, payload = 503, {"error": "unavailable"}
        elif scenario == "chatgpt_malformed":
            status, payload = 200, {"rate_limit": [None]}
        elif scenario == "chatgpt_stale":
            status, payload = (
                (200, self._chatgpt_usage_payload(used_percent=58))
                if sequence == 1
                else (503, {"error": "unavailable"})
            )
        else:
            status, payload = 400, {"error": "unknown deterministic scenario"}

        self._append_subscription_request(
            scenario=scenario,
            path=path,
            sequence=sequence,
            status=status,
            required_headers=headers,
        )
        if status == "transport_close":
            self.close_connection = True
            self.connection.close()
            return
        self._write_json(status, payload)

    def _write_xai_usage(self, *, path: str) -> None:
        """Return one deterministic xAI settings or billing outcome."""
        account_id = self.headers.get("x-userid")
        scenario = _XAI_USAGE_SCENARIOS.get(account_id or "", "unknown")
        sequence = self._next_subscription_sequence(scenario=scenario, path=path)
        headers = {
            "authorization": self.headers.get("Authorization") is not None,
            "token_auth": self.headers.get("X-XAI-Token-Auth") is not None,
            "account": account_id is not None,
            "client_version": self.headers.get("x-grok-client-version") is not None,
            "client_identifier": self.headers.get("x-grok-client-identifier")
            is not None,
            "client_mode": self.headers.get("x-grok-client-mode") is not None,
        }

        status: int | str
        payload: object
        if path == _XAI_SETTINGS_PATH:
            if scenario == "xai_external":
                status, payload = (
                    200,
                    {
                        "usage_billing_redirect_url": "https://grok.com/usage",
                    },
                )
            elif scenario == "xai_invalid_redirect":
                status, payload = (
                    200,
                    {
                        "usage_billing_redirect_url": "https://example.com/rejected",
                    },
                )
            elif scenario == "xai_settings_failure":
                status, payload = 503, {"error": "unavailable"}
            else:
                status, payload = (
                    200,
                    {
                        "subscription_tier": "supergrok",
                        "subscription_tier_display": "SuperGrok",
                    },
                )
        elif path == _XAI_BILLING_PATH:
            query = parse_qs(urlsplit(self.path).query)
            if query.get("format") != ["credits"]:
                status, payload = 400, {"error": "format is required"}
            elif scenario == "xai_billing_denied":
                status, payload = 403, {"error": "denied"}
            elif scenario == "xai_transport":
                status, payload = "transport_close", None
            elif scenario == "xai_unavailable":
                status, payload = 503, {"error": "unavailable"}
            elif scenario == "xai_malformed":
                status, payload = 200, {"config": [None]}
            elif scenario in {"xai_external", "xai_invalid_redirect"}:
                status, payload = 500, {"error": "billing must be short-circuited"}
            else:
                status, payload = 200, self._xai_billing_payload()
        else:
            status, payload = 200, self._xai_auto_top_up_payload()

        self._append_subscription_request(
            scenario=scenario,
            path=path,
            sequence=sequence,
            status=status,
            required_headers=headers,
        )
        if status == "transport_close":
            self.close_connection = True
            self.connection.close()
            return
        self._write_json(status, payload)

    def _write_chatgpt_oauth_token_response(self, body: bytes) -> None:
        """Return a deterministic ChatGPT refresh token without journaling it."""
        form = parse_qs(body.decode())
        refresh_token = form.get("refresh_token", [None])[0]
        scenario = (
            "chatgpt_refresh"
            if refresh_token == "test-chatgpt-refresh-success"
            else "unknown"
        )
        status = 200 if scenario == "chatgpt_refresh" else 400
        sequence = self._next_subscription_sequence(
            scenario=scenario,
            path=_CHATGPT_TOKEN_PATH,
        )
        self._append_subscription_request(
            scenario=scenario,
            path=_CHATGPT_TOKEN_PATH,
            sequence=sequence,
            status=status,
            required_headers={
                "content_type": self.headers.get("Content-Type")
                == "application/x-www-form-urlencoded",
            },
        )
        if status != 200:
            self._write_json(status, {"error": "invalid_grant"})
            return
        self._write_json(
            200,
            {
                "access_token": "test-chatgpt-refreshed",
                "refresh_token": "test-chatgpt-refresh-success",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    @staticmethod
    def _chatgpt_usage_payload(*, used_percent: int) -> dict[str, object]:
        """Build a valid deterministic ChatGPT usage response."""
        return {
            "plan_type": "Pro",
            "rate_limit": {
                "primary_window": {
                    "used_percent": used_percent,
                    "limit_window_seconds": 18_000,
                    "reset_at": 1_784_460_000,
                },
                "secondary_window": {
                    "used_percent": 81,
                    "limit_window_seconds": 604_800,
                    "reset_at": 1_784_894_400,
                },
            },
            "additional_rate_limits": [],
            "credits": {
                "has_credits": True,
                "unlimited": False,
                "balance": "120 credits",
            },
            "spend_control": {
                "reached": False,
                "individual_limit": {
                    "limit": "500 credits",
                    "used": "180 credits",
                    "remaining_percent": 64,
                    "reset_at": 1_785_542_400,
                },
            },
        }

    @staticmethod
    def _xai_billing_payload() -> dict[str, object]:
        """Build a valid deterministic xAI billing response."""
        return {
            "subscriptionTier": "SuperGrok",
            "onDemandEnabled": True,
            "config": {
                "creditUsagePercent": 42,
                "currentPeriod": {
                    "type": "USAGE_PERIOD_TYPE_WEEKLY",
                    "start": "2026-07-13T00:00:00+00:00",
                    "end": "2026-07-20T00:00:00+00:00",
                },
                "prepaidBalance": {"val": 2540},
                "onDemandCap": {"val": 10000},
                "onDemandUsed": {"val": 1275},
                "isUnifiedBillingUser": True,
            },
        }

    @staticmethod
    def _xai_auto_top_up_payload() -> dict[str, object]:
        """Build a valid deterministic xAI auto top-up response."""
        return {
            "rule": {
                "enabled": True,
                "minBeforeHittingSl": {"val": 500},
                "topupAmount": {"val": 2000},
                "maxAmountPerMonth": {"val": 10000},
            }
        }

    @staticmethod
    def _next_subscription_sequence(*, scenario: str, path: str) -> int:
        """Return a monotonic request sequence for one safe scenario/path key."""
        key = (scenario, path)
        with _State.lock:
            sequence = _State.subscription_usage_sequences.get(key, 0) + 1
            _State.subscription_usage_sequences[key] = sequence
        return sequence

    @staticmethod
    def _append_subscription_request(
        *,
        scenario: str,
        path: str,
        sequence: int,
        status: int | str,
        required_headers: dict[str, bool],
    ) -> None:
        """Append one sanitized subscription-usage journal entry."""
        with _State.lock:
            _State.subscription_usage_requests.append(
                {
                    "scenario": scenario,
                    "path": path,
                    "sequence": sequence,
                    "status": status,
                    "required_headers": required_headers,
                }
            )

    def _write_xai_imagine_response(self, body: bytes) -> None:
        """Return deterministic Imagine output and bounded auth failures."""
        try:
            request_value: object = json.loads(body)
        except json.JSONDecodeError:
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        if not isinstance(request_value, dict):
            self._write_json(400, {"error": {"message": "invalid request"}})
            return
        request = cast(dict[str, object], request_value)
        prompt = request.get("prompt")
        if not isinstance(prompt, str):
            self._write_json(400, {"error": {"message": "prompt is required"}})
            return
        credential = self._xai_credential_label()
        status = 200
        if prompt == _XAI_OAUTH_REFRESH_IMAGE_PROMPT and credential == "oauth_initial":
            status = 401
        elif prompt == _XAI_OAUTH_REJECTED_IMAGE_PROMPT:
            status = 401
        elif prompt not in {
            _XAI_API_KEY_IMAGE_PROMPT,
            _XAI_OAUTH_IMAGE_PROMPT,
            _XAI_OAUTH_REFRESH_IMAGE_PROMPT,
            _XAI_OAUTH_REJECTED_IMAGE_PROMPT,
        }:
            status = 400
        with _State.lock:
            _State.imagine_requests.append(
                {
                    "prompt": prompt,
                    "credential": credential,
                    "status": status,
                }
            )
        if status != 200:
            self._write_json(status, {"error": {"message": "deterministic failure"}})
            return
        self._write_json(
            200,
            {"data": [{"b64_json": b64encode(_IMAGE_PATH.read_bytes()).decode()}]},
        )

    def _write_xai_oauth_token_response(self, body: bytes) -> None:
        """Return a deterministic replacement token without journaling secrets."""
        form = parse_qs(body.decode())
        refresh_token = form.get("refresh_token", [None])[0]
        if refresh_token == "test-xai-refresh-success":
            refresh_case = "success"
            access_token = "test-xai-oauth-refreshed"
        elif refresh_token == "test-xai-refresh-rejected":
            refresh_case = "rejected"
            access_token = "test-xai-oauth-rejected-refreshed"
        else:
            self._write_json(400, {"error": "invalid_grant"})
            return
        with _State.lock:
            _State.oauth_requests.append({"refresh_case": refresh_case})
        self._write_json(
            200,
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )

    def _xai_credential_label(self) -> str:
        """Classify deterministic credentials without recording token values."""
        authorization = self.headers.get("Authorization")
        return {
            "Bearer test-xai-api-key": "api_key",
            "Bearer test-xai-oauth-token": "oauth",
            "Bearer test-xai-oauth-refresh-initial": "oauth_initial",
            "Bearer test-xai-oauth-refreshed": "oauth_refreshed",
            "Bearer test-xai-oauth-rejected-initial": "oauth_rejected_initial",
            "Bearer test-xai-oauth-rejected-refreshed": "oauth_rejected_refreshed",
        }.get(authorization or "", "unknown")

    def log_message(self, format: str, *args: object) -> None:
        """Suppress routine proxy access logs."""
        del format, args

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def _write_text_response(
        self,
        request: dict[str, object],
        text: str,
        *,
        response_id: str,
    ) -> None:
        """Write one deterministic assistant message response."""
        model_value = request.get("model")
        model = model_value if isinstance(model_value, str) else "gpt-5.5"
        item_id = f"msg_{response_id.removeprefix('resp_')}"
        message_item: dict[str, object] = {
            "id": item_id,
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                    "annotations": [],
                }
            ],
        }
        response = self._response(
            request=request,
            response_id=response_id,
            model=model,
            output=[message_item],
        )
        if request.get("stream") is not True:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {
                        **message_item,
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item": message_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 3,
                    "response": response,
                },
            ]
        )

    def _write_semantic_web_search_response(
        self,
        request: dict[str, object],
    ) -> None:
        """Write Web-search semantics followed by a separate assistant answer."""
        model_value = request.get("model")
        model = model_value if isinstance(model_value, str) else "gpt-5.5"
        search_item: dict[str, object] = {
            "id": _SEMANTIC_ITEM_ID,
            "type": "web_search_call",
            "status": "completed",
            "action": {
                "type": "search",
                "query": _SEMANTIC_QUERY,
                "sources": [
                    {
                        "type": "url",
                        "url": _SEMANTIC_SOURCE_URL,
                    }
                ],
            },
        }
        message_item: dict[str, object] = {
            "id": "msg_provider_semantic",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": _SEMANTIC_RESPONSE,
                    "annotations": [],
                }
            ],
        }
        response = self._response(
            request=request,
            response_id="resp_provider_semantic",
            model=model,
            output=[search_item, message_item],
        )
        if request.get("stream") is not True:
            self._write_json(200, response)
            return
        self._write_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 0,
                    "response": {**response, "status": "in_progress", "output": []},
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 1,
                    "output_index": 0,
                    "item": {**search_item, "status": "in_progress"},
                },
                {
                    "type": "response.web_search_call.in_progress",
                    "sequence_number": 2,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.web_search_call.searching",
                    "sequence_number": 3,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.web_search_call.completed",
                    "sequence_number": 4,
                    "output_index": 0,
                    "item_id": _SEMANTIC_ITEM_ID,
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 5,
                    "output_index": 0,
                    "item": search_item,
                },
                {
                    "type": "response.output_item.added",
                    "sequence_number": 6,
                    "output_index": 1,
                    "item": {
                        **message_item,
                        "status": "in_progress",
                        "content": [],
                    },
                },
                {
                    "type": "response.output_item.done",
                    "sequence_number": 7,
                    "output_index": 1,
                    "item": message_item,
                },
                {
                    "type": "response.completed",
                    "sequence_number": 8,
                    "response": response,
                },
            ]
        )

    def _response(
        self,
        *,
        request: dict[str, object],
        response_id: str,
        model: str,
        output: list[dict[str, object]],
    ) -> dict[str, object]:
        """Build one completed Responses payload."""
        return {
            "id": response_id,
            "object": "response",
            "created_at": time.time(),
            "model": model,
            "status": "completed",
            "output": output,
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": request.get("tools", []),
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }

    def _write_sse(self, events: list[dict[str, object]]) -> None:
        """Write deterministic Responses server-sent events."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("Responses event type is missing.")
            encoded = json.dumps(event, separators=(",", ":")).encode()
            self.wfile.write(b"event: " + event_type.encode() + b"\n")
            self.wfile.write(b"data: " + encoded + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _write_image_generation_response(self, request: dict[str, object]) -> None:
        image_base64 = b64encode(_IMAGE_PATH.read_bytes()).decode()
        model_value = request.get("model")
        model = model_value if isinstance(model_value, str) else "gpt-5.5"
        response_id = "resp_provider_image_generation"
        item_id = "ig_provider_image_generation"
        created_at = time.time()
        image_item = {
            "id": item_id,
            "type": "image_generation_call",
            "status": "completed",
            "result": image_base64,
        }
        response = {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "status": "completed",
            "output": [image_item],
            "parallel_tool_calls": True,
            "tool_choice": "auto",
            "tools": request.get("tools", []),
            "usage": {
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "input_tokens_details": {
                    "cached_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        if request.get("stream") is not True:
            self._write_json(200, response)
            return

        events: list[dict[str, object]] = [
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {**response, "status": "in_progress", "output": []},
            },
            {
                "type": "response.output_item.added",
                "sequence_number": 1,
                "output_index": 0,
                "item": {
                    "id": item_id,
                    "type": "image_generation_call",
                    "status": "in_progress",
                    "result": None,
                },
            },
            {
                "type": "response.image_generation_call.in_progress",
                "sequence_number": 2,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.generating",
                "sequence_number": 3,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.image_generation_call.completed",
                "sequence_number": 4,
                "output_index": 0,
                "item_id": item_id,
            },
            {
                "type": "response.output_item.done",
                "sequence_number": 5,
                "output_index": 0,
                "item": image_item,
            },
            {
                "type": "response.completed",
                "sequence_number": 6,
                "response": response,
            },
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        for event in events:
            event_type = event.get("type")
            if not isinstance(event_type, str):
                raise RuntimeError("Responses event type is missing.")
            encoded = json.dumps(event, separators=(",", ":")).encode()
            self.wfile.write(b"event: " + event_type.encode() + b"\n")
            self.wfile.write(b"data: " + encoded + b"\n\n")
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _proxy(self, body: bytes | None = None) -> None:
        target = f"{_UPSTREAM}{self.path}"
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "content-length", "connection"}
        }
        request = urllib.request.Request(
            target,
            data=body,
            headers=headers,
            method=self.command,
        )
        try:
            response = urllib.request.urlopen(request, timeout=300)
        except urllib.error.HTTPError as error:
            response = error
        except urllib.error.URLError as error:
            self._write_json(502, {"error": {"message": str(error.reason)}})
            return
        try:
            status = response.getcode()
            self.send_response(status if status is not None else 502)
            for key, value in response.headers.items():
                if key.lower() not in {
                    "content-length",
                    "connection",
                    "transfer-encoding",
                }:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            read_chunk = getattr(response, "read1", response.read)
            while chunk := read_chunk(64 * 1024):
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            response.close()
        self.close_connection = True

    def _write_json(self, status: int, value: object) -> None:
        payload = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    """Run the deterministic proxy."""
    server = ThreadingHTTPServer(("0.0.0.0", 8081), _Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
