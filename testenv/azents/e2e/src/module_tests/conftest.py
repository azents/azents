"""Local dependency fixtures for module tests."""

import secrets
from collections.abc import Generator

import boto3
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from types_boto3_s3.client import S3Client

_DOCKER_CLIENT_TIMEOUT_SECONDS = 300


def _random_secret(length: int = 32) -> str:
    """Return an isolated hexadecimal fixture secret."""
    return secrets.token_hex(length)


@pytest.fixture(scope="session")
def container_network() -> Generator[Network, None, None]:
    """Provide an isolated network for local module dependencies."""
    with Network() as network:
        yield network


@pytest.fixture(scope="session")
def s3_credentials() -> tuple[str, str]:
    """Return isolated RustFS credentials."""
    return _random_secret(16), _random_secret(32)


@pytest.fixture(scope="session")
def rustfs_container(
    s3_credentials: tuple[str, str],
    container_network: Network,
) -> Generator[DockerContainer, None, None]:
    """Run RustFS without building or starting an Azents application image."""
    access_key, secret_key = s3_credentials
    with (
        DockerContainer(
            "rustfs/rustfs:1.0.0-alpha.90",
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
def rustfs_access_key(s3_credentials: tuple[str, str]) -> str:
    """Return the RustFS access key."""
    return s3_credentials[0]


@pytest.fixture(scope="session")
def rustfs_secret_key(s3_credentials: tuple[str, str]) -> str:
    """Return the RustFS secret key."""
    return s3_credentials[1]


@pytest.fixture(scope="session")
def s3_bucket_name(
    rustfs_container: DockerContainer,
    rustfs_access_key: str,
    rustfs_secret_key: str,
) -> Generator[str, None, None]:
    """Create an isolated bucket in the module test RustFS instance."""
    bucket_name = f"azents-module-{_random_secret(8)}"
    host = rustfs_container.get_container_host_ip()
    port = rustfs_container.get_exposed_port(9000)
    s3_client: S3Client = boto3.client(  # boto3.client overload returns Unknown
        "s3",
        endpoint_url=f"http://{host}:{port}",
        aws_access_key_id=rustfs_access_key,
        aws_secret_access_key=rustfs_secret_key,
    )
    s3_client.create_bucket(Bucket=bucket_name)
    yield bucket_name
