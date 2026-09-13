"""Agent-owned Toolkit management Web Surface E2E journey."""

from dataclasses import dataclass
from typing import Any, cast

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.invitation_v1_api import InvitationV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.toolkit_v1_api import ToolkitV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_type import AgentType
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
from azentspublicclient.models.toolkit_config_create_request import (
    ToolkitConfigCreateRequest,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)

_SIGNUP_PASSWORD = "TestPass123!"


@dataclass(frozen=True)
class _AgentToolkitWebContext:
    """Product-created state for the browser Toolkit management journey."""

    owner_token: str
    owner_email: str
    member_email: str
    handle: str
    model_selection: AgentModelSelectionInput


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
        lambda current_driver: any(
            element.is_displayed()
            for element in current_driver.find_elements(
                By.XPATH,
                f"//*[normalize-space()={text!r}]",
            )
        )
    )


def _click_button(driver: WebDriver, text: str) -> None:
    """Click one visible button by exact text."""
    _wait(driver).until(
        ec.element_to_be_clickable((By.XPATH, f"//button[normalize-space()={text!r}]"))
    ).click()


def _fill_text_input(driver: WebDriver, label: str, value: str) -> None:
    """Replace the value of a Mantine text input by its visible label."""
    field = _wait(driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//label[normalize-space(text())={label!r}]/following::input[1]",
            )
        )
    )
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(value)


