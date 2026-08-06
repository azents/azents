"""Unit tests for shared E2E support helpers."""

from unittest.mock import Mock

import pytest
import requests

from support import utils


def _catalog_response(payload: dict[str, object]) -> Mock:
    response = Mock(spec=requests.Response)
    response.status_code = 200
    response.json.return_value = payload
    return response


def test_model_listing_rejects_system_catalog_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not select a system model while integration sync is still pending."""
    response = _catalog_response(
        {
            "catalog_scope": "system",
            "latest_attempt": {"status": "succeeded"},
            "entries": [{"provider_model_identifier": "system-model"}],
        }
    )
    monkeypatch.setattr(utils.http_requests, "get", Mock(return_value=response))

    with pytest.raises(AssertionError, match="Integration-scoped catalog"):
        utils.list_ready_integration_models("http://server", "token", "workspace", "id")


def test_model_listing_requires_completed_integration_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not select entries from an integration snapshot still being replaced."""
    response = _catalog_response(
        {
            "catalog_scope": "integration",
            "latest_attempt": {"status": "running"},
            "entries": [{"provider_model_identifier": "stale-model"}],
        }
    )
    monkeypatch.setattr(utils.http_requests, "get", Mock(return_value=response))

    with pytest.raises(AssertionError, match="has not succeeded"):
        utils.list_ready_integration_models("http://server", "token", "workspace", "id")


def test_model_listing_accepts_completed_integration_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Return selectable entries only after the integration projection succeeds."""
    payload: dict[str, object] = {
        "catalog_scope": "integration",
        "latest_attempt": {"status": "succeeded"},
        "entries": [{"provider_model_identifier": "gpt-5.5"}],
    }
    response = _catalog_response(payload)
    monkeypatch.setattr(utils.http_requests, "get", Mock(return_value=response))

    assert (
        utils.list_ready_integration_models(
            "http://server", "token", "workspace", "integration"
        )
        == payload
    )
