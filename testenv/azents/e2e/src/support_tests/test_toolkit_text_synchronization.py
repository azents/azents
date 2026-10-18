"""Toolkit text readiness re-queries nodes replaced by a React render."""

from unittest.mock import Mock

import pytest
from selenium.common.exceptions import (
    StaleElementReferenceException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from tests.web.public.test_agent_toolkits import _visible_text


def test_text_readiness_requeries_replaced_nodes_without_accepting_hidden_text() -> (
    None
):
    driver = Mock(spec=WebDriver)
    stale = Mock(spec=WebElement)
    stale.is_displayed.side_effect = StaleElementReferenceException()
    hidden = Mock(spec=WebElement)
    hidden.is_displayed.return_value = False
    visible = Mock(spec=WebElement)
    visible.is_displayed.return_value = True
    driver.find_elements.side_effect = [[stale], [], [hidden], [hidden, visible]]
    assert [_visible_text(driver, "Toolkit") for _ in range(4)] == [
        False,
        False,
        False,
        True,
    ]
    assert driver.find_elements.call_count == 4
    driver.find_elements.assert_called_with(
        By.XPATH, "//*[normalize-space()='Toolkit']"
    )


def test_text_readiness_preserves_browser_transport_failures() -> None:
    driver = Mock(spec=WebDriver)
    driver.find_elements.side_effect = WebDriverException("Disconnected")
    with pytest.raises(WebDriverException, match="Disconnected"):
        _visible_text(driver, "Toolkit")
