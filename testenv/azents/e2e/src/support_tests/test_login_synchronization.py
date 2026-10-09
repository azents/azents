"""Login readiness must never retain a node across WebDriver commands."""

from collections.abc import Iterator
from typing import Any

import pytest
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

from tests.web.public.test_login import _login_email_ready


class _ReplacingDocumentDriver(WebDriver):
    """Model document replacement between every remote command."""

    def __init__(self, observations: list[object]) -> None:
        self.observations: Iterator[object] = iter(observations)
        self.scripts: list[str] = []

    def execute_script(self, script: str, *args: Any) -> object:
        """Only primitive observations survive replacement; never return a node."""
        assert not args
        assert "document.querySelector" in script
        assert "checkVisibility" in script
        assert "visibilityProperty: true" in script
        assert "opacityProperty: true" in script
        assert "email.matches(':disabled')" in script
        self.scripts.append(script)
        return next(self.observations)

    def execute(self, driver_command: object, params: dict | None = None) -> dict:
        """Reject a second remote element command against an obsolete document."""
        raise AssertionError("Readiness must not retain a WebElement reference")


def test_login_readiness_requeries_current_document_atomically() -> None:
    """Missing/disabled/replaced nodes become not-ready, not stale exceptions."""
    driver = _ReplacingDocumentDriver([False, False, True, False, True])
    assert [_login_email_ready(driver) for _ in range(5)] == [
        False,
        False,
        True,
        False,
        True,
    ]
    assert len(driver.scripts) == 5
    assert len(set(driver.scripts)) == 1


@pytest.mark.parametrize("value", [None, 1, "true", {}])
def test_login_readiness_requires_a_boolean_observation(value: object) -> None:
    assert not _login_email_ready(_ReplacingDocumentDriver([value]))


def test_login_readiness_does_not_suppress_browser_failures() -> None:
    class _BrokenDriver(_ReplacingDocumentDriver):
        def execute_script(self, script: str, *args: Any) -> object:
            raise WebDriverException("Browser transport failed")

    with pytest.raises(WebDriverException, match="Browser transport failed"):
        _login_email_ready(_BrokenDriver([]))
