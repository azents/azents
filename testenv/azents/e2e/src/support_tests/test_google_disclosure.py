"""Browser synchronization follows the current native disclosure state."""

from typing import Literal
from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from tests.web.public.test_google_connection import disclose


@pytest.mark.parametrize("replacement", ["open", "closed", "stale"])
def test_disclosure_rechecks_current_dom_after_click(
    replacement: Literal["open", "closed", "stale"],
) -> None:
    driver = MagicMock(spec=WebDriver)
    first = MagicMock(spec=WebElement)
    current = MagicMock(spec=WebElement)
    first.is_displayed.return_value = True
    current.is_displayed.return_value = True
    state: dict[str, str | None] = {"open": None}
    first.find_element.return_value.get_dom_attribute.return_value = None
    current.find_element.return_value.get_dom_attribute.side_effect = lambda _: state[
        "open"
    ]
    driver.find_elements.return_value = [first]

    def click_first() -> None:
        driver.find_elements.return_value = [current]
        if replacement == "open":
            state["open"] = ""
        elif replacement == "stale":
            raise StaleElementReferenceException("Render replaced the disclosure")

    def click_current() -> None:
        state["open"] = ""

    first.click.side_effect = click_first
    current.click.side_effect = click_current
    disclose(driver, "Permissions and tools")
    first.click.assert_called_once()
    assert current.click.call_count == int(replacement != "open")
    assert state["open"] == ""


def test_open_disclosure_is_never_toggled_closed() -> None:
    driver = MagicMock(spec=WebDriver)
    element = MagicMock(spec=WebElement)
    element.is_displayed.return_value = True
    element.find_element.return_value.get_dom_attribute.return_value = ""
    driver.find_elements.return_value = [element]
    disclose(driver, "Permissions and tools")
    element.click.assert_not_called()
