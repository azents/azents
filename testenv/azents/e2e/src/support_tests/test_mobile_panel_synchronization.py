"""Responsive panel preparation accepts the authoritative already-closed state."""

import pytest
from selenium.common.exceptions import (
    ElementNotInteractableException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from tests.web.public.test_runtime_capability_web import _close_mobile_session_panel


class _PanelElement(WebElement):
    def __init__(self, *, expanded: str, disappears: bool) -> None:
        self.expanded = expanded
        self.disappears = disappears
        self.clicks = 0

    def is_displayed(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str:
        assert name == "aria-expanded"
        return self.expanded

    def click(self) -> None:
        self.clicks += 1
        self.expanded = "false"
        if self.disappears:
            raise ElementNotInteractableException("Responsive panel already closed")


class _PanelDriver(WebDriver):
    def __init__(self, *, expanded: str, disappears: bool) -> None:
        self.panel = _PanelElement(expanded=expanded, disappears=disappears)
        self.selectors: list[str] = []

    def find_element(self, by: object = By.ID, value: str | None = None) -> WebElement:
        assert value is not None
        self.selectors.append(value)
        return self.panel

    def find_elements(
        self, by: object = By.ID, value: str | None = None
    ) -> list[WebElement]:
        assert value is not None
        self.selectors.append(value)
        return [self.panel]


def test_already_closed_panel_never_waits_for_hidden_close_control() -> None:
    driver = _PanelDriver(expanded="false", disappears=False)
    assert _close_mobile_session_panel(driver)
    assert driver.panel.clicks == 0
    assert driver.selectors == ["button[aria-label='Toggle session panel']"]


@pytest.mark.parametrize("disappears", [False, True])
def test_panel_close_race_is_reobserved_before_proceeding(disappears: bool) -> None:
    driver = _PanelDriver(expanded="true", disappears=disappears)
    assert not _close_mobile_session_panel(driver)
    assert _close_mobile_session_panel(driver)
    assert driver.panel.clicks == 1


def test_panel_readiness_does_not_suppress_transport_failures() -> None:
    class _BrokenDriver(_PanelDriver):
        def find_elements(
            self, by: object = By.ID, value: str | None = None
        ) -> list[WebElement]:
            raise WebDriverException("Browser transport failed")

    with pytest.raises(WebDriverException, match="Browser transport failed"):
        _close_mobile_session_panel(_BrokenDriver(expanded="true", disappears=False))


def test_mobile_toggle_is_selected_instead_of_hidden_desktop_duplicate() -> None:
    class _HiddenElement(_PanelElement):
        def is_displayed(self) -> bool:
            return False

    class _ResponsiveDriver(_PanelDriver):
        def find_elements(
            self, by: object = By.ID, value: str | None = None
        ) -> list[WebElement]:
            return [
                _HiddenElement(expanded="true", disappears=False),
                self.panel,
            ]

    driver = _ResponsiveDriver(expanded="false", disappears=False)
    assert _close_mobile_session_panel(driver)
    assert driver.panel.clicks == 0
