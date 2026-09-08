"""Browser E2E coverage for composer model execution options."""

import azentsadminclient
import azentspublicclient
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import unique
from tests.required.public.test_per_prompt_inference_profile import (
    _history,
    _setup_profile_agent,
    _wait_for_session_profile,
)
from tests.required.public.test_session_model_profile_api import _journal

_SIGNUP_PASSWORD = "TestPass123!"


def _wait(driver: WebDriver) -> WebDriverWait[WebDriver]:
    """Return the bounded browser wait used by this surface."""
    return WebDriverWait(driver, 20)


def _login_main_web(
    driver: WebDriver,
    *,
    base_url: str,
    email: str,
) -> None:
    """Authenticate through the deployed Main Web login flow."""
    driver.delete_all_cookies()
    driver.get(f"{base_url}/login")
    email_input = _wait(driver).until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/login/password"))
    password_input = _wait(driver).until(
        ec.element_to_be_clickable((By.NAME, "password"))
    )
    password_input.send_keys(_SIGNUP_PASSWORD, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))


def _select_reasoning_effort(driver: WebDriver, effort: str) -> None:
    """Select a pending reasoning effort through the desktop composer picker."""
    model_trigger = _wait(driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    )
    model_trigger.send_keys(Keys.ARROW_DOWN)
    effort_section = _wait(driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='dialog' and @aria-label='Model']"
                    "//button[.//*[normalize-space()='Reasoning effort']]"
                ),
            )
        )
    )
    effort_section.click()
    effort_button = _wait(driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='group' and @aria-label='Reasoning effort']"
                    f"//button[normalize-space()={effort!r}]"
                ),
            )
        )
    )
    effort_button.click()


def test_existing_session_fast_toggle_saves_complete_displayed_profile(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    mock_openai_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Confirm pending effort plus Fast and preserve the selection after reload."""
    suffix = unique()
    email = f"execution-option-web-{suffix}@example.com"
    handle = f"execution-option-web-{suffix}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=email,
        workspace_handle=handle,
    )
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()
    before_history = _history(azents_public_server_url, token, session_id)
    before_journal = _journal(mock_openai_url)

    browser_driver.set_window_size(1440, 1000)
    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=email,
    )
    session_url = (
        f"{azents_main_web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}"
    )
    browser_driver.get(session_url)
    _wait(browser_driver).until(ec.element_to_be_clickable((By.NAME, "message")))

    _select_reasoning_effort(browser_driver, "xhigh")
    model_trigger = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    )
    model_trigger.click()
    fast = _wait(browser_driver).until(
        ec.presence_of_element_located(
            (By.CSS_SELECTOR, "input[role='switch'][aria-label='Fast']")
        )
    )
    assert not fast.is_selected()
    fast.send_keys(Keys.SPACE)
    assert fast.is_selected()
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal
    model_trigger.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, "button[aria-label='Apply model change']")
        )
    ).click()
    _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Quality",
        effort="xhigh",
        enabled_execution_options=["fast"],
    )
    browser_driver.refresh()
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    ).click()
    fast = _wait(browser_driver).until(
        ec.presence_of_element_located(
            (By.CSS_SELECTOR, "input[role='switch'][aria-label='Fast']")
        )
    )
    assert fast.is_selected()
