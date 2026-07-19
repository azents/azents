"""Tests for ChatGPT OAuth constants and headers."""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from .chatgpt_oauth import (
    CHATGPT_OAUTH_DEVICE_TOKEN_URL,
    CHATGPT_OAUTH_DEVICE_USER_CODE_URL,
    CHATGPT_OAUTH_TOKEN_URL,
    resolve_chatgpt_oauth_device_token_url,
    resolve_chatgpt_oauth_device_user_code_url,
    resolve_chatgpt_oauth_token_url,
)


@pytest.mark.parametrize(
    ("environment_name", "resolver", "production_url"),
    [
        (
            "AZ_CHATGPT_OAUTH_DEVICE_USER_CODE_URL",
            resolve_chatgpt_oauth_device_user_code_url,
            CHATGPT_OAUTH_DEVICE_USER_CODE_URL,
        ),
        (
            "AZ_CHATGPT_OAUTH_DEVICE_TOKEN_URL",
            resolve_chatgpt_oauth_device_token_url,
            CHATGPT_OAUTH_DEVICE_TOKEN_URL,
        ),
    ],
)
def test_resolve_oauth_device_url_defaults_to_production(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    resolver: Callable[[], str],
    production_url: str,
) -> None:
    """Use production device endpoints when no override is configured."""
    monkeypatch.delenv(environment_name, raising=False)

    assert resolver() == production_url


@pytest.mark.parametrize(
    ("environment_name", "resolver", "override"),
    [
        (
            "AZ_CHATGPT_OAUTH_DEVICE_USER_CODE_URL",
            resolve_chatgpt_oauth_device_user_code_url,
            "http://openai-proxy:8081/chatgpt/device/usercode",
        ),
        (
            "AZ_CHATGPT_OAUTH_DEVICE_TOKEN_URL",
            resolve_chatgpt_oauth_device_token_url,
            "http://openai-proxy:8081/chatgpt/device/token",
        ),
    ],
)
def test_resolve_oauth_device_url_uses_process_override(
    monkeypatch: pytest.MonkeyPatch,
    environment_name: str,
    resolver: Callable[[], str],
    override: str,
) -> None:
    """Use process-local non-secret device endpoint overrides."""
    monkeypatch.setenv(environment_name, override)

    assert resolver() == override


def test_resolve_oauth_token_url_defaults_to_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the production token endpoint when no override is configured."""
    monkeypatch.delenv("AZ_CHATGPT_OAUTH_TOKEN_URL", raising=False)

    assert resolve_chatgpt_oauth_token_url() == CHATGPT_OAUTH_TOKEN_URL


def test_resolve_oauth_token_url_uses_process_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the process-local non-secret token endpoint override."""
    override = "http://openai-proxy:8081/chatgpt/oauth/token"
    monkeypatch.setenv("AZ_CHATGPT_OAUTH_TOKEN_URL", override)

    assert resolve_chatgpt_oauth_token_url() == override


def test_build_headers_without_installed_package_metadata() -> None:
    """Build headers when Azents is loaded directly from its source tree."""
    source_root = Path(__file__).parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root)
    script = """
from importlib.metadata import PackageNotFoundError, version

try:
    version("azents")
except PackageNotFoundError:
    pass
else:
    raise AssertionError("azents package metadata must be unavailable")

from azents.core.chatgpt_oauth import build_chatgpt_oauth_headers

assert build_chatgpt_oauth_headers(account_id="account-id") == {
    "originator": "azents",
    "user-agent": "azents/0.1.0",
    "ChatGPT-Account-Id": "account-id",
}
"""

    subprocess.run(
        [sys.executable, "-S", "-c", script],
        check=True,
        env=env,
    )
