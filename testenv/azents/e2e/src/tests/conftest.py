"""E2E test fixtures."""

import base64
import dataclasses
import datetime
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import boto3
import docker as docker_py
import pytest
import requests
from docker.errors import APIError, DockerException, NotFound
from docker.models.containers import Container
from pydantic import TypeAdapter
from python_on_whales import docker as pow_docker
from selenium import webdriver
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.remote.webdriver import WebDriver
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer
from types_boto3_s3.client import S3Client

from support.consts import REPOSITORY_ROOT
from support.container_logs import (
    ContainerLogs,
    emit_container_logs,
    read_container_logs,
)
from support.runtime_provider_auth import (
    RuntimeProviderAuthenticationError,
    issue_runtime_provider_credential,
)
from support.runtime_provider_mode import docker_infrastructure_profile_spec
from support.server_readiness import wait_for_server_ready
from support.strict_network_control_plane import (
    StrictNetworkControlPlaneFixture,
    load_control_plane_evidence,
)
from support.system_bootstrap import SystemBootstrapEvidence
from support.timing_observability import (
    TimingObservabilityPlugin,
    timing_path,
)

_AIMOCK_FIXTURE_DIR = REPOSITORY_ROOT / "testenv/azents/e2e/src/support/aimock_fixtures"
_IMAGE_GENERATION_PROXY = (
    REPOSITORY_ROOT / "testenv/azents/e2e/src/support/image_generation_openai_proxy.py"
)
_IMAGE_GENERATION_FIXTURE_DIR = (
    REPOSITORY_ROOT / "testenv/azents/e2e/src/support/fixtures"
)
_GITHUB_VALIDATION_PROXY = (
    REPOSITORY_ROOT / "testenv/azents/e2e/src/support/github_validation_proxy.py"
)
_GITHUB_VALIDATION_INTERNAL_URL = "http://github-validation-proxy:8082"
_SLACK_PROVIDER_FAKE = (
    REPOSITORY_ROOT / "testenv/azents/e2e/src/support/slack_provider_fake.py"
)
_SLACK_PROVIDER_INTERNAL_API_URL = "http://slack-fake:8083/api"
_DISCORD_PROVIDER_FAKE = (
    REPOSITORY_ROOT / "testenv/azents/e2e/src/support/discord_provider_fake.py"
)
_DISCORD_PROVIDER_INTERNAL_API_URL = "http://discord-fake:8085/api/v10"
_DOCKER_CLIENT_TIMEOUT_SECONDS = 300
_RUNTIME_PROVIDER_DATA_CLEANUP_TIMEOUT_SECONDS = 120
_RUNTIME_PROVIDER_ID = "system-docker"
_STRICT_NETWORK_PROVIDER_ID = "system-kubernetes-e2e"
_RUNTIME_WORKSPACE_PATH = "/workspace/agent"
_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_KEY = "e2e/runtime-providers"
_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_CONTAINER_PATH = (
    "/var/run/azents/runtime-provider-bootstrap/providers.yaml"
)
_RUNTIME_CONTAINER_NAME_RE = re.compile(r"^azents-runtime-[0-9a-f]{32}$")
_DOCKER_BUILDER_ENV = "AZENTS_E2E_DOCKER_BUILDER"
_GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV = "AZENTS_E2E_DOCKER_GHA_CACHE_SCOPE_PREFIX"
_GHA_DOCKER_CACHE_WRITE_REPOSITORIES_ENV = (
    "AZENTS_E2E_DOCKER_GHA_CACHE_WRITE_REPOSITORIES"
)
_LOCAL_DOCKER_CACHE_ROOT_ENV = "AZENTS_E2E_DOCKER_CACHE_ROOT"
_LOCAL_DOCKER_CACHE_WRITE_ROOT_ENV = "AZENTS_E2E_DOCKER_CACHE_WRITE_ROOT"
_E2E_ARTIFACT_DIR_ENV = "AZENTS_E2E_ARTIFACT_DIR"
_E2E_IMAGE_BUILD_PROFILE_ENV = "AZENTS_E2E_IMAGE_BUILD_PROFILE"
_SELENIUM_IMAGE = "selenium/standalone-chromium:4.45.0-20260606"
_MAIN_WEB_UPSTREAM_URL = "http://azents-web:3000"
_ADMIN_WEB_UPSTREAM_URL = "http://azents-admin-web:3000"
_MAIN_WEB_BROWSER_URL = "https://azents-web-gateway:8443"
_ADMIN_WEB_GATEWAY_URL = "https://azents-web-gateway:8444/console"
_ADMIN_WEB_BROWSER_URL = "https://azents-web-gateway:8445"
_JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])
_JSON_OBJECT_LIST_ADAPTER = TypeAdapter(list[dict[str, object]])
_BROWSER_CALL_REPORT = pytest.StashKey[pytest.TestReport]()
_IMAGE_BUILD_OBSERVABILITY_LOCK = threading.Lock()


@dataclasses.dataclass(frozen=True)
class _E2EImageBuild:
    """Describe one product image that an E2E lane may build."""

    environment_variable: str
    tag_prefix: str
    dockerfile: Path
    cache_repository: str
    web: bool


@dataclasses.dataclass(frozen=True)
class _CoreServiceContainers:
    """Hold the concurrently started core product services."""

    public: DockerContainer
    admin: DockerContainer
    engine: DockerContainer


_SERVER_IMAGE_BUILD = _E2EImageBuild(
    environment_variable="AZENTS_E2E_SERVER_IMAGE",
    tag_prefix="azents-e2e",
    dockerfile=REPOSITORY_ROOT / "azents.Dockerfile",
    cache_repository="azents-server",
    web=False,
)
_RUNTIME_RUNNER_IMAGE_BUILD = _E2EImageBuild(
    environment_variable="AZENTS_E2E_RUNTIME_RUNNER_IMAGE",
    tag_prefix="azents-runtime-runner-e2e",
    dockerfile=REPOSITORY_ROOT / "python/apps/azents-runtime-runner/Dockerfile",
    cache_repository="azents-runtime-runner",
    web=False,
)
_RUNTIME_PROVIDER_DOCKER_IMAGE_BUILD = _E2EImageBuild(
    environment_variable="AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE",
    tag_prefix="azents-runtime-provider-docker-e2e",
    dockerfile=(
        REPOSITORY_ROOT / "python/apps/azents-runtime-provider-docker/Dockerfile"
    ),
    cache_repository="azents-runtime-provider-docker",
    web=False,
)
_WEB_IMAGE_BUILD = _E2EImageBuild(
    environment_variable="AZENTS_E2E_WEB_IMAGE",
    tag_prefix="azents-web-e2e",
    dockerfile=REPOSITORY_ROOT / "azents-web.Dockerfile",
    cache_repository="azents-web",
    web=True,
)
_ADMIN_WEB_IMAGE_BUILD = _E2EImageBuild(
    environment_variable="AZENTS_E2E_ADMIN_WEB_IMAGE",
    tag_prefix="azents-admin-web-e2e",
    dockerfile=REPOSITORY_ROOT / "azents-admin-web.Dockerfile",
    cache_repository="azents-admin-web",
    web=True,
)
_CORE_E2E_IMAGE_BUILDS = (
    _SERVER_IMAGE_BUILD,
    _RUNTIME_RUNNER_IMAGE_BUILD,
    _RUNTIME_PROVIDER_DOCKER_IMAGE_BUILD,
)
_E2E_IMAGE_BUILD_PROFILES = {
    "required": _CORE_E2E_IMAGE_BUILDS,
    "web": (*_CORE_E2E_IMAGE_BUILDS, _WEB_IMAGE_BUILD, _ADMIN_WEB_IMAGE_BUILD),
}


@dataclasses.dataclass(frozen=True)
class _ServerLogCapture:
    """One active server container whose logs are available for failure output."""

    container: ContainerLogs


_SERVER_LOG_CAPTURES: dict[str, _ServerLogCapture] = {}


class _RedactedSecret(str):
    """String secret whose pytest/debug representation never reveals its value."""

    def __repr__(self) -> str:
        return "<redacted>"


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item,
    call: pytest.CallInfo[None],
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Retain the browser test call report for bounded failure evidence."""
    report = yield
    if report.when == "call":
        item.stash[_BROWSER_CALL_REPORT] = report
        if report.failed:
            _emit_active_server_logs(item.config)
    return report


def pytest_configure(config: pytest.Config) -> None:
    """Register timing hooks globally so session fixtures are observable."""
    if timing_path() is not None:
        config.pluginmanager.register(
            TimingObservabilityPlugin(),
            "azents-e2e-timing-observability",
        )


def random_secret(length: int = 32) -> str:
    return secrets.token_hex(length)


def random_fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture(scope="session")
def auth_jwt_secret_key() -> str:
    """Return one JWT signing key shared by all server processes."""
    return random_secret(32)


@pytest.fixture(scope="session")
def system_bootstrap_setup_token() -> str:
    """Return a configured bootstrap token that is never written to test output."""
    return _RedactedSecret(secrets.token_urlsafe(32))


@pytest.fixture(scope="session")
def runtime_provider_bootstrap_source_path(
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    """Return trusted declarations for deterministic E2E Runtime Providers."""
    source_path = (
        tmp_path_factory.mktemp("runtime-provider-bootstrap") / "providers.yaml"
    )
    source_path.write_text(
        f"""apiVersion: azents.io/v1
source:
  key: {_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_KEY}
  revision: e2e-runtime-providers-v2
  digest: {"e" * 64}
