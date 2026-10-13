"""Real browser Google callback/review with fixed-host synthetic TLS provider."""

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec

from support.google_provider_fixture import GoogleProviderFixture
from support.utils import single_candidate_model_options
from tests.required.public.test_google_connection import (
    fixture_ready,
    prepare_operator,
    saved_status,
    scenario,
)
from tests.required.public.test_runtime_optional_capability import _create_workspace
from tests.web.public.test_agent_toolkits import (
    _assert_visible_text,
    _click_button,
    _fill_text_input,
    _login_main_web,
    _wait,
)

E2E_PLANNER_FALLBACK_WEIGHT = 35.0


def check(driver: WebDriver, label: str) -> None:
    _wait(driver).until(
        ec.element_to_be_clickable((By.XPATH, f"//label[normalize-space()={label!r}]"))
    ).click()


@pytest.mark.parametrize("agent_owned", [False, True])
def test_google_same_context_partial_review_and_metadata_preservation(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    google_provider_fixture: GoogleProviderFixture | None,
    agent_owned: bool,
) -> None:
    fixture = fixture_ready(google_provider_fixture)
    scenario(fixture, "partial")
    prepare_operator(admin_api_client)
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": "Bearer " + workspace.token}
    agent_id = None
    if agent_owned:
        agent = AgentV1Api(public_api_client).agent_v1_create_agent(
            workspace.handle,
            AgentCreateRequest(
                name="Google browser Agent",
                type=AgentType.PUBLIC,
                selectable_model_options=single_candidate_model_options(
                    workspace.model_selection
                ),
                main_model_label="default",
                lightweight_model_label="default",
            ),
            _headers=headers,
        )
        agent_id = agent.id
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=workspace.email)
    path = (
        f"/w/{workspace.handle}/toolkits/new"
        if agent_id is None
        else (
            f"/w/{workspace.handle}/agents/{agent_id}"
            "/settings/capabilities#agent-toolkits"
        )
    )
    browser_driver.set_window_size(430, 900)
    browser_driver.get(azents_main_web_url + path)
    if agent_id is not None:
        _click_button(browser_driver, "Add Toolkit")
        _click_button(browser_driver, "Google")
    else:
        _wait(browser_driver).until(
            ec.element_to_be_clickable(
                (
                    By.XPATH,
                    '//label[starts-with(., "Tool")]/following::input[1]',
                )
            )
        ).click()
        _wait(browser_driver).until(
            ec.element_to_be_clickable(
                (By.XPATH, '//*[@role="option" and normalize-space()="Google"]')
            )
        ).click()
    _assert_visible_text(browser_driver, "1. Choose tasks")
    assert not any(
        item.is_selected()
        for item in browser_driver.find_elements(
            By.CSS_SELECTOR,
            'section[aria-labelledby="google-select-heading"] input[type="checkbox"]',
        )
    )
    check(browser_driver, "Read calendars and events")
    check(browser_driver, "Read Gmail")
    original_window = browser_driver.current_window_handle
    _click_button(browser_driver, "Continue to Google")
    _assert_visible_text(browser_driver, "2. Review account and permissions")
    _assert_visible_text(browser_driver, "connected-account@example.invalid")
    assert browser_driver.current_window_handle == original_window
    assert browser_driver.current_url == azents_main_web_url + path
    assert (
        "state=" not in browser_driver.current_url
        and "code=" not in browser_driver.current_url
    )
    api = ToolkitV1Api(public_api_client)
    if agent_id is None:
        assert not any(
            item.toolkit_type == "google"
            for item in api.toolkit_v1_list_toolkit_configs(
                workspace.handle, _headers=headers
            ).items
        )
    else:
        assert not any(
            item.toolkit.toolkit_type == "google"
            for item in api.toolkit_v1_list_agent_toolkit_management(
                handle=workspace.handle, agent_id=agent_id, _headers=headers
            ).items
        )
    save = browser_driver.find_element(
        By.XPATH, '//button[normalize-space()="Save Google Toolkit"]'
    )
    assert not save.is_enabled()
    _fill_text_input(browser_driver, "Toolkit name", "Google browser connection")
    check(
        browser_driver,
        "I have reviewed these screening limits and the ownership of this connection.",
    )
    _click_button(browser_driver, "Save Google Toolkit")
    _assert_visible_text(browser_driver, "Google browser connection")
    if agent_id is None:
        saved = next(
            item
            for item in api.toolkit_v1_list_toolkit_configs(
                workspace.handle, _headers=headers
            ).items
            if item.toolkit_type == "google"
        )
        browser_driver.get(
            f"{azents_main_web_url}/w/{workspace.handle}/toolkits/{saved.id}/edit"
        )
    else:
        saved = next(
            item.toolkit
            for item in api.toolkit_v1_list_agent_toolkit_management(
                handle=workspace.handle, agent_id=agent_id, _headers=headers
            ).items
            if item.toolkit.toolkit_type == "google"
        )
        # Drive the same embedded edit surface that must reopen after OAuth return.
        _click_button(browser_driver, "View details")
        _click_button(browser_driver, "Edit")
    _assert_visible_text(browser_driver, "Saved Google account")
    _fill_text_input(browser_driver, "Tool request timeout (seconds)", "12")
    _click_button(browser_driver, "Authorize replacement connection")
    _assert_visible_text(browser_driver, "2. Review account and permissions")
    check(
        browser_driver,
        "I have reviewed these screening limits and the ownership of this connection.",
    )
    _click_button(browser_driver, "Replace saved connection")
    _assert_visible_text(browser_driver, "Connection saved")
    _fill_text_input(browser_driver, "Name", "Renamed after reconnect")
    if agent_owned:
        _wait(browser_driver).until(
            ec.element_to_be_clickable(
                (By.XPATH, '//*[@role="dialog"]//button[normalize-space()="Save"]')
            )
        ).click()
    else:
        _click_button(browser_driver, "Save")
    _assert_visible_text(browser_driver, "Renamed after reconnect")
    current = (
        api.toolkit_v1_get_toolkit_config(
            handle=workspace.handle, toolkit_config_id=saved.id, _headers=headers
        )
        if agent_id is None
        else api.toolkit_v1_get_agent_toolkit_config(
            handle=workspace.handle,
            agent_id=agent_id,
            toolkit_config_id=saved.id,
            _headers=headers,
        )
    )
    assert current.config["timeout"] == 12
    assert current.name == "Renamed after reconnect"
    base = f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}" + (
        "" if agent_id is None else "/agents/" + agent_id
    )
    assert saved_status(base, workspace.token, saved.id).status == "connected"
    assert (
        "synthetic-access-" not in browser_driver.page_source
        and "synthetic-renewal-" not in browser_driver.page_source
    )
