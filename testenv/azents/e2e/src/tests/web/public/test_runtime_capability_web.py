"""Optional managed Runtime Web Surface E2E journey."""

import time
from dataclasses import dataclass

import azentsadminclient
import azentspublicclient
from azentspublicclient.api.agent_runtime_v1_api import AgentRuntimeV1Api
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
from azentspublicclient.models.runtime_provider_connection_state import (
    RuntimeProviderConnectionState,
)
from azentspublicclient.models.runtime_system_metrics_summary import (
    RuntimeSystemMetricsSummary,
)
from azentspublicclient.models.secrets import Secrets
from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
)
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
    single_candidate_model_options,
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
    return WebDriverWait(
        driver,
        20,
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    )


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
    email_input.send_keys(email)
    if not driver.find_elements(By.NAME, "password"):
        email_input.send_keys(Keys.ENTER)
        _wait(driver).until(ec.url_contains("/login/password"))
    password_input = _wait(driver).until(
        ec.element_to_be_clickable((By.NAME, "password"))
    )
    password_input.send_keys(_SIGNUP_PASSWORD, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))


def _assert_visible_text(
    driver: WebDriver,
    text: str,
    *,
    timeout_seconds: int = 20,
) -> None:
    """Wait for exact visible text."""
    WebDriverWait(driver, timeout_seconds, poll_frequency=0.1).until(
        ec.visibility_of_element_located((By.XPATH, f"//*[normalize-space()={text!r}]"))
    )


def _click_button(driver: WebDriver, text: str) -> None:
    """Click one visible button by exact text."""
    _wait(driver).until(
        ec.element_to_be_clickable((By.XPATH, f"//button[normalize-space()={text!r}]"))
    ).click()


def _open_metrics_tab(driver: WebDriver) -> None:
    """Open the Runtime system metrics tab."""
    _wait(driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='tab' and @aria-label='Metrics']")
        )
    ).click()


def _wait_for_runtime_metrics(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
    timeout_seconds: float,
) -> None:
    """Wait for the current Runner generation to publish usable metrics."""
    deadline = time.monotonic() + timeout_seconds
    assert driver.current_window_handle, "Runtime Web browser session is unavailable"
    admitted = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id, handle=handle, _headers=_headers(token)
    )
    assert admitted.lifecycle is not None
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Runtime metrics exhausted the original readiness budget"
    _wait_for_runtime_ready(
        driver,
        runtime_api=runtime_api,
        token=token,
        handle=handle,
        agent_id=agent_id,
        minimum_generation=admitted.lifecycle.desired_generation,
        timeout_seconds=remaining,
    )

    def metrics_are_ready(current: WebDriver) -> bool:
        # Keep browser ownership observable during API polling, not only at teardown.
        assert current.current_window_handle, (
            "Runtime Web browser session is unavailable"
        )
        metrics = runtime_api.agent_runtime_v1_get_agent_runtime_system_metrics(
            agent_id=agent_id,
            handle=handle,
            _headers=_headers(token),
        )
        return (
            metrics.summary
            in {
                RuntimeSystemMetricsSummary.FRESH,
                RuntimeSystemMetricsSummary.PARTIAL,
            }
            and metrics.scope is not None
            and bool(metrics.samples)
            and metrics.memory.used is not None
            and metrics.disk.used is not None
        )

    remaining = deadline - time.monotonic()
    assert remaining > 0, "Runtime metrics exhausted the original readiness budget"
    WebDriverWait(driver, remaining, poll_frequency=1).until(metrics_are_ready)