providers:
  - declarationKey: system-docker
    providerId: {_RUNTIME_PROVIDER_ID}
    kind: docker
    initial:
      displayName: System Docker
      enabled: true
      availabilityMode: platform_wide
      setAsPlatformDefaultWhenUnset: true
  - declarationKey: system-kubernetes-e2e
    providerId: {_STRICT_NETWORK_PROVIDER_ID}
    kind: kubernetes
    authentication:
      method: kubernetes_service_account
      subject: system:serviceaccount:azents-e2e:strict-network-control-plane
      namespace: azents-e2e
      serviceAccountName: strict-network-control-plane
      audience: azents-runtime-control
    initial:
      displayName: Kubernetes Control Plane E2E
      enabled: true
      availabilityMode: platform_wide
      setAsPlatformDefaultWhenUnset: false
""",
        encoding="utf-8",
    )
    return source_path


@pytest.fixture(scope="session")
def runtime_workspace_path() -> str:
    """Return the explicitly configured E2E Runtime workspace mount path."""
    return _RUNTIME_WORKSPACE_PATH


# =============================================================================
# Network
# =============================================================================


@pytest.fixture(scope="session")
def container_network() -> Generator[Network, None, None]:
    with Network() as network:
        yield network


# =============================================================================
# Infrastructure Containers
# =============================================================================


@pytest.fixture(scope="session")
def postgres_container(
    container_network: Network,
) -> Generator[PostgresContainer, None, None]:
    """PostgreSQL container."""
    postgres_image = "postgres:18"
    with (
        PostgresContainer(
            postgres_image,
            driver="psycopg",
            dbname="azents",
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_network(container_network)
        .with_network_aliases("rdb") as postgres
    ):
        yield postgres


@pytest.fixture(scope="session")
def s3_credentials() -> tuple[str, str]:
    return random_secret(16), random_secret(32)


@pytest.fixture(scope="session")
def valkey_container(
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Start a Valkey container that provides Redis-compatible storage."""
    valkey_image = "valkey/valkey:9-alpine"
    with (
        DockerContainer(
            valkey_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_exposed_ports(6379)
        .with_network(container_network)
        .with_network_aliases("valkey") as container
    ):
        yield container


@pytest.fixture(scope="session")
def rustfs_container(
    s3_credentials: tuple[str, str],
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Start a RustFS container that provides S3-compatible storage."""
    access_key, secret_key = s3_credentials
    rustfs_image = "rustfs/rustfs:1.0.0-alpha.90"
    with (
        DockerContainer(
            rustfs_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_env("RUSTFS_ADDRESS", ":9000")
        .with_env("RUSTFS_ACCESS_KEY", access_key)
        .with_env("RUSTFS_SECRET_KEY", secret_key)
        .with_exposed_ports(9000)
        .with_network(container_network)
        .with_network_aliases("rustfs") as container
    ):
        yield container


@pytest.fixture(scope="session")
def mock_openai_container(
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Start the AIMock container for the OpenAI Responses API."""
    with (
        DockerContainer(
            "ghcr.io/copilotkit/aimock:1.36.1",
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(
            str(_AIMOCK_FIXTURE_DIR),
            "/fixtures",
            "ro",
        )
        .with_command(
            [
                "-p",
                "8080",
                "-h",
                "0.0.0.0",
                "-f",
                "/fixtures",
                "--strict",
                "--validate-on-load",
            ]
        )
        .with_exposed_ports(8080)
        .with_network(container_network)
        .with_network_aliases("mock-openai") as container
    ):
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8080)
        for _ in range(30):
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("mock OpenAI server did not start in time")
        yield container


@pytest.fixture(scope="session")
def openai_proxy_container(
    container_network: Network,
    mock_openai_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Proxy AIMock and add deterministic Responses image generation."""
    del mock_openai_container
    python_image = "python:3.14-alpine"
    with (
        DockerContainer(
            python_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(str(_IMAGE_GENERATION_PROXY), "/app/proxy.py", "ro")
        .with_volume_mapping(
            str(_IMAGE_GENERATION_FIXTURE_DIR),
            "/fixtures",
            "ro",
        )
        .with_command(["python", "/app/proxy.py"])
        .with_exposed_ports(8081)
        .with_network(container_network)
        .with_network_aliases("openai-proxy") as container
    ):
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8081)
        for _ in range(30):
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("OpenAI image-generation proxy did not start in time")
        yield container


@pytest.fixture(scope="session")
def github_validation_proxy_container(
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Run the deterministic GitHub App validation boundary."""
    python_image = "python:3.14-alpine"
    with (
        DockerContainer(
            python_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(str(_GITHUB_VALIDATION_PROXY), "/app/proxy.py", "ro")
        .with_command(["python", "/app/proxy.py"])
        .with_exposed_ports(8082)
        .with_network(container_network)
        .with_network_aliases("github-validation-proxy") as container
    ):
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8082)
        for _ in range(30):
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("GitHub validation proxy did not start in time")
        yield container


@pytest.fixture(scope="session")
def github_validation_proxy_url(
    github_validation_proxy_container: DockerContainer,
) -> str:
    """Return the host-visible deterministic GitHub validation URL."""
    host = github_validation_proxy_container.get_container_host_ip()
    port = github_validation_proxy_container.get_exposed_port(8082)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def slack_provider_fake_container(
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Run the deterministic Slack HTTP and Socket Mode boundary."""
    python_image = "python:3.14-alpine"
    with (
        DockerContainer(
            python_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(str(_SLACK_PROVIDER_FAKE), "/app/slack_fake.py", "ro")
        .with_command(["python", "/app/slack_fake.py"])
        .with_exposed_ports(8083, 8084)
        .with_network(container_network)
        .with_network_aliases("slack-fake") as container
    ):
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8083)
        for _ in range(30):
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("Slack provider fake did not start in time")
        yield container


@pytest.fixture(scope="session")
def slack_provider_fake_url(
    slack_provider_fake_container: DockerContainer,
) -> str:
    """Return the host-visible deterministic Slack control URL."""
    host = slack_provider_fake_container.get_container_host_ip()
    port = slack_provider_fake_container.get_exposed_port(8083)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def discord_provider_fake_container(
    container_network: Network,
    azents_server_image: str,
) -> Generator[DockerContainer, None, None]:
    """Run the deterministic Discord REST and Gateway boundary."""
    with (
        DockerContainer(
            azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(str(_DISCORD_PROVIDER_FAKE), "/app/discord_fake.py", "ro")
        .with_command(["python", "/app/discord_fake.py"])
        .with_exposed_ports(8085)
        .with_network(container_network)
        .with_network_aliases("discord-fake") as container
    ):
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8085)
        for _ in range(30):
            try:
                response = requests.get(f"http://{host}:{port}/health", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            pytest.fail("Discord provider fake did not start in time")
        yield container


@pytest.fixture(scope="session")
def discord_provider_fake_url(
    discord_provider_fake_container: DockerContainer,
) -> str:
    """Return the host-visible deterministic Discord fake control URL."""
    host = discord_provider_fake_container.get_container_host_ip()
    port = discord_provider_fake_container.get_exposed_port(8085)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def rustfs_access_key(s3_credentials: tuple[str, str]) -> str:
    """RustFS access key."""
    return s3_credentials[0]


@pytest.fixture(scope="session")
def rustfs_secret_key(s3_credentials: tuple[str, str]) -> str:
    """RustFS secret key."""
    return s3_credentials[1]


# =============================================================================
# S3 Bucket
# =============================================================================


@pytest.fixture(scope="session")
def s3_bucket_name(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
) -> Generator[str, None, None]:
    """Create the S3 bucket used by the E2E environment."""
    bucket_name = f"azents-dev-{random_secret(8)}"

    rustfs_host = rustfs_container.get_container_host_ip()
    rustfs_port = rustfs_container.get_exposed_port(9000)

    s3_client: S3Client = boto3.client(
        "s3",
        endpoint_url=f"http://{rustfs_host}:{rustfs_port}",
        aws_access_key_id=rustfs_access_key,
        aws_secret_access_key=rustfs_secret_key,
    )
    s3_client.create_bucket(Bucket=bucket_name)

    yield bucket_name


# =============================================================================
# azents Server
# =============================================================================


def _build_e2e_web_image(
    *,
    image_tag: str,
    dockerfile: Path,
    cache_repository: str,
) -> None:
    """Build a Next.js image with the required empty cache context."""
    with tempfile.TemporaryDirectory(prefix="azents-next-cache-") as cache_root:
        (Path(cache_root) / "next-cache").mkdir()
        _build_e2e_image(
            image_tag=image_tag,
            dockerfile=dockerfile,
            cache_repository=cache_repository,
            build_contexts={"next-cache": cache_root},
        )


def _build_configured_e2e_image(
    image_build: _E2EImageBuild,
    image_tag: str,
) -> None:
    """Build one configured image using its required context."""
    if image_build.web:
        _build_e2e_web_image(
            image_tag=image_tag,
            dockerfile=image_build.dockerfile,
            cache_repository=image_build.cache_repository,
        )
        return

    _build_e2e_image(
        image_tag=image_tag,
        dockerfile=image_build.dockerfile,
        cache_repository=image_build.cache_repository,
    )


def _prepare_e2e_images(profile: str | None) -> dict[str, str]:
    """Build one CI lane's independent product images concurrently."""
    if profile is None:
        return {}
    try:
        image_builds = _E2E_IMAGE_BUILD_PROFILES[profile]
    except KeyError:
        supported = ", ".join(sorted(_E2E_IMAGE_BUILD_PROFILES))
        raise RuntimeError(
            f"Unsupported {_E2E_IMAGE_BUILD_PROFILE_ENV} {profile!r}; "
            f"expected one of: {supported}."
        ) from None

    images: dict[str, str] = {}
    pending_builds: list[tuple[_E2EImageBuild, str]] = []
    for image_build in image_builds:
        if image := os.environ.get(image_build.environment_variable):
            images[image_build.cache_repository] = image
            continue
        image_tag = f"{image_build.tag_prefix}:{random_secret(8)}"
        images[image_build.cache_repository] = image_tag
        pending_builds.append((image_build, image_tag))

    if not pending_builds:
        return images

    with ThreadPoolExecutor(max_workers=len(pending_builds)) as executor:
        futures = [
            executor.submit(_build_configured_e2e_image, image_build, image_tag)
            for image_build, image_tag in pending_builds
        ]
        for future in futures:
            future.result()
    return images


@pytest.fixture(scope="session")
def e2e_images() -> dict[str, str]:
    """Return CI-prepared images, leaving focused local builds lazy by default."""
    return _prepare_e2e_images(os.environ.get(_E2E_IMAGE_BUILD_PROFILE_ENV))


def _resolve_e2e_image(
    image_build: _E2EImageBuild,
    prepared_images: dict[str, str],
) -> str:
    """Return a prepared image or build only the locally requested image."""
    if image := prepared_images.get(image_build.cache_repository):
        return image
    if image := os.environ.get(image_build.environment_variable):
        return image

    image_tag = f"{image_build.tag_prefix}:{random_secret(8)}"
    _build_configured_e2e_image(image_build, image_tag)
    return image_tag


@pytest.fixture(scope="session")
def azents_server_image(e2e_images: dict[str, str]) -> str:
    return _resolve_e2e_image(_SERVER_IMAGE_BUILD, e2e_images)


@pytest.fixture(scope="session")
def azents_web_image(e2e_images: dict[str, str]) -> str:
    """Build or reuse the Main Web image for browser E2E."""
    return _resolve_e2e_image(_WEB_IMAGE_BUILD, e2e_images)


@pytest.fixture(scope="session")
def azents_admin_web_image(e2e_images: dict[str, str]) -> str:
    """Build or reuse the Admin Web image for browser E2E."""
    return _resolve_e2e_image(_ADMIN_WEB_IMAGE_BUILD, e2e_images)


@pytest.fixture(scope="session")
def azents_runtime_runner_image(e2e_images: dict[str, str]) -> str:
    return _resolve_e2e_image(_RUNTIME_RUNNER_IMAGE_BUILD, e2e_images)


@pytest.fixture(scope="session")
def azents_runtime_provider_docker_image(e2e_images: dict[str, str]) -> str:
    return _resolve_e2e_image(_RUNTIME_PROVIDER_DOCKER_IMAGE_BUILD, e2e_images)


def _build_e2e_image(
    *,
    image_tag: str,
    dockerfile: Path,
    cache_repository: str,
    build_contexts: dict[str, str] | None = None,
) -> None:
    """Build one E2E product image with an optional BuildKit cache backend."""
    cache_from, cache_to, cache_backend, cache_scope = _get_e2e_image_cache_options(
        cache_repository
    )
    builder = os.environ.get(_DOCKER_BUILDER_ENV)
    started_at = time.monotonic()
    completed = False

    try:
        pow_docker.build(
            context_path=str(REPOSITORY_ROOT),
            file=str(dockerfile),
            tags=[image_tag],
            builder=builder,
            cache_from=cache_from or None,
            cache_to=cache_to,
            build_contexts=cast(Any, build_contexts or {}),
            load=True,
        )
        completed = True
    finally:
        _write_e2e_image_build_observability(
            cache_repository=cache_repository,
            cache_backend=cache_backend,
            cache_scope=cache_scope,
            cache_export_enabled=cache_to is not None,
            completed=completed,
            duration_seconds=time.monotonic() - started_at,
        )


def _get_e2e_image_cache_options(
    cache_repository: str,
) -> tuple[list[dict[str, str]], dict[str, str] | None, str, str | None]:
    """Return cache import/export settings for one E2E product image."""
    builder = os.environ.get(_DOCKER_BUILDER_ENV)
    gha_scope_prefix = os.environ.get(_GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV)
    if gha_scope_prefix:
        if not builder:
            raise RuntimeError(
                f"{_GHA_DOCKER_CACHE_SCOPE_PREFIX_ENV} requires {_DOCKER_BUILDER_ENV}."
            )

        cache_scope = f"{gha_scope_prefix}-{cache_repository}"
        cache_from = [{"type": "gha", "scope": cache_scope}]
        write_repositories = frozenset(
            repository.strip()
            for repository in os.environ.get(
                _GHA_DOCKER_CACHE_WRITE_REPOSITORIES_ENV, ""
            ).split(",")
            if repository.strip()
        )
        cache_to = (
            {
                "type": "gha",
                "scope": cache_scope,
                "mode": "max",
                "ignore-error": "true",
            }
            if cache_repository in write_repositories
            else None
        )
        return cache_from, cache_to, "gha", cache_scope

    cache_from: list[dict[str, str]] = []
    cache_to: dict[str, str] | None = None
    if builder:
        local_cache_root = os.environ.get(_LOCAL_DOCKER_CACHE_ROOT_ENV)
        if local_cache_root:
            local_cache_path = Path(local_cache_root) / cache_repository
            if local_cache_path.exists():
                cache_from.append({"type": "local", "src": str(local_cache_path)})

        local_cache_write_root = os.environ.get(_LOCAL_DOCKER_CACHE_WRITE_ROOT_ENV)
        if local_cache_write_root:
            local_cache_write_path = Path(local_cache_write_root) / cache_repository
            local_cache_write_path.parent.mkdir(parents=True, exist_ok=True)
            cache_to = {
                "type": "local",
                "dest": str(local_cache_write_path),
                "mode": "min",
            }

    return cache_from, cache_to, "local" if cache_from or cache_to else "none", None


def _write_e2e_image_build_observability(
    *,
    cache_repository: str,
    cache_backend: str,
    cache_scope: str | None,
    cache_export_enabled: bool,
    completed: bool,
    duration_seconds: float,
) -> None:
    """Append safe per-image build timing evidence to the CI artifact directory."""
    artifact_root = os.environ.get(_E2E_ARTIFACT_DIR_ENV)
    if not artifact_root:
        return

    artifact_path = Path(artifact_root) / "image-build-timings.jsonl"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_record = {
        "image": cache_repository,
        "cache_backend": cache_backend,
        "cache_scope": cache_scope,
        "cache_export_enabled": cache_export_enabled,
        "completed": completed,
        "duration_seconds": round(duration_seconds, 3),
    }
    with _IMAGE_BUILD_OBSERVABILITY_LOCK:
        with artifact_path.open("a", encoding="utf-8") as artifact_file:
            artifact_file.write(json.dumps(artifact_record, sort_keys=True) + "\n")


@pytest.fixture(scope="session")
def credential_encryption_key() -> str:
    return random_fernet_key()


def _configure_azents_server_container(
    container: DockerContainer,
    network: Network,
    postgres_container: PostgresContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    system_bootstrap_setup_token: str,
) -> DockerContainer:
    """Build environment settings for an Azents server container."""
    return (
        container.with_network(network)
        .with_env("AZ_RUNTIME_ENV", "deployed")
        .with_env("AZ_RDB_HOST", "rdb")
        .with_env("AZ_RDB_PORT", "5432")
        .with_env("AZ_RDB_USER", postgres_container.username)
        .with_env("AZ_RDB_PASSWORD", postgres_container.password)
        .with_env("AZ_RDB_DB_NAME", postgres_container.dbname)
        .with_env("AZ_S3_ENDPOINT", "http://rustfs:9000")
        .with_env("AZ_S3_BUCKET_NAME", s3_bucket_name)
        .with_env("AWS_ACCESS_KEY_ID", rustfs_access_key)
        .with_env("AWS_SECRET_ACCESS_KEY", rustfs_secret_key)
        .with_env("AZ_AUTH_JWT_SECRET_KEY", auth_jwt_secret_key)
        .with_env("AZ_CREDENTIAL_ENCRYPTION_KEY", credential_encryption_key)
        .with_env("AZ_SYSTEM_BOOTSTRAP_SETUP_TOKEN", system_bootstrap_setup_token)
        .with_env("AZ_REDIS_URL", "redis://valkey:6379")
        .with_env("AZ_WEB_URL", _MAIN_WEB_BROWSER_URL)
        .with_env("AZ_WORKSPACE_S3_BUCKET", s3_bucket_name)
        .with_env("AZ_WORKSPACE_S3_PREFIX", "v1")
        .with_env("AZ_WORKSPACE_S3_ENDPOINT_URL", "http://rustfs:9000")
        .with_env("AZ_LLM_CATALOG_SYNC_ENABLED", "true")
        .with_env("AZ_LLM_CATALOG_STARTUP_SYNC_ENABLED", "true")
        .with_env("AZ_LLM_CATALOG_SOURCE_MODE", "fixture")
        .with_env("AZ_OPENAI_BASE_URL", "http://openai-proxy:8081/v1")
        .with_env(
            "AZ_CHATGPT_USAGE_BASE_URL",
            "http://openai-proxy:8081/backend-api",
        )
        .with_env(
            "AZ_CHATGPT_OAUTH_DEVICE_USER_CODE_URL",
            "http://openai-proxy:8081/chatgpt/device/usercode",
        )
        .with_env(
            "AZ_CHATGPT_OAUTH_DEVICE_TOKEN_URL",
            "http://openai-proxy:8081/chatgpt/device/token",
        )
        .with_env(
            "AZ_CHATGPT_OAUTH_TOKEN_URL",
            "http://openai-proxy:8081/chatgpt/oauth/token",
        )
        .with_env("AZ_XAI_API_BASE_URL", "http://openai-proxy:8081/v1")
        .with_env("AZ_XAI_USAGE_BASE_URL", "http://openai-proxy:8081/v1")
        .with_env(
            "AZ_XAI_OAUTH_DEVICE_CODE_URL",
            "http://openai-proxy:8081/oauth2/device/code",
        )
        .with_env("AZ_XAI_OAUTH_TOKEN_URL", "http://openai-proxy:8081/oauth2/token")
        .with_env(
            "AZ_TESTENV_SLACK_API_BASE_URL",
            _SLACK_PROVIDER_INTERNAL_API_URL,
        )
        .with_env("AZ_TESTENV_SLACK_ALLOW_INSECURE_WEBSOCKET", "true")
        .with_env("AZ_EXTERNAL_CHANNEL_MULTI_APP_ENABLED", "true")
        .with_env(
            "AZ_EXTERNAL_CHANNEL_DISCORD_CALLBACK_URL",
            "http://azents-public-server:8010",
        )
        .with_env(
            "AZ_TESTENV_DISCORD_API_BASE_URL",
            _DISCORD_PROVIDER_INTERNAL_API_URL,
        )
        .with_env("AZ_TESTENV_RUNTIME_HOOK_QA_ENABLED", "true")
        .with_env("AZ_TOOL_INTERNAL_ERROR_DETAILS", "true")
        .with_env("AZ_AGENT_HOME_IDLE_TIMEOUT_SECS", "60")
        .with_env("AZ_AGENT_HOME_SESSION_HIBERNATE_IDLE_SECONDS", "60")
        .with_env("AZ_AZENTS_SESSION_HIBERNATE_IDLE_SECONDS", "60")
        .with_env("AZ_AGENT_HOME_CLEANUP_INTERVAL_SECS", "1")
        .with_env("AZ_FAILED_RUN_MAX_RETRIES", "3")
        .with_env("AZ_FAILED_RUN_BASE_BACKOFF_SECONDS", "1")
        .with_env("AZ_FAILED_RUN_BACKOFF_MULTIPLIER", "1")
        .with_env("AZ_FAILED_RUN_MAX_BACKOFF_SECONDS", "1")
        .with_env("AZ_MODEL_STREAM_CONNECT_TIMEOUT_SECONDS", "2")
        .with_env("AZ_MODEL_STREAM_IDLE_TIMEOUT_SECONDS", "0.5")
        .with_env("AZ_MODEL_STREAM_ABSOLUTE_TIMEOUT_SECONDS", "1.5")
        .with_env("AZ_MODEL_STREAM_CLOSE_GRACE_SECONDS", "0.25")
    )


def _wait_for_tcp_ready(
    container: DockerContainer,
    port: int,
    server_name: str,
) -> None:
    host = container.get_container_host_ip()
    exposed_port = container.get_exposed_port(port)

    max_retries = 30
    for i in range(max_retries):
        if container.get_wrapped_container().status == "exited":
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} exited\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        try:
            with socket.create_connection((host, int(exposed_port)), timeout=2):
                return
        except OSError:
            pass

        if i == max_retries - 1:
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        time.sleep(1)


def _wait_for_runtime_control_ready(container: DockerContainer) -> None:
    """Wait until Runtime Control confirms that its gRPC server has started."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        if wrapped.status == "exited":
            pytest.fail(
                "azents-runtime-control exited before gRPC startup\n\n"
                f"logs:\n{_read_container_logs(container)}"
            )
        logs = _read_container_logs(container)
        if "Runtime Control gRPC server started" in logs:
            return
        time.sleep(0.5)
    pytest.fail(
        "azents-runtime-control did not confirm gRPC startup\n\n"
        f"logs:\n{_read_container_logs(container)}"
    )


def _read_container_logs(container: DockerContainer) -> str:
    """Read complete server logs for E2E diagnostics."""
    return read_container_logs(container)


def _register_server_log_capture(
    server_name: str,
    container: ContainerLogs,
) -> None:
    """Make a running server's logs available to failure reporting."""
    _SERVER_LOG_CAPTURES[server_name] = _ServerLogCapture(container=container)


def _unregister_server_log_capture(server_name: str) -> None:
    """Remove a server after its container fixture starts teardown."""
    _SERVER_LOG_CAPTURES.pop(server_name, None)


def _emit_active_server_logs(config: pytest.Config) -> None:
    """Write all active server logs directly to the pytest terminal."""
    terminal_reporter = config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter is None:
        original_stdout = sys.__stdout__

        def write_line(line: str) -> None:
            if original_stdout is not None:
                original_stdout.write(f"{line}\n")

    else:
        write_line = terminal_reporter.write_line
    for server_name, capture in _SERVER_LOG_CAPTURES.items():
        emit_container_logs(
            capture.container,
            server_name=server_name,
            write_line=write_line,
        )
    for line in _runtime_container_diagnostics():
        write_line(line)


def _runtime_container_diagnostics() -> tuple[str, ...]:
    """Return bounded managed Runtime container evidence for E2E failures."""
    client = None
    lines: list[str] = []
    try:
        client = docker_py.from_env()
        containers: list[Container] = client.containers.list(
            all=True,
            filters={"label": "azents/managed-by=azents-runtime-provider-docker"},
        )
        for container in containers:
            container.reload()
            attributes = container.attrs
            config = attributes.get("Config", {})
            host_config = attributes.get("HostConfig", {})
            state = attributes.get("State", {})
            if not all(
                isinstance(value, dict) for value in (config, host_config, state)
            ):
                continue
            evidence = {
                "name": container.name,
                "image": config.get("Image"),
                "user": config.get("User"),
                "state": {
                    "status": state.get("Status"),
                    "running": state.get("Running"),
                    "exit_code": state.get("ExitCode"),
                    "oom_killed": state.get("OOMKilled"),
                    "error": state.get("Error"),
                },
                "security": {
                    "cap_add": host_config.get("CapAdd"),
                    "cap_drop": host_config.get("CapDrop"),
                    "security_opt": host_config.get("SecurityOpt"),
                    "userns_mode": host_config.get("UsernsMode"),
                    "masked_paths": host_config.get("MaskedPaths"),
                    "readonly_paths": host_config.get("ReadonlyPaths"),
                    "privileged": host_config.get("Privileged"),
                },
            }
            lines.append(f"=== Runtime container {container.name} evidence ===")
            lines.append(json.dumps(evidence, sort_keys=True, default=str))
            logs = container.logs(stdout=True, stderr=True, tail=200)
            if isinstance(logs, bytes):
                lines.extend(logs.decode(errors="replace").splitlines())
        artifact_dir = os.environ.get(_E2E_ARTIFACT_DIR_ENV)
        if artifact_dir is not None and lines:
            path = Path(artifact_dir) / "runtime-containers.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n")
    except DockerException, OSError:
        return ()
    finally:
        if client is not None:
            client.close()
    return tuple(lines)


def _log_server_output(container: DockerContainer, server_name: str) -> None:
    """Write one server container's stdout and stderr to the test output."""
    try:
        stdout, stderr = container.get_logs()
        sys.stdout.write(f"\n\n=== {server_name} stdout ===\n{stdout.decode()}\n")
        sys.stdout.write(f"\n=== {server_name} stderr ===\n{stderr.decode()}\n")
    except (DockerException, UnicodeDecodeError) as exc:
        sys.stderr.write(
            f"\nFailed to capture {server_name} container output: "
            f"{type(exc).__name__}: {exc}\n"
        )


def _remove_agent_runtime_containers(network_name: str) -> None:
    client = docker_py.from_env()
    try:
        containers: list[Container] = client.containers.list(
            all=True,
            filters={"network": network_name},
        )
        for container in containers:
            container_name = container.name
            if container_name is None or not (
                container_name.startswith("azents-agent-")
                or _RUNTIME_CONTAINER_NAME_RE.fullmatch(container_name)
            ):
                continue
            try:
                container.remove(force=True)
            except NotFound:
                continue
    except APIError as exc:
        pytest.fail(f"failed to remove agent-runtime containers: {exc}")
    finally:
        client.close()


@pytest.fixture(scope="session")
def azents_database_schema(
    container_network: Network,
    postgres_container: PostgresContainer,
    rustfs_container: DockerContainer,
    valkey_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    azents_server_image: str,
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    system_bootstrap_setup_token: str,
) -> None:
    """Upgrade the shared E2E database before core services start concurrently."""
    del rustfs_container, valkey_container
    base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-database-migration-{random_secret(4)}")
        .with_command(
            [
                "/bin/sh",
                "-ec",
                (
                    'revision="$(cat db-schemas/rdb/revision)"; '
                    'alembic -c db-schemas/rdb/alembic.ini upgrade "$revision"'
                ),
            ]
        )
    )
    container = _configure_azents_server_container(
        base_container,
        container_network,
        postgres_container,
        rustfs_access_key,
        rustfs_secret_key,
        s3_bucket_name,
        auth_jwt_secret_key,
        credential_encryption_key,
        system_bootstrap_setup_token,
    )

    with container:
        result = container.get_wrapped_container().wait(timeout=120)
        if result["StatusCode"] != 0:
            stdout, stderr = container.get_logs()
            pytest.fail(
                "azents database migration failed\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )


@pytest.fixture(scope="session")
def azents_core_service_containers(
    container_network: Network,
    postgres_container: PostgresContainer,
    rustfs_container: DockerContainer,
    valkey_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    azents_server_image: str,
    azents_database_schema: None,
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    system_bootstrap_setup_token: str,
    openai_proxy_container: DockerContainer,
    slack_provider_fake_container: DockerContainer,
    github_validation_proxy_container: DockerContainer,
    runtime_provider_bootstrap_source_path: Path,
) -> Generator[_CoreServiceContainers, None, None]:
    """Start Public API, Admin API, and Engine Worker concurrently."""
    del (
        azents_database_schema,
        openai_proxy_container,
        slack_provider_fake_container,
        github_validation_proxy_container,
    )
    public_base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-public-server-{random_secret(4)}")
        .with_network_aliases("azents-public-server")
        .with_exposed_ports(8010)
    )
    public_container = _configure_azents_server_container(
        public_base_container,
        container_network,
        postgres_container,
        rustfs_access_key,
        rustfs_secret_key,
        s3_bucket_name,
        auth_jwt_secret_key,
        credential_encryption_key,
        system_bootstrap_setup_token,
    )
    admin_base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-admin-server-{random_secret(4)}")
        .with_network_aliases("azents-admin-server")
        .with_command(["./bin/adminserver.sh"])
        .with_exposed_ports(8011)
    )
    admin_container = (
        _configure_azents_server_container(
            admin_base_container,
            container_network,
            postgres_container,
            rustfs_access_key,
            rustfs_secret_key,
            s3_bucket_name,
            auth_jwt_secret_key,
            credential_encryption_key,
            system_bootstrap_setup_token,
        )
        .with_env(
            "AZ_TESTENV_GITHUB_PLATFORM_VALIDATION_BASE_URL",
            _GITHUB_VALIDATION_INTERNAL_URL,
        )
        .with_env("AZ_TESTENV_API_ENABLED", "true")
        .with_env(
            "AZ_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_KEY",
            _RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_KEY,
        )
        .with_env(
            "AZ_RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_PATH",
            _RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_CONTAINER_PATH,
        )
        .with_volume_mapping(
            str(runtime_provider_bootstrap_source_path),
            _RUNTIME_PROVIDER_BOOTSTRAP_SOURCE_CONTAINER_PATH,
            "ro",
        )
    )
    engine_base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-engine-worker-{random_secret(4)}")
        .with_network_aliases("azents-engine-worker")
        .with_command(["./bin/engineworker.sh"])
        .with_exposed_ports(8012)
        .with_volume_mapping("/var/run/docker.sock", "/var/run/docker.sock", "rw")
    )
    engine_container = _configure_azents_server_container(
        engine_base_container,
        container_network,
        postgres_container,
        rustfs_access_key,
        rustfs_secret_key,
        s3_bucket_name,
        auth_jwt_secret_key,
        credential_encryption_key,
        system_bootstrap_setup_token,
    )
    engine_container = engine_container.with_env(
        "AZ_WORKER_HEALTH_PORT", "8012"
    ).with_env("AZ_AGENT_HOME_DOCKER_NETWORK", container_network.name)
    engine_container = engine_container.with_env(
        "AZ_RUNTIME_TRANSFER_COORDINATOR_ENDPOINT", "runtime-control:8030"
    ).with_env("AZ_RUNTIME_TRANSFER_COORDINATOR_ALLOW_INSECURE", "true")

    containers = _CoreServiceContainers(
        public=public_container,
        admin=admin_container,
        engine=engine_container,
    )
    container_items = (
        ("azents-public-server", containers.public),
        ("azents-admin-server", containers.admin),
        ("azents-engine-worker", containers.engine),
    )

    def wait_for_engine_worker_ready() -> None:
        host = containers.engine.get_container_host_ip()
        port = containers.engine.get_exposed_port(8012)
        base_url = f"http://{host}:{port}"
        for _ in range(60):
            if containers.engine.get_wrapped_container().status == "exited":
                stdout, stderr = containers.engine.get_logs()
                pytest.fail(
                    "azents-engine-worker exited\n\n"
                    f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
                )
            try:
                response = requests.get(f"{base_url}/readyz", timeout=2)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        else:
            stdout, stderr = containers.engine.get_logs()
            pytest.fail(
                "azents-engine-worker did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )

    started_containers: list[DockerContainer] = []
    started_containers_lock = threading.Lock()
    registered_names: list[str] = []

    def start_container(container: DockerContainer) -> None:
        container.start()
        with started_containers_lock:
            started_containers.append(container)

    try:
        with ThreadPoolExecutor(max_workers=3) as executor:
            start_futures = [
                executor.submit(start_container, container)
                for _, container in container_items
            ]
            for future in start_futures:
                future.result()
        with ThreadPoolExecutor(max_workers=3) as executor:
            readiness_futures = (
                executor.submit(
                    wait_for_server_ready,
                    containers.public,
                    8010,
                    "azents-public-server",
                ),
                executor.submit(
                    wait_for_server_ready,
                    containers.admin,
                    8011,
                    "azents-admin-server",
                ),
                executor.submit(wait_for_engine_worker_ready),
            )
            for future in readiness_futures:
                future.result()
        for server_name, container in container_items:
            _register_server_log_capture(server_name, container)
            registered_names.append(server_name)
        yield containers
    finally:
        try:
            for server_name in reversed(registered_names):
                _unregister_server_log_capture(server_name)
            _remove_agent_runtime_containers(container_network.name)
        finally:
            with ThreadPoolExecutor(max_workers=3) as executor:
                stop_futures = [
                    executor.submit(container.stop) for container in started_containers
                ]
                for future in stop_futures:
                    future.result()


@pytest.fixture(scope="session")
def azents_public_server_container(
    azents_core_service_containers: _CoreServiceContainers,
) -> DockerContainer:
    """azents Public API server container (port 8010)."""
    return azents_core_service_containers.public


@pytest.fixture(scope="session")
def azents_admin_server_container(
    azents_core_service_containers: _CoreServiceContainers,
) -> DockerContainer:
    """azents Admin API server container (port 8011)."""
    return azents_core_service_containers.admin


@pytest.fixture(scope="session")
def azents_engine_worker_container(
    azents_core_service_containers: _CoreServiceContainers,
) -> DockerContainer:
    """WebSocket session runtime process azents Engine Worker container."""
    return azents_core_service_containers.engine


@pytest.fixture
def azents_external_channel_gateway_factory(
    container_network: Network,
    postgres_container: PostgresContainer,
    rustfs_container: DockerContainer,
    valkey_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    azents_server_image: str,
    azents_public_server_container: DockerContainer,
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    system_bootstrap_setup_token: str,
    discord_provider_fake_container: DockerContainer,
) -> Callable[[], AbstractContextManager[DockerContainer]]:
    """Return a starter for persistent provider ingress after durable setup."""
    del azents_public_server_container, discord_provider_fake_container

    @contextmanager
    def start() -> Generator[DockerContainer, None, None]:
        base_container = (
            DockerContainer(
                image=azents_server_image,
                docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
            )
            .with_name(f"azents-external-channel-gateway-{random_secret(4)}")
            .with_network_aliases("azents-external-channel-gateway")
            .with_command(["./bin/externalchannelgateway.sh"])
            .with_exposed_ports(8013)
        )
        container = (
            _configure_azents_server_container(
                base_container,
                container_network,
                postgres_container,
                rustfs_access_key,
                rustfs_secret_key,
                s3_bucket_name,
                auth_jwt_secret_key,
                credential_encryption_key,
                system_bootstrap_setup_token,
            )
            .with_env("AZ_WORKER_HEALTH_PORT", "8013")
            .with_env(
                "AZ_TESTENV_EXTERNAL_CHANNEL_GATEWAY_LEASE_DURATION_SECONDS",
                "5",
            )
            .with_env(
                "AZ_TESTENV_EXTERNAL_CHANNEL_GATEWAY_RENEWAL_INTERVAL_SECONDS",
                "1",
            )
        )

        with container:
            _wait_for_tcp_ready(container, 8013, "azents-external-channel-gateway")
            try:
                yield container
            finally:
                _log_server_output(container, "azents-external-channel-gateway")

    return start


@pytest.fixture(scope="session")
def azents_runtime_control_container(
    container_network: Network,
    postgres_container: PostgresContainer,
    rustfs_container: DockerContainer,
    valkey_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    azents_server_image: str,
    azents_admin_server_container: DockerContainer,
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    system_bootstrap_setup_token: str,
    openai_proxy_container: DockerContainer,
    azents_runtime_runner_image: str,
) -> Generator[DockerContainer, None, None]:
    """Runtime Control gRPC server container."""
    del azents_admin_server_container, openai_proxy_container

    base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-runtime-control-{random_secret(4)}")
        .with_network_aliases("runtime-control")
        .with_command(["python", "src/cli/runtime_control_server.py"])
        .with_exposed_ports(8030)
    )
    container = _configure_azents_server_container(
        base_container,
        container_network,
        postgres_container,
        rustfs_access_key,
        rustfs_secret_key,
        s3_bucket_name,
        auth_jwt_secret_key,
        credential_encryption_key,
        system_bootstrap_setup_token,
    )
    container = (
        container.with_env("AZ_RUNTIME_CONTROL_PORT", "8030")
        .with_env("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
        .with_env("AZ_RUNTIME_CONTROL_INSTANCE_ID", "azents-e2e-runtime-control")
        .with_env("AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS", "1")
        .with_env("AZ_RUNTIME_CONTROL_LIFECYCLE_RETRY_DELAY_SECONDS", "1")
        .with_env("AZ_RUNTIME_CONTROL_START_TIMEOUT_SECONDS", "120")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET", s3_bucket_name)
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_PREFIX", "v1")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL", "http://rustfs:9000")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ACCESS_KEY_ID", rustfs_access_key)
        .with_env(
            "AZ_RUNTIME_CONTROL_WORKSPACE_S3_SECRET_ACCESS_KEY",
            rustfs_secret_key,
        )
        .with_env("AZ_RUNTIME_RUNNER_IMAGE", azents_runtime_runner_image)
        .with_env("AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT", "runtime-control:8030")
        .with_env("AZ_RUNTIME_RUNNER_TRANSFER_ENDPOINT", "runtime-control:8030")
    )

    with container:
        _wait_for_runtime_control_ready(container)
        _register_server_log_capture("azents-runtime-control", container)
        try:
            yield container
        finally:
            _unregister_server_log_capture("azents-runtime-control")
            _log_server_output(container, "azents-runtime-control")


