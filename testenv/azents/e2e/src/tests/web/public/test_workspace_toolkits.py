"""Workspace Toolkit management through the assembled browser and public API."""

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.toolkit_config_response import ToolkitConfigResponse
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec

from tests.required.public.test_runtime_optional_capability import _create_workspace
from tests.web.public.test_agent_toolkits import (
    _assert_visible_text,
    _click_button,
    _fill_text_input,
    _login_main_web,
    _wait,
)

E2E_PLANNER_FALLBACK_WEIGHT = 30.0


def _open_details(driver: WebDriver, name: str) -> None:
    """Open the exact card, not another instance with the same provider type."""
    card = _wait(driver).until(
        ec.presence_of_element_located(
            (
                By.XPATH,
                f"//*[normalize-space()={name!r}]/ancestor::article[1]",
            )
        )
    )
    card.find_element(By.XPATH, ".//button[normalize-space()='View details']").click()


def test_workspace_toolkit_catalog_details_and_mutations_are_persisted(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Create, inspect, edit, toggle and explicitly delete a shared Toolkit."""
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": f"Bearer {workspace.token}"}
    api = ToolkitV1Api(public_api_client)
    name = "Workspace browser MCP"
    renamed = "Workspace browser MCP renamed"
    path = f"/w/{workspace.handle}/toolkits"

    def configs() -> list[ToolkitConfigResponse]:
        return api.toolkit_v1_list_toolkit_configs(
            workspace.handle, _headers=headers
        ).items

    _login_main_web(browser_driver, base_url=azents_main_web_url, email=workspace.email)
    browser_driver.set_window_size(430, 900)
    browser_driver.get(azents_main_web_url + path)
    _click_button(browser_driver, "Add Toolkit")
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, '//button[.//*[normalize-space()="MCP"]]')
        )
    ).click()
    _fill_text_input(browser_driver, "Name", name)
    _fill_text_input(browser_driver, "Server URL", "https://example.com/mcp")
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, '//summary[.="Advanced naming and instructions"]')
        )
    ).click()
    _fill_text_input(browser_driver, "Slug", "workspace_browser_service")
    _click_button(browser_driver, "Add")
    _assert_visible_text(browser_driver, name)
    # The form's settings review already displays the name before save completes.
    created = _wait(browser_driver).until(
        lambda _: next((item for item in configs() if item.name == name), None)
    )
    assert created is not None
    saved = created
    assert saved.toolkit_type == "mcp"
    assert saved.slug == "workspace_browser_service"
    assert saved.enabled is True
    assert saved.config["server_url"] == "https://example.com/mcp"
    assert browser_driver.current_url == azents_main_web_url + path

    _open_details(browser_driver, name)
    _assert_visible_text(browser_driver, "https://example.com")
    _click_button(browser_driver, "Edit")
    _fill_text_input(browser_driver, "Name", renamed)
    _click_button(browser_driver, "Save")
    _assert_visible_text(browser_driver, renamed)
    updated = _wait(browser_driver).until(
        lambda _: next(
            (
                item
                for item in configs()
                if item.id == saved.id and item.name == renamed
            ),
            None,
        )
    )
    assert updated is not None
    assert updated.slug == saved.slug
    # Saving an edit returns to the exact Toolkit's details dialog.
    # Mantine's visible label remains clickable while its hidden input is disabled.
    _wait(browser_driver).until(
        lambda driver: driver.find_element(
            By.CSS_SELECTOR, '[role="dialog"] input[role="switch"]'
        ).is_enabled()
    )
    browser_driver.find_element(
        By.XPATH, '//label[normalize-space()="Toolkit enabled"]'
    ).click()
    _wait(browser_driver).until(
        lambda _: not next(item for item in configs() if item.id == saved.id).enabled
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//*[@role="dialog"]//button[@aria-label="Close"]',
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.invisibility_of_element_located((By.CSS_SELECTOR, '[role="dialog"]'))
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//article[@aria-label={renamed!r}]"
                '//button[normalize-space()="Delete"]',
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//*[@role="dialog"][.//*[normalize-space()='
                '"Are you sure you want to delete this toolkit?"]]'
                '//button[normalize-space()="Delete"]',
            )
        )
    ).click()
    _wait(browser_driver).until(
        lambda _: not any(item.id == saved.id for item in configs())
    )
    _wait(browser_driver).until(
        lambda driver: (
            not any(
                item.is_displayed()
                for item in driver.find_elements(
                    By.XPATH, f"//*[normalize-space()={renamed!r}]"
                )
            )
        )
    )
    browser_driver.refresh()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, '//button[normalize-space()="Add Toolkit"]')
        )
    )
    assert not any(item.id == saved.id for item in configs())
    browser_driver.set_window_size(1440, 1000)
