"""Web-suite execution profile."""

import pytest
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session", autouse=True)
def web_suite_browser_start(selenium_container_start: object) -> None:
    """Start shared Chromium before other Web-suite session fixtures."""


@pytest.fixture(autouse=True)
def web_suite_substrate(
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Require the backend; actual Web image consumers join the full image gate.

    Browser API-only journeys may run while unused Web images prepare. The shared
    preparation owner still drains every selected image and propagates failures.
    """
