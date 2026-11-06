"""Login readiness must never retain a node across WebDriver commands."""

from collections.abc import Iterator
from typing import Any

import pytest
from selenium.common.exceptions import NoSuchElementException, WebDriverException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.relative_locator import RelativeBy

from tests.web.public.test_login import _login_email_ready
from tests.web.public.test_model_execution_options import _login_main_web


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


class _LoginElement(WebElement):
    """A visible login field drives the same URL transitions as the UI."""

    def __init__(self, driver: "_LoginResetDriver", name: str) -> None:
        super().__init__(driver, name)
        self.driver = driver
        self.name = name

    def is_displayed(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def send_keys(self, *value: str) -> None:
        if Keys.ENTER in value:
            self.driver.url = (
                "https://web.example/login/password"
                if self.name == "email"
                else "https://web.example/workspaces"
            )


class _LoginResetDriver(WebDriver):
    """Model a pending authenticated page restoring cookies during a reset."""

    def __init__(self) -> None:
        self.url = "https://web.example/w/team"
        self.commands: list[str] = []
        self.authenticated_document = True
        self.cookies_present = True

    @property
    def current_url(self) -> str:
        return self.url

    def get(self, url: str) -> None:
        self.commands.append(url)
        if url.endswith("/favicon.ico"):
            self.authenticated_document = False
        elif url.endswith("/login"):
            assert not self.cookies_present, "Pending auth restored the session"
        self.url = url

    def delete_all_cookies(self) -> None:
        self.commands.append("delete cookies")
        self.cookies_present = self.authenticated_document

    def find_element(
        self, by: str | By | RelativeBy = By.ID, value: str | None = None
    ) -> WebElement:
        del by
        if value == "email" or (
            value == "password" and self.url.endswith("/login/password")
        ):
            return _LoginElement(self, value)
        raise NoSuchElementException()

    def find_elements(
        self, by: str | By | RelativeBy = By.ID, value: str | None = None
    ) -> list[WebElement]:
        try:
            return [self.find_element(by, value)]
        except NoSuchElementException:
            return []


def test_login_reset_quiesces_authenticated_page_before_clearing_cookies() -> None:
    driver = _LoginResetDriver()
    _login_main_web(driver, base_url="https://web.example", email="user@example.com")
    assert driver.commands == [
        "https://web.example/favicon.ico",
        "delete cookies",
        "https://web.example/login",
    ]
    assert driver.current_url == "https://web.example/workspaces"
