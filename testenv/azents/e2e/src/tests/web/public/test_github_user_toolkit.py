"""Real browser popup/callback/review/confirmation against synthetic GitHub."""

from typing import Literal, Self

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
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    model_validator,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec

from support.utils import single_candidate_model_options
from tests.required.admin.test_03_system_settings import _generate_private_key
from tests.required.public.test_github_user_toolkit import (
    _create_confirmed,
    _decode,
    _GitHubConfig,
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


class _CreationContext(BaseModel):
    """Mirror the current strict browser storage producer, not OAuth wire state."""

    model_config = ConfigDict(extra="forbid")
    handle: StrictStr = Field(min_length=1)
    agent_id: StrictStr | None = Field(default=None, alias="agentId", min_length=1)
    attempt_id: StrictStr = Field(alias="attemptId", pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    return_path: StrictStr = Field(alias="returnPath")
    phase: Literal["AUTHORIZING", "REVIEW", "ERROR"]

    @model_validator(mode="after")
    def validate_return_path(self) -> Self:
        expected = (
            f"/w/{self.handle}/toolkits/new"
            if self.agent_id is None
            else (
                f"/w/{self.handle}/agents/{self.agent_id}"
                "/settings/capabilities#agent-toolkits"
            )
        )
        if self.return_path != expected:
            raise ValueError("Creation context has an invalid return path.")
        if "agent_id" in self.model_fields_set and self.agent_id is None:
            raise ValueError("Creation context has an invalid Agent identity.")
        return self


def _creation_context(stored: str) -> _CreationContext:
    try:
        return _CreationContext.model_validate_json(stored)
    except ValidationError:
        raise AssertionError(
            "Creation context did not match the storage contract."
        ) from None


def _click_choice(driver: WebDriver, title: str) -> None:
    """Select an identity or method choice by its visible title."""
    _wait(driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, f"//button[.//*[normalize-space()={title!r}]]")
        )
    ).click()


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
    assert _status(base, workspace.token).model_dump(exclude_unset=True) == {
        "connection": None
    }
    _click_button(browser_driver, "Confirm account and sharing")
    _assert_visible_text(browser_driver, "Execution account: connected-user")
    active = _status(base, workspace.token).connection
    assert active is not None
    assert "synthetic-token" not in browser_driver.page_source
    _click_button(browser_driver, "Save")
    _wait(browser_driver).until(
        lambda driver: driver.current_url.endswith(f"/w/{workspace.handle}/toolkits")
    )
    assert _status(base, workspace.token).connection == active
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
    assert _status(base, workspace.token).model_dump(exclude_unset=True) == {
        "connection": None
    }
    for window in list(browser_driver.window_handles):
        if window != original_window:
            browser_driver.switch_to.window(window)
            browser_driver.close()
    browser_driver.switch_to.window(original_window)


@pytest.mark.parametrize(
    "agent_owned,publish", [(False, True), (True, True), (True, False)]
)
def test_new_github_user_creation_returns_before_publication(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    github_validation_proxy_url: str,
    agent_owned: bool,
    publish: bool,
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
    _click_choice(browser_driver, "Connect with my GitHub account")
    _click_choice(browser_driver, "Register a GitHub App")
    _fill_text_input(browser_driver, "App ID", "123")
    _fill_text_input(browser_driver, "OAuth Client ID", "Iv1.azents-test")
    _fill_text_input(browser_driver, "OAuth Client Secret", "synthetic-client-secret")
    browser_driver.find_element(
        By.XPATH,
        '//label[starts-with(normalize-space(), "Private Key (PEM)")]'
        "/following::textarea[1]",
    ).send_keys(_generate_private_key())
    window = browser_driver.current_window_handle
    _click_button(browser_driver, "Authorize with GitHub")
    _assert_visible_text(browser_driver, "connected-user")
    assert browser_driver.current_window_handle == window
    assert browser_driver.current_url == azents_main_web_url + path
    assert (
        "code=" not in browser_driver.current_url
        and "state=" not in browser_driver.current_url
    )
    api = ToolkitV1Api(public_api_client)
    if agent_id:
        assert not any(
            item.toolkit.toolkit_type == "github"
            for item in api.toolkit_v1_list_agent_toolkit_management(
                handle=workspace.handle, agent_id=agent_id, _headers=headers
            ).items
        )
    else:
        assert not any(
            item.toolkit_type == "github"
            for item in api.toolkit_v1_list_toolkit_configs(
                workspace.handle, _headers=headers
            ).items
        )
    if not publish:
        assert agent_id is not None
        stored = browser_driver.execute_script(
            "return sessionStorage.getItem('azents.github-user.creation')"
        )
        assert isinstance(stored, str)
        attempt = _creation_context(stored).attempt_id
        candidate_url = (
            f"{azents_public_server_url}/toolkit/v1/workspaces/{workspace.handle}"
            f"/agents/{agent_id}/github-user-creations/{attempt}"
        )
        browser_driver.find_element(
            By.CSS_SELECTOR, '[role="dialog"] button[aria-label="Close"]'
        ).click()
        _wait(browser_driver).until(
            lambda _: (
                requests.get(candidate_url, headers=headers, timeout=10).status_code
                == 404
            )
        )
        assert (
            browser_driver.execute_script(
                "return sessionStorage.getItem('azents.github-user.creation')"
            )
            is None
        )
        assert not any(
            item.toolkit.toolkit_type == "github"
            for item in api.toolkit_v1_list_agent_toolkit_management(
                handle=workspace.handle, agent_id=agent_id, _headers=headers
            ).items
        )
        browser_driver.set_window_size(1440, 1000)
        return
    _click_button(browser_driver, "Continue to features")
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//label[normalize-space()="Actions"]',
            )
        )
    ).click()
    _click_button(browser_driver, "Continue to Runtime")
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//label[starts-with(normalize-space(), "Use this connection '
                'for git and gh commands")]',
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                '//label[normalize-space()="I understand that Agent processes '
                'can read or copy these tokens."]',
            )
        )
    ).click()
    _click_button(browser_driver, "Review connection")
    _fill_text_input(browser_driver, "Name", "Authorized browser creation")
    _click_button(browser_driver, "Save GitHub connection")
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
    if agent_id:
        saved = next(
            item.toolkit
            for item in api.toolkit_v1_list_agent_toolkit_management(
                handle=workspace.handle, agent_id=agent_id, _headers=headers
            ).items
            if item.toolkit.name == "Authorized browser creation"
        )
        config = _decode(saved.config, _GitHubConfig, label="Saved Agent GitHub config")
        assert "actions" in config.toolsets
        assert config.inject_runtime_environment is True
    else:
        saved_toolkit = next(
            item
            for item in api.toolkit_v1_list_toolkit_configs(
                workspace.handle, _headers=headers
            ).items
            if item.name == "Authorized browser creation"
        )
        config = _decode(
            saved_toolkit.config, _GitHubConfig, label="Saved GitHub config"
        )
        assert "actions" in config.toolsets
        assert config.inject_runtime_environment is True
    browser_driver.set_window_size(1440, 1000)
