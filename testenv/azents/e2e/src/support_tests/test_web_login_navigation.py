"""Plain-login helper ends the old document and retains strict auth evidence."""

from unittest.mock import Mock, call

import pytest
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait

from tests.web.public import test_model_execution_options as login


@pytest.mark.parametrize(
    "missing_evidence",
    [None, "inert-document", "destination", "cookie", "landmark"],
)
def test_plain_login_requires_new_document_exact_destination_and_authentication(
    monkeypatch: pytest.MonkeyPatch, missing_evidence: str | None
) -> None:
    driver = Mock(spec=WebDriver)
    email = Mock(spec=WebElement)
    password = Mock(spec=WebElement)
    landmark = Mock(spec=WebElement)
    email.is_displayed.return_value = email.is_enabled.return_value = True
    password.is_displayed.return_value = password.is_enabled.return_value = True
    landmark.is_displayed.return_value = missing_evidence != "landmark"
    base = "https://web.invalid"
    driver.current_url = f"{base}/w/old/agents/old/sessions/old"

    def navigate(url: str) -> None:
        if url != "about:blank" or missing_evidence != "inert-document":
            driver.current_url = url

    def find_element(by: str, value: str) -> Mock:
        if (by, value) == (By.NAME, "email"):
            return email
        if (by, value) == (By.NAME, "password"):
            return password
        assert (by, value) == (
            By.XPATH,
            "//h2[normalize-space(.)='Choose a workspace']",
        )
        return landmark

    def submit(*keys: str) -> None:
        assert keys == (login._SIGNUP_PASSWORD, Keys.ENTER)
        driver.current_url = (
            f"{base}/w/old/agents/old/sessions/old"
            if missing_evidence == "destination"
            else f"{base}/workspaces"
        )

    driver.get.side_effect = navigate
    driver.find_element.side_effect = find_element
    driver.find_elements.return_value = [password]
    driver.get_cookie.side_effect = lambda name: (
        None
        if missing_evidence == "cookie" and name == "az-refresh"
        else {"name": name, "value": "synthetic"}
    )
    password.send_keys.side_effect = submit
    monkeypatch.setattr(login, "_wait", lambda current: WebDriverWait(current, 0))
    if missing_evidence is None:
        login._login_main_web(driver, base_url=base, email="reader@example.test")
    else:
        with pytest.raises(TimeoutException):
            login._login_main_web(driver, base_url=base, email="reader@example.test")
    assert driver.mock_calls[:2] == [
        call.delete_all_cookies(),
        call.get("about:blank"),
    ]
    if missing_evidence == "inert-document":
        assert driver.get.call_args_list == [call("about:blank")]
        password.send_keys.assert_not_called()
    else:
        assert driver.get.call_args_list == [
            call("about:blank"),
            call(f"{base}/login"),
        ]
        email.send_keys.assert_called_once_with("reader@example.test")
        password.send_keys.assert_called_once_with(login._SIGNUP_PASSWORD, Keys.ENTER)
    driver.add_cookie.assert_not_called()
