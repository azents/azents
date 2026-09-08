"""Browser E2E coverage for composer model execution options."""

import azentsadminclient
import azentspublicclient
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
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


def _execution_option_button(
    driver: WebDriver,
    *,
    state: str,
) -> WebElement:
    """Return the keyboard-operable Fast option button in one state."""
    return _wait(driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, f"//button[starts-with(@aria-label, 'Fast, {state}.')]")
        )
    )


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


def _select_model(driver: WebDriver, label: str) -> None:
    """Select a pending model target through the desktop composer picker."""
    model_trigger = _wait(driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    )
    if model_trigger.get_attribute("aria-expanded") != "true":
        model_trigger.click()
    model_section = _wait(driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='dialog' and @aria-label='Model']"
                    "//button[.//*[normalize-space()='Model']]"
                ),
            )
        )
    )
    model_section.click()
    model_button = _wait(driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='group' and @aria-label='Model']"
                    f"//button[.//*[normalize-space()={label!r}]]"
                ),
            )
        )
    )
    model_button.click()


def test_existing_session_fast_toggle_saves_complete_displayed_profile(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    mock_openai_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Save pending effort plus Fast, survive reload, and clear on switch."""
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

    fast_off = _execution_option_button(browser_driver, state="off")
    assert fast_off.get_attribute("aria-pressed") == "false"
    assert fast_off.get_attribute("title")
    _select_reasoning_effort(browser_driver, "xhigh")
    fast_off = _execution_option_button(browser_driver, state="off")
    browser_driver.execute_script(
        """
        window.__executionOptionOriginalFetch = window.fetch;
        window.__executionOptionReleaseFetch = null;
        window.__executionOptionDelayed = false;
        window.fetch = (...args) => {
          const request = args[0];
          const url =
            typeof request === "string" ? request : String(request?.url ?? request);
          if (
            url.includes("chat.replaceSessionModelProfile") &&
            !window.__executionOptionDelayed
          ) {
            window.__executionOptionDelayed = true;
            return new Promise((resolve, reject) => {
              window.__executionOptionReleaseFetch = () => {
                window.__executionOptionOriginalFetch(...args).then(resolve, reject);
              };
            });
          }
          return window.__executionOptionOriginalFetch(...args);
        };
        """
    )
    fast_off.send_keys(Keys.SPACE)
    WebDriverWait(browser_driver, 5).until(
        lambda driver: driver.execute_script(
            "return window.__executionOptionReleaseFetch !== null;"
        )
    )
    pending_fast = _wait(browser_driver).until(
        ec.presence_of_element_located(
            (
                By.XPATH,
                "//button[starts-with(@aria-label, 'Fast, on.') and @disabled]",
            )
        )
    )
    assert pending_fast.get_attribute("aria-pressed") == "true"
    pending_model_trigger = _wait(browser_driver).until(
        ec.presence_of_element_located(
            (By.CSS_SELECTOR, "button[aria-label='Model'][disabled]")
        )
    )
    assert pending_model_trigger.get_attribute("disabled") is not None
    browser_driver.execute_script(
        """
        const release = window.__executionOptionReleaseFetch;
        window.fetch = window.__executionOptionOriginalFetch;
        release();
        """
    )

    _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Quality",
        effort="xhigh",
        enabled_execution_options=["fast"],
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal

    browser_driver.refresh()
    _wait(browser_driver).until(ec.element_to_be_clickable((By.NAME, "message")))
    fast_on = _execution_option_button(browser_driver, state="on")
    assert fast_on.get_attribute("aria-pressed") == "true"
    model_trigger = _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (By.CSS_SELECTOR, "button[aria-label='Model']")
        )
    )
    assert "Quality" in model_trigger.text
    assert "xhigh" in model_trigger.text

    fast_on.send_keys(Keys.SPACE)
    _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Quality",
        effort="xhigh",
        enabled_execution_options=[],
    )

    _select_model(browser_driver, "Fast")
    WebDriverWait(browser_driver, 5).until(
        lambda driver: (
            not driver.find_elements(
                By.XPATH,
                "//button[starts-with(@aria-label, 'Fast,')]",
            )
        )
    )

    browser_driver.set_window_size(420, 900)
    browser_driver.refresh()
    _wait(browser_driver).until(ec.element_to_be_clickable((By.NAME, "message")))
    narrow_fast = _execution_option_button(browser_driver, state="off")
    assert narrow_fast.is_displayed()
    assert narrow_fast.get_attribute("aria-pressed") == "false"

    browser_driver.execute_script(
        """
        window.__executionOptionOriginalFetch = window.fetch;
        window.fetch = (...args) => {
          const request = args[0];
          const url =
            typeof request === "string" ? request : String(request?.url ?? request);
          if (url.includes("chat.replaceSessionModelProfile")) {
            return Promise.reject(
              new TypeError("Deterministic execution-option save failure"),
            );
          }
          return window.__executionOptionOriginalFetch(...args);
        };
        """
    )
    narrow_fast.click()
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                (
                    "//*[normalize-space()='Could not save the execution option. "
                    "Your previous setting was restored.']"
                ),
            )
        )
    )
    reverted_fast = _execution_option_button(browser_driver, state="off")
    assert reverted_fast.get_attribute("aria-pressed") == "false"
    _wait_for_session_profile(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
        target="Quality",
        effort="xhigh",
        enabled_execution_options=[],
    )
    browser_driver.execute_script(
        "window.fetch = window.__executionOptionOriginalFetch;"
    )
