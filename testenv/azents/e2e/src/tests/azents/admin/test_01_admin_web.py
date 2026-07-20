"""Real-browser E2E coverage for Main Web and Admin Web auth boundaries."""

# pyright: reportMissingTypeArgument=false, reportUnknownLambdaType=false
# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false
# pyright: reportUnknownVariableType=false

import time
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import pytest
from azentsadminclient.api.system_v1_api import SystemV1Api
from azentsadminclient.api.user_v1_api import UserV1Api as AdminUserV1Api
from azentsadminclient.models.file_lifecycle_settings_update_request import (
    FileLifecycleSettingsUpdateRequest,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import authenticate_user, unique

_MAIN_COOKIE_NAMES = ("az-token", "az-refresh", "az-token-expires-at")
_ADMIN_COOKIE_NAMES = (
    "az-admin-token",
    "az-admin-refresh",
    "az-admin-token-expires-at",
)
_BOOTSTRAP_PASSWORD = "SystemAdmin123!"
_SIGNUP_PASSWORD = "TestPass123!"


def _wait(driver: WebDriver) -> WebDriverWait:
    return WebDriverWait(driver, 20)


def _login_main_web(
    driver: WebDriver,
    *,
    base_url: str,
    email: str,
    password: str,
) -> None:
    driver.delete_all_cookies()
    driver.get(f"{base_url}/login")
    email_input = _wait(driver).until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/login/password"))
    password_input = _wait(driver).until(
        ec.element_to_be_clickable((By.NAME, "password"))
    )
    password_input.send_keys(password, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))


def _login_admin_web(
    driver: WebDriver,
    *,
    base_url: str,
    email: str,
    password: str,
) -> None:
    driver.delete_all_cookies()
    driver.get(f"{base_url}/login")
    email_input = _wait(driver).until(
        ec.element_to_be_clickable((By.CSS_SELECTOR, "input[type='email']"))
    )
    password_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    email_input.send_keys(email)
    password_input.send_keys(password, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))
    _wait(driver).until(ec.visibility_of_element_located((By.LINK_TEXT, "Users")))


def _assert_auth_cookies(
    driver: WebDriver,
    *,
    names: tuple[str, ...],
    expected_path: str,
) -> None:
    cookies: dict[str, dict[str, Any]] = {
        cookie["name"]: cookie for cookie in driver.get_cookies()
    }
    for name in names:
        cookie = cookies.get(name)
        if cookie is None:
            raise AssertionError(f"authentication cookie {name} is missing")
        if cookie.get("httpOnly") is not True:
            raise AssertionError(f"authentication cookie {name} is not HttpOnly")
        if cookie.get("secure") is not True:
            raise AssertionError(f"authentication cookie {name} is not Secure")
        if cookie.get("sameSite") != "Lax":
            raise AssertionError(f"authentication cookie {name} is not SameSite=Lax")
        if cookie.get("path") != expected_path:
            raise AssertionError(f"authentication cookie {name} has an unexpected path")


def _wait_for_cookies_cleared(
    driver: WebDriver,
    *,
    names: tuple[str, ...],
) -> None:
    def cookies_absent(current_driver: WebDriver) -> bool:
        current_names = {cookie["name"] for cookie in current_driver.get_cookies()}
        return all(name not in current_names for name in names)

    _wait(driver).until(cookies_absent)


def _open_main_user_menu(driver: WebDriver) -> None:
    buttons = _wait(driver).until(
        lambda current_driver: current_driver.find_elements(
            By.CSS_SELECTOR, "header button"
        )
    )
    buttons[-1].click()
    _wait(driver).until(
        ec.visibility_of_element_located((By.XPATH, "//button[contains(., 'Log out')]"))
    )


def _logout_main_web(driver: WebDriver) -> None:
    driver.find_element(By.XPATH, "//button[contains(., 'Log out')]").click()
    _wait_for_cookies_cleared(driver, names=_MAIN_COOKIE_NAMES)


