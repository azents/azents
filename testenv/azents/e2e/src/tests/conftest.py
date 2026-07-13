"""E2E test fixtures."""

import base64
import os
import re
import secrets
import socket
import sys
import tempfile
import time
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import azentsadminclient
import azentspublicclient
import boto3
import docker as docker_py
import pytest
import requests
from azcommon.testing.images import get_docker_hub_image
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from python_on_whales import docker as pow_docker
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer
from types_boto3_s3.client import S3Client

from support.consts import REPOSITORY_ROOT

_AIMOCK_FIXTURE_DIR = REPOSITORY_ROOT / "testenv/azents/e2e/src/support/aimock_fixtures"
_DOCKER_CLIENT_TIMEOUT_SECONDS = 300
_RUNTIME_PROVIDER_ID = "system-docker"
_RUNTIME_CONTAINER_NAME_RE = re.compile(r"^azents-runtime-[0-9a-f]{32}$")
_ECR_CACHE_PREFIX = "azents-production-server"
_DOCKER_BUILDER_ENV = "AZENTS_E2E_DOCKER_BUILDER"
_LOCAL_DOCKER_CACHE_ROOT_ENV = "AZENTS_E2E_DOCKER_CACHE_ROOT"
_LOCAL_DOCKER_CACHE_WRITE_ROOT_ENV = "AZENTS_E2E_DOCKER_CACHE_WRITE_ROOT"


def random_secret(length: int = 32) -> str:
    """testt t t create."""
    return secrets.token_hex(length)


