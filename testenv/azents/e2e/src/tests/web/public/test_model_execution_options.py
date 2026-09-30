"""Browser E2E coverage for composer model execution options."""

import azentsadminclient
import azentspublicclient
import pytest
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
    _object,
    _setup_profile_agent,
    _wait_for_input_event,
    _wait_for_proxy_service_tier,
    _wait_for_session_profile,
    _wait_for_turn_provenance,
)
from tests.required.public.test_session_model_profile_api import (
    _journal,
    _replace_profile,
)

_SIGNUP_PASSWORD = "TestPass123!"
_MOBILE_PROFILE_SHEET = (
    ".mantine-Drawer-content[role='dialog']:has(button[aria-label='Done'])"
)


def _wait(driver: WebDriver) -> WebDriverWait[WebDriver]:
    """Return the bounded browser wait used by this surface."""
    return WebDriverWait(driver, 20, poll_frequency=0.1)


def _emulate_mobile_device(driver: WebDriver) -> None:
    """Set screen, touch, and mobile identity before the product mounts."""
    version = driver.capabilities["browserVersion"]
    assert isinstance(version, str)
    driver.execute_cdp_cmd(
        "Emulation.setDeviceMetricsOverride",
        {
            "width": 390,
            "height": 844,
            "deviceScaleFactor": 1,
            "mobile": True,
            "screenWidth": 390,
            "screenHeight": 844,
            "screenOrientation": {"type": "portraitPrimary", "angle": 0},
        },
    )
    driver.execute_cdp_cmd(
        "Emulation.setTouchEmulationEnabled",
        {"enabled": True, "maxTouchPoints": 5},
    )
    driver.execute_cdp_cmd(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": (
                "Mozilla/5.0 (Linux; Android 14; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{version} Mobile Safari/537.36"
            ),
            "platform": "Android",
            "userAgentMetadata": {
                "brands": [{"brand": "Chromium", "version": version.split(".")[0]}],
                "fullVersionList": [{"brand": "Chromium", "version": version}],
                "platform": "Android",
                "platformVersion": "14.0.0",
                "architecture": "arm",
                "model": "Pixel 7",
                "mobile": True,
            },
        },
    )


def _assert_mobile_device(driver: WebDriver) -> None:
    """Verify the actual touch authority and viewport used by the composer."""
    evidence = _object(
        driver.execute_script(
            """
            return {
              touchPoints: navigator.maxTouchPoints,
              touchSupported: 'ontouchstart' in window,
              mobileUserAgent: navigator.userAgent.includes('Mobile'),
              mobileClientHint: navigator.userAgentData.mobile,
              width: window.innerWidth,
              height: window.innerHeight,
              screenWidth: screen.width,
              screenHeight: screen.height,
            };
            """
        ),
        label="emulated mobile device",
    )
    assert evidence == {
        "touchPoints": 5,
        "touchSupported": True,
        "mobileUserAgent": True,
        "mobileClientHint": True,
        "width": 390,
        "height": 844,
        "screenWidth": 390,
        "screenHeight": 844,
    }


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


def _speed_radio(driver: WebDriver, option: str) -> WebElement:
    """Locate the real group-aware speed control by its canonical option ID."""
    return _wait(driver).until(
        ec.presence_of_element_located(
            (By.CSS_SELECTOR, f"input[type='radio'][value='{option}']")
        )
    )


