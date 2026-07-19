"""Tests for xAI OAuth endpoint resolution."""

import pytest

from .xai_oauth import (
    XAI_OAUTH_DEVICE_CODE_URL,
    XAI_OAUTH_TOKEN_URL,
    resolve_xai_oauth_device_code_url,
    resolve_xai_oauth_token_url,
)


def test_resolve_device_code_url_defaults_to_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the production device-code endpoint without an override."""
    monkeypatch.delenv("AZ_XAI_OAUTH_DEVICE_CODE_URL", raising=False)

    assert resolve_xai_oauth_device_code_url() == XAI_OAUTH_DEVICE_CODE_URL


def test_resolve_device_code_url_uses_process_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the process-local non-secret device-code endpoint override."""
    override = "http://openai-proxy:8081/oauth2/device/code"
    monkeypatch.setenv("AZ_XAI_OAUTH_DEVICE_CODE_URL", override)

    assert resolve_xai_oauth_device_code_url() == override


def test_resolve_token_url_defaults_to_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the production token endpoint without an override."""
    monkeypatch.delenv("AZ_XAI_OAUTH_TOKEN_URL", raising=False)

    assert resolve_xai_oauth_token_url() == XAI_OAUTH_TOKEN_URL


def test_resolve_token_url_uses_process_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the process-local non-secret token endpoint override."""
    override = "http://openai-proxy:8081/oauth2/token"
    monkeypatch.setenv("AZ_XAI_OAUTH_TOKEN_URL", override)

    assert resolve_xai_oauth_token_url() == override
