"""Browser E2E coverage for model fallback and Primary recovery controls."""

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

from support.utils import unique, wait_until
from tests.required.public.test_per_prompt_inference_profile import (
    _headers,
    _object,
    _objects,
    _response_object,
    _setup_profile_agent,
)
from tests.web.public.test_model_execution_options import _login_main_web


def _wait(driver: WebDriver) -> WebDriverWait[WebDriver]:
    """Return the bounded browser wait for recovery UI."""
    return WebDriverWait(driver, 20)


def _model_trigger(driver: WebDriver) -> WebElement:
    """Return the visible model control after responsive React replacement."""
    return next(
        element
        for element in driver.find_elements(
            By.CSS_SELECTOR,
            "button[aria-label='Model']",
        )
        if element.is_displayed()
    )


def _model_trigger_text(driver: WebDriver) -> str:
    """Return DOM text without CSS text-transform changing Badge casing."""
    return _model_trigger(driver).get_attribute("textContent") or ""


def _configure_quality_fallback_chain(
    *,
    server_url: str,
    token: str,
    handle: str,
    agent_id: str,
) -> None:
    """Replace Quality with an ordered Primary and fallback candidate chain."""
    agent_url = f"{server_url}/agent/v1/workspaces/{handle}/agents/{agent_id}"
    agent = _response_object(
        requests.get(agent_url, headers=_headers(token), timeout=10)
    )
    options = {
        option["label"]: option
        for option in _objects(
            agent.get("selectable_model_options"),
            label="Agent selectable model options",
        )
        if isinstance(option.get("label"), str)
    }

    def selection(label: str) -> dict[str, object]:
        candidates = _objects(
            options[label].get("candidates"),
            label=f"{label} candidates",
        )
        stored = _object(
            candidates[0].get("model_selection"),
            label=f"{label} model selection",
        )
        integration_id = stored.get("llm_provider_integration_id")
        model_identifier = stored.get("model_identifier")
        if not isinstance(integration_id, str) or not isinstance(model_identifier, str):
            raise AssertionError(
                f"Stored {label} candidate selection is incomplete: {stored!r}"
            )
        return {
            "llm_provider_integration_id": integration_id,
            "model_identifier": model_identifier,
        }

    quality = selection("Quality")
    fast = selection("Fast")
    response = requests.patch(
        agent_url,
        headers={**_headers(token), "Content-Type": "application/json"},
        json={
            "selectable_model_options": [
                {
                    "label": "Quality",
                    "candidates": [
                        {"model_selection": quality},
                        {"model_selection": fast},
                    ],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                },
                {
                    "label": "Fast",
                    "candidates": [{"model_selection": fast}],
                    "subagent_enabled": True,
                    "subagent_guidance": None,
                },
            ],
            "main_model_label": "Quality",
            "lightweight_model_label": "Fast",
        },
        timeout=10,
    )
    response.raise_for_status()


def _create_configured_session(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> tuple[str, str, str, str, str]:
    """Create a Session with an available Primary and ordered fallback."""
    suffix = unique()
    email = f"quota-fallback-web-{suffix}@example.com"
    handle = f"quota-fallback-web-{suffix}"
    token, agent_id, session_id = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        server_url,
        user_email=email,
        workspace_handle=handle,
    )
    _configure_quality_fallback_chain(
        server_url=server_url,
        token=token,
        handle=handle,
        agent_id=agent_id,
    )
    return email, handle, token, agent_id, session_id


def _wait_for_cooldown(
    *,
    server_url: str,
    token: str,
    agent_id: str,
    session_id: str,
) -> None:
    """Wait for authoritative Primary cooldown across Runtime startup."""
    availability_url = (
        f"{server_url}/chat/v1/agents/{agent_id}/sessions/"
        f"{session_id}/model-availability"
    )

    def cooldown_reached() -> bool:
        response = requests.get(
            availability_url,
            headers=_headers(token),
            timeout=10,
        )
        return (
            response.status_code == 200
            and _response_object(response).get("state") == "cooldown"
        )

    wait_until(
        cooldown_reached,
        timeout=120,
        interval=0.5,
        message="Primary candidate did not enter cooldown",
    )


