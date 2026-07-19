"""Direct deterministic subscription usage proxy contract tests."""

# pyright: reportPrivateUsage=false

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager

import pytest
import requests
from pydantic import TypeAdapter

from support import image_generation_openai_proxy as proxy

_JOURNAL_PATH = "/v1/_subscription_usage_requests"
_JSON_OBJECT_LIST = TypeAdapter(list[dict[str, object]])
_BOOLEAN_MAP = TypeAdapter(dict[str, bool])
_CHATGPT_HEADERS = {
    "Authorization": "Bearer test-access",
    "originator": "azents",
    "user-agent": "azents/test",
}
_XAI_HEADERS = {
    "Authorization": "Bearer test-access",
    "X-XAI-Token-Auth": "xai-grok-cli",
    "x-grok-client-version": "test",
    "x-grok-client-identifier": "grok-shell",
    "x-grok-client-mode": "interactive",
}


@contextmanager
def _running_proxy() -> Generator[str, None, None]:
    """Run the proxy on an ephemeral localhost port with isolated usage state."""
    with proxy._State.lock:
        proxy._State.subscription_usage_requests.clear()
        proxy._State.subscription_usage_sequences.clear()
        for queue in proxy._State.oauth_connection_queues.values():
            queue.clear()
        proxy._State.oauth_connection_sessions.clear()
        proxy._State.oauth_connection_sequence = 0
    server = proxy.ThreadingHTTPServer(("127.0.0.1", 0), proxy._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _journal(base_url: str) -> list[dict[str, object]]:
    """Read one sanitized journal snapshot."""
    response = requests.get(f"{base_url}{_JOURNAL_PATH}", timeout=2)
    response.raise_for_status()
    return _JSON_OBJECT_LIST.validate_python(response.json())


def _chatgpt(base_url: str, scenario: str) -> requests.Response:
    """Read one ChatGPT fixture scenario."""
    return requests.get(
        f"{base_url}/backend-api/wham/usage",
        headers={**_CHATGPT_HEADERS, "ChatGPT-Account-Id": scenario},
        timeout=2,
    )


def _xai(base_url: str, path: str, scenario: str) -> requests.Response:
    """Read one xAI fixture scenario endpoint."""
    return requests.get(
        f"{base_url}{path}",
        headers={**_XAI_HEADERS, "x-userid": scenario},
        timeout=2,
    )


def _assert_safe(journal: list[dict[str, object]]) -> None:
    """Assert journals contain no credentials, identities, or provider values."""
    serialized = json.dumps(journal, ensure_ascii=False, sort_keys=True)
    for forbidden in (
        "Bearer test-access",
        "test-chatgpt-normal",
        "test-xai-normal",
        "120 credits",
        "SuperGrok",
        "https://grok.com/usage",
        "https://example.com/rejected",
        "2540",
        "1275",
        "10000",
    ):
        assert forbidden not in serialized
    expected_keys = {"scenario", "path", "sequence", "status", "required_headers"}
    assert all(set(entry) == expected_keys for entry in journal)


def test_normal_payloads_headers_and_sequence_reset() -> None:
    """Return production-shaped payloads and reset safe sequence state."""
    with _running_proxy() as base_url:
        chatgpt = _chatgpt(base_url, "test-chatgpt-normal")
        chatgpt.raise_for_status()
        assert chatgpt.json()["rate_limit"]["primary_window"]["used_percent"] == 42
        settings = _xai(base_url, "/v1/settings", "test-xai-normal")
        settings.raise_for_status()
        assert settings.json()["subscription_tier_display"] == "SuperGrok"
        billing = _xai(base_url, "/v1/billing?format=credits", "test-xai-normal")
        billing.raise_for_status()
        assert billing.json()["config"]["creditUsagePercent"] == 42
        auto_top_up = _xai(base_url, "/v1/auto-topup-rule", "test-xai-normal")
        auto_top_up.raise_for_status()
        assert auto_top_up.json()["rule"]["enabled"] is True

        journal = _journal(base_url)
        assert [entry["sequence"] for entry in journal] == [1, 1, 1, 1]
        assert all(
            all(_BOOLEAN_MAP.validate_python(entry["required_headers"]).values())
            for entry in journal
        )
        _assert_safe(journal)

        requests.delete(f"{base_url}{_JOURNAL_PATH}", timeout=2).raise_for_status()
        assert _journal(base_url) == []
        _chatgpt(base_url, "test-chatgpt-normal").raise_for_status()
        assert _journal(base_url)[0]["sequence"] == 1


@pytest.mark.parametrize(
    ("scenario", "status"),
    [
        ("test-chatgpt-exhausted", 200),
        ("test-chatgpt-rate-limited", 429),
        ("test-chatgpt-unavailable", 503),
        ("test-chatgpt-malformed", 200),
    ],
)
def test_chatgpt_status_scenarios(scenario: str, status: int) -> None:
    """Return deterministic ChatGPT statuses without leaking source values."""
    with _running_proxy() as base_url:
        response = _chatgpt(base_url, scenario)
        assert response.status_code == status
        if scenario == "test-chatgpt-exhausted":
            assert (
                response.json()["rate_limit"]["primary_window"]["used_percent"] == 100
            )
        if scenario == "test-chatgpt-malformed":
            assert isinstance(response.json()["rate_limit"], list)
        _assert_safe(_journal(base_url))


def test_chatgpt_transport_stale_and_refresh_scenarios() -> None:
    """Close transport, sequence stale responses, and exchange refresh tokens."""
    with _running_proxy() as base_url:
        with pytest.raises(requests.ConnectionError):
            _chatgpt(base_url, "test-chatgpt-transport")

        first = _chatgpt(base_url, "test-chatgpt-stale")
        second = _chatgpt(base_url, "test-chatgpt-stale")
        assert first.status_code == 200
        assert second.status_code == 503

        unauthorized = requests.get(
            f"{base_url}/backend-api/wham/usage",
            headers={
                **_CHATGPT_HEADERS,
                "Authorization": "Bearer test-chatgpt-refresh-initial",
                "ChatGPT-Account-Id": "test-chatgpt-refresh",
            },
            timeout=2,
        )
        assert unauthorized.status_code == 401
        token = requests.post(
            f"{base_url}/chatgpt/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": "test-chatgpt-refresh-success",
            },
            timeout=2,
        )
        token.raise_for_status()
        assert token.json()["access_token"] == "test-chatgpt-refreshed"
        retried = requests.get(
            f"{base_url}/backend-api/wham/usage",
            headers={
                **_CHATGPT_HEADERS,
                "Authorization": "Bearer test-chatgpt-refreshed",
                "ChatGPT-Account-Id": "test-chatgpt-refresh",
            },
            timeout=2,
        )
        retried.raise_for_status()
        assert retried.json()["rate_limit"]["primary_window"]["used_percent"] == 35
        _assert_safe(_journal(base_url))


