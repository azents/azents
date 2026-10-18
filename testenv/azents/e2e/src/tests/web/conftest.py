"""Web-suite execution profile."""

from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from functools import partial

import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer

from support.background_fixture import BackgroundFixture, background_fixture
from tests.web.public.test_runtime_web_gateway import (
    _prepare_runtime_web_stack_factory,
    _RuntimeWebStackFactory,
)


@pytest.fixture(scope="session", autouse=True)
def web_suite_browser_start(selenium_container_start: object) -> None:
    """Start shared Chromium before other Web-suite session fixtures."""


@pytest.fixture(scope="session")
def runtime_web_surface_preparation(
    container_network: Network,
    postgres_container: PostgresContainer,
    azents_server_image: str,
    azents_web_image: str,
    azents_runtime_runner_image: str,
    azents_runtime_control_container: DockerContainer,
    selenium_container: DockerContainer,
    runtime_web_capacity_backend: str,
    credential_encryption_key: str,
    auth_jwt_secret_key: str,
    system_bootstrap_setup_token: str,
    s3_bucket_name: str,
    rustfs_access_key: str,
    rustfs_secret_key: str,
) -> Callable[[], AbstractContextManager[_RuntimeWebStackFactory]]:
    """Declare dependencies only when the gateway suite actually needs them."""
    return partial(
        _prepare_runtime_web_stack_factory,
        container_network=container_network,
        postgres_container=postgres_container,
        azents_server_image=azents_server_image,
        azents_web_image=azents_web_image,
        azents_runtime_runner_image=azents_runtime_runner_image,
        azents_runtime_control_container=azents_runtime_control_container,
        selenium_container=selenium_container,
        runtime_web_capacity_backend=runtime_web_capacity_backend,
        credential_encryption_key=credential_encryption_key,
        auth_jwt_secret_key=auth_jwt_secret_key,
        system_bootstrap_setup_token=system_bootstrap_setup_token,
        s3_bucket_name=s3_bucket_name,
        rustfs_access_key=rustfs_access_key,
        rustfs_secret_key=rustfs_secret_key,
    )


@pytest.fixture(scope="session", autouse=True)
def runtime_web_surfaces_start(
    request: pytest.FixtureRequest,
    web_suite_browser_start: None,
) -> Generator[BackgroundFixture[_RuntimeWebStackFactory] | None, None, None]:
    """Overlap the same isolated auth surfaces with independent earlier Web tests."""
    if not any(
        "test_runtime_web_gateway.py" in item.nodeid for item in request.session.items
    ):
        yield None
        return
    prepare: Callable[[], AbstractContextManager[_RuntimeWebStackFactory]] = (
        request.getfixturevalue("runtime_web_surface_preparation")
    )
    with background_fixture(
        prepare, fixture="runtime_web_auth_surface_background"
    ) as future:
        yield future


@pytest.fixture(autouse=True)
def web_suite_substrate(
    azents_runtime_provider_docker_container: DockerContainer,
    e2e_images: dict[str, str],
) -> None:
    """Require ready backend substrate and every selected image before Web bodies."""
