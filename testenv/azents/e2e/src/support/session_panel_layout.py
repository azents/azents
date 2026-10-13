"""Synchronize browser journeys with the session panel's responsive state."""

from typing import Literal
from urllib.parse import parse_qs, urlsplit

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait

TOGGLE = (By.CSS_SELECTOR, "button[aria-label='Toggle session panel']")
CLOSE = (By.CSS_SELECTOR, "button[aria-label='Close session panel']")
COMPOSER = (By.CSS_SELECTOR, "textarea")


def prepare_mobile_session_composer(driver: WebDriver) -> WebElement:
    """Settle explicit panel navigation before waiting for the mobile composer."""
    wait = WebDriverWait(driver, 20)
    # Explicit pages keep the panel open on mobile. Close while desktop is stable,
    # then let a page-free responsive transition close the implicit desktop panel.
    if "page" in parse_qs(urlsplit(driver.current_url).query):
        wait.until(ec.element_to_be_clickable(CLOSE)).click()
        wait.until(
            lambda current: "page" not in parse_qs(urlsplit(current.current_url).query)
        )
    driver.set_window_size(390, 844)

    def mobile_composer(current: WebDriver) -> WebElement | Literal[False]:
        if not any(item.is_displayed() for item in current.find_elements(*TOGGLE)):
            return False
        if any(item.is_displayed() for item in current.find_elements(*CLOSE)):
            return False
        return ec.element_to_be_clickable(COMPOSER)(current)

    return wait.until(mobile_composer)
