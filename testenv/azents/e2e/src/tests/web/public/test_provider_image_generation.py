"""Web Surface coverage for promoted image rendering."""

import azentsadminclient
import azentspublicclient
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.public.test_provider_image_generation import (
    TestProviderImageGeneration as _TestProviderImageGeneration,
)


def test_renders_promoted_attachment_without_activity_across_refresh(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: object,
    openai_proxy_url: str,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    _TestProviderImageGeneration().run_renders_promoted_attachment_without_activity_across_refresh(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_engine_worker_container,
        openai_proxy_url,
        browser_driver,
        azents_main_web_url,
    )