def test_agent_editor_reorders_and_persists_fallback_candidates(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """The nested editor preserves the whole chain and changes Primary by order."""
    suffix = unique()
    email = f"quota-editor-web-{suffix}@example.com"
    handle = f"quota-editor-web-{suffix}"
    token, agent_id, _ = _setup_profile_agent(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        user_email=email,
        workspace_handle=handle,
    )
    _configure_quality_fallback_chain(
        server_url=azents_public_server_url,
        token=token,
        handle=handle,
        agent_id=agent_id,
    )
    browser_driver.set_window_size(1440, 1000)
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{handle}/agents/{agent_id}/settings/model"
    )
    _wait(browser_driver).until(
        ec.visibility_of_element_located((By.XPATH, "//*[normalize-space()='Primary']"))
    )
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[normalize-space()='Fallback 1']")
        )
    )
    move_up_buttons = _wait(browser_driver).until(
        ec.presence_of_all_elements_located(
            (By.CSS_SELECTOR, "button[aria-label='Move candidate up']")
        )
    )
    enabled_move_up = next(button for button in move_up_buttons if button.is_enabled())
    enabled_move_up.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Save']"))
    ).click()

    agent_url = (
        f"{azents_public_server_url}/agent/v1/workspaces/{handle}/agents/{agent_id}"
    )

    def reordered() -> bool:
        response = requests.get(agent_url, headers=_headers(token), timeout=10)
        if response.status_code != 200:
            return False
        options = _objects(
            _response_object(response).get("selectable_model_options"),
            label="saved selectable model options",
        )
        quality = next(option for option in options if option.get("label") == "Quality")
        candidates = _objects(
            quality.get("candidates"),
            label="saved Quality candidates",
        )
        selection = _object(
            candidates[0].get("model_selection"),
            label="saved Primary selection",
        )
        return selection.get("model_identifier") == "gpt-5.5-mini"

    wait_until(
        reordered,
        timeout=20,
        interval=0.2,
        message="Candidate reorder was not persisted",
    )


@pytest.mark.parametrize(
    ("width", "height", "prompt"),
    [
        (1440, 1000, "Quota fallback desktop uses secondary candidate"),
        (390, 844, "Quota fallback mobile uses secondary candidate"),
    ],
    ids=["desktop-popover", "mobile-drawer"],
)
def test_fallback_badge_and_primary_next_reservation_are_reachable(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    mock_openai_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    width: int,
    height: int,
    prompt: str,
) -> None:
    """Desktop and mobile expose authoritative fallback and reservation actions."""
    email, handle, token, agent_id, session_id = _create_configured_session(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    browser_driver.set_window_size(width, height)
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{handle}/agents/{agent_id}/sessions/{session_id}"
    )
    message_input = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.NAME, "message"))
    )
    trigger = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "button[aria-label='Model']"))
    )
    assert "Fallback" not in (trigger.get_attribute("textContent") or "")
    requests.delete(f"{mock_openai_url}/v1/_requests", timeout=10).raise_for_status()
    message_input.send_keys(prompt, Keys.ENTER)
    _wait_for_cooldown(
        server_url=azents_public_server_url,
        token=token,
        agent_id=agent_id,
        session_id=session_id,
    )
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                "//*[normalize-space()='Secondary candidate completed the request.']",
            )
        )
    )
    _wait(browser_driver).until(
        lambda driver: "Fallback" in _model_trigger_text(driver)
    )
    _model_trigger(browser_driver).click()
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(), 'Current fallback:')]")
        )
    )
    reserve = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Try Primary next']")
        )
    )
    reserve.click()
    cancel = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Cancel Primary next']")
        )
    )
    _wait(browser_driver).until(
        lambda driver: "Primary next" in _model_trigger_text(driver)
    )
    cancel.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Try Primary next']")
        )
    )
