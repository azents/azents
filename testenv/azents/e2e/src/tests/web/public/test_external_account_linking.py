"""Web E2E coverage for External Account linking management."""

import azentsadminclient
import azentspublicclient
import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.public.external_account_linking_scenarios import (
    run_web_external_account_link_management,
)


def test_external_account_owner_list_elevation_and_mobile_unlink(
    request: pytest.FixtureRequest,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    slack_provider_fake_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    """Render and disconnect one own link without mobile overflow."""
    run_web_external_account_link_management(
        request,
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        slack_provider_fake_url,
        browser_driver,
        azents_main_web_url,
    )