@pytest.mark.parametrize(
    ("target", "option"),
    [("Quality", "fast"), ("Astra", "ultrafast")],
)
def test_existing_session_speed_choice_saves_complete_displayed_profile(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    mock_openai_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    target: str,
    option: str,
) -> None:
    """Save exclusive speed plus pending effort, reload, then filter on switch."""
    suffix = unique()
    email = f"execution-option-web-{suffix}@example.com"
    handle = f"execution-option-web-{suffix}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=email,
        workspace_handle=handle,
        speed_targets=True,
    )
    _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target=target,
        effort="high",
        enabled_execution_options=[],
        client_request_id=f"initial-web-profile-{unique()}",
    ).raise_for_status()
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
    _wait(browser_driver).until(ec.element_to_be_clickable((By.NAME, "chat-message")))

    _select_reasoning_effort(browser_driver, "xhigh")
    model_trigger = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    )
    model_trigger.click()
    selected_speed = _speed_radio(browser_driver, option)
    assert not selected_speed.is_selected()
    selected_speed.send_keys(Keys.SPACE)
    assert selected_speed.is_selected()
    assert not _speed_radio(browser_driver, "").is_selected()
    if option == "ultrafast":
        assert not _speed_radio(browser_driver, "fast").is_selected()
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
        target=target,
        effort="xhigh",
        enabled_execution_options=[option],
    )
    browser_driver.refresh()
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    ).click()
    assert _speed_radio(browser_driver, option).is_selected()
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal

    # Switch to the unsupported model through the real deployed picker.
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//*[@role='dialog' and @aria-label='Model']"
                "//button[.//*[normalize-space()='Model']]",
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//*[@role='group' and @aria-label='Model']"
                "//button[.//*[normalize-space()='Fast']]",
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    ).click()
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
        target="Fast",
        effort=None,
        enabled_execution_options=[],
    )
    assert _history(azents_public_server_url, token, session_id) == before_history
    assert _journal(mock_openai_url) == before_journal


def test_before_first_message_ultrafast_submit_reaches_provider(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    openai_proxy_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Submit exclusive Ultrafast from the actual mobile bottom-sheet composer."""
    suffix = unique()
    email = f"ultrafast-submit-web-{suffix}@example.com"
    handle = f"ultrafast-submit-web-{suffix}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=email,
        workspace_handle=handle,
        speed_targets=True,
    )
    _replace_profile(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Astra",
        effort="high",
        enabled_execution_options=[],
        client_request_id=f"initial-web-profile-{unique()}",
    ).raise_for_status()
    _emulate_mobile_device(browser_driver)
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}"
    )
    _assert_mobile_device(browser_driver)
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    ).click()
    sheet = _wait(browser_driver).until(
        ec.visibility_of_element_located((By.CSS_SELECTOR, _MOBILE_PROFILE_SHEET))
    )
    _wait(browser_driver).until(
        lambda driver: driver.execute_script(
            """
            const rect = arguments[0].getBoundingClientRect();
            return Math.abs(rect.bottom - window.innerHeight) <= 1;
            """,
            sheet,
        )
    )
    fast = sheet.find_element(By.CSS_SELECTOR, "input[type='radio'][value='fast']")
    fast.send_keys(Keys.SPACE)
    ultrafast = sheet.find_element(
        By.CSS_SELECTOR, "input[type='radio'][value='ultrafast']"
    )
    ultrafast.send_keys(Keys.SPACE)
    assert ultrafast.is_selected()
    assert not fast.is_selected()
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Done']"))
    ).click()
    _wait(browser_driver).until(
        ec.invisibility_of_element_located((By.CSS_SELECTOR, _MOBILE_PROFILE_SHEET))
    )
    message = f"Ultrafast E2E served-ultrafast browser-{unique()}"
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.NAME, "chat-message"))
    ).send_keys(message)
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Send']"))
    ).click()
    event = _wait_for_input_event(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        message=message,
    )
    assert _object(event["payload"], label="input payload")[
        "requested_inference_profile"
    ] == {
        "model_target_label": "Astra",
        "reasoning_effort": "high",
        "enabled_execution_options": ["ultrafast"],
    }
    _wait_for_proxy_service_tier(
        openai_proxy_url=openai_proxy_url,
        message=message,
        model_id="gpt-6-astra",
        expected_tier="ultrafast",
    )
    marker = _wait_for_turn_provenance(
        server_url=azents_public_server_url,
        token=token,
        session_id=session_id,
        target="Astra",
        effort="high",
        enabled_execution_options=["ultrafast"],
        display_name="GPT 6 Astra Deterministic",
        effective_context_window_tokens=32_000,
    )
    # REST history omits null payload fields; unavailable is not zero.
    assert _object(marker["usage"], label="turn usage").get("cost_usd") is None
