"""Web Surface coverage for model stream watchdog recovery."""

import azentsadminclient
import azentspublicclient
from selenium.webdriver.remote.webdriver import WebDriver

from tests.required.public.test_model_stream_watchdog import (
    TestModelStreamWatchdog as _TestModelStreamWatchdog,
)


def test_absolute_cap_discards_failed_prefix_before_retry_and_browser_reload(
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_engine_worker_container: object,
    browser_driver: WebDriver,
    azents_main_web_url: str,
) -> None:
    _TestModelStreamWatchdog().run_absolute_cap_discards_failed_prefix_before_retry_and_browser_reload(
        public_api_client,
        admin_api_client,
        azents_public_server_url,
        azents_engine_worker_container,
        browser_driver,
        azents_main_web_url,
    )