@pytest.fixture(scope="session")
def azents_runtime_provider_docker_container(
    container_network: Network,
    azents_runtime_control_container: DockerContainer,
    azents_runtime_provider_docker_image: str,
    runtime_provider_credential: str,
    runtime_workspace_path: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> Generator[DockerContainer, None, None]:
    """Docker Runtime Provider container."""
    del azents_runtime_control_container

    docker_host = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    if not docker_host.startswith("unix://"):
        pytest.fail("E2E Docker Runtime Provider requires a Unix Docker socket")
    docker_socket_path = docker_host.removeprefix("unix://")

    with tempfile.TemporaryDirectory(
        prefix="azents-runtime-provider-e2e-"
    ) as data_root:
        container = (
            DockerContainer(
                image=azents_runtime_provider_docker_image,
                docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
            )
            .with_name(f"azents-runtime-provider-docker-{random_secret(4)}")
            .with_network(container_network)
            .with_volume_mapping(docker_socket_path, "/var/run/docker.sock", "rw")
            .with_volume_mapping(data_root, data_root, "rw")
            .with_env("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
            .with_env("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
            .with_env("AZ_RUNTIME_PROVIDER_ID", _RUNTIME_PROVIDER_ID)
            .with_env("AZ_RUNTIME_PROVIDER_DOCKER_NETWORK", container_network.name)
            .with_env("AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT", data_root)
            .with_env(
                "AZ_RUNTIME_PROVIDER_WORKSPACE_PATH",
                runtime_workspace_path,
            )
            .with_env(
                "AZ_RUNTIME_PROVIDER_DOCKER_HOST",
                "unix:///var/run/docker.sock",
            )
            .with_env(
                "AZ_RUNTIME_PROVIDER_CREDENTIAL",
                runtime_provider_credential,
            )
            .with_env("AZ_LOG_LEVEL", "INFO")
            .with_kwargs(user="root")
        )
        try:
            with container:
                _wait_for_runtime_provider_registered(
                    container,
                    provider_id=_RUNTIME_PROVIDER_ID,
                )
                _wait_for_runtime_provider_contract(
                    admin_server_url=azents_admin_server_url,
                    access_token=system_bootstrap_evidence.access_token,
                    provider_id=_RUNTIME_PROVIDER_ID,
                )
                _create_e2e_docker_infrastructure_profile(
                    admin_server_url=azents_admin_server_url,
                    access_token=system_bootstrap_evidence.access_token,
                    provider_id=_RUNTIME_PROVIDER_ID,
                    network_name=container_network.name,
                )
                yield container
                _log_server_output(container, "azents-runtime-provider-docker")
        finally:
            _remove_agent_runtime_containers(container_network.name)
            _remove_runtime_provider_data_root(
                data_root,
                image=azents_runtime_provider_docker_image,
            )


def _remove_runtime_provider_data_root(data_root: str, *, image: str) -> None:
    """Delete root-owned Provider data before its host temporary directory exits."""
    cleanup = (
        DockerContainer(
            image=image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_volume_mapping(data_root, "/provider-data", "rw")
        .with_command(["/bin/sh", "-ec", "find /provider-data -mindepth 1 -delete"])
        .with_kwargs(user="root")
    )
    with cleanup:
        result = cleanup.get_wrapped_container().wait(
            timeout=_RUNTIME_PROVIDER_DATA_CLEANUP_TIMEOUT_SECONDS
        )
        logs = b"\n".join(cleanup.get_logs()).decode(errors="replace")
    if result["StatusCode"] != 0:
        pytest.fail(f"E2E Runtime Provider data cleanup failed: {logs}")


def _wait_for_runtime_provider_registered(
    container: DockerContainer,
    *,
    provider_id: str,
) -> None:
    deadline = time.monotonic() + 60
    last_logs = ""
    while time.monotonic() < deadline:
        if container.get_wrapped_container().status == "exited":
            logs = _read_container_logs(container)
            pytest.fail(f"azents-runtime-provider-docker exited\n\nlogs:\n{logs}")
        last_logs = _read_container_logs(container)
        if "Runtime Provider registered" in last_logs:
            return
        time.sleep(1)
    pytest.fail(
        f"runtime provider {provider_id} did not register in time\n{last_logs[-4000:]}"
    )


def _wait_for_runtime_provider_contract(
    *,
    admin_server_url: str,
    access_token: str,
    provider_id: str,
) -> None:
    """Wait for the registered Provider capability contract to become current."""
    headers = {"Authorization": f"Bearer {access_token}"}
    deadline = time.monotonic() + 60
    last_error = ""
    while time.monotonic() < deadline:
        providers_response = requests.get(
            f"{admin_server_url}/runtime-provider/v1/providers",
            headers=headers,
            timeout=10,
        )
        if providers_response.status_code != 200:
            last_error = (
                "provider inventory returned "
                f"HTTP {providers_response.status_code}: {providers_response.text}"
            )
            time.sleep(1)
            continue
        payload = _JSON_OBJECT_ADAPTER.validate_python(providers_response.json())
        items = _JSON_OBJECT_LIST_ADAPTER.validate_python(payload.get("items"))
        provider = next(
            (item for item in items if item.get("provider_id") == provider_id),
            None,
        )
        if provider is None:
            last_error = f"provider {provider_id} was not present in inventory"
            time.sleep(1)
            continue
        current_revision = provider.get("current_contract_revision_id")
        if isinstance(current_revision, str) and current_revision:
            return
        last_error = f"provider {provider_id} has no current capability contract"
        time.sleep(1)
    pytest.fail(
        f"runtime provider {provider_id} contract did not become current: {last_error}"
    )


def _create_e2e_docker_infrastructure_profile(
    *,
    admin_server_url: str,
    access_token: str,
    provider_id: str,
    network_name: str,
) -> None:
    """Create the selectable Docker Profile used by Runtime Provider journeys."""
    response = requests.post(
        (
            f"{admin_server_url}/runtime-provider/v1/providers/"
            f"{provider_id}/container-profiles"
        ),
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "display_name": "E2E Docker Container",
            "description": "Deterministic Docker Profile for Runtime Provider E2E.",
            "lifecycle": "active",
            "spec": docker_infrastructure_profile_spec(
                network_name=network_name,
            ),
        },
        timeout=10,
    )
    if response.status_code != 201:
        pytest.fail(
            "failed to create E2E Docker infrastructure Profile: "
            f"HTTP {response.status_code}: {response.text}"
        )
    payload = _JSON_OBJECT_ADAPTER.validate_python(response.json())
    if payload.get("compatible") is not True:
        pytest.fail(
            "E2E Docker infrastructure Profile is not compatible: "
            f"{payload.get('compatibility_reason_code')!r}"
        )


@pytest.fixture(scope="session")
def strict_network_control_plane(
    tmp_path_factory: pytest.TempPathFactory,
    container_network: Network,
    azents_runtime_control_container: DockerContainer,
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> Generator[StrictNetworkControlPlaneFixture, None, None]:
    """Run a bounded Kubernetes control-plane simulator without packet claims."""
    provider_resource_id = _provider_resource_id(
        admin_server_url=azents_admin_server_url,
        access_token=system_bootstrap_evidence.access_token,
        provider_id=_STRICT_NETWORK_PROVIDER_ID,
    )
    expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=30)
    try:
        credential = issue_runtime_provider_credential(
            admin_server_url=azents_admin_server_url,
            public_server_url=azents_public_server_url,
            admin_access_token=system_bootstrap_evidence.access_token,
            provider_id=_STRICT_NETWORK_PROVIDER_ID,
            subject=f"e2e:{provider_resource_id}",
            expires_at=expires_at,
        )
    except RuntimeProviderAuthenticationError as error:
        pytest.fail(str(error))

    runtime_control = azents_runtime_control_container.get_wrapped_container()
    runtime_control.reload()
    host = runtime_control.attrs["NetworkSettings"]["Networks"][container_network.name][
        "IPAddress"
    ]
    if not isinstance(host, str) or not host:
        pytest.fail("Runtime Control has no address on the E2E container network")
    state_dir = tmp_path_factory.mktemp("strict-network-control-plane")
    evidence_path = state_dir / "evidence.jsonl"
    log_path = state_dir / "simulator.log"
    command = [
        sys.executable,
        str(
            REPOSITORY_ROOT
            / "testenv/azents/e2e/src/support/strict_network_control_plane.py"
        ),
        "--endpoint",
        f"{host}:8030",
        "--provider-id",
        _STRICT_NETWORK_PROVIDER_ID,
        "--network-name",
        container_network.name,
        "--evidence-path",
        str(evidence_path),
    ]
    environment = {
        **os.environ,
        "AZ_RUNTIME_PROVIDER_CREDENTIAL": credential,
    }
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_for_control_plane_provider_registered(
                process=process,
                evidence_path=evidence_path,
                log_path=log_path,
            )
            _wait_for_runtime_provider_contract(
                admin_server_url=azents_admin_server_url,
                access_token=system_bootstrap_evidence.access_token,
                provider_id=_STRICT_NETWORK_PROVIDER_ID,
            )
            _create_e2e_strict_network_infrastructure_profile(
                admin_server_url=azents_admin_server_url,
                access_token=system_bootstrap_evidence.access_token,
                provider_id=_STRICT_NETWORK_PROVIDER_ID,
            )
            yield StrictNetworkControlPlaneFixture(
                provider_id=_STRICT_NETWORK_PROVIDER_ID,
                evidence_path=evidence_path,
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def _provider_resource_id(
    *,
    admin_server_url: str,
    access_token: str,
    provider_id: str,
) -> str:
    """Wait for one bootstrapped durable Provider resource ID."""
    deadline = time.monotonic() + 60
    last_error = ""
    while time.monotonic() < deadline:
        response = requests.get(
            f"{admin_server_url}/runtime-provider/v1/providers",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if response.status_code != 200:
            last_error = (
                f"Runtime Provider inventory returned HTTP {response.status_code}"
            )
            time.sleep(0.5)
            continue
        payload = _JSON_OBJECT_ADAPTER.validate_python(response.json())
        items = _JSON_OBJECT_LIST_ADAPTER.validate_python(payload.get("items"))
        matches = [item for item in items if item.get("provider_id") == provider_id]
        if len(matches) == 1 and isinstance(matches[0].get("id"), str):
            return cast(str, matches[0]["id"])
        last_error = f"inventory contained {len(matches)} matching Providers"
        time.sleep(0.5)
    pytest.fail(
        f"Runtime Provider bootstrap did not create {provider_id}: {last_error}"
    )


def _wait_for_control_plane_provider_registered(
    *,
    process: subprocess.Popen[str],
    evidence_path: Path,
    log_path: Path,
) -> None:
    """Wait for the secret-free Provider registration evidence."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            pytest.fail(
                "strict-network control-plane simulator exited with "
                f"{return_code}: {log_path.read_text(encoding='utf-8')[-4000:]}"
            )
        evidence = load_control_plane_evidence(evidence_path)
        if any(item.event == "provider_registered" for item in evidence):
            return
        time.sleep(0.5)
    pytest.fail("strict-network control-plane simulator did not register")


def _create_e2e_strict_network_infrastructure_profile(
    *,
    admin_server_url: str,
    access_token: str,
    provider_id: str,
) -> None:
    """Create one v3 boundary Profile for deterministic strict-mode journeys."""
    response = requests.post(
        f"{admin_server_url}/runtime-provider/v1/providers/{provider_id}/pod-profiles",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "display_name": "E2E Strict Kubernetes Boundary",
            "description": (
                "Control-plane-only Kubernetes v3 Profile for deterministic E2E."
            ),
            "lifecycle": "active",
            "spec": {
                "profile_kind": "kubernetes_pod",
                "contract_family": "kubernetes.pod-profile",
                "schema_version": 3,
                "runner_resources": {
                    "cpu_request_millicores": None,
                    "cpu_limit_millicores": None,
                    "memory_request_bytes": None,
                    "memory_limit_bytes": None,
                },
                "workspace_volume": {
                    "storage_class_name": "control-plane-only",
                    "storage_request_bytes": 1,
                },
                "network_access": {
                    "mode": "direct",
                    "allowed_cidrs": ["0.0.0.0/0"],
                    "denied_cidrs": [],
                },
                "service_account_name": None,
                "scheduling": {"node_selector": {}, "tolerations": []},
                "dind": None,
            },
        },
        timeout=10,
    )
    if response.status_code != 201:
        pytest.fail(
            "failed to create strict-network infrastructure Profile: "
            f"HTTP {response.status_code}: {response.text}"
        )
    payload = _JSON_OBJECT_ADAPTER.validate_python(response.json())
    if payload.get("compatible") is not True:
        pytest.fail(
            "strict-network infrastructure Profile is not compatible: "
            f"{payload.get('compatibility_reason_code')!r}"
        )


@pytest.fixture(scope="session")
def mock_openai_url(mock_openai_container: DockerContainer) -> str:
    host = mock_openai_container.get_container_host_ip()
    port = mock_openai_container.get_exposed_port(8080)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def openai_proxy_url(openai_proxy_container: DockerContainer) -> str:
    """Return the host-visible deterministic OpenAI proxy URL."""
    host = openai_proxy_container.get_container_host_ip()
    port = openai_proxy_container.get_exposed_port(8081)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def azents_public_server_url(
    azents_public_server_container: DockerContainer,
) -> str:
    """azents Public API server URL."""
    host = azents_public_server_container.get_container_host_ip()
    port = azents_public_server_container.get_exposed_port(8010)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def azents_admin_server_url(
    azents_admin_server_container: DockerContainer,
) -> str:
    """azents Admin API server URL."""
    host = azents_admin_server_container.get_container_host_ip()
    port = azents_admin_server_container.get_exposed_port(8011)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def system_bootstrap_evidence(
    azents_public_server_container: DockerContainer,
    azents_admin_server_container: DockerContainer,
    azents_admin_server_url: str,
    system_bootstrap_setup_token: str,
) -> SystemBootstrapEvidence:
    """Bootstrap the initial administrator and retain diagnostic evidence."""
    status_response = requests.get(
        f"{azents_admin_server_url}/system/v1/bootstrap/status",
        timeout=5,
    )
    if status_response.status_code != 200:
        admin_logs = _read_container_logs(azents_admin_server_container)
        pytest.fail(
            f"bootstrap status failed with HTTP {status_response.status_code}\n"
            f"Admin API logs:\n{admin_logs[-12000:]}"
        )
    initial_available = status_response.json().get("available") is True

    invalid_response = requests.post(
        f"{azents_admin_server_url}/system/v1/bootstrap/first-admin",
        headers={"X-Azents-Setup-Token": f"invalid-{random_secret(8)}"},
        json={
            "email": "invalid-bootstrap@example.com",
            "password": "InvalidBootstrap123!",
        },
        timeout=10,
    )

    email = f"system-admin-{random_secret(4)}@example.com"
    request_body = {"email": email, "password": "SystemAdmin123!"}

    def attempt_bootstrap(_: int) -> requests.Response:
        return requests.post(
            f"{azents_admin_server_url}/system/v1/bootstrap/first-admin",
            headers={"X-Azents-Setup-Token": system_bootstrap_setup_token},
            json=request_body,
            timeout=15,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(attempt_bootstrap, range(2)))

    statuses = sorted(response.status_code for response in responses)
    if statuses != [201, 403]:
        pytest.fail(f"concurrent bootstrap returned unexpected statuses: {statuses}")
    success_response = next(
        response for response in responses if response.status_code == 201
    )
    success_payload = success_response.json()
    access_token = success_payload.get("access_token")
    refresh_token = success_payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        pytest.fail("successful bootstrap did not return a complete session")

    final_status_response = requests.get(
        f"{azents_admin_server_url}/system/v1/bootstrap/status",
        timeout=5,
    )
    if final_status_response.status_code != 200:
        pytest.fail(
            "post-bootstrap status failed with HTTP "
            f"{final_status_response.status_code}"
        )
    final_available = final_status_response.json().get("available") is True

    for container in (
        azents_public_server_container,
        azents_admin_server_container,
    ):
        stdout, stderr = container.get_logs()
        logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        if system_bootstrap_setup_token in logs:
            pytest.fail("configured bootstrap token appeared in server logs")

    return SystemBootstrapEvidence(
        access_token=access_token,
        refresh_token=refresh_token,
        email=email,
        initial_available=initial_available,
        invalid_attempt_status=invalid_response.status_code,
        concurrent_attempt_statuses=(statuses[0], statuses[1]),
        final_available=final_available,
    )


@pytest.fixture(scope="session")
def runtime_provider_resource_id(
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> str:
    """Return the durable ID of the bootstrapped E2E Docker Provider."""
    authorization = {
        "Authorization": f"Bearer {system_bootstrap_evidence.access_token}"
    }
    providers_response = requests.get(
        f"{azents_admin_server_url}/runtime-provider/v1/providers",
        headers=authorization,
        timeout=10,
    )
    if providers_response.status_code != 200:
        pytest.fail(
            "Runtime Provider inventory request failed with HTTP "
            f"{providers_response.status_code}"
        )
    providers_payload = _JSON_OBJECT_ADAPTER.validate_python(providers_response.json())
    provider_items = _JSON_OBJECT_LIST_ADAPTER.validate_python(
        providers_payload.get("items")
    )
    matching_providers = [
        item
        for item in provider_items
        if item.get("provider_id") == _RUNTIME_PROVIDER_ID
    ]
    if len(matching_providers) != 1:
        pytest.fail(
            "Runtime Provider bootstrap did not create exactly one "
            f"{_RUNTIME_PROVIDER_ID} Provider"
        )
    provider_id = matching_providers[0].get("id")
    if not isinstance(provider_id, str):
        pytest.fail("Runtime Provider inventory item did not contain an ID")
    return provider_id


@pytest.fixture(scope="session")
def runtime_provider_credential(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    runtime_provider_resource_id: str,
) -> str:
    """Enroll the E2E Docker Provider through the supported HTTP APIs."""
    expires_at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=5)
    try:
        credential = issue_runtime_provider_credential(
            admin_server_url=azents_admin_server_url,
            public_server_url=azents_public_server_url,
            admin_access_token=system_bootstrap_evidence.access_token,
            provider_id=_RUNTIME_PROVIDER_ID,
            subject=f"e2e:{runtime_provider_resource_id}",
            expires_at=expires_at,
        )
    except RuntimeProviderAuthenticationError as error:
        pytest.fail(str(error))
    return _RedactedSecret(credential)


# =============================================================================
# Web and Browser E2E
# =============================================================================


def _wait_for_web_ready(
    container: DockerContainer,
    *,
    port: int,
    path: str,
    name: str,
) -> None:
    """Wait until a web container serves a non-error response."""
    host = container.get_container_host_ip()
    exposed_port = container.get_exposed_port(port)
    url = f"http://{host}:{exposed_port}{path}"
    for _ in range(60):
        if container.get_wrapped_container().status == "exited":
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{name} exited\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        try:
            response = requests.get(url, timeout=2, allow_redirects=False)
            if response.status_code < 500:
                return
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
    stdout, stderr = container.get_logs()
    pytest.fail(
        f"{name} did not start in time\n\n"
        f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
    )


@pytest.fixture(scope="session")
def azents_main_web_container(
    container_network: Network,
    azents_web_image: str,
    azents_public_server_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Run Main Web with the Admin Web gateway URL configured."""
    del azents_public_server_container
    container = (
        DockerContainer(
            image=azents_web_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-web-{random_secret(4)}")
        .with_network(container_network)
        .with_network_aliases("azents-web")
        .with_env("PUBLIC_API_URL", _MAIN_WEB_BROWSER_URL)
        .with_env("INTERNAL_API_URL", "http://azents-public-server:8010")
        .with_env("ADMIN_WEB_URL", _ADMIN_WEB_GATEWAY_URL)
        .with_exposed_ports(3000)
    )
    with container:
        _wait_for_web_ready(
            container,
            port=3000,
            path="/login",
            name="azents-web",
        )
        yield container
        _log_server_output(container, "azents-web")


@pytest.fixture(scope="session")
def azents_admin_web_container(
    container_network: Network,
    azents_admin_web_image: str,
    azents_public_server_container: DockerContainer,
    azents_admin_server_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Run Admin Web on a dedicated internal host."""
    del azents_public_server_container, azents_admin_server_container
    container = (
        DockerContainer(
            image=azents_admin_web_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-admin-web-{random_secret(4)}")
        .with_network(container_network)
        .with_network_aliases("azents-admin-web")
        .with_env("PUBLIC_BASE_URL", _ADMIN_WEB_BROWSER_URL)
        .with_env("INTERNAL_PUBLIC_API_URL", "http://azents-public-server:8010")
        .with_env("INTERNAL_ADMIN_API_URL", "http://azents-admin-server:8011")
        .with_env("PUBLIC_WEB_URL", _MAIN_WEB_BROWSER_URL)
        .with_exposed_ports(3000)
    )
    with container:
        _wait_for_web_ready(
            container,
            port=3000,
            path="/login",
            name="azents-admin-web",
        )
        yield container
        _log_server_output(container, "azents-admin-web")


@pytest.fixture(scope="session")
def azents_admin_web_path_container(
    container_network: Network,
    azents_admin_web_image: str,
    azents_public_server_container: DockerContainer,
    azents_admin_server_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Run Admin Web behind a path-stripping gateway profile."""
    del azents_public_server_container, azents_admin_server_container
    container = (
        DockerContainer(
            image=azents_admin_web_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-admin-web-path-{random_secret(4)}")
        .with_network(container_network)
        .with_network_aliases("azents-admin-web-path")
        .with_env("PUBLIC_BASE_URL", _ADMIN_WEB_GATEWAY_URL)
        .with_env("INTERNAL_PUBLIC_API_URL", "http://azents-public-server:8010")
        .with_env("INTERNAL_ADMIN_API_URL", "http://azents-admin-server:8011")
        .with_env("PUBLIC_WEB_URL", _MAIN_WEB_BROWSER_URL)
        .with_exposed_ports(3000)
    )
    with container:
        _wait_for_web_ready(
            container,
            port=3000,
            path="/login",
            name="azents-admin-web-path",
        )
        yield container
        _log_server_output(container, "azents-admin-web-path")


@pytest.fixture(scope="session")
def azents_admin_gateway_container(
    container_network: Network,
    azents_main_web_container: DockerContainer,
    azents_admin_web_container: DockerContainer,
    azents_admin_web_path_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Expose Main and Admin Web profiles through a TLS gateway."""
    del (
        azents_main_web_container,
        azents_admin_web_container,
        azents_admin_web_path_container,
    )
    config = """
server {
    listen 8443 ssl;
    ssl_certificate /etc/nginx/tls/tls.crt;
    ssl_certificate_key /etc/nginx/tls/tls.key;

    location /chat/ {
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_pass http://azents-public-server:8010;
    }

    location / {
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://azents-web:3000;
    }
}

server {
    listen 8444 ssl;
    ssl_certificate /etc/nginx/tls/tls.crt;
    ssl_certificate_key /etc/nginx/tls/tls.key;

    location = /console {
        return 308 /console/;
    }

    location /console/ {
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://azents-admin-web-path:3000/;
    }

    location /_next/ {
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://azents-admin-web-path:3000;
    }
}

server {
    listen 8445 ssl;
    ssl_certificate /etc/nginx/tls/tls.crt;
    ssl_certificate_key /etc/nginx/tls/tls.key;

    location / {
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://azents-admin-web:3000;
    }
}
""".strip()
    with tempfile.TemporaryDirectory(prefix="azents-web-gateway-") as temp_dir:
        temp_path = Path(temp_dir)
        config_path = temp_path / "default.conf"
        certificate_path = temp_path / "tls.crt"
        key_path = temp_path / "tls.key"
        config_path.write_text(config, encoding="utf-8")
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-nodes",
                "-newkey",
                "rsa:2048",
                "-keyout",
                str(key_path),
                "-out",
                str(certificate_path),
                "-days",
                "1",
                "-subj",
                "/CN=azents-web-gateway",
                "-addext",
                "subjectAltName=DNS:azents-web-gateway",
            ],
            check=True,
            capture_output=True,
        )
        container = (
            DockerContainer(
                image="nginx:1.29-alpine",
                docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
            )
            .with_name(f"azents-web-gateway-{random_secret(4)}")
            .with_network(container_network)
            .with_network_aliases("azents-web-gateway")
            .with_volume_mapping(
                str(config_path),
                "/etc/nginx/conf.d/default.conf",
                "ro",
            )
            .with_volume_mapping(str(certificate_path), "/etc/nginx/tls/tls.crt", "ro")
            .with_volume_mapping(str(key_path), "/etc/nginx/tls/tls.key", "ro")
            .with_exposed_ports(8443, 8444, 8445)
        )
        with container:
            host = container.get_container_host_ip()
            port = container.get_exposed_port(8443)
            for _ in range(30):
                try:
                    response = requests.get(
                        f"https://{host}:{port}/login",
                        timeout=2,
                        verify=False,
                    )
                    if response.status_code < 500:
                        break
                except requests.exceptions.RequestException:
                    pass
                time.sleep(1)
            else:
                pytest.fail("azents web TLS gateway did not start in time")
            yield container
            _log_server_output(container, "azents-web-gateway")


@pytest.fixture(scope="session")
def selenium_container(
    container_network: Network,
    azents_main_web_container: DockerContainer,
    azents_admin_web_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """Run a remote Chromium browser on the E2E container network."""
    del azents_main_web_container, azents_admin_web_container
    container = (
        DockerContainer(
            image=_SELENIUM_IMAGE,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-selenium-{random_secret(4)}")
        .with_network(container_network)
        .with_env("SE_NODE_SESSION_TIMEOUT", "120")
        .with_exposed_ports(4444)
        .with_kwargs(shm_size="2g")
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(4444)
        status_url = f"http://{host}:{port}/status"
        for _ in range(60):
            try:
                payload = cast(
                    dict[str, object],
                    requests.get(status_url, timeout=2).json(),
                )
                value = payload.get("value")
                if isinstance(value, dict):
                    status = cast(dict[str, object], value)
                    if status.get("ready") is True:
                        break
            except requests.exceptions.RequestException:
                pass
            except ValueError:
                pass
            time.sleep(1)
        else:
            pytest.fail("Selenium did not become ready")
        yield container
        _log_server_output(container, "selenium")


@pytest.fixture(scope="function")
def browser_driver(
    selenium_container: DockerContainer,
    request: pytest.FixtureRequest,
) -> Generator[WebDriver, None, None]:
    """Create an isolated headless Chromium session."""
    host = selenium_container.get_container_host_ip()
    port = selenium_container.get_exposed_port(4444)
    options = ChromeOptions()
    options.accept_insecure_certs = True
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    driver = webdriver.Remote(
        command_executor=f"http://{host}:{port}",
        options=options,
    )
    try:
        yield driver
    finally:
        node = cast(pytest.Item, cast(Any, request).node)
        report = node.stash.get(_BROWSER_CALL_REPORT, None)
        artifact_root = os.environ.get("AZENTS_E2E_ARTIFACT_DIR")
        if report is not None and report.failed and artifact_root:
            _capture_browser_failure(
                driver,
                artifact_root=Path(artifact_root),
                node_id=node.nodeid,
            )
        driver.quit()


def _capture_browser_failure(
    driver: WebDriver,
    *,
    artifact_root: Path,
    node_id: str,
) -> None:
    """Capture screenshot and HTML evidence for one failed browser test."""
    browser_root = artifact_root / "browser"
    try:
        browser_root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        sys.stderr.write(f"Failed to create browser artifact directory: {error}\n")
        return
    artifact_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", node_id).strip("-")[:180]

    try:
        (browser_root / f"{artifact_name}.png").write_bytes(
            driver.get_screenshot_as_png()
        )
    except (OSError, WebDriverException) as error:
        _write_browser_capture_error(
            browser_root / f"{artifact_name}-screenshot-error.txt",
            error,
        )

    try:
        (browser_root / f"{artifact_name}.html").write_text(
            driver.page_source,
            encoding="utf-8",
        )
    except (OSError, WebDriverException) as error:
        _write_browser_capture_error(
            browser_root / f"{artifact_name}-html-error.txt",
            error,
        )


def _write_browser_capture_error(
    path: Path,
    error: OSError | WebDriverException,
) -> None:
    """Record a browser evidence failure without masking the original test failure."""
    try:
        path.write_text(str(error), encoding="utf-8")
    except OSError as write_error:
        sys.stderr.write(f"Failed to write browser capture error: {write_error}\n")


@pytest.fixture(scope="session")
def azents_main_web_url(azents_admin_gateway_container: DockerContainer) -> str:
    """Return the Main Web URL reachable from the remote browser."""
    return _MAIN_WEB_BROWSER_URL


@pytest.fixture(scope="session")
def azents_admin_web_url(azents_admin_gateway_container: DockerContainer) -> str:
    """Return the dedicated-host Admin Web URL reachable from the browser."""
    return _ADMIN_WEB_BROWSER_URL


@pytest.fixture(scope="session")
def azents_admin_web_gateway_url(
    azents_admin_gateway_container: DockerContainer,
) -> str:
    """Return the path-prefix Admin Web URL reachable from the browser."""
    return _ADMIN_WEB_GATEWAY_URL


# =============================================================================
# API Clients
# =============================================================================


@pytest.fixture(scope="function")
def admin_api_client(
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
) -> azentsadminclient.ApiClient:
    """Azents Admin API client authenticated as the bootstrapped administrator."""
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=system_bootstrap_evidence.access_token,
        )
    )


@pytest.fixture(scope="function")
def public_api_client(
    azents_public_server_url: str,
) -> azentspublicclient.ApiClient:
    """Azents Public API client."""
    return azentspublicclient.ApiClient(
        configuration=azentspublicclient.Configuration(host=azents_public_server_url)
    )