def _create_workspace_context(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _AgentToolkitWebContext:
    """Create an owner, member, Workspace, and deterministic model selection."""
    suffix = unique()
    owner_token, _, owner_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"agent-toolkits-owner-{suffix}@example.com",
    )
    member_token, _, member_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"agent-toolkits-member-{suffix}@example.com",
    )
    handle = f"agent-toolkits-{suffix}"
    headers = _headers(owner_token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Agent Toolkits {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    invitation = InvitationV1Api(public_api_client).invitation_v1_create_invitation(
        handle,
        CreateInvitationRequest(email=member_email),
        _headers=headers,
    )
    InvitationV1Api(public_api_client).invitation_v1_accept_invitation(
        invitation.id,
        _headers=_headers(member_token),
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-agent-toolkit-web")),
        ),
        _headers=headers,
    )
    return _AgentToolkitWebContext(
        owner_token=owner_token,
        owner_email=owner_email,
        member_email=member_email,
        handle=handle,
        model_selection=model_selection_from_first_candidate(
            server_url,
            owner_token,
            handle,
            integration.id,
        ),
    )


def test_agent_owned_toolkit_owner_management_and_member_legacy_view(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Manage an Agent-only MCP Toolkit and retain the member legacy boundary."""
    context = _create_workspace_context(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=context.handle,
        agent_create_request=AgentCreateRequest(
            name=f"Agent Toolkit Web {unique()}",
            selectable_model_options=single_candidate_model_options(
                context.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
        ),
        _headers=_headers(context.owner_token),
    )
    assert agent.toolkit_management_available is True
    shared_name = f"Workspace MCP {unique()}"
    ToolkitV1Api(public_api_client).toolkit_v1_create_toolkit_config(
        handle=context.handle,
        toolkit_config_create_request=ToolkitConfigCreateRequest(
            toolkit_type="mcp",
            slug=f"workspace_mcp_{unique()}",
            name=shared_name,
            config={
                "server_url": "https://example.com/mcp",
                "auth_type": "none",
                "timeout": 30.0,
            },
            enabled=True,
        ),
        _headers=_headers(context.owner_token),
    )

    settings_url = (
        f"{azents_main_web_url}/w/{context.handle}/agents/{agent.id}"
        "/settings/capabilities"
    )
    toolkit_name = f"Agent-only MCP {unique()}"
    toolkit_slug = f"agent_mcp_{unique()}"

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=context.owner_email,
    )
    browser_driver.get(settings_url)
    _assert_visible_text(browser_driver, "Toolkits")
    _assert_visible_text(
        browser_driver,
        "Attach a workspace-shared toolkit or configure one only for this agent.",
    )
    add_button = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Add Toolkit']")
        )
    )
    add_button.send_keys(Keys.ENTER)
    _assert_visible_text(browser_driver, "Add Toolkit")
    tool_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//label[normalize-space(text())='Tool']/following::input[1]",
            )
        )
    )
    tool_input.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='option' and normalize-space()='MCP']")
        )
    ).click()
    _assert_visible_text(browser_driver, "Workspace shared")
    _assert_visible_text(browser_driver, "This agent only")
    shared_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//input[@aria-label='Select a toolkit to attach']",
            )
        )
    )
    shared_input.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                f"//*[@role='option' and normalize-space()='{shared_name} (mcp)']",
            )
        )
    ).click()
    attach_button = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Attach']"))
    )
    attach_button.send_keys(Keys.ENTER)
    _assert_visible_text(browser_driver, shared_name)
    _assert_visible_text(
        browser_driver,
        "Edit, authorization, and deletion remain in Workspace Toolkit management.",
    )
    detach_button = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Detach']"))
    )
    detach_button.send_keys(Keys.ENTER)
    _wait(browser_driver).until(
        ec.invisibility_of_element_located(
            (By.XPATH, f"//*[normalize-space()={shared_name!r}]")
        )
    )

    _click_button(browser_driver, "Add Toolkit")
    tool_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//label[normalize-space(text())='Tool']/following::input[1]",
            )
        )
    )
    tool_input.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='option' and normalize-space()='MCP']")
        )
    ).click()
    configure_button = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Configure for this agent']")
        )
    )
    configure_button.send_keys(Keys.ENTER)
    unsaved_name = f"Unsaved MCP {unique()}"
    _fill_text_input(browser_driver, "Name", unsaved_name)
    _click_button(browser_driver, "Cancel")
    assert not browser_driver.find_elements(
        By.XPATH,
        f"//*[normalize-space()={unsaved_name!r}]",
    )

    _click_button(browser_driver, "Add Toolkit")
    tool_input = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (
                By.XPATH,
                "//label[normalize-space(text())='Tool']/following::input[1]",
            )
        )
    )
    tool_input.click()
    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='option' and normalize-space()='MCP']")
        )
    ).click()
    _click_button(browser_driver, "Configure for this agent")

    _fill_text_input(browser_driver, "Slug", toolkit_slug)
    _fill_text_input(browser_driver, "Name", toolkit_name)
    _fill_text_input(browser_driver, "Server URL", "https://example.com/mcp")
    _assert_visible_text(browser_driver, "Authentication")
    _wait(browser_driver).until(
        lambda current_driver: (
            current_driver.find_element(
                By.XPATH,
                "//label[normalize-space(text())='Authentication']/following::input[1]",
            ).get_attribute("value")
            == "None"
        )
    )
    _click_button(browser_driver, "Add")

    _assert_visible_text(browser_driver, toolkit_name)
    _assert_visible_text(browser_driver, "This agent only")
    _assert_visible_text(browser_driver, "Ready")

    browser_driver.set_window_size(390, 844)
    toolkit_name_element = browser_driver.find_element(
        By.XPATH,
        f"//*[normalize-space()={toolkit_name!r}]",
    )
    ownership_element = browser_driver.find_element(
        By.XPATH,
        "//*[normalize-space()='This agent only']",
    )
    readiness_element = browser_driver.find_element(
        By.XPATH,
        "//*[normalize-space()='Ready']",
    )
    primary_action_element = browser_driver.find_element(
        By.XPATH,
        "//button[normalize-space()='Disable']",
    )
    layout = cast(
        dict[str, float | bool],
        cast(Any, browser_driver).execute_script(
            "return {"
            "overflow: document.documentElement.scrollWidth > "
            "document.documentElement.clientWidth,"
            "toolkitTop: arguments[0].getBoundingClientRect().top,"
            "ownershipTop: arguments[1].getBoundingClientRect().top,"
            "readinessTop: arguments[2].getBoundingClientRect().top,"
            "actionTop: arguments[3].getBoundingClientRect().top"
            "};",
            toolkit_name_element,
            ownership_element,
            readiness_element,
            primary_action_element,
        ),
    )
    assert layout["overflow"] is False
    assert layout["toolkitTop"] <= layout["ownershipTop"]
    assert layout["ownershipTop"] <= layout["readinessTop"]
    assert layout["readinessTop"] <= layout["actionTop"]
    browser_driver.set_window_size(1280, 844)

    disable_button = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Disable']"))
    )
    disable_button.send_keys(Keys.ENTER)
    _assert_visible_text(browser_driver, "Disabled")
    _click_button(browser_driver, "Enable")
    _assert_visible_text(browser_driver, "Ready")

    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, "//button[@aria-label='Delete']"))
    ).click()
    _assert_visible_text(browser_driver, "Delete agent-only toolkit")
    _assert_visible_text(
        browser_driver,
        (
            f"Delete {toolkit_name} from this agent and permanently remove its "
            "stored credentials?"
        ),
    )
    _click_button(browser_driver, "Delete toolkit")
    _wait(browser_driver).until(
        ec.invisibility_of_element_located(
            (By.XPATH, f"//*[normalize-space()={toolkit_name!r}]")
        )
    )
    _assert_visible_text(browser_driver, "No toolkits attached")

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=context.member_email,
    )
    browser_driver.get(settings_url)
    _assert_visible_text(browser_driver, "Toolkits")
    _assert_visible_text(browser_driver, "No toolkits attached")
    assert not browser_driver.find_elements(
        By.XPATH,
        "//button[normalize-space()='Add Toolkit']",
    )
    assert not browser_driver.find_elements(
        By.XPATH,
        "//*[normalize-space()='Attach workspace toolkit']",
    )
