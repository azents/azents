"""Shared OpenAI client configuration preserves existing SDK input semantics."""

import pytest

from azents.core.enums import LLMProvider
from azents.core.openai_client_config import (
    openai_credential_headers,
    openai_responses_client_config,
)


def test_explicit_credentials_override_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep endpoint, organization and header precedence unchanged."""
    monkeypatch.setenv("AZ_OPENAI_BASE_URL", "https://az.example.test/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://sdk.example.test/v1")
    monkeypatch.setenv("OPENAI_ORG_ID", "environment-organization")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "environment-project")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", "X-Shared: env\nX-Env: retained")
    headers = {"X-Shared": "credential", "X-Account": "account"}
    config = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={
            "api_key": "synthetic-test-key",
            "base_url": "https://explicit.example.test/v1",
            "api_base": "https://alias.example.test/v1",
            "organization": "explicit-organization",
            "project": "explicit-project",
            "extra_headers": headers,
        },
    )
    assert config.api_key == "synthetic-test-key"
    assert config.base_url == "https://explicit.example.test/v1"
    assert config.organization == "explicit-organization"
    assert config.project == "explicit-project"
    assert config.default_headers == {
        "X-Shared": "credential",
        "X-Env": "retained",
        "X-Account": "account",
    }
    headers["X-Shared"] = "later-change"
    assert config.default_headers["X-Shared"] == "credential"


def test_provider_endpoint_environment_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Apply the Azents OpenAI override only to its existing provider identity."""
    monkeypatch.setenv("AZ_OPENAI_BASE_URL", "https://az.example.test/v1")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://sdk.example.test/v1")
    openai = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={},
    )
    chatgpt = openai_responses_client_config(
        provider=LLMProvider.CHATGPT_OAUTH,
        credential_kwargs={},
    )
    alias = openai_responses_client_config(
        provider=LLMProvider.OPENAI,
        credential_kwargs={"api_base": "https://alias.example.test/v1"},
    )
    assert openai.base_url == "https://az.example.test/v1"
    assert chatgpt.base_url == "https://sdk.example.test/v1"
    assert alias.base_url == "https://alias.example.test/v1"


@pytest.mark.parametrize(
    "key", ["api_key", "base_url", "api_base", "organization", "project"]
)
def test_invalid_credential_type_does_not_serialize_value(key: str) -> None:
    """Configuration validation identifies only the field, never its value."""
    with pytest.raises(TypeError, match=f"OpenAI client option {key} must be a string"):
        openai_responses_client_config(
            provider=LLMProvider.OPENAI,
            credential_kwargs={key: {"private-value": "synthetic-canary"}},
        )


@pytest.mark.parametrize("value", [None, {}, {"X-Account": "test"}])
def test_header_copy_retains_none_and_empty_contract(
    value: dict[str, str] | None,
) -> None:
    """Preserve absent versus explicitly empty configuration without aliasing."""
    copied = openai_credential_headers(value)
    assert copied == value
    if value is not None:
        assert copied is not value


@pytest.mark.parametrize(
    "value", [{"X-Invalid": 1}, {1: "invalid"}, "synthetic-canary"]
)
def test_invalid_headers_fail_without_value_serialization(value: object) -> None:
    """Keep invalid header diagnostics independent of credential content."""
    with pytest.raises(TypeError, match=r"extra_headers must be dict\[str, str\]"):
        openai_credential_headers(value)
