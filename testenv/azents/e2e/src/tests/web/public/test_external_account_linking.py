"""Web E2E coverage for global External Account OAuth management."""

import azentsadminclient
import azentspublicclient
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.public.external_account_linking_scenarios import (
    run_web_external_account_oauth_management,
)


def test_external_account_web_oauth_mobile_list_and_unlink(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Authorize, list, and disconnect one global identity without overflow."""
    run_web_external_account_oauth_management(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_admin_server_url,
        slack_provider_fake_url,
        browser_driver,
        azents_main_web_url,
    )