def random_fernet_key() -> str:
    """testt t Fernet key create (URL-safe base64 t 32t)."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


@pytest.fixture(scope="session")
def auth_jwt_secret_key() -> str:
    """Return one JWT signing key shared by all server processes."""
    return random_secret(32)


# =============================================================================
# Network
# =============================================================================


@pytest.fixture(scope="session")
def container_network() -> Generator[Network, None, None]:
    """t containert t Docker t."""
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
    postgres_image = get_docker_hub_image("postgres:18")
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
    """testt S3 t t create."""
    return random_secret(16), random_secret(32)


@pytest.fixture(scope="session")
def valkey_container(
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Valkey (Redis t) container."""
    valkey_image = get_docker_hub_image("valkey/valkey:9-alpine")
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
    """RustFS (S3 t) container."""
    access_key, secret_key = s3_credentials
    rustfs_image = get_docker_hub_image("rustfs/rustfs:1.0.0-alpha.90")
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
    """AIMock t OpenAI Responses API mock container."""
    with (
        DockerContainer(
            "ghcr.io/copilotkit/aimock:1.24.1",
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
    """S3 t create."""
    bucket_name = f"azents-dev-{random_secret(8)}"

    rustfs_host = rustfs_container.get_container_host_ip()
    rustfs_port = rustfs_container.get_exposed_port(9000)

    s3_client: S3Client = boto3.client(  # pyright: ignore[reportUnknownMemberType] # boto3.clientt overload return t t Unknown
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


@pytest.fixture(scope="session")
def azents_server_image() -> str:
    """azents server Docker t t."""
    if image := os.environ.get("AZENTS_E2E_SERVER_IMAGE"):
        return image

    image_tag = f"azents-e2e:{random_secret(8)}"
    _build_e2e_image(
        image_tag=image_tag,
        dockerfile=REPOSITORY_ROOT / "azents.Dockerfile",
        cache_repository="azents-server",
    )
    return image_tag


@pytest.fixture(scope="session")
def azents_runtime_runner_image() -> str:
    """azents Runtime Runner Docker t t."""
    if image := os.environ.get("AZENTS_E2E_RUNTIME_RUNNER_IMAGE"):
        return image

    image_tag = f"azents-runtime-runner-e2e:{random_secret(8)}"
    _build_e2e_image(
        image_tag=image_tag,
        dockerfile=REPOSITORY_ROOT / "python/apps/azents-runtime-runner/Dockerfile",
        cache_repository="azents-runtime-runner",
    )
    return image_tag


@pytest.fixture(scope="session")
def azents_runtime_provider_docker_image() -> str:
    """azents Docker Runtime Provider Docker t t."""
    if image := os.environ.get("AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE"):
        return image

    image_tag = f"azents-runtime-provider-docker-e2e:{random_secret(8)}"
    _build_e2e_image(
        image_tag=image_tag,
        dockerfile=REPOSITORY_ROOT
        / "python/apps/azents-runtime-provider-docker/Dockerfile",
        cache_repository="azents-runtime-provider-docker",
    )
    return image_tag


def _build_e2e_image(
    *,
    image_tag: str,
    dockerfile: Path,
    cache_repository: str,
) -> None:
    """E2E container image t registry/local cache t t t."""
    cache_from: list[dict[str, str]] = []
    cache_to: dict[str, str] | None = None
    builder = os.environ.get(_DOCKER_BUILDER_ENV)

    ecr_registry = os.environ.get("ECR_REGISTRY")
    if ecr_registry:
        cache_uri = f"{ecr_registry}/{_ECR_CACHE_PREFIX}/{cache_repository}:cache"
        cache_from.append({"type": "registry", "ref": cache_uri})
        cache_to = {"type": "registry", "ref": cache_uri, "mode": "min"}
    elif builder:
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

    pow_docker.build(
        context_path=str(REPOSITORY_ROOT),
        file=str(dockerfile),
        tags=[image_tag],
        builder=builder,
        cache_from=cache_from or None,
        cache_to=cache_to,
        load=True,
    )


@pytest.fixture(scope="session")
def credential_encryption_key() -> str:
    """testt LLM t t t key (Fernet key)."""
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
    mock_openai_container: DockerContainer,
) -> DockerContainer:
    """azents server container t settings."""
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
        .with_env("AZ_REDIS_URL", "redis://valkey:6379")
        .with_env("AZ_WORKSPACE_S3_BUCKET", s3_bucket_name)
        .with_env("AZ_WORKSPACE_S3_PREFIX", "v1")
        .with_env("AZ_WORKSPACE_S3_ENDPOINT_URL", "http://rustfs:9000")
        .with_env("AZ_LLM_CATALOG_SYNC_ENABLED", "true")
        .with_env("AZ_LLM_CATALOG_STARTUP_SYNC_ENABLED", "true")
        .with_env("AZ_LLM_CATALOG_SOURCE_MODE", "fixture")
        .with_env("AZ_OPENAI_BASE_URL", "http://mock-openai:8080/v1")
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
    )


def _wait_for_server_ready(
    container: DockerContainer,
    port: int,
    server_name: str,
) -> str:
    """servert preparet t pendingt base URLt return."""
    host = container.get_container_host_ip()
    exposed_port = container.get_exposed_port(port)
    base_url = f"http://{host}:{exposed_port}"

    max_retries = 30
    for i in range(max_retries):
        if container.get_wrapped_container().status == "exited":
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} exited\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        try:
            response = requests.get(f"{base_url}/health/v1/readiness", timeout=2)
            if response.status_code == 200:
                break
        except requests.exceptions.RequestException:
            pass

        if i == max_retries - 1:
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        time.sleep(1)

    return base_url


def _wait_for_tcp_ready(
    container: DockerContainer,
    port: int,
    server_name: str,
) -> None:
    """TCP t t t pendingt."""
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


def _log_server_output(container: DockerContainer, server_name: str) -> None:
    """server t output."""
    try:
        stdout, stderr = container.get_logs()
        sys.stdout.write(f"\n\n=== {server_name} stdout ===\n{stdout.decode()}\n")
        sys.stdout.write(f"\n=== {server_name} stderr ===\n{stderr.decode()}\n")
    except Exception:
        pass  # containert t t t t


