"""Current-document browser observations never replay navigation actions."""

from unittest.mock import Mock

import pytest
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver

from tests.web.public.test_runtime_web_gateway import _current_application_ready


@pytest.mark.parametrize("observation", [True, False, None, 1, "true"])
def test_final_document_observation_requires_an_actual_boolean(
    observation: object,
) -> None:
    driver = Mock(spec=WebDriver)
    driver.execute_script.return_value = observation
    destination = "https://service.invalid/catalog#details"
    assert _current_application_ready(driver, destination) is (observation is True)
    driver.execute_script.assert_called_once()
    assert driver.execute_script.call_args.args[1] == destination
    driver.get.assert_not_called()
    driver.back.assert_not_called()
    driver.forward.assert_not_called()
    driver.find_element.assert_not_called()


def test_navigation_abort_is_only_an_unready_observation_not_action_replay() -> None:
    driver = Mock(spec=WebDriver)
    driver.execute_script.side_effect = [
        WebDriverException(
            "aborted by navigation: Inspected target navigated or closed"
        ),
        True,
    ]
    destination = "https://service.invalid/catalog#details"
    assert not _current_application_ready(driver, destination)
    assert _current_application_ready(driver, destination)
    assert driver.execute_script.call_count == 2
    driver.get.assert_not_called()
    driver.back.assert_not_called()
    driver.forward.assert_not_called()


@pytest.mark.parametrize(
    "message", [None, "script failed", "invalid session id", "disconnected"]
)
def test_unrelated_browser_errors_remain_failures(message: str | None) -> None:
    driver = Mock(spec=WebDriver)
    failure = WebDriverException(message)
    driver.execute_script.side_effect = failure
    with pytest.raises(WebDriverException) as raised:
        _current_application_ready(driver, "https://service.invalid/")
    assert raised.value is failure
