"""Routine inspection across real Web, public API, Worker and Runtime boundaries."""

import os
from pathlib import Path

import azentsadminclient
import azentspublicclient
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import AgentSessionSetup
from tests.required.public.test_routines import run_routine_journey
from tests.web.public.test_model_execution_options import _login_main_web


def test_routine_panel_and_collapsed_judgment_survive_reload(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    ordinary_model_stream_worker: object,
    openai_proxy_url: str,
    azents_main_web_url: str,
    browser_driver: WebDriver,
) -> None:
    """Inspect tool-created data without a fixture-only presentation shortcut."""
    del ordinary_model_stream_worker
    driver = browser_driver
    wait = WebDriverWait(driver, 30, poll_frequency=0.1)

    def inspect(setup: AgentSessionSetup) -> None:
        _login_main_web(driver, base_url=azents_main_web_url, email=setup.email)
        path = (
            f"{azents_main_web_url}/w/{setup.workspace_handle}/agents/"
            f"{setup.agent_id}/sessions/{setup.session_id}"
        )
        driver.get(path + "?page=routines")
        alpha = (By.XPATH, "//nav//button[.//*[text()='ROUTINE_E2E Alpha']]")
        wait.until(ec.element_to_be_clickable(alpha)).click()
        wait.until(
            ec.visibility_of_element_located(
                (
                    By.XPATH,
                    "//*[text()='ROUTINE_E2E a: check the local Runtime proof "
                    "once; retain a result.']",
                )
            )
        )
        root = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
        if root is not None:
            Path(root).mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(str(Path(root) / "routine-web-panel.png"))
        driver.get(path)
        attachment = (By.XPATH, "//*[normalize-space()='routine-e2e-proof.txt']")
        wait.until(ec.visibility_of_element_located(attachment))
        summaries = (By.CSS_SELECTOR, "button[aria-label='Routine'][aria-expanded]")
        wait.until(lambda current: len(current.find_elements(*summaries)) == 2)
        disclosures = driver.find_elements(*summaries)
        assert all(
            item.get_attribute("aria-expanded") == "false" for item in disclosures
        )
        disclosures[0].send_keys(Keys.ENTER)
        wait.until(
            ec.visibility_of_element_located(
                (By.XPATH, "//*[normalize-space()='Judgment completed']")
            )
        )
        if root is not None:
            driver.save_screenshot(str(Path(root) / "routine-web-judgment.png"))
        driver.refresh()
        wait.until(ec.visibility_of_element_located(attachment))
        wait.until(lambda current: len(current.find_elements(*summaries)) == 2)
        assert all(
            item.get_attribute("aria-expanded") == "false"
            for item in driver.find_elements(*summaries)
        )

    run_routine_journey(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_admin_server_url,
        openai_proxy_url,
        inspect,
        None,
    )
