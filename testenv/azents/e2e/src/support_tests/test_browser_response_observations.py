"""Listener-free validation of the actual Browser E2E response boundaries."""

import json
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from tests.required.public.test_session_browser_confidential import _BrowserVerification
from tests.web.public import test_session_browser as browser


def test_actual_enable_browser_decodes_capability_and_keeps_extensions_opaque(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = Mock()
    response.json.return_value = {
        "browser_enabled": True,
        "extension": {"opaque": [None, True, 42]},
    }
    patch = Mock(return_value=response)
    monkeypatch.setattr(browser.requests, "patch", patch)
    browser._enable_browser("http://invalid.test", "workspace", "agent", "token")
    response.raise_for_status.assert_called_once_with()
    assert patch.call_args.kwargs["json"] == {"browser_enabled": True}


@pytest.mark.parametrize("value", [None, 1, "true", [], {}])
def test_actual_browser_capability_never_coerces_invalid_evidence(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    response = Mock()
    response.json.return_value = {"browser_enabled": value, "private": "canary"}
    monkeypatch.setattr(browser.requests, "patch", Mock(return_value=response))
    with pytest.raises(ValidationError) as error:
        browser._enable_browser("http://invalid.test", "workspace", "agent", "token")
    assert "canary" not in str(error.value)
    assert "input_value" not in str(error.value)


def test_browser_verification_projects_title_without_rejecting_additive_payload() -> (
    None
):
    result = _BrowserVerification.model_validate_json(
        json.dumps(
            {
                "page": {"title": "Verified", "future": [None, True]},
                "tasks": [],
                "extension": {"new": True},
            }
        )
    )
    assert result.page.title == "Verified"


@pytest.mark.parametrize("value", [None, 123, True, [], {}])
def test_browser_verification_does_not_coerce_or_log_private_payload(
    value: object,
) -> None:
    with pytest.raises(ValidationError) as error:
        _BrowserVerification.model_validate_json(
            json.dumps({"page": {"title": value}, "private": "canary"})
        )
    assert "canary" not in str(error.value)
    assert "input_value" not in str(error.value)
