"""Real browser popup/callback/review/confirmation against synthetic GitHub."""

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.admin.test_03_system_settings import _generate_private_key
from tests.required.public.test_github_user_toolkit import _scenario, _status
from tests.required.public.test_runtime_optional_capability import _create_workspace
from tests.web.public.test_agent_toolkits import (
    _assert_visible_text,
    _click_button,
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
    toolkit = ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=workspace.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
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
        _headers=headers,
    )
    base = (
        f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
        f"/toolkit-configs/{toolkit.id}/github-user"
    )
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=workspace.email)
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/toolkits/{toolkit.id}/edit"
    )
    _assert_visible_text(browser_driver, "No GitHub execution account is connected.")
    original_window = browser_driver.current_window_handle
    _click_button(browser_driver, "Authorize GitHub account")
    _wait(browser_driver).until(lambda driver: len(driver.window_handles) == 2)
    _assert_visible_text(browser_driver, "Confirm GitHub execution account")
    assert browser_driver.current_window_handle == original_window
    dialog = browser_driver.find_element(By.CSS_SELECTOR, '[role="dialog"]')
    assert "connected-user" in dialog.text
    assert _status(base, workspace.token) == {"connection": None}
    _click_button(browser_driver, "Confirm account and sharing")
    _assert_visible_text(browser_driver, "Execution account: connected-user")
    active = _status(base, workspace.token)["connection"]
    assert active is not None
    assert "synthetic-token" not in browser_driver.page_source
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
