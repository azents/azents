"""Real-browser subscription usage card isolation coverage."""

# pyright: reportMissingTypeArgument=false, reportUnknownLambdaType=false
# pyright: reportUnknownMemberType=false, reportUnknownParameterType=false

import azentsadminclient
import azentspublicclient
import pytest
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

from tests.azents.public.test_subscription_usage import (
    clear_subscription_usage_journal,
    create_chatgpt_subscription_integration,
    create_xai_subscription_integration,
    setup_subscription_workspace,
    subscription_usage_journal,
)

_PASSWORD = "TestPass123!"


def _wait(driver: WebDriver) -> WebDriverWait:
    """Return the standard browser wait."""
    return WebDriverWait(driver, 30)


def _login(
    driver: WebDriver,
    *,
    base_url: str,
    email: str,
) -> None:
    """Authenticate through the normal Main Web login flow."""
    driver.delete_all_cookies()
    driver.get(f"{base_url}/login")
    email_input = _wait(driver).until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/login/password"))
    password_input = _wait(driver).until(
        ec.element_to_be_clickable((By.NAME, "password"))
    )
    password_input.send_keys(_PASSWORD, Keys.ENTER)
    _wait(driver).until(ec.url_contains("/workspaces"))


def _card(driver: WebDriver, *, name: str) -> WebElement:
    """Return the integration card owning one management control."""
    edit = _wait(driver).until(
        ec.presence_of_element_located((By.CSS_SELECTOR, f'[aria-label="Edit {name}"]'))
    )
    return edit.find_element(
        By.XPATH,
        "./ancestor::div[contains(@class, 'mantine-Card-root')][1]",
    )


def _visible_text(card: WebElement, text: str) -> bool:
    """Return whether one exact text node is visible within a card."""
    elements = card.find_elements(By.XPATH, f".//*[normalize-space()='{text}']")
    return any(element.is_displayed() for element in elements)


@pytest.mark.web_surface
def test_subscription_usage_cards_are_live_local_safe_and_responsive(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    openai_proxy_url: str,
) -> None:
    """Exercise owner cards, stale refresh, redirects, disabled state, and width."""
    workspace = setup_subscription_workspace(public_api_client, admin_api_client)
    api = LLMProviderIntegrationV1Api(public_api_client)
    stale_name = "ChatGPT test-chatgpt-stale"
    broken_name = "ChatGPT test-chatgpt-malformed"
    disabled_name = "ChatGPT test-chatgpt-normal"
    healthy_name = "xAI test-xai-normal"
    external_name = "xAI test-xai-external"
    invalid_redirect_name = "xAI test-xai-invalid-redirect"
    create_chatgpt_subscription_integration(
        api, workspace, scenario="test-chatgpt-stale"
    )
    create_chatgpt_subscription_integration(
        api, workspace, scenario="test-chatgpt-malformed"
    )
    create_chatgpt_subscription_integration(
        api,
        workspace,
        scenario="test-chatgpt-normal",
        enabled=False,
    )
    create_xai_subscription_integration(api, workspace, scenario="test-xai-normal")
    create_xai_subscription_integration(api, workspace, scenario="test-xai-external")
    create_xai_subscription_integration(
        api, workspace, scenario="test-xai-invalid-redirect"
    )
    clear_subscription_usage_journal(openai_proxy_url)

    _login(
        browser_driver,
        base_url=azents_main_web_url,
        email=workspace.owner_email,
    )
    browser_driver.get(f"{azents_main_web_url}/w/{workspace.handle}/settings")
    _wait(browser_driver).until(
        ec.visibility_of_element_located(
            (By.XPATH, "//h3[normalize-space()='LLM Integrations']")
        )
    )

    stale_card = _card(browser_driver, name=stale_name)
    broken_card = _card(browser_driver, name=broken_name)
    disabled_card = _card(browser_driver, name=disabled_name)
    healthy_card = _card(browser_driver, name=healthy_name)
    external_card = _card(browser_driver, name=external_name)
    invalid_redirect_card = _card(browser_driver, name=invalid_redirect_name)

    _wait(browser_driver).until(lambda _driver: "58%" in stale_card.text)
    _wait(browser_driver).until(
        lambda _driver: "Subscription usage unavailable" in broken_card.text
    )
    _wait(browser_driver).until(lambda _driver: "Weekly limit" in healthy_card.text)
    _wait(browser_driver).until(
        lambda _driver: "Enable this integration" in disabled_card.text
    )

    for name, card in (
        (stale_name, stale_card),
        (broken_name, broken_card),
        (healthy_name, healthy_card),
    ):
        assert card.find_element(
            By.CSS_SELECTOR,
            f'[aria-label="Toggle {name}"]',
        ).is_enabled()
        assert card.find_element(
            By.CSS_SELECTOR,
            f'[aria-label="Edit {name}"]',
        ).is_displayed()
        assert card.find_element(
            By.CSS_SELECTOR,
            f'[aria-label="Delete {name}"]',
        ).is_displayed()

    financial = healthy_card.find_element(
        By.XPATH,
        ".//button[normalize-space()='Financial details']",
    )
    assert financial.get_attribute("aria-expanded") == "false"
    assert not _visible_text(healthy_card, "Prepaid balance")
    financial.click()
    _wait(browser_driver).until(
        lambda _driver: _visible_text(healthy_card, "Prepaid balance")
    )
    assert "$25.40" in healthy_card.text

    external_link = _wait(browser_driver).until(
        lambda _driver: external_card.find_element(
            By.LINK_TEXT,
            "View usage on xAI",
        )
    )
    assert external_link.get_attribute("href") == "https://grok.com/usage"
    assert external_link.get_attribute("target") == "_blank"
    assert set((external_link.get_attribute("rel") or "").split()) == {
        "noopener",
        "noreferrer",
    }
    assert not invalid_redirect_card.find_elements(
        By.LINK_TEXT,
        "View usage on xAI",
    )

    stale_card.find_element(
        By.CSS_SELECTOR,
        '[aria-label="Refresh subscription usage"]',
    ).click()
    _wait(browser_driver).until(lambda _driver: "Update failed" in stale_card.text)
    assert "58%" in stale_card.text
    assert "Showing the last successful" in stale_card.text
    assert "Weekly limit" in healthy_card.text

    journal = subscription_usage_journal(openai_proxy_url)
    assert all(entry["scenario"] != "chatgpt_normal" for entry in journal)
    stale_entries = [entry for entry in journal if entry["scenario"] == "chatgpt_stale"]
    assert [entry["status"] for entry in stale_entries] == [200, 503]

    browser_driver.set_window_size(390, 844)
    _wait(browser_driver).until(
        lambda driver: driver.execute_script(
            "return document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth"
        )
    )
    assert browser_driver.execute_script(
        "return arguments[0].scrollWidth <= arguments[0].clientWidth",
        healthy_card,
    )
    assert healthy_card.find_element(
        By.CSS_SELECTOR,
        '[aria-label="Refresh subscription usage"]',
    ).is_displayed()
    assert healthy_card.find_element(
        By.CSS_SELECTOR,
        f'[aria-label="Edit {healthy_name}"]',
    ).is_displayed()
