"""Login entrypoint browser regressions."""

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support.ui import WebDriverWait


def _login_email_ready(driver: WebDriver) -> bool:
    """Inspect current-document visibility and enabled state in one command."""
    return (
        driver.execute_script(
            """
        const email = document.querySelector('input[name="email"]');
        return email !== null
          && email.checkVisibility({
            visibilityProperty: true,
            opacityProperty: true,
          })
          && !email.matches(':disabled');
        """
        )
        is True
    )


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
        WebDriverWait(
            browser_driver,
            20,
            poll_frequency=0.1,
        ).until(_login_email_ready)
        assert "/login" in browser_driver.current_url
    finally:
        browser_driver.delete_all_cookies()