def _logout_admin_web(driver: WebDriver) -> None:
    driver.find_element(
        By.XPATH,
        "//*[self::button or self::a][contains(., 'Sign out')]",
    ).click()
    _wait(driver).until(ec.url_contains("/login"))
    _wait_for_cookies_cleared(driver, names=_ADMIN_COOKIE_NAMES)


def _user_id_by_email(
    admin_api_client: azentsadminclient.ApiClient,
    email: str,
) -> str:
    users = AdminUserV1Api(admin_api_client).user_v1_list_users(limit=1000)
    for user in users.items:
        if user.primary_email == email:
            return user.id
    raise AssertionError("created user was not returned by the Admin API")


def _set_retention(system_api: SystemV1Api, retention_days: int | None) -> None:
    """Apply a future-archive retention revision."""
    current = system_api.system_v1_get_file_lifecycle_settings()
    if current.archived_session_retention_days == retention_days:
        return
    system_api.system_v1_update_file_lifecycle_settings(
        FileLifecycleSettingsUpdateRequest(
            expected_revision=current.revision,
            archived_session_retention_days=retention_days,
            application_scope="new_archives_only",
        )
    )


@pytest.mark.web_surface
def test_dual_web_auth_link_logout_self_revoke_and_path_routing(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_admin_web_url: str,
    azents_admin_web_gateway_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_admin_server_url: str,
) -> None:
    """Exercise both web apps, independent cookies, and gateway path routing."""
    ordinary_token, _, ordinary_email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"browser-ordinary-{unique()}@example.com",
    )
    ordinary_user_id = _user_id_by_email(admin_api_client, ordinary_email)

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=system_bootstrap_evidence.email,
        password=_BOOTSTRAP_PASSWORD,
    )
    _assert_auth_cookies(
        browser_driver,
        names=_MAIN_COOKIE_NAMES,
        expected_path="/",
    )
    _open_main_user_menu(browser_driver)
    admin_link = _wait(browser_driver).until(
        ec.visibility_of_element_located((By.LINK_TEXT, "System Administration"))
    )
    if admin_link.get_attribute("href") != azents_admin_web_gateway_url:
        raise AssertionError("Main Web returned an unexpected Admin Web link")
    _logout_main_web(browser_driver)

    _login_main_web(
        browser_driver,
        base_url=azents_main_web_url,
        email=ordinary_email,
        password=_SIGNUP_PASSWORD,
    )
    _open_main_user_menu(browser_driver)
    time.sleep(1)
    if browser_driver.find_elements(By.LINK_TEXT, "System Administration"):
        raise AssertionError("ordinary user received the Admin Web link")
    _logout_main_web(browser_driver)

    _login_admin_web(
        browser_driver,
        base_url=azents_admin_web_url,
        email=system_bootstrap_evidence.email,
        password=_BOOTSTRAP_PASSWORD,
    )
    _assert_auth_cookies(
        browser_driver,
        names=_ADMIN_COOKIE_NAMES,
        expected_path="/",
    )
    _logout_admin_web(browser_driver)

    _login_admin_web(
        browser_driver,
        base_url=azents_admin_web_gateway_url,
        email=system_bootstrap_evidence.email,
        password=_BOOTSTRAP_PASSWORD,
    )
    if "/console/workspaces" not in browser_driver.current_url:
        raise AssertionError("Admin Web path-prefix routing was not preserved")
    _assert_auth_cookies(
        browser_driver,
        names=_ADMIN_COOKIE_NAMES,
        expected_path="/console",
    )
    _logout_admin_web(browser_driver)

    system_api = SystemV1Api(admin_api_client)
    system_api.system_v1_grant_system_admin(ordinary_user_id)
    _login_admin_web(
        browser_driver,
        base_url=azents_admin_web_url,
        email=ordinary_email,
        password=_SIGNUP_PASSWORD,
    )
    browser_driver.find_element(By.LINK_TEXT, "Users").click()
    user_row = _wait(browser_driver).until(
        ec.element_to_be_clickable((By.XPATH, f"//tr[contains(., '{ordinary_email}')]"))
    )
    user_row.click()
    revoke_button = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[contains(., 'Revoke system administrator')]")
        )
    )
    revoke_button.click()
    confirm_revoke_button = _wait(browser_driver).until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[normalize-space()='Revoke access']")
        )
    )
    confirm_revoke_button.click()
    _wait(browser_driver).until(ec.url_contains("/login"))
    _wait_for_cookies_cleared(browser_driver, names=_ADMIN_COOKIE_NAMES)

    ordinary_client = azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=ordinary_token,
        )
    )
    with ordinary_client:
        with pytest.raises(azentsadminclient.ApiException) as revoked:
            SystemV1Api(ordinary_client).system_v1_get_system_admin_me()
    if cast(Any, revoked.value).status != 403:
        raise AssertionError("self-revoked Admin session did not lose authorization")