def _start_runtime(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
) -> float:
    """Admit one UI activation and return the remaining 120-second budget."""
    deadline = time.monotonic() + 120
    before = runtime_api.agent_runtime_v1_get_agent_runtime(
        agent_id=agent_id, handle=handle, _headers=_headers(token)
    )
    assert before.lifecycle is not None
    prior_generation = before.lifecycle.desired_generation
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Runtime Start exhausted the original readiness budget"
    WebDriverWait(
        driver,
        min(20, remaining),
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    ).until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Start']"))
    ).click()
    last_state = "unobserved"

    def admitted(current: WebDriver) -> bool:
        nonlocal last_state
        assert current.current_window_handle, (
            "Runtime Web browser session is unavailable"
        )
        observed = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id, handle=handle, _headers=_headers(token)
        )
        lifecycle = observed.lifecycle
        if lifecycle is None:
            last_state = "no lifecycle"
            return False
        last_state = (
            f"generation={lifecycle.desired_generation}, target={lifecycle.target}, "
            f"convergence={lifecycle.convergence}, "
            f"availability={lifecycle.availability}, "
            f"provider_resource={lifecycle.provider.resource}, "
            f"runner_state={lifecycle.runner.state}"
        )
        return (
            lifecycle.desired_generation > prior_generation
            and lifecycle.target == "running"
        )

    try:
        remaining = deadline - time.monotonic()
        assert remaining > 0, "Runtime Start exhausted the original readiness budget"
        WebDriverWait(driver, min(20, remaining), poll_frequency=0.1).until(admitted)
    except TimeoutException as error:
        raise AssertionError(
            "One Runtime Start click did not advance authoritative admission; "
            f"previous_generation={prior_generation}; {last_state}"
        ) from error
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Runtime Start exhausted the original readiness budget"
    return remaining


def _wait_for_settings_metrics_layout(driver: WebDriver, *, deadline: float) -> None:
    """Observe the real upper content before targeting lifecycle controls."""
    remaining = deadline - time.monotonic()
    assert remaining > 0, "Runtime Start exhausted the original readiness budget"

    def ready(current: WebDriver) -> bool:
        return bool(
            ec.visibility_of_element_located(
                (By.XPATH, "//*[normalize-space()='Scope: Container']")
            )(current)
            and ec.visibility_of_element_located(
                (
                    By.CSS_SELECTOR,
                    "[role='img'][aria-label='Recent one-hour usage trend']",
                )
            )(current)
        )

    WebDriverWait(
        driver,
        remaining,
        poll_frequency=0.1,
        ignored_exceptions=(StaleElementReferenceException,),
    ).until(ready)


def _start_runtime_and_wait_for_metrics(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
) -> None:
    """Observe one admission and metrics within the original combined budget."""
    remaining = _start_runtime(
        driver,
        runtime_api=runtime_api,
        token=token,
        handle=handle,
        agent_id=agent_id,
    )
    _wait_for_runtime_metrics(
        driver,
        runtime_api=runtime_api,
        token=token,
        handle=handle,
        agent_id=agent_id,
        timeout_seconds=remaining,
    )


def _wait_for_runtime_ready(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
    minimum_generation: int,
    timeout_seconds: float,
) -> None:
    """Wait for one newer Runtime generation to regain full availability."""
    last_state = "unobserved"

    def runtime_is_ready(current: WebDriver) -> bool:
        nonlocal last_state
        assert current.current_window_handle, (
            "Runtime Web browser session is unavailable"
        )
        runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=handle,
            _headers=_headers(token),
        )
        lifecycle = runtime.lifecycle
        if lifecycle is None:
            last_state = "no lifecycle"
            return False
        last_state = (
            f"generation={lifecycle.desired_generation}, target={lifecycle.target}, "
            f"convergence={lifecycle.convergence}, "
            f"availability={lifecycle.availability}, "
            f"provider_resource={lifecycle.provider.resource}, "
            f"runner_state={lifecycle.runner.state}"
        )
        return (
            lifecycle.desired_generation >= minimum_generation
            and lifecycle.target == "running"
            and lifecycle.convergence == "stable"
            and lifecycle.availability == "ready"
            and lifecycle.provider.resource == "running"
            and lifecycle.runner.state == "ready"
        )

    try:
        WebDriverWait(driver, timeout_seconds, poll_frequency=1).until(runtime_is_ready)
    except TimeoutException as error:
        raise AssertionError(
            "Runtime generation did not regain full readiness; "
            f"minimum_generation={minimum_generation}; {last_state}"
        ) from error