def _remove_agent_runtime_containers(network_name: str) -> None:
    """E2E t engine worker t t agent-runtime containert cleanupt."""
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
def azents_public_server_container(
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
    mock_openai_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """azents Public API server container (port 8010)."""
    base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-public-server-{random_secret(4)}")
        .with_network_aliases("azents-public-server")
        .with_exposed_ports(8010)
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
        mock_openai_container,
    )

    with container:
        _wait_for_server_ready(container, 8010, "azents-public-server")
        yield container
        _log_server_output(container, "azents-public-server")


@pytest.fixture(scope="session")
def azents_admin_server_container(
    container_network: Network,
    postgres_container: PostgresContainer,
    rustfs_container: DockerContainer,
    valkey_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
    s3_bucket_name: str,
    azents_server_image: str,
    azents_public_server_container: DockerContainer,  # public server t t
    auth_jwt_secret_key: str,
    credential_encryption_key: str,
    mock_openai_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """azents Admin API server container (port 8011)."""
    base_container = (
        DockerContainer(
            image=azents_server_image,
            docker_client_kw={"timeout": _DOCKER_CLIENT_TIMEOUT_SECONDS},
        )
        .with_name(f"azents-admin-server-{random_secret(4)}")
        .with_network_aliases("azents-admin-server")
        .with_command(["./bin/adminserver.sh"])
        .with_exposed_ports(8011)
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
        mock_openai_container,
    )

    with container:
        _wait_for_server_ready(container, 8011, "azents-admin-server")
        yield container
        _log_server_output(container, "azents-admin-server")


@pytest.fixture(scope="session")
def azents_engine_worker_container(
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
    mock_openai_container: DockerContainer,
) -> Generator[DockerContainer, None, None]:
    """WebSocket session runt processt azents engine worker container."""
    del azents_admin_server_container

    base_container = (
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
    container = _configure_azents_server_container(
        base_container,
        container_network,
        postgres_container,
        rustfs_access_key,
        rustfs_secret_key,
        s3_bucket_name,
        auth_jwt_secret_key,
        credential_encryption_key,
        mock_openai_container,
    )
    container = container.with_env("AZ_WORKER_HEALTH_PORT", "8012").with_env(
        "AZ_AGENT_HOME_DOCKER_NETWORK", container_network.name
    )

    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(8012)
        base_url = f"http://{host}:{port}"
        for _ in range(60):
            if container.get_wrapped_container().status == "exited":
                stdout, stderr = container.get_logs()
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
            stdout, stderr = container.get_logs()
            pytest.fail(
                "azents-engine-worker did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        try:
            yield container
        finally:
            _log_server_output(container, "azents-engine-worker")
            _remove_agent_runtime_containers(container_network.name)


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
    mock_openai_container: DockerContainer,
    azents_runtime_runner_image: str,
) -> Generator[DockerContainer, None, None]:
    """Runtime Control gRPC server container."""
    del azents_admin_server_container

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
        mock_openai_container,
    )
    container = (
        container.with_env("AZ_RUNTIME_CONTROL_PORT", "8030")
        .with_env("AZ_RUNTIME_CONTROL_INSTANCE_ID", "azents-e2e-runtime-control")
        .with_env("AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS", "1")
        .with_env("AZ_RUNTIME_CONTROL_LIFECYCLE_RETRY_DELAY_SECONDS", "1")
        .with_env("AZ_RUNTIME_CONTROL_START_TIMEOUT_SECONDS", "120")
        .with_env("AZ_RUNTIME_RUNNER_IMAGE", azents_runtime_runner_image)
        .with_env("AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT", "runtime-control:8030")
    )

    with container:
        _wait_for_tcp_ready(container, 8030, "azents-runtime-control")
        yield container
        _log_server_output(container, "azents-runtime-control")


@pytest.fixture(scope="session")
def azents_runtime_provider_docker_container(
    container_network: Network,
    azents_runtime_control_container: DockerContainer,
    azents_runtime_provider_docker_image: str,
) -> Generator[DockerContainer, None, None]:
    """Docker Runtime Provider container."""
    del azents_runtime_control_container

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
            .with_volume_mapping("/var/run/docker.sock", "/var/run/docker.sock", "rw")
            .with_volume_mapping(data_root, data_root, "rw")
            .with_env("AZ_RUNTIME_CONTROL_ENDPOINT", "runtime-control:8030")
            .with_env("AZ_RUNTIME_PROVIDER_ID", _RUNTIME_PROVIDER_ID)
            .with_env("AZ_RUNTIME_PROVIDER_DOCKER_NETWORK", container_network.name)
            .with_env("AZ_RUNTIME_PROVIDER_HOST_DATA_ROOT", data_root)
            .with_env("AZ_RUNTIME_PROVIDER_AUTH_CREDENTIAL_ID", _RUNTIME_PROVIDER_ID)
            .with_env("AZ_LOG_LEVEL", "INFO")
            .with_kwargs(user="root")
        )
        with container:
            _wait_for_runtime_provider_registered(
                container,
                provider_id=_RUNTIME_PROVIDER_ID,
            )
            yield container
            _log_server_output(container, "azents-runtime-provider-docker")


