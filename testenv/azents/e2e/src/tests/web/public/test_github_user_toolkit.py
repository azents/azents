"""Real browser popup/callback/review/confirmation against synthetic GitHub."""

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from support.utils import single_candidate_model_options
from tests.required.admin.test_03_system_settings import _generate_private_key
from tests.required.public.test_github_user_toolkit import (
    _create_confirmed,
    _scenario,
    _status,
)
from tests.required.public.test_runtime_optional_capability import _create_workspace
from tests.web.public.test_agent_toolkits import (
    _assert_visible_text,
    _click_button,
    _fill_text_input,
    _login_main_web,
    _wait,
)

E2E_PLANNER_FALLBACK_WEIGHT = 45.0


def test_github_user_popup_callback_requires_explicit_sharing_confirmation(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    github_validation_proxy_url: str,
) -> None:
    """A callback stages identity; explicit confirmation grants shared authority."""
    _scenario(github_validation_proxy_url, "user_success")
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": f"Bearer {workspace.token}"}
    toolkit = _create_confirmed(
        public_api_client,
        azents_public_server_url,
        workspace.handle,
        workspace.token,
        ToolkitConfigCreateRequest(
            toolkit_type="github",
            slug="github_user",
            name="Browser GitHub execution account",
            config={
                "github_auth_type": "github_app_user",
                "toolsets": ["users", "repos"],
            },
            credentials={
                "type": "github_app_user",
                "app_id": "123",
                "client_id": "Iv1.azents-test",
                "private_key": _generate_private_key(),
                "client_secret": "synthetic-client-secret",
            },
            enabled=True,
        ),
    )
    base = (
        f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
        f"/toolkit-configs/{toolkit.id}/github-user"
    )
    disconnected = requests.delete(base + "/connection", headers=headers, timeout=15)
    assert disconnected.status_code == 204
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=workspace.email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/toolkits/{toolkit.id}/edit"
    )
    _assert_visible_text(browser_driver, "No GitHub execution account is connected.")
    original_window = browser_driver.current_window_handle
    _click_button(browser_driver, "Authorize GitHub account")
    _wait(browser_driver).until(lambda driver: len(driver.window_handles) == 2)
    authorization_window = next(
        window for window in browser_driver.window_handles if window != original_window
    )
    browser_driver.switch_to.window(authorization_window)
    _wait(browser_driver).until(
        lambda driver: (
            driver.current_url
            == f"{azents_main_web_url}/w/{workspace.handle}/toolkits/{toolkit.id}/edit"
        )
    )
    _assert_visible_text(browser_driver, "Confirm GitHub execution account")
    assert browser_driver.current_window_handle == authorization_window
    assert "code=" not in browser_driver.current_url
    assert "state=" not in browser_driver.current_url
    dialog = browser_driver.find_element(By.CSS_SELECTOR, '[role="dialog"]')
    assert "connected-user" in dialog.text
    assert _status(base, workspace.token) == {"connection": None}
    _click_button(browser_driver, "Confirm account and sharing")
    _assert_visible_text(browser_driver, "Execution account: connected-user")
    active = _status(base, workspace.token)["connection"]
    assert active is not None
    assert "synthetic-token" not in browser_driver.page_source
    _click_button(browser_driver, "Save")
    _wait(browser_driver).until(
        lambda driver: driver.current_url.endswith(f"/w/{workspace.handle}/toolkits")
    )
    assert _status(base, workspace.token)["connection"] == active
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/toolkits/{toolkit.id}/edit"
    )
    _assert_visible_text(browser_driver, "Execution account: connected-user")
    _scenario(github_validation_proxy_url, "user_cleanup_failure")
    _click_button(browser_driver, "Disconnect account")
    _assert_visible_text(browser_driver, "Disconnect this GitHub account?")
    browser_driver.find_element(
        By.XPATH,
        '//*[@role="dialog"]//button[normalize-space()="Disconnect account"]',
    ).click()
    _assert_visible_text(browser_driver, "No GitHub execution account is connected.")
    assert _status(base, workspace.token) == {"connection": None}
    for window in list(browser_driver.window_handles):
        if window != original_window:
            browser_driver.switch_to.window(window)
            browser_driver.close()
    browser_driver.switch_to.window(original_window)