@pytest.mark.web_surface
def test_admin_system_settings_page_renders_redacted_platform_fields(
    browser_driver: WebDriver,
    azents_admin_web_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> None:
    """Admin Web exposes System Settings without rendering secret plaintext."""
    _login_admin_web(
        browser_driver,
        base_url=azents_admin_web_url,
        email=system_bootstrap_evidence.email,
        password=_BOOTSTRAP_PASSWORD,
    )
    _wait(browser_driver).until(
        ec.element_to_be_clickable((By.LINK_TEXT, "System Settings"))
    ).click()
    _wait(browser_driver).until(ec.url_contains("/system-settings"))
    for text in (
        "System Settings",
        "Platform GitHub App",
        "App ID",
        "Client ID",
        "Private key replacement",
        "Client secret replacement",
        "Effective health",
        "Audit events",
    ):
        _wait(browser_driver).until(
            ec.visibility_of_element_located(
                (By.XPATH, f"//*[contains(normalize-space(), '{text}')]")
            )
        )

    private_key_input = browser_driver.find_element(
        By.XPATH,
        "//label[contains(normalize-space(), 'Private key replacement')]"
        "/following::input[1]",
    )
    client_secret_input = browser_driver.find_element(
        By.XPATH,
        "//label[contains(normalize-space(), 'Client secret replacement')]"
        "/following::input[1]",
    )
    assert private_key_input.get_attribute("value") == ""
    assert client_secret_input.get_attribute("value") == ""
    assert "effective_generation" not in browser_driver.page_source


@pytest.mark.web_surface
def test_admin_retention_page_updates_future_archive_policy(
    browser_driver: WebDriver,
    azents_admin_web_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    admin_api_client: azentsadminclient.ApiClient,
) -> None:
    """Admin Web exposes and persists the future-only retention workflow."""
    system_api = SystemV1Api(admin_api_client)
    _set_retention(system_api, 30)
    try:
        _login_admin_web(
            browser_driver,
            base_url=azents_admin_web_url,
            email=system_bootstrap_evidence.email,
            password=_BOOTSTRAP_PASSWORD,
        )
        _wait(browser_driver).until(
            ec.element_to_be_clickable((By.LINK_TEXT, "Retention"))
        ).click()
        _wait(browser_driver).until(ec.url_contains("/retention"))
        _wait(browser_driver).until(
            ec.visibility_of_element_located(
                (By.XPATH, "//*[contains(., 'Archived session retention')]")
            )
        )

        retention_input = _wait(browser_driver).until(
            ec.element_to_be_clickable(
                (
                    By.XPATH,
                    "//label[normalize-space()='Retention days']/following::input[1]",
                )
            )
        )
        retention_input.send_keys(Keys.CONTROL, "a")
        retention_input.send_keys("14")
        _wait(browser_driver).until(
            ec.element_to_be_clickable(
                (By.XPATH, "//button[normalize-space()='Save retention policy']")
            )
        ).click()
        _wait(browser_driver).until(
            ec.visibility_of_element_located(
                (By.XPATH, "//*[contains(., 'Archive retention settings updated.')]")
            )
        )
        assert (
            system_api.system_v1_get_file_lifecycle_settings().archived_session_retention_days
            == 14
        )
    finally:
        _set_retention(system_api, 30)
