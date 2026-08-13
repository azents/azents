"""Required-suite execution profile."""

import pytest
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session", autouse=True)
def required_suite_runtime_provider(
    azents_runtime_provider_docker_container: DockerContainer,
) -> None:
    """Use one Docker Runtime Provider substrate for every required-suite lane."""