@pytest.mark.parametrize("agent_owned", [False, True])
def test_new_github_user_creation_returns_before_publication(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    github_validation_proxy_url: str,
    agent_owned: bool,
) -> None:
    """Same-context mobile-sized creation returns and requires explicit sharing."""
    _scenario(github_validation_proxy_url, "user_success")
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
        with_runtime_profile=False,
    )
    headers = {"Authorization": f"Bearer {workspace.token}"}
    agent_id = None
    if agent_owned:
        agent = AgentV1Api(public_api_client).agent_v1_create_agent(
            workspace.handle,
            AgentCreateRequest(
                name="Creation browser Agent",
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
    path = f"/w/{workspace.handle}/toolkits/new"
    if agent_id:
        path = (
            f"/w/{workspace.handle}/agents/{agent_id}"
            "/settings/capabilities#agent-toolkits"
        )
    browser_driver.set_window_size(430, 900)
    browser_driver.get(azents_main_web_url + path)
    if agent_owned:
        _click_button(browser_driver, "Add Toolkit")
        _click_button(browser_driver, "GitHub")
    else:
        browser_driver.find_element(
            By.XPATH, '//label[normalize-space(text())="Tool"]/following::input[1]'
        ).click()
        _wait(browser_driver).until(
            lambda d: d.find_element(
                By.XPATH, '//*[@role="option" and normalize-space()="GitHub"]'
            )
        ).click()
    _fill_text_input(browser_driver, "Name", "Authorized browser creation")
    browser_driver.find_element(
        By.XPATH,
        '//label[normalize-space(text())="Authentication Method"]/following::input[1]',
    ).click()
    _wait(browser_driver).until(
        lambda d: d.find_element(
            By.XPATH,
            '//*[@role="option" and normalize-space()='
            '"GitHub App (self-managed) · user account"]',
        )
    ).click()
    _fill_text_input(browser_driver, "App ID", "123")
    _fill_text_input(browser_driver, "OAuth Client ID", "Iv1.azents-test")
    _fill_text_input(browser_driver, "OAuth Client Secret", "synthetic-client-secret")
    browser_driver.find_element(
        By.XPATH,
        '//label[starts-with(normalize-space(), "Private Key (PEM)")]'
        "/following::textarea[1]",
    ).send_keys(_generate_private_key())
    window = browser_driver.current_window_handle
    _click_button(browser_driver, "Authorize GitHub account")
    _assert_visible_text(browser_driver, "Confirm GitHub execution account")
    assert browser_driver.current_window_handle == window
    assert browser_driver.current_url == azents_main_web_url + path
    assert (
        "code=" not in browser_driver.current_url
        and "state=" not in browser_driver.current_url
    )
    api = ToolkitV1Api(public_api_client)
    assert not any(
        item.name == "Authorized browser creation"
        for item in api.toolkit_v1_list_toolkit_configs(
            workspace.handle, _headers=headers
        ).items
    )
    _click_button(browser_driver, "Confirm account and sharing")
    if agent_owned:
        _assert_visible_text(browser_driver, "Authorized browser creation")
    else:
        _assert_visible_text(browser_driver, "Execution account: connected-user")
        _wait(browser_driver).until(
            lambda driver: (
                driver.find_element(
                    By.XPATH,
                    '//label[normalize-space(text())="Name"]/following::input[1]',
                ).get_attribute("value")
                == "Authorized browser creation"
            )
        )
    assert "synthetic-token" not in browser_driver.page_source
    browser_driver.set_window_size(1440, 1000)
