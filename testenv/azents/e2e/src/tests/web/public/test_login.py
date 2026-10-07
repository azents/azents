"""Login entrypoint browser regressions."""

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait


def test_login_renders_with_invalid_refresh_cookie(
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Expired authentication must not block anonymous login capability reads."""
    browser_driver.get(f"{azents_main_web_url}/login")
    browser_driver.delete_all_cookies()
    browser_driver.add_cookie(
        {
            "name": "az-refresh",
            "value": "invalid-refresh-token-for-login-regression",
            "path": "/",
            "secure": True,
            "httpOnly": True,
        }
    )

    try:
        browser_driver.get(f"{azents_main_web_url}/login")
        email_input = WebDriverWait(browser_driver, 20, poll_frequency=0.1).until(
            ec.element_to_be_clickable((By.NAME, "email"))
        )
        assert email_input.is_displayed()
        assert "/login" in browser_driver.current_url
    finally:
        browser_driver.delete_all_cookies()