@pytest.mark.parametrize(
    ("scenario", "settings_status", "billing_status"),
    [
        ("test-xai-external", 200, None),
        ("test-xai-invalid-redirect", 200, None),
        ("test-xai-settings-failure", 503, 200),
        ("test-xai-billing-denied", 200, 403),
        ("test-xai-unavailable", 200, 503),
        ("test-xai-malformed", 200, 200),
    ],
)
def test_xai_status_scenarios(
    scenario: str,
    settings_status: int,
    billing_status: int | None,
) -> None:
    """Return deterministic xAI settings and billing outcomes."""
    with _running_proxy() as base_url:
        settings = _xai(base_url, "/v1/settings", scenario)
        assert settings.status_code == settings_status
        if scenario == "test-xai-external":
            assert (
                settings.json()["usage_billing_redirect_url"]
                == "https://grok.com/usage"
            )
        if scenario == "test-xai-invalid-redirect":
            assert (
                settings.json()["usage_billing_redirect_url"]
                == "https://example.com/rejected"
            )
        if billing_status is not None:
            billing = _xai(base_url, "/v1/billing?format=credits", scenario)
            assert billing.status_code == billing_status
            if scenario == "test-xai-malformed":
                assert isinstance(billing.json()["config"], list)
        _assert_safe(_journal(base_url))


def test_xai_transport_and_required_billing_query() -> None:
    """Close the xAI billing transport and require credits format."""
    with _running_proxy() as base_url:
        _xai(base_url, "/v1/settings", "test-xai-transport").raise_for_status()
        with pytest.raises(requests.ConnectionError):
            _xai(base_url, "/v1/billing?format=credits", "test-xai-transport")
        missing_format = _xai(base_url, "/v1/billing", "test-xai-normal")
        assert missing_format.status_code == 400
        _assert_safe(_journal(base_url))


def _queue_oauth_connection(base_url: str, *, provider: str) -> None:
    """Queue one deterministic OAuth account for a provider device flow."""
    response = requests.post(
        f"{base_url}/v1/_oauth_connection_scenarios",
        json={
            "provider": provider,
            "scenario": f"test-{provider}-account",
            "access_token": f"test-{provider}-access",
            "refresh_token": f"test-{provider}-refresh",
        },
        timeout=2,
    )
    response.raise_for_status()
    assert "access" not in response.text
    assert "refresh" not in response.text


def test_chatgpt_device_flow_returns_queued_account_tokens() -> None:
    """Complete ChatGPT device authorization through provider-shaped endpoints."""
    with _running_proxy() as base_url:
        _queue_oauth_connection(base_url, provider="chatgpt")
        started = requests.post(
            f"{base_url}/chatgpt/device/usercode",
            json={"client_id": "test-client"},
            timeout=2,
        )
        started.raise_for_status()
        device_auth_id = started.json()["device_auth_id"]
        authorized = requests.post(
            f"{base_url}/chatgpt/device/token",
            json={
                "device_auth_id": device_auth_id,
                "user_code": started.json()["user_code"],
            },
            timeout=2,
        )
        authorized.raise_for_status()
        token = requests.post(
            f"{base_url}/chatgpt/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": authorized.json()["authorization_code"],
            },
            timeout=2,
        )
        token.raise_for_status()
        assert token.json()["access_token"] == "test-chatgpt-access"
        assert token.json()["refresh_token"] == "test-chatgpt-refresh"
        assert isinstance(token.json()["id_token"], str)
        assert _journal(base_url) == []


def test_xai_device_flow_returns_queued_account_tokens() -> None:
    """Complete xAI device authorization through provider-shaped endpoints."""
    with _running_proxy() as base_url:
        _queue_oauth_connection(base_url, provider="xai")
        started = requests.post(
            f"{base_url}/oauth2/device/code",
            data={"client_id": "test-client"},
            timeout=2,
        )
        started.raise_for_status()
        token = requests.post(
            f"{base_url}/oauth2/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "device_code": started.json()["device_code"],
            },
            timeout=2,
        )
        token.raise_for_status()
        assert token.json()["access_token"] == "test-xai-access"
        assert token.json()["refresh_token"] == "test-xai-refresh"
        assert isinstance(token.json()["id_token"], str)
        assert _journal(base_url) == []