def _wait_for_runtime_stopped(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
) -> None:
    """Keep the Session panel's actual Stop mutation and settled backend outcome."""

    def stopped(_: WebDriver) -> bool:
        runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id, handle=handle, _headers=_headers(token)
        )
        lifecycle = runtime.lifecycle
        return (
            lifecycle is not None
            and lifecycle.target == "stopped"
            and lifecycle.convergence == "stable"
            and lifecycle.availability == "stopped"
        )

    WebDriverWait(driver, 120, poll_frequency=1).until(stopped)


def _wait_for_runtime_start_authorized(
    driver: WebDriver,
    *,
    runtime_api: AgentRuntimeV1Api,
    token: str,
    handle: str,
    agent_id: str,
) -> None:
    """Wait for Provider observation to authorize managed host creation."""

    def runtime_start_is_authorized(_: WebDriver) -> bool:
        runtime = runtime_api.agent_runtime_v1_get_agent_runtime(
            agent_id=agent_id,
            handle=handle,
            _headers=_headers(token),
        )
        lifecycle = runtime.lifecycle
        return (
            lifecycle is not None
            and lifecycle.provider.connection
            is RuntimeProviderConnectionState.CONNECTED
            and runtime.actions.start
        )

    WebDriverWait(driver, 120, poll_frequency=1).until(runtime_start_is_authorized)


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
    """Retain one assembled add/start/metrics/remove journey."""
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
            selectable_model_options=single_candidate_model_options(
                workspace.model_selection
            ),
            main_model_label="default",
            lightweight_model_label="default",
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

    runtime_api = AgentRuntimeV1Api(public_api_client)
    _wait_for_runtime_start_authorized(
        browser_driver,
        runtime_api=runtime_api,
        token=workspace.token,
        handle=workspace.handle,
        agent_id=agent.id,
    )
    browser_driver.refresh()
    _start_runtime_and_wait_for_metrics(
        browser_driver,
        runtime_api=runtime_api,
        token=workspace.token,
        handle=workspace.handle,
        agent_id=agent.id,
    )
    browser_driver.refresh()
    _assert_visible_text(browser_driver, "System metrics")
    _assert_visible_text(browser_driver, "CPU")
    _assert_visible_text(browser_driver, "Memory")
    _assert_visible_text(browser_driver, "Disk")
    _assert_visible_text(browser_driver, "Scope: Container", timeout_seconds=120)
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                "[role='img'][aria-label='Recent one-hour usage trend']",
            )
        )
    )

    browser_driver.set_window_size(1440, 1000)
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/agents/{agent.id}/sessions/new"
    )
    message_input = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.NAME, "chat-message"))
    )
    message_input.send_keys("Verify Runtime metrics", Keys.ENTER)
    _wait(browser_driver).until(
        lambda driver: (
            "/sessions/" in driver.current_url
            and not driver.current_url.endswith("/sessions/new")
        )
    )
    _open_metrics_tab(browser_driver)
    _assert_visible_text(browser_driver, "System metrics", timeout_seconds=120)
    _assert_visible_text(browser_driver, "Scope: Container")
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (
                By.CSS_SELECTOR,
                "[role='img'][aria-label='Recent one-hour usage trend']",
            )
        )
    )

    _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//*[@role='tab' and normalize-space()='Runtime']")
        )
    ).click()
    _click_button(browser_driver, "Stop runtime")
    _wait_for_runtime_stopped(
        browser_driver,
        runtime_api=runtime_api,
        token=workspace.token,
        handle=workspace.handle,
        agent_id=agent.id,
    )
    browser_driver.get(
        f"{azents_main_web_url}/w/{workspace.handle}/agents/{agent.id}/settings/runtime"
    )
    _wait_for_settings_metrics_layout(browser_driver, deadline=time.monotonic() + 120)

    _assert_visible_text(browser_driver, "Permanently remove managed Runtime")
    _click_button(browser_driver, "Remove Runtime")
    _assert_visible_text(browser_driver, "Permanently remove Runtime?")
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
