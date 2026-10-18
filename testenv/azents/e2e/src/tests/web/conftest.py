"""Web-suite execution profile."""

import pytest
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session", autouse=True)
def web_suite_browser_start(selenium_container_start: object) -> None:
    """Start shared Chromium before other Web-suite session fixtures."""


@pytest.fixture(autouse=True)
def web_suite_substrate(
    azents_runtime_provider_docker_container: DockerContainer,
    e2e_images: dict[str, str],
) -> None:
    """Require ready backend substrate and every selected image before Web bodies."""
