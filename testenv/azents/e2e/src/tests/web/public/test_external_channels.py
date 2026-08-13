"""Web Surface coverage for External Channel management."""

import azentsadminclient
import azentspublicclient
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.public import test_external_channels as required_scenarios


def test_connection_management_web_surface_uses_redacted_operational_state(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    required_scenarios.run_connection_management_web_surface_uses_redacted_operational_state(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
        browser_driver,
        azents_main_web_url,
    )
