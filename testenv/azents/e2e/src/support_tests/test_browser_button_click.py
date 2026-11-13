"""Retry only WebDriver rejections that guarantee no button action dispatched."""

from unittest.mock import MagicMock

import pytest
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from tests.web.public.test_agent_toolkits import _click_button


@pytest.mark.parametrize(
    "error", [ElementClickInterceptedException, StaleElementReferenceException]
)
def test_button_click_re_resolves_after_rejected_dispatch(
    error: type[WebDriverException],
) -> None:
    driver = MagicMock(spec=WebDriver)
    first = MagicMock(spec=WebElement)
    second = MagicMock(spec=WebElement)
    for element in (first, second):
        element.is_displayed.return_value = True
        element.is_enabled.return_value = True
    driver.find_element.side_effect = [first, second]
    first.click.side_effect = error("Target moved before dispatch")
    _click_button(driver, "Start")
    first.click.assert_called_once()
    second.click.assert_called_once()


def test_uncertain_button_failure_is_not_replayed() -> None:
    driver = MagicMock(spec=WebDriver)
    element = MagicMock(spec=WebElement)
    element.is_displayed.return_value = True
    element.is_enabled.return_value = True
    driver.find_element.return_value = element
    element.click.side_effect = WebDriverException("Transport lost after click")
    with pytest.raises(WebDriverException, match="Transport lost"):
        _click_button(driver, "Start")
    element.click.assert_called_once()
