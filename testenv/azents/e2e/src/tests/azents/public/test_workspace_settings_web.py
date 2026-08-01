"""Workspace settings hub Web Surface E2E tests."""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_invitation_request import (
    CreateInvitationRequest,
)
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.secrets import Secrets
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import authenticate_user, unique

pytestmark = pytest.mark.web_surface

_SIGNUP_PASSWORD = "TestPass123!"


def _wait(driver: WebDriver) -> WebDriverWait[WebDriver]:
    """Return the bounded browser wait used by this surface."""
    return WebDriverWait(driver, 20)


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


def _assert_visible_text(driver: WebDriver, text: str) -> None:
    """Wait for exact visible text."""
    _wait(driver).until(
        ec.visibility_of_element_located((By.XPATH, f"//*[normalize-space()={text!r}]"))
    )


def test_workspace_settings_hub_owner_and_member_flows(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Navigate focused settings as Owner and inspect them as a read-only member."""
    suffix = unique()
    owner_token, _, owner_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"workspace-settings-owner-{suffix}@example.com",
    )
    member_token, _, member_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"workspace-settings-member-{suffix}@example.com",
    )
    handle = f"workspace-settings-{suffix}"
    workspace_name = f"Workspace Settings {suffix}"
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    member_headers = {"Authorization": f"Bearer {member_token}"}

    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=workspace_name,
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=owner_headers,
    )
    invitation = InvitationV1Api(public_api_client).invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=member_email),
        _headers=owner_headers,
    )
    InvitationV1Api(public_api_client).invitation_v1_accept_invitation(
        invitation.id,
        _headers=member_headers,
    )
    integration_name = f"Workspace settings integration {suffix}"
    LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name=integration_name,
            secrets=Secrets(ApiKeySecrets(api_key="sk-workspace-settings-e2e")),
        ),
        _headers=owner_headers,
    )

    settings_url = f"{azents_main_web_url}/w/{handle}/settings"
    _login_main_web(browser_driver, base_url=azents_main_web_url, email=owner_email)
    browser_driver.get(settings_url)
    _assert_visible_text(browser_driver, workspace_name)
    _assert_visible_text(browser_driver, "Workspace settings")

    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.CSS_SELECTOR, f"a[href='/w/{handle}/settings/models']")
        )
    ).click()
    _wait(browser_driver).until(ec.url_contains("/settings/models"))
    _assert_visible_text(browser_driver, "Default models")
    _assert_visible_text(browser_driver, "Save default models")
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Back to settings"))
    ).click()
    _wait(browser_driver).until(lambda driver: driver.current_url == settings_url)

    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                f"a[href='/w/{handle}/settings/runtime-profiles']",
            )
        )
    ).click()
    _wait(browser_driver).until(ec.url_contains("/settings/runtime-profiles"))
    _assert_visible_text(browser_driver, workspace_name)
    _assert_visible_text(browser_driver, "Runtime profiles")
    _assert_visible_text(browser_driver, "No Provider profiles available")
    _assert_visible_text(browser_driver, "Add profile")
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Back to settings"))
    ).click()
    _wait(browser_driver).until(lambda driver: driver.current_url == settings_url)

    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                f"a[href='/w/{handle}/settings/llm-integrations']",
            )
        )
    ).click()
    _wait(browser_driver).until(ec.url_contains("/settings/llm-integrations"))
    _assert_visible_text(browser_driver, integration_name)
    _assert_visible_text(browser_driver, "Add integration")
    _wait(browser_driver).until(
        ec.presence_of_element_located(
            (
                By.XPATH,
                f"//input[@aria-label='Toggle {integration_name}']",
            )
        )
    )
    edit_button = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//button[@aria-label='Edit {integration_name}']",
            )
        )
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//button[@aria-label='Delete {integration_name}']",
            )
        )
    )
    edit_button.click()
    _assert_visible_text(browser_driver, "Edit LLM Integration")
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Cancel']"))
    ).click()

    browser_driver.set_window_size(390, 844)
    browser_driver.get(f"{settings_url}/llm-integrations")
    _assert_visible_text(browser_driver, workspace_name)
    _assert_visible_text(browser_driver, integration_name)
    _assert_visible_text(browser_driver, "Back to settings")
    _wait(browser_driver).until(
        ec.presence_of_element_located(
            (
                By.XPATH,
                f"//input[@aria-label='Toggle {integration_name}']",
            )
        )
    )
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                f"//button[@aria-label='Edit {integration_name}']",
            )
        )
    )
    has_horizontal_overflow = cast(
        Any,
        browser_driver,
    ).execute_script(
        "return document.documentElement.scrollWidth > "
        "document.documentElement.clientWidth;"
    )
    assert has_horizontal_overflow is False
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Back to settings"))
    ).click()
    _wait(browser_driver).until(lambda driver: driver.current_url == settings_url)
    _assert_visible_text(browser_driver, "Default models")
    browser_driver.set_window_size(1280, 844)

    browser_driver.get(f"{settings_url}/not-a-section")
    _wait(browser_driver).until(
        lambda driver: "404" in driver.find_element(By.TAG_NAME, "body").text
    )

    _login_main_web(browser_driver, base_url=azents_main_web_url, email=member_email)
    browser_driver.get(f"{settings_url}/llm-integrations")
    _assert_visible_text(browser_driver, integration_name)
    assert not browser_driver.find_elements(
        By.XPATH, "//button[normalize-space()='Add integration']"
    )
    assert not browser_driver.find_elements(
        By.XPATH,
        "//input[starts-with(@aria-label, 'Toggle ')]",
    )
    assert not browser_driver.find_elements(
        By.XPATH, "//button[starts-with(@aria-label, 'Edit ')]"
    )
    assert not browser_driver.find_elements(
        By.XPATH, "//button[starts-with(@aria-label, 'Delete ')]"
    )

    browser_driver.get(f"{settings_url}/models")
    _assert_visible_text(browser_driver, "Default models")
    assert not browser_driver.find_elements(
        By.XPATH, "//button[normalize-space()='Save default models']"
    )

    browser_driver.get(f"{settings_url}/runtime-profiles")
    _assert_visible_text(browser_driver, "Runtime profiles")
    assert not browser_driver.find_elements(
        By.XPATH, "//button[normalize-space()='Add profile']"
    )

    browser_driver.set_window_size(390, 844)
    browser_driver.get(settings_url)
    _assert_visible_text(browser_driver, workspace_name)
    _assert_visible_text(browser_driver, "Default models")
    has_horizontal_overflow = cast(
        Any,
        browser_driver,
    ).execute_script(
        "return document.documentElement.scrollWidth > "
        "document.documentElement.clientWidth;"
    )
    assert has_horizontal_overflow is False
