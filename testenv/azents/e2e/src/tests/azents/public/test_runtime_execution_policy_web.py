"""Runtime Execution Policy Web Surface E2E test."""

# pyright: reportMissingTypeStubs=false
# pyright: reportUnknownArgumentType=false
# pyright: reportUnknownLambdaType=false
# pyright: reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false

from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.runtime_execution_policy import (
    create_runtime_execution_agent_context,
)

pytestmark = pytest.mark.web_surface

_SIGNUP_PASSWORD = "TestPass123!"
_STATUS_RESPONSE_OVERRIDE = r"""
(() => {
  const originalFetch = window.fetch.bind(window);
  const status = () => ({
    status: window.localStorage.getItem("e2e-runtime-policy-status") ?? "configured",
    configured: {
      profile_id: "standard",
      digest: "configured-digest-0123456789",
      capabilities: [
        { module_id: "container.image_build", version: 1, enabled: false },
        { module_id: "container.run", version: 1, enabled: true },
        { module_id: "container.compose", version: 1, enabled: false },
      ],
      storage_mode: "ephemeral",
      storage_capacity_bytes: 10737418240,
      network_mode: "restricted",
    },
    target: null,
    applied: null,
    desired_generation: 3,
    governing_layers: {},
    reason_codes: [],
    required_action: window.localStorage.getItem(
      "e2e-runtime-policy-required-action",
    ) ?? "apply",
  });
  const trpcResult = () => ({
    result: { data: { json: status() } },
  });
  window.fetch = async (...args) => {
    const requestUrl =
      typeof args[0] === "string" ? args[0] : args[0]?.url ?? "";
    if (requestUrl.includes("runtimeExecution.getAgentStatus")) {
      const body = requestUrl.includes("batch=1")
        ? [trpcResult()]
        : trpcResult();
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    return originalFetch(...args);
  };
})();
"""


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


def _set_status_projection(
    driver: WebDriver,
    *,
    status: str,
    required_action: str,
) -> None:
    """Select the server-shaped status projection returned at the browser boundary."""
    driver.execute_script(
        """
        window.localStorage.setItem("e2e-runtime-policy-status", arguments[0]);
        window.localStorage.setItem(
          "e2e-runtime-policy-required-action",
          arguments[1],
        );
        """,
        status,
        required_action,
    )


def _assert_status_projection(
    driver: WebDriver,
    *,
    status_label: str,
    action_label: str,
    apply_available: bool,
) -> None:
    """Assert exact server-provided status and required-action presentation."""
    _wait(driver).until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                f"//*[normalize-space()='{status_label}']",
            )
        )
    )
    _wait(driver).until(
        ec.visibility_of_element_located(
            (
                By.XPATH,
                f"//*[normalize-space()='{action_label}']",
            )
        )
    )
    apply_buttons = driver.find_elements(
        By.XPATH,
        "//button[normalize-space()='Apply to Runtime']",
    )
    assert bool(apply_buttons) is apply_available


def test_agent_runtime_execution_renders_server_status_and_required_action(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Render every bounded status/action pair without client-side inference."""
    context = create_runtime_execution_agent_context(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
    )
    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=context.email,
    )
    page_url = (
        f"{azents_main_web_url}/w/{context.workspace_handle}/agents/"
        f"{context.agent_id}/settings/execution"
    )
    cast(Any, browser_driver).execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": _STATUS_RESPONSE_OVERRIDE},
    )
    _set_status_projection(
        browser_driver,
        status="configured",
        required_action="apply",
    )
    browser_driver.get(page_url)
    _assert_status_projection(
        browser_driver,
        status_label="Configured",
        action_label="Apply configured policy",
        apply_available=True,
    )

    cases = (
        ("pending", "wait", "Pending", "Wait for Runtime", False),
        ("applied", "none", "Applied", "No action required", False),
        (
            "unavailable",
            "administrator_action",
            "Unavailable",
            "Administrator action required",
            False,
        ),
        (
            "divergent",
            "administrator_action",
            "Divergent",
            "Administrator action required",
            False,
        ),
    )
    for status, required_action, status_label, action_label, apply_available in cases:
        _set_status_projection(
            browser_driver,
            status=status,
            required_action=required_action,
        )
        browser_driver.get(page_url)
        _assert_status_projection(
            browser_driver,
            status_label=status_label,
            action_label=action_label,
            apply_available=apply_available,
        )
