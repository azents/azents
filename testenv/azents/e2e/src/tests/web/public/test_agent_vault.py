"""Exercise the Vault card and shared request dialog in the assembled Main Web."""

import azentsadminclient
import azentspublicclient
import requests
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.image_generation_openai_proxy import VAULT_REQUEST_PROMPT
from support.utils import create_agent_session_setup, wait_until
from tests.required.public.test_run_tool_to_file import _history, _initialized
from tests.web.public.test_model_execution_options import _login_main_web


def test_vault_card_and_link_share_one_explicit_dialog(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    ordinary_model_stream_worker: object,
    browser_driver: WebDriver,
) -> None:
    """Use the same dialog from a card and deep link; settle both open tabs."""
    del ordinary_model_stream_worker
    setup = create_agent_session_setup(
        public_api_client, admin_api_client, azents_public_server_url
    )
    params = {
        "server_url": azents_public_server_url,
        "token": setup.access_token,
        "session_id": setup.session_id,
    }
    wait_until(
        lambda: _initialized(**params),
        timeout=120,
        interval=0.5,
        message="Vault Web Session did not initialize",
    )
    driver = browser_driver
    wait = WebDriverWait(driver, 40, poll_frequency=0.2)
    _login_main_web(driver, base_url=azents_main_web_url, email=setup.email)
    session_url = (
        f"{azents_main_web_url}/w/{setup.workspace_handle}/agents/"
        f"{setup.agent_id}/sessions/{setup.session_id}"
    )
    driver.get(session_url)
    response = requests.post(
        f"{azents_public_server_url}/chat/v1/sessions/{setup.session_id}/inputs",
        headers={"Authorization": f"Bearer {setup.access_token}"},
        json={
            "agent_id": setup.agent_id,
            "client_request_id": f"vault-web-{setup.session_id}",
            "message": VAULT_REQUEST_PROMPT,
            "inference_profile": {
                "model_target_label": "default",
                "reasoning_effort": None,
                "enabled_execution_options": [],
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    card_button = (By.XPATH, "//section[@aria-label='Vault request']//button")
    dialog = (By.CSS_SELECTOR, "[role='dialog']")
    wait.until(ec.element_to_be_clickable(card_button))
    assert not any(item.is_displayed() for item in driver.find_elements(*dialog))
    wait.until(ec.element_to_be_clickable(card_button)).click()
    fields = (By.CSS_SELECTOR, "[role='dialog'] input[type='password']")
    wait.until(lambda current: len(current.find_elements(*fields)) == 2)
    driver.find_element(
        By.CSS_SELECTOR, "[role='dialog'] button[aria-label='Close']"
    ).click()
    wait.until(ec.invisibility_of_element_located(dialog))

    anchors = [
        item for item in _history(**params).items if item.kind == "vault_request"
    ]
    assert len(anchors) == 1
    request_id = anchors[0].payload["request_id"]
    assert isinstance(request_id, str)
    first_tab = driver.current_window_handle
    driver.switch_to.new_window("tab")
    driver.get(f"{session_url}?vaultRequest={request_id}")
    wait.until(lambda current: len(current.find_elements(*fields)) == 2)
    assert "vaultRequest=" not in driver.current_url
    for field, value in zip(
        driver.find_elements(*fields),
        ("synthetic-vault-account", "synthetic-vault-password"),
        strict=True,
    ):
        field.send_keys(value)
    wait.until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='dialog']//button[@type='submit']")
        )
    ).click()
    wait.until(ec.invisibility_of_element_located(dialog))
    driver.switch_to.window(first_tab)
    submitted = (
        By.XPATH,
        "//section[@aria-label='Vault request']//*[normalize-space()='Submitted']",
    )
    wait.until(ec.visibility_of_element_located(submitted))
    assert not driver.find_elements(*card_button)
    driver.refresh()
    wait.until(ec.visibility_of_element_located(submitted))
