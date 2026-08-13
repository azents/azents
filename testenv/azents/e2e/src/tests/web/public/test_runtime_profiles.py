"""Web Surface coverage for Runtime Profile removal."""

import azentsadminclient
import azentspublicclient
from selenium.webdriver.remote.webdriver import WebDriver
from testcontainers.core.container import DockerContainer

from tests.required.public import test_runtime_profiles as required_scenarios


def test_owner_deletes_runtime_profile_in_web_and_running_runtime_is_retained(
    browser_driver: WebDriver,
    azents_main_web_url: str,
    azents_public_server_url: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_engine_worker_container: DockerContainer,
) -> None:
    required_scenarios.run_owner_deletes_runtime_profile_in_web_and_running_runtime_is_retained(
        browser_driver,
        azents_main_web_url,
        azents_public_server_url,
        public_api_client,
        admin_api_client,
        azents_runtime_provider_docker_container,
        azents_engine_worker_container,
    )
