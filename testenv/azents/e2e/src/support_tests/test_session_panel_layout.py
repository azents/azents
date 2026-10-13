"""Docker-free regressions for responsive panel readiness ordering."""

from collections.abc import Callable
from unittest.mock import Mock

import pytest
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement

from support import session_panel_layout as layout


@pytest.mark.parametrize("page", [None, "metrics"])
def test_mobile_composer_waits_for_closed_responsive_layout(
    page: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    driver = Mock(spec=WebDriver)
    driver.current_url = "https://web/w/workspace/agents/agent/sessions/session"
    if page is not None:
        driver.current_url += f"?page={page}"
    close = Mock(spec=WebElement)
    close.is_displayed.return_value = True
    close.is_enabled.return_value = True
    toggle = Mock(spec=WebElement)
    toggle.is_displayed.return_value = False
    composer = Mock(spec=WebElement)
    composer.is_displayed.return_value = True
    composer.is_enabled.return_value = True
    driver.find_element.return_value = close
    driver.find_elements.side_effect = lambda by, selector: (
        [toggle] if selector == layout.TOGGLE[1] else [close]
    )
    wait = Mock()
    factory = Mock(return_value=wait)
    monkeypatch.setattr(layout, "WebDriverWait", factory)
    step = 0

    def until(
        condition: Callable[[WebDriver], WebElement | bool],
    ) -> WebElement | bool:
        nonlocal step
        step += 1
        if page is not None and step == 1:
            driver.set_window_size.assert_not_called()
            return condition(driver)
        if page is not None and step == 2:
            close.click.assert_called_once_with()
            driver.set_window_size.assert_not_called()
            # React closes immediately, but the route update is asynchronous.
            assert not condition(driver)
            driver.current_url = driver.current_url.split("?")[0]
            assert condition(driver)
            return True
        driver.set_window_size.assert_called_once_with(390, 844)
        # The old desktop Close control may still be present after viewport resize.
        # Never try to click it or wait for it to return after React removes it.
        assert not condition(driver)
        toggle.is_displayed.return_value = True
        assert not condition(driver)
        close.is_displayed.return_value = False
        composer.is_displayed.return_value = False
        driver.find_element.return_value = composer
        assert not condition(driver)
        composer.is_displayed.return_value = True
        assert condition(driver) is composer
        return composer

    wait.until.side_effect = until
    assert layout.prepare_mobile_session_composer(driver) is composer
    factory.assert_called_once_with(driver, 20)
    assert wait.until.call_count == (1 if page is None else 3)
    if page is None:
        close.click.assert_not_called()
    else:
        close.click.assert_called_once_with()
