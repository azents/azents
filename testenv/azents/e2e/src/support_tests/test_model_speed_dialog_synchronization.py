"""Deterministic DOM readiness proofs for the deployed Model picker helper."""

import pytest
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.relative_locator import RelativeBy

from tests.web.public.test_model_execution_options import _speed_radio


class _Element(WebElement):
    """Typed element whose actions update an explicitly modeled DOM."""

    def __init__(self, driver: "_Driver", kind: str) -> None:
        super().__init__(driver, kind)
        self.driver = driver
        self.kind = kind

    def is_displayed(self) -> bool:
        return True

    def is_enabled(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str | None:
        if name == "aria-expanded" and self.kind == "trigger":
            return "true" if self.driver.expanded else "false"
        return None

    def click(self) -> None:
        if self.kind == "trigger":
            self.driver.model_clicks += 1
            self.driver.expanded = not self.driver.expanded
        elif self.kind == "processing":
            assert self.driver.expanded and self.driver.mount_queries == 0
            self.driver.processing_clicks += 1
            self.driver.speed_visible = True


class _Driver(WebDriver):
    """Advance mount readiness on DOM queries, never scheduler delays."""

    def __init__(
        self, *, expanded: bool, mount_queries: int, speed_visible: bool
    ) -> None:
        self.expanded = expanded
        self.initially_expanded = expanded
        self.mount_queries = mount_queries
        self.speed_visible = speed_visible
        self.model_clicks = 0
        self.processing_clicks = 0

    def find_elements(
        self,
        by: str | By | RelativeBy = By.ID,
        value: str | None = None,
    ) -> list[WebElement]:
        if value is not None and "data-execution-option-id" in value:
            return [_Element(self, "speed")] if self.speed_visible else []
        if value == "button[aria-label='Model']":
            return [_Element(self, "trigger")]
        if value is not None and (
            "role='dialog'" in value or "Processing speed" in value
        ):
            if self.initially_expanded and not self.expanded:
                raise AssertionError("Helper toggled an opening dialog closed")
            if not self.expanded:
                return []
            if self.mount_queries:
                self.mount_queries -= 1
                return []
            return [
                _Element(
                    self, "processing" if "Processing speed" in value else "dialog"
                )
            ]
        return []

    def find_element(
        self,
        by: str | By | RelativeBy = By.ID,
        value: str | None = None,
    ) -> WebElement:
        elements = self.find_elements(by, value)
        if not elements:
            raise NoSuchElementException("Modeled DOM boundary has not mounted")
        return elements[0]


@pytest.mark.parametrize(
    "expanded,mount_queries,model_clicks",
    [
        (False, 2, 1),
        (True, 2, 0),
        (True, 0, 0),
    ],
)
def test_speed_helper_respects_open_intent_and_mount_readiness(
    expanded: bool,
    mount_queries: int,
    model_clicks: int,
) -> None:
    driver = _Driver(
        expanded=expanded, mount_queries=mount_queries, speed_visible=False
    )
    result = _speed_radio(driver, "openai_priority")
    assert isinstance(result, _Element)
    assert result.kind == "speed"
    assert driver.model_clicks == model_clicks
    assert driver.processing_clicks == 1


def test_visible_speed_control_needs_no_dialog_toggle() -> None:
    driver = _Driver(expanded=True, mount_queries=0, speed_visible=True)
    result = _speed_radio(driver, "openai_priority")
    assert isinstance(result, _Element)
    assert driver.model_clicks == driver.processing_clicks == 0
