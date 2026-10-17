"""Real Workspace personal management and reverse Agent policy Web journey."""

import azentsadminclient
import azentspublicclient
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.personal_toolkit_response import PersonalToolkitResponse
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import single_candidate_model_options, unique
from tests.required.public.test_github_user_toolkit import _response
from tests.required.public.test_personal_toolkits import _list
from tests.required.public.test_runtime_optional_capability import _create_workspace
from tests.web.public.test_agent_toolkits import (
    _assert_visible_text,
    _click_button,
    _fill_text_input,
    _login_main_web,
    _wait,
)


def _toggle_policy(driver: WebDriver, *, initially_selected: bool) -> None:
    """Locate the hydrated policy control again if React replaces its DOM node."""
    wait = WebDriverWait(
        driver,
        20,
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    )
    locator = (By.CSS_SELECTOR, "[role='checkbox']")
    selected = str(initially_selected).lower()
    wait.until(
        lambda current: (
            current.find_element(*locator).get_attribute("aria-checked") == selected
        )
    )

    def toggle(current: WebDriver) -> bool:
        checkbox = current.find_element(*locator)
        if checkbox.get_attribute("aria-checked") != selected:
            return True
        checkbox.click()
        return False

    wait.until(toggle)


def test_workspace_personal_management_and_agent_policy(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_main_web_url: str,
    browser_driver: WebDriver,
) -> None:
    """Same User navigation and form writes retain exact Workspace ownership."""
    a = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": f"Bearer {a.token}"}
    b = "personal-web-b-" + unique()
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name="Personal B", workspace_handle=b, owner_name="Owner"
        ),
        _headers=headers,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        a.handle,
        AgentCreateRequest(
            name="Personal policy Agent",
            selectable_model_options=single_candidate_model_options(a.model_selection),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
        ),
        _headers=headers,
    )
    base = (
        f"{azents_public_server_url}/toolkit/v1/workspaces/{a.handle}"
        "/personal-toolkit-configs"
    )
    saved = _response(
        requests.post(
            base,
            headers=headers,
            json={
                "toolkit_type": "mcp",
                "name": "A private connection",
                "slug": "private",
                "config": {
                    "server_url": "https://example.com/mcp",
                    "auth_type": "none",
                },
                "always_expose_tools": True,
            },
            timeout=10,
        ),
        PersonalToolkitResponse,
        label="Personal Web fixture",
    )
    web = azents_main_web_url
    _login_main_web(browser_driver, base_url=web, email=a.email)
    browser_driver.get(f"{web}/w/{a.handle}/personal-tools")
    _assert_visible_text(browser_driver, saved.name)
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Agent access"))
    ).click()
    _toggle_policy(browser_driver, initially_selected=True)
    _click_button(browser_driver, "Save access")
    _assert_visible_text(browser_driver, "Access saved.")
    restricted = _response(
        requests.get(base + "/" + saved.id, headers=headers, timeout=10),
        PersonalToolkitResponse,
        label="Saved personal policy",
    )
    assert (
        restricted.access_mode == "selected"
        and agent.id not in restricted.selected_agent_ids
    )
    browser_driver.get(f"{web}/w/{a.handle}/agents/{agent.id}/personal-tools")
    _assert_visible_text(browser_driver, saved.name)
    _toggle_policy(browser_driver, initially_selected=False)
    _click_button(browser_driver, "Save access")
    _assert_visible_text(browser_driver, "Access saved.")
    restored = _response(
        requests.get(base + "/" + saved.id, headers=headers, timeout=10),
        PersonalToolkitResponse,
        label="Reverse policy save",
    )
    assert agent.id in restored.selected_agent_ids
    browser_driver.get(f"{web}/w/{b}/personal-tools")
    _assert_visible_text(
        browser_driver,
        "No personal connections yet. "
        "Connect a tool to use it in your personal Sessions.",
    )
    assert saved.name not in browser_driver.find_element(By.TAG_NAME, "body").text
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Connect a tool"))
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//label[normalize-space(text())='Tool']/following::input[1]")
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='option' and normalize-space()='MCP']")
        )
    ).click()
    _fill_text_input(browser_driver, "Name", "B private connection")
    _fill_text_input(browser_driver, "Server URL", "https://example.com/mcp")
    _click_button(browser_driver, "Add")
    _assert_visible_text(browser_driver, "B private connection")
    assert saved.name not in browser_driver.find_element(By.TAG_NAME, "body").text
    [created] = _list(azents_public_server_url, a.token, b).items
    assert (
        created.id != saved.id
        and created.owner.workspace_id != saved.owner.workspace_id
    )
    assert created.access_mode == "all"
    browser_driver.get(f"{web}/w/{a.handle}/personal-tools")
    _assert_visible_text(browser_driver, saved.name)
    assert (
        "B private connection"
        not in browser_driver.find_element(By.TAG_NAME, "body").text
    )
    [unchanged] = _list(azents_public_server_url, a.token, a.handle).items
    assert unchanged.id == saved.id and unchanged.access_mode == "selected"