def _wait_for_runtime_provider_registered(
    container: DockerContainer,
    *,
    provider_id: str,
) -> None:
    """Runtime Provider register t t t pendingt."""
    deadline = time.monotonic() + 60
    last_logs = ""
    while time.monotonic() < deadline:
        if container.get_wrapped_container().status == "exited":
            stdout, stderr = container.get_logs()
            pytest.fail(
                "azents-runtime-provider-docker exited\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        stdout, stderr = container.get_logs()
        last_logs = stdout.decode(errors="replace") + stderr.decode(errors="replace")
        if "Runtime Provider registered" in last_logs:
            return
        time.sleep(1)
    pytest.fail(
        f"runtime provider {provider_id} did not register in time\n{last_logs[-4000:]}"
    )


@pytest.fixture(scope="session")
def mock_openai_url(mock_openai_container: DockerContainer) -> str:
    """test runner t t t mock OpenAI URL."""
    host = mock_openai_container.get_container_host_ip()
    port = mock_openai_container.get_exposed_port(8080)
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
def admin_access_token(
    azents_public_server_url: str,
    azents_admin_server_container: DockerContainer,
) -> str:
    """Create and promote the initial User for authenticated Admin API tests."""
    email = f"e2e-system-admin-{random_secret(4)}@example.com"
    password = "SystemAdmin123!"
    bootstrap_response = requests.post(
        f"{azents_public_server_url}/workspace/v1/bootstrap/first-owner",
        json={
            "email": email,
            "password": password,
            "owner_name": "E2E system administrator",
            "workspace_name": "E2E bootstrap",
            "workspace_handle": f"e2e-bootstrap-{random_secret(4)}",
            "locale": "en-US",
        },
        timeout=10,
    )
    if bootstrap_response.status_code != 201:
        pytest.fail(
            f"first-owner bootstrap failed with HTTP {bootstrap_response.status_code}"
        )

    cli_result = azents_admin_server_container.get_wrapped_container().exec_run(
        [
            "python",
            "src/cli/system_admin.py",
            "grant",
            "--email",
            email,
        ]
    )
    if cast(Any, cli_result).exit_code != 0:
        pytest.fail("system-admin CLI grant failed")

    login_response = requests.post(
        f"{azents_public_server_url}/auth/v1/login/password",
        json={"email": email, "password": password},
        timeout=10,
    )
    if login_response.status_code != 200:
        pytest.fail(
            f"initial Admin login failed with HTTP {login_response.status_code}"
        )
    access_token = login_response.json().get("access_token")
    if not isinstance(access_token, str):
        pytest.fail("initial Admin login returned no access token")
    return access_token


# =============================================================================
# API Clients
# =============================================================================


@pytest.fixture(scope="function")
def admin_api_client(
    azents_admin_server_url: str,
    admin_access_token: str,
) -> azentsadminclient.ApiClient:
    """Azents Admin API client authenticated as a system administrator."""
    return azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=admin_access_token,
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
