"""Optional managed Runtime Web Surface E2E journey."""

from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.runtime_profile_v1_api import RuntimeProfileV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_runtime_capability import AgentRuntimeCapability
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
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
from testcontainers.core.container import DockerContainer

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_SIGNUP_PASSWORD = "TestPass123!"


@dataclass(frozen=True)
class _RuntimeWebWorkspace:
    """Product-created inputs for the Runtime browser journey."""

    token: str
    email: str
    handle: str
    model_selection: AgentModelSelectionInput
    runtime_profile_name: str


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


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


def _click_button(driver: WebDriver, text: str) -> None:
    """Click one visible button by exact text."""
    _wait(driver).until(
        ec.element_to_be_clickable((By.XPATH, f"//button[normalize-space()={text!r}]"))
    ).click()


def _create_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _RuntimeWebWorkspace:
    """Create one Workspace with model and Runtime Profile through product APIs."""
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-web-{suffix}@example.com",
    )
    handle = f"runtime-web-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Web {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-web")),
        ),
        _headers=headers,
    )
    profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    profiles = RuntimeProfileV1Api(
        public_api_client
    ).runtime_profile_v1_list_workspace_runtime_profiles(
        handle=handle,
        include_disabled=True,
        _headers=headers,
    )
    profile = next(item for item in profiles.items if item.id == profile_id)
    return _RuntimeWebWorkspace(
        token=token,
        email=email,
        handle=handle,
        model_selection=model_selection_from_first_candidate(
            server_url,
            token,
            handle,
            integration.id,
        ),
        runtime_profile_name=profile.display_name,
    )


def test_runtime_free_add_and_remove_progress(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Exercise Runtime-free, add, destructive confirmation, and progress states."""
    del azents_runtime_provider_docker_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=workspace.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Web Agent {unique()}",
            model_selection=workspace.model_selection,
            lightweight_model_selection=workspace.model_selection,
            type=AgentType.PUBLIC,
        ),
        _headers=_headers(workspace.token),
    )
    assert agent.runtime_capability == AgentRuntimeCapability.NONE
    assert agent.runtime_profile_id is None

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=workspace.email,
    )
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/agents/{agent.id}/sessions/new"
    )
    _assert_visible_text(browser_driver, "Start without local Projects")
    _assert_visible_text(browser_driver, "Add a managed Runtime")
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "Add a managed Runtime"))
    ).click()
    _wait(browser_driver).until(ec.url_contains("/settings/runtime"))

    _assert_visible_text(browser_driver, "Runtime")
    _assert_visible_text(browser_driver, "No Runtime")
    _assert_visible_text(browser_driver, "This agent has no managed Runtime")
    profile_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//label[normalize-space()='Runtime Profile']/following::input[1]",
            )
        )
    )
    profile_input.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='option' and "
                    f"normalize-space()={workspace.runtime_profile_name!r}]"
                ),
            )
        )
    ).click()
    _click_button(browser_driver, "Add Runtime")
    _assert_visible_text(browser_driver, "Add managed Runtime?")
    _assert_visible_text(
        browser_driver,
        f"Add managed Runtime with {workspace.runtime_profile_name}?",
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//*[@role='dialog']//button[normalize-space()='Add Runtime']",
            )
        )
    ).click()

    _assert_visible_text(browser_driver, "Runtime was added.")
    _assert_visible_text(browser_driver, "Managed")
    _assert_visible_text(browser_driver, "Temporary Runtime controls")
    _assert_visible_text(browser_driver, "Permanently remove managed Runtime")
    _click_button(browser_driver, "Remove Runtime")
    _assert_visible_text(browser_driver, "Permanently remove Runtime?")
    _assert_visible_text(browser_driver, "This action is irreversible")
    _assert_visible_text(browser_driver, "Active root sessions")
    _assert_visible_text(browser_driver, "Deleted")
    _assert_visible_text(browser_driver, "Retained")
    _assert_visible_text(
        browser_driver,
        "I understand that Runtime removal is permanent and may interrupt active work.",
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.CSS_SELECTOR,
                "[role='dialog'] input[type='checkbox']",
            )
        )
    ).click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                (
                    "//*[@role='dialog']//button"
                    "[normalize-space()='Permanently remove Runtime']"
                ),
            )
        )
    ).click()

    _assert_visible_text(browser_driver, "Runtime removal is in progress")
    _assert_visible_text(
        browser_driver,
        (
            "Removal cannot be cancelled. Runtime-dependent access remains "
            "unavailable until it completes."
        ),
    )
    _assert_visible_text(browser_driver, "Active root sessions")
