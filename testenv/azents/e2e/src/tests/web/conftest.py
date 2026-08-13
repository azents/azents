"""Web-suite execution profile."""

import pytest
from selenium.webdriver.remote.webdriver import WebDriver
from testcontainers.core.container import DockerContainer


@pytest.fixture(autouse=True)
def web_suite_substrate(
    browser_driver: WebDriver,
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Use one browser and Docker Runtime Provider substrate for every web test."""
