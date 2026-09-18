"""Runtime Web Gateway browser, transport, and authority E2E journeys."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import zlib
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

import azentsadminclient
import azentspublicclient
import pytest
import requests
from azentspublicclient.api.agent_v1_api import AgentV1Api
from azentspublicclient.api.llm_provider_integration_v1_api import (
    LLMProviderIntegrationV1Api,
)
from azentspublicclient.api.runtime_web_v1_api import RuntimeWebV1Api
from azentspublicclient.api.workspace_v1_api import WorkspaceV1Api
from azentspublicclient.exceptions import ApiException
from azentspublicclient.models.agent_create_request import AgentCreateRequest
from azentspublicclient.models.agent_model_selection_input import (
    AgentModelSelectionInput,
)
from azentspublicclient.models.agent_type import AgentType
from azentspublicclient.models.api_key_secrets import ApiKeySecrets
from azentspublicclient.models.create_workspace_request import CreateWorkspaceRequest
from azentspublicclient.models.llm_provider import LLMProvider
from azentspublicclient.models.llm_provider_integration_create_request import (
    LLMProviderIntegrationCreateRequest,
)
from azentspublicclient.models.runtime_web_create_request import RuntimeWebCreateRequest
from azentspublicclient.models.runtime_web_expected_revision_request import (
    RuntimeWebExpectedRevisionRequest,
)
from azentspublicclient.models.runtime_web_service_response import (
    RuntimeWebServiceResponse,
)
from azentspublicclient.models.secrets import Secrets
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer
from websockets.asyncio.client import connect as async_connect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect
from websockets.sync.connection import Connection
from websockets.typing import Origin

from support.runtime_profiles import create_workspace_runtime_profile
from support.system_bootstrap import SystemBootstrapEvidence
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    single_candidate_model_options,
    unique,
)
from tests.required.public.test_runtime_terminal import (
    _start_runtime,
    _TerminalSocket,
    _TerminalWorkspace,
    _wait_terminal_projection,
)


class _TlsEdgeFiles(NamedTuple):
    """Field-named result for ``_write_tls_edge_files``."""

    certificate_path: Path
    private_key_path: Path
    config_path: Path


_RUNTIME_PROVIDER_ID = "system-docker"
_RUNTIME_RUNNER_PYTHON = "/workspace/python/apps/azents-runtime-runner/.venv/bin/python"
_RUNTIME_WEB_PORT = 8765
_MAIN_ORIGIN = "https://web.runtime-e2e.test"
_BROKER_ORIGIN = "https://auth.services.runtime-e2e.test"
_SERVICE_SUFFIX = "services.runtime-e2e.test"
_SHARED_COOKIE_DOMAIN = "runtime-e2e.test"
_SEPARATE_COOKIE_DOMAIN = _SERVICE_SUFFIX
_TERMINAL_ORIGIN = "https://azents-web-gateway:8443"
_SIGNUP_PASSWORD = "TestPass123!"


def _bounded_workload_value(
    name: str,
    *,
    default: int,
    maximum: int,
) -> int:
    """Read one bounded positive E2E workload override."""
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer") from None
    if not 1 <= value <= maximum:
        raise RuntimeError(f"{name} must be between 1 and {maximum}")
    return value


_BROWSER_TRANSFER_BYTES = _bounded_workload_value(
    "AZENTS_E2E_RUNTIME_WEB_TRANSFER_BYTES",
    default=1024 * 1024,
    maximum=1024 * 1024 * 1024,
)
_BROWSER_ASSET_COUNT = _bounded_workload_value(
    "AZENTS_E2E_RUNTIME_WEB_ASSET_COUNT",
    default=8,
    maximum=2_000,
)
_BROWSER_SCRIPT_TIMEOUT_SECONDS = _bounded_workload_value(
    "AZENTS_E2E_RUNTIME_WEB_SCRIPT_TIMEOUT_SECONDS",
    default=120,
    maximum=7_200,
)
_REJECTED_REQUEST_CONTENT_LENGTH = _BROWSER_TRANSFER_BYTES
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _RuntimeWebWorkspace:
    """Product-created authority and browser identity for one journey."""

    token: str
    email: str
    handle: str
    agent_id: str
    session_id: str


class _RuntimeApplicationCommands:
    """Run fixture commands through short-lived Terminal attachments."""

    def __init__(
        self,
        *,
        public_api_client: azentspublicclient.ApiClient,
        workspace: _TerminalWorkspace,
        server_url: str,
    ) -> None:
        self.public_api_client = public_api_client
        self.workspace = workspace
        self.server_url = server_url
        self.last_output_sequence: int | None = None

    def command(self, command: str, marker: str) -> bytes:
        """Attach for one command so idle fixture work cannot become a slow consumer."""
        terminal = _TerminalSocket.connect(
            public_api_client=self.public_api_client,
            workspace=self.workspace,
            server_url=self.server_url,
            origin=_TERMINAL_ORIGIN,
            last_output_sequence=self.last_output_sequence,
        )
        try:
            return terminal.command(command, marker)
        finally:
            self.last_output_sequence = terminal.output_sequence
            terminal.close()
            terminal_id = terminal.accepted.terminal_id
            _wait_terminal_projection(
                public_api_client=self.public_api_client,
                workspace=self.workspace,
                predicate=lambda projection: (
                    projection.terminal is not None
                    and projection.terminal.terminal_id == terminal_id
                    and not projection.terminal.attached
                ),
                message="Runtime Web fixture Terminal did not detach after command",
            )


@dataclass(frozen=True)
class _RuntimeWebApplication:
    """Module-scoped Runtime application reused across isolated Gateway stacks."""

    workspace: _RuntimeWebWorkspace
    commands: _RuntimeApplicationCommands


@dataclass(frozen=True)
class _RuntimeWebAuthSurface:
    """Module-scoped stateless Web and API processes for one authentication mode."""

    public_api_url: str
    main_web_alias: str


@dataclass(frozen=True)
class _RuntimeWebStack:
    """Function-scoped Runtime Web browser topology."""

    main_origin: str
    public_api_url: str
    operations_url: str
    owner_control_operations_url: str
    accepting_control_operations_url: str
    capacity_backend: str
    edge_ip: str
    edge_host_url: str
    selenium_url: str


@dataclass(frozen=True)
class _RuntimeApplicationState:
    """Content-free fixture state used for authoritative synchronization."""

    upload_invocations: int
    active_sse: int
    sse_connections: int
    active_websockets: int
    websocket_connections: int


@dataclass(frozen=True, repr=False)
class _RuntimeWebStackFactory:
    """Create one mode-specific stack without exposing fixture secrets in failures."""

    network: Network
    postgres: PostgresContainer
    server_image: str
    owner_control: DockerContainer
    relay_operations_url: str
    auth_surfaces: dict[str, _RuntimeWebAuthSurface]
    diagnostic_containers: tuple[tuple[str, DockerContainer], ...]
    capacity_backend: str
    credential_encryption_key: str
    selenium_url: str

    def start(
        self,
        mode: str,
        *,
        maximum_active_exchanges: int,
        maximum_application_buffer_bytes: int,
        maintenance: bool,
        relay_path: bool,
    ) -> AbstractContextManager[_RuntimeWebStack]:
        """Create one function-scoped Runtime Web stack."""
        return _runtime_web_stack(
            mode=mode,
            maximum_active_exchanges=maximum_active_exchanges,
            maximum_application_buffer_bytes=maximum_application_buffer_bytes,
            maintenance=maintenance,
            relay_path=relay_path,
            network=self.network,
            postgres=self.postgres,
            server_image=self.server_image,
            owner_control=self.owner_control,
            relay_operations_url=self.relay_operations_url,
            auth_surface=self.auth_surfaces[mode],
            diagnostic_containers=self.diagnostic_containers,
            capacity_backend=self.capacity_backend,
            credential_encryption_key=self.credential_encryption_key,
            selenium_url=self.selenium_url,
        )


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _container_logs(container: DockerContainer) -> str:
    """Return combined bounded container logs."""
    stdout, stderr = container.get_logs()
    return (stdout + stderr).decode(errors="replace")[-12_000:]


def _log_runtime_web_container(
    *,
    name: str,
    container: DockerContainer,
) -> None:
    """Emit bounded diagnostics without replacing the active failure."""
    try:
        container_logs = _container_logs(container)
    except Exception as error:
        logger.warning(
            "Runtime Web E2E container logs for %s were unavailable: %s",
            name,
            type(error).__name__,
            extra={
                "container_name": name,
                "diagnostic_error": type(error).__name__,
            },
        )
        return
    logger.warning(
        "Runtime Web E2E container logs for %s:\n%s",
        name,
        container_logs,
        extra={
            "container_name": name,
            "container_logs": container_logs,
        },
    )


def _wait_for_log(container: DockerContainer, marker: str, *, name: str) -> None:
    """Wait for one explicit process readiness log."""
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        if wrapped.status == "exited":
            raise AssertionError(f"{name} exited:\n{_container_logs(container)}")
        if marker in _container_logs(container):
            return
        time.sleep(0.5)
    raise AssertionError(f"{name} did not become ready:\n{_container_logs(container)}")


def _wait_for_http(
    container: DockerContainer,
    *,
    port: int,
    path: str,
    name: str,
) -> None:
    """Wait for an exposed HTTP listener."""
    wrapped = container.get_wrapped_container()
    wrapped.reload()
    if wrapped.status == "exited":
        raise AssertionError(f"{name} exited:\n{_container_logs(container)}")
    host = container.get_container_host_ip()
    exposed = container.get_exposed_port(port)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        wrapped = container.get_wrapped_container()
        wrapped.reload()
        if wrapped.status == "exited":
            raise AssertionError(f"{name} exited:\n{_container_logs(container)}")
        try:
            response = requests.get(
                f"http://{host}:{exposed}{path}",
                timeout=2,
                allow_redirects=False,
            )
            if response.status_code < 500:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise AssertionError(f"{name} did not become ready:\n{_container_logs(container)}")


def _configure_server_database(
    container: DockerContainer,
    *,
    network: Network,
    postgres: PostgresContainer,
    credential_encryption_key: str,
) -> DockerContainer:
    """Configure one server-image process against the shared E2E stores."""
    return (
        container.with_network(network)
        .with_env("AZ_RUNTIME_ENV", "local")
        .with_env("AZ_RDB_HOST", "rdb")
        .with_env("AZ_RDB_PORT", "5432")
        .with_env("AZ_RDB_USER", postgres.username)
        .with_env("AZ_RDB_PASSWORD", postgres.password)
        .with_env("AZ_RDB_DB_NAME", postgres.dbname)
        .with_env("AZ_REDIS_URL", "redis://valkey:6379")
        .with_env("AZ_CREDENTIAL_ENCRYPTION_KEY", credential_encryption_key)
    )


def _runtime_control_relay_container(
    *,
    image: str,
    network: Network,
    postgres: PostgresContainer,
    credential_encryption_key: str,
    runner_image: str,
    s3_bucket_name: str,
    s3_access_key: str,
    s3_secret_key: str,
    capacity_backend: str,
) -> DockerContainer:
    """Create a second Control replica used only as the Gateway relay ingress."""
    base = (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-control-relay-{unique()}")
        .with_network_aliases("runtime-control-relay")
        .with_command(["python", "src/cli/runtime_control_server.py"])
        .with_exposed_ports(8031, 8033, 8034)
    )
    return (
        _configure_server_database(
            base,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
        )
        .with_env("AZ_RUNTIME_CONTROL_PORT", "8031")
        .with_env("AZ_RUNTIME_CONTROL_ALLOW_INSECURE", "true")
        .with_env("AZ_RUNTIME_CONTROL_WEB_TRANSPORT_ENABLED", "true")
        .with_env("AZ_RUNTIME_CONTROL_TRUSTED_PORT", "8033")
        .with_env(
            "AZ_RUNTIME_CONTROL_TRUSTED_ADVERTISE_ADDRESS",
            "runtime-control-relay:8033",
        )
        .with_env("AZ_RUNTIME_CONTROL_WEB_METRICS_PORT", "8034")
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_BACKEND", capacity_backend)
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_ACTIVE_STREAMS", "128")
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_SSE_STREAMS", "32")
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_WEBSOCKET_STREAMS",
            "32",
        )
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_PENDING_OPENS", "128")
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_MAXIMUM_BUFFER_BYTES", "67108864")
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_CAPACITY_INBOUND_BYTES_PER_SECOND",
            "268435456",
        )
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_CAPACITY_OUTBOUND_BYTES_PER_SECOND",
            "268435456",
        )
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_BURST_BYTES", "67108864")
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_NAMESPACE",
            "azents:e2e:runtime-web:capacity",
        )
        .with_env("AZ_RUNTIME_CONTROL_WEB_CAPACITY_REDIS_TTL_SECONDS", "30")
        .with_env("AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_SESSIONS", "128")
        .with_env("AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_ACTIVE_STREAMS", "1024")
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_APPLICATION_BUFFER_BYTES",
            "536870912",
        )
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_CONTROL_BUFFER_BYTES",
            "67108864",
        )
        .with_env("AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_QUEUED_ENVELOPES", "4096")
        .with_env("AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_PENDING_TASKS", "2048")
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_EVENT_LOOP_LAG_MILLISECONDS",
            "250",
        )
        .with_env(
            "AZ_RUNTIME_CONTROL_WEB_HARD_MAXIMUM_RESIDENT_MEMORY_BYTES",
            "1073741824",
        )
        .with_env("AZ_RUNTIME_CONTROL_INSTANCE_ID", "azents-e2e-runtime-control-relay")
        .with_env("AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS", "60")
        .with_env("AZ_RUNTIME_CONTROL_WEB_ROUTE_LEASE_SECONDS", "10")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET", s3_bucket_name)
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_PREFIX", "v1")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL", "http://rustfs:9000")
        .with_env(
            "AZ_RUNTIME_CONTROL_WORKSPACE_S3_PUBLIC_ENDPOINT_URL",
            "http://rustfs:9000",
        )
        .with_env(
            "AZ_RUNTIME_CONTROL_WORKSPACE_S3_CORS_ORIGINS",
            _MAIN_ORIGIN,
        )
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ACCESS_KEY_ID", s3_access_key)
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_SECRET_ACCESS_KEY", s3_secret_key)
        .with_env("AZ_RUNTIME_RUNNER_IMAGE", runner_image)
        .with_env("AZ_RUNTIME_RUNNER_CONTROL_ENDPOINT", "runtime-control-relay:8031")
        .with_env("AZ_RUNTIME_RUNNER_TRANSFER_ENDPOINT", "runtime-control-relay:8031")
    )


def _runtime_web_gateway_container(
    *,
    image: str,
    network: Network,
    postgres: PostgresContainer,
    credential_encryption_key: str,
    mode: str,
    maximum_active_exchanges: int,
    maximum_application_buffer_bytes: int,
    maintenance: bool,
    control_endpoint: str,
) -> DockerContainer:
    """Create the enabled Gateway process for one authentication mode."""
    cookie_domain = (
        _SHARED_COOKIE_DOMAIN if mode == "shared_cookie" else _SEPARATE_COOKIE_DOMAIN
    )
    base = (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-web-gateway-{mode}-{unique()}")
        .with_network_aliases("runtime-web-gateway")
        .with_command(["./bin/runtime-web-gateway.sh"])
        .with_exposed_ports(8040, 8041)
    )
    return (
        _configure_server_database(
            base,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
        )
        .with_env("AZ_RUNTIME_WEB_GATEWAY_ENABLED", "true")
        .with_env("AZ_RUNTIME_WEB_GATEWAY_PORT", "8040")
        .with_env("AZ_RUNTIME_WEB_GATEWAY_MAINTENANCE", str(maintenance).lower())
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_REQUEST_BODY_BYTES",
            str(_BROWSER_TRANSFER_BYTES),
        )
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_MAXIMUM_ACTIVE_EXCHANGES",
            str(maximum_active_exchanges),
        )
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_MAXIMUM_APPLICATION_BUFFER_BYTES",
            str(maximum_application_buffer_bytes),
        )
        .with_env("AZ_RUNTIME_WEB_GATEWAY_AUTH_MODE", mode)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN", _MAIN_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_BROKER_ORIGIN", _BROKER_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX", _SERVICE_SUFFIX)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN", cookie_domain)
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_CONTROL_ENDPOINT",
            control_endpoint,
        )
        .with_env("AZ_RUNTIME_WEB_GATEWAY_CONTROL_ALLOW_INSECURE", "true")
    )


def _runtime_web_public_api_container(
    *,
    image: str,
    network: Network,
    postgres: PostgresContainer,
    credential_encryption_key: str,
    auth_jwt_secret_key: str,
    system_bootstrap_setup_token: str,
    mode: str,
    network_alias: str,
) -> DockerContainer:
    """Create the Public API process with the matching Gateway configuration."""
    cookie_domain = (
        _SHARED_COOKIE_DOMAIN if mode == "shared_cookie" else _SEPARATE_COOKIE_DOMAIN
    )
    base = (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-web-public-{mode}-{unique()}")
        .with_network_aliases(network_alias)
        .with_command(
            [
                "uvicorn",
                "apiserver:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8010",
                "--ws",
                "websockets-sansio",
            ]
        )
        .with_exposed_ports(8010)
    )
    return (
        _configure_server_database(
            base,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
        )
        .with_env("AZ_AUTH_JWT_SECRET_KEY", auth_jwt_secret_key)
        .with_env("AZ_SYSTEM_BOOTSTRAP_SETUP_TOKEN", system_bootstrap_setup_token)
        .with_env("AZ_WEB_URL", _MAIN_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_ENABLED", "true")
        .with_env("AZ_RUNTIME_WEB_GATEWAY_AUTH_MODE", mode)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN", _MAIN_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_BROKER_ORIGIN", _BROKER_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX", _SERVICE_SUFFIX)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN", cookie_domain)
    )


def _runtime_web_main_container(
    *,
    image: str,
    network: Network,
    mode: str,
    network_alias: str,
    public_api_alias: str,
) -> DockerContainer:
    """Create Main Web with the exact Runtime Web browser configuration."""
    cookie_domain = (
        _SHARED_COOKIE_DOMAIN if mode == "shared_cookie" else _SEPARATE_COOKIE_DOMAIN
    )
    return (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-web-main-{mode}-{unique()}")
        .with_network(network)
        .with_network_aliases(network_alias)
        .with_env("PUBLIC_API_URL", _MAIN_ORIGIN)
        .with_env("INTERNAL_API_URL", f"http://{public_api_alias}:8010")
        .with_env("RUNTIME_WEB_GATEWAY_ENABLED", "true")
        .with_env("RUNTIME_WEB_GATEWAY_AUTH_MODE", mode)
        .with_env("RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN", _MAIN_ORIGIN)
        .with_env("RUNTIME_WEB_GATEWAY_BROKER_ORIGIN", _BROKER_ORIGIN)
        .with_env("RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN", cookie_domain)
        .with_env(
            "RUNTIME_WEB_GATEWAY_IDENTITY_COOKIE_NAME",
            "__Http-Azents-Runtime-Web",
        )
        .with_exposed_ports(3000)
    )


def _runtime_web_edge_container(
    *,
    network: Network,
    certificate_path: Path,
    private_key_path: Path,
    config_path: Path,
) -> DockerContainer:
    """Create one TLS edge for Main Web, broker, and wildcard service hosts."""
    return (
        DockerContainer(image="nginx:1.29-alpine")
        .with_name(f"azents-runtime-web-edge-{unique()}")
        .with_network(network)
        .with_network_aliases("runtime-web-edge")
        .with_volume_mapping(str(config_path), "/etc/nginx/conf.d/default.conf", "ro")
        .with_volume_mapping(str(certificate_path), "/etc/nginx/tls/tls.crt", "ro")
        .with_volume_mapping(str(private_key_path), "/etc/nginx/tls/tls.key", "ro")
        .with_exposed_ports(443)
    )


def _write_tls_edge_files(
    root: Path,
    *,
    main_web_alias: str,
) -> _TlsEdgeFiles:
    """Write a local certificate and exact reverse-proxy configuration."""
    certificate_path = root / "tls.crt"
    private_key_path = root / "tls.key"
    config_path = root / "default.conf"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(private_key_path),
            "-out",
            str(certificate_path),
            "-days",
            "1",
            "-subj",
            "/CN=runtime-e2e.test",
            "-addext",
            (
                "subjectAltName=DNS:web.runtime-e2e.test,"
                "DNS:auth.services.runtime-e2e.test,"
                "DNS:*.services.runtime-e2e.test"
            ),
        ],
        check=True,
        capture_output=True,
    )
    config_path.write_text(
        """
map $host $runtime_web_upstream {
    web.runtime-e2e.test __MAIN_WEB_ALIAS__:3000;
    default runtime-web-gateway:8040;
}

map $host $runtime_web_chat_upstream {
    web.runtime-e2e.test azents-public-server:8010;
    default runtime-web-gateway:8040;
}

server {
    resolver 127.0.0.11 valid=10s;
    listen 443 ssl;
    ssl_certificate /etc/nginx/tls/tls.crt;
    ssl_certificate_key /etc/nginx/tls/tls.key;
    client_max_body_size 1g;
    proxy_read_timeout 1900s;
    proxy_send_timeout 1900s;
    proxy_next_upstream off;

    location /chat/ {
        proxy_http_version 1.1;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_pass http://$runtime_web_chat_upstream;
    }

    location / {
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_pass http://$runtime_web_upstream;
    }
}
""".replace(
            "__MAIN_WEB_ALIAS__",
            main_web_alias,
        )
        .replace(
            "map $host $runtime_web_upstream {",
            "map $http_upgrade $connection_upgrade { default upgrade; '' close; }\n\n"
            "map $host $runtime_web_upstream {",
        )
        .strip()
        + "\n",
        encoding="utf-8",
    )
    return _TlsEdgeFiles(
        certificate_path=certificate_path,
        private_key_path=private_key_path,
        config_path=config_path,
    )


@contextmanager
def _runtime_web_stack(
    *,
    mode: str,
    maximum_active_exchanges: int,
    maximum_application_buffer_bytes: int,
    maintenance: bool,
    relay_path: bool,
    network: Network,
    postgres: PostgresContainer,
    server_image: str,
    owner_control: DockerContainer,
    relay_operations_url: str,
    auth_surface: _RuntimeWebAuthSurface,
    diagnostic_containers: tuple[tuple[str, DockerContainer], ...],
    capacity_backend: str,
    credential_encryption_key: str,
    selenium_url: str,
) -> Generator[_RuntimeWebStack, None, None]:
    """Start one isolated Gateway and TLS edge against shared stateless surfaces."""
    with tempfile.TemporaryDirectory(prefix="runtime-web-e2e-") as temporary_root:
        certificate_path, private_key_path, config_path = _write_tls_edge_files(
            Path(temporary_root),
            main_web_alias=auth_surface.main_web_alias,
        )
        gateway = _runtime_web_gateway_container(
            image=server_image,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
            mode=mode,
            maximum_active_exchanges=maximum_active_exchanges,
            maximum_application_buffer_bytes=maximum_application_buffer_bytes,
            maintenance=maintenance,
            control_endpoint=(
                "runtime-control-relay:8033" if relay_path else "runtime-control:8032"
            ),
        )
        edge = _runtime_web_edge_container(
            network=network,
            certificate_path=certificate_path,
            private_key_path=private_key_path,
            config_path=config_path,
        )
        started_containers: list[tuple[str, DockerContainer]] = []
        started_containers_lock = threading.Lock()

        def start_container(name: str, container: DockerContainer) -> None:
            try:
                container.start()
            except BaseException:
                _log_runtime_web_container(name=name, container=container)
                with suppress(Exception):
                    container.stop()
                raise
            with started_containers_lock:
                started_containers.append((name, container))

        try:
            concurrent_containers = (
                ("Runtime Web Gateway", gateway),
                ("Runtime Web TLS edge", edge),
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(start_container, name, container)
                    for name, container in concurrent_containers
                ]
                for future in futures:
                    future.result()
            _wait_for_http(
                gateway,
                port=8041,
                path="/__azents/live",
                name="Runtime Web Gateway",
            )
            edge_host = edge.get_container_host_ip()
            edge_port = edge.get_exposed_port(443)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                try:
                    response = requests.get(
                        f"https://{edge_host}:{edge_port}/login",
                        headers={"Host": "web.runtime-e2e.test"},
                        verify=False,
                        timeout=2,
                    )
                    if response.status_code < 500:
                        break
                except requests.RequestException:
                    pass
                time.sleep(0.5)
            else:
                edge_logs = _container_logs(edge)
                raise AssertionError(
                    f"Runtime Web TLS edge did not become ready:\n{edge_logs}"
                )
            wrapped = edge.get_wrapped_container()
            wrapped.reload()
            edge_ip = wrapped.attrs["NetworkSettings"]["Networks"][network.name][
                "IPAddress"
            ]
            if not isinstance(edge_ip, str) or not edge_ip:
                raise AssertionError("Runtime Web TLS edge has no network address")
            yield _RuntimeWebStack(
                main_origin=_MAIN_ORIGIN,
                public_api_url=auth_surface.public_api_url,
                operations_url=(
                    f"http://{gateway.get_container_host_ip()}:"
                    f"{gateway.get_exposed_port(8041)}"
                ),
                owner_control_operations_url=(
                    f"http://{owner_control.get_container_host_ip()}:"
                    f"{owner_control.get_exposed_port(8033)}"
                ),
                accepting_control_operations_url=(
                    (relay_operations_url)
                    if relay_path
                    else (
                        f"http://{owner_control.get_container_host_ip()}:"
                        f"{owner_control.get_exposed_port(8033)}"
                    )
                ),
                capacity_backend=capacity_backend,
                edge_ip=edge_ip,
                edge_host_url=f"https://{edge_host}:{edge_port}",
                selenium_url=selenium_url,
            )
        except Exception:
            for name, container in (*started_containers, *diagnostic_containers):
                _log_runtime_web_container(name=name, container=container)
            raise
        finally:
            with ThreadPoolExecutor(
                max_workers=max(len(started_containers), 1)
            ) as executor:
                stop_futures = [
                    executor.submit(container.stop)
                    for _, container in reversed(started_containers)
                ]
                for future in stop_futures:
                    future.result()


@pytest.fixture(scope="module")
def runtime_web_stack_factory(
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
) -> Generator[_RuntimeWebStackFactory, None, None]:
    """Prepare shared stateless auth surfaces and one relay for isolated Gateways."""
    selenium_url = (
        f"http://{selenium_container.get_container_host_ip()}:"
        f"{selenium_container.get_exposed_port(4444)}"
    )
    relay = _runtime_control_relay_container(
        image=azents_server_image,
        network=container_network,
        postgres=postgres_container,
        credential_encryption_key=credential_encryption_key,
        runner_image=azents_runtime_runner_image,
        s3_bucket_name=s3_bucket_name,
        s3_access_key=rustfs_access_key,
        s3_secret_key=rustfs_secret_key,
        capacity_backend=runtime_web_capacity_backend,
    )
    auth_surface_containers: dict[
        str,
        tuple[DockerContainer, DockerContainer, str, str],
    ] = {}
    for mode in ("shared_cookie", "separate_domain"):
        alias_suffix = mode.replace("_", "-")
        public_api_alias = f"runtime-web-public-{alias_suffix}"
        main_web_alias = f"runtime-web-main-{alias_suffix}"
        public_api = _runtime_web_public_api_container(
            image=azents_server_image,
            network=container_network,
            postgres=postgres_container,
            credential_encryption_key=credential_encryption_key,
            auth_jwt_secret_key=auth_jwt_secret_key,
            system_bootstrap_setup_token=system_bootstrap_setup_token,
            mode=mode,
            network_alias=public_api_alias,
        )
        main_web = _runtime_web_main_container(
            image=azents_web_image,
            network=container_network,
            mode=mode,
            network_alias=main_web_alias,
            public_api_alias=public_api_alias,
        )
        auth_surface_containers[mode] = (
            public_api,
            main_web,
            public_api_alias,
            main_web_alias,
        )

    started_containers: list[tuple[str, DockerContainer]] = []
    started_containers_lock = threading.Lock()

    def start_container(name: str, container: DockerContainer) -> None:
        try:
            container.start()
        except BaseException:
            _log_runtime_web_container(name=name, container=container)
            with suppress(Exception):
                container.stop()
            raise
        with started_containers_lock:
            started_containers.append((name, container))

    try:
        configured_containers = [("Runtime Control relay", relay)]
        for mode, (public_api, main_web, _, _) in auth_surface_containers.items():
            configured_containers.extend(
                (
                    (f"Runtime Web Public API ({mode})", public_api),
                    (f"Runtime Web Main Web ({mode})", main_web),
                )
            )
        with ThreadPoolExecutor(max_workers=len(configured_containers)) as executor:
            futures = [
                executor.submit(start_container, name, container)
                for name, container in configured_containers
            ]
            for future in futures:
                future.result()

        _wait_for_log(
            relay,
            "Runtime Control gRPC server started",
            name="Runtime Control relay",
        )
        auth_surfaces: dict[str, _RuntimeWebAuthSurface] = {}
        for mode, (
            public_api,
            main_web,
            _public_api_alias,
            main_web_alias,
        ) in auth_surface_containers.items():
            _wait_for_http(
                public_api,
                port=8010,
                path="/healthz",
                name=f"Runtime Web Public API ({mode})",
            )
            _wait_for_http(
                main_web,
                port=3000,
                path="/login",
                name=f"Runtime Web Main Web ({mode})",
            )
            auth_surfaces[mode] = _RuntimeWebAuthSurface(
                public_api_url=(
                    f"http://{public_api.get_container_host_ip()}:"
                    f"{public_api.get_exposed_port(8010)}"
                ),
                main_web_alias=main_web_alias,
            )

        yield _RuntimeWebStackFactory(
            network=container_network,
            postgres=postgres_container,
            server_image=azents_server_image,
            owner_control=azents_runtime_control_container,
            relay_operations_url=(
                f"http://{relay.get_container_host_ip()}:{relay.get_exposed_port(8034)}"
            ),
            auth_surfaces=auth_surfaces,
            diagnostic_containers=tuple(configured_containers),
            capacity_backend=runtime_web_capacity_backend,
            credential_encryption_key=credential_encryption_key,
            selenium_url=selenium_url,
        )
    except Exception:
        for name, container in started_containers:
            _log_runtime_web_container(name=name, container=container)
        raise
    finally:
        with ThreadPoolExecutor(
            max_workers=max(len(started_containers), 1)
        ) as executor:
            stop_futures = [
                executor.submit(container.stop)
                for _, container in reversed(started_containers)
            ]
            for future in stop_futures:
                future.result()


def _create_workspace(
    *,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    server_url: str,
) -> _RuntimeWebWorkspace:
    """Create one managed Runtime and primary Session through product APIs."""
    suffix = unique()
    token, _, email = authenticate_user(
        public_api_client,
        admin_api_client,
        email=f"runtime-web-gateway-{suffix}@example.com",
    )
    handle = f"runtime-web-gateway-{suffix}"
    headers = _headers(token)
    WorkspaceV1Api(public_api_client).workspace_v1_create_workspace(
        CreateWorkspaceRequest(
            workspace_name=f"Runtime Web Gateway {suffix}",
            workspace_handle=handle,
            owner_name=f"Owner {suffix}",
        ),
        _headers=headers,
    )
    integration = LLMProviderIntegrationV1Api(
        public_api_client
    ).llm_provider_integration_v1_create_integration(
        handle=handle,
        llm_provider_integration_create_request=LLMProviderIntegrationCreateRequest(
            provider=LLMProvider.OPENAI,
            name="__testenv_model_listing:deterministic-success",
            secrets=Secrets(ApiKeySecrets(api_key="sk-runtime-web-gateway")),
        ),
        _headers=headers,
    )
    model_selection: AgentModelSelectionInput = model_selection_from_first_candidate(
        server_url,
        token,
        handle,
        integration.id,
    )
    runtime_profile_id = create_workspace_runtime_profile(
        public_api_client,
        token=token,
        workspace_handle=handle,
        provider_id=_RUNTIME_PROVIDER_ID,
    )
    agent = AgentV1Api(public_api_client).agent_v1_create_agent(
        handle=handle,
        agent_create_request=AgentCreateRequest(
            name=f"Runtime Web Gateway Agent {suffix}",
            selectable_model_options=single_candidate_model_options(model_selection),
            main_model_label="default",
            lightweight_model_label="default",
            type=AgentType.PUBLIC,
            runtime_profile_id=runtime_profile_id,
        ),
        _headers=headers,
    )
    primary = requests.get(
        f"{server_url}/chat/v1/agents/{agent.id}/team-primary-session",
        headers=headers,
        timeout=10,
    )
    primary.raise_for_status()
    session_id = primary.json()["id"]
    if not isinstance(session_id, str):
        raise AssertionError("Team primary Session omitted its ID")
    workspace = _RuntimeWebWorkspace(
        token=token,
        email=email,
        handle=handle,
        agent_id=agent.id,
        session_id=session_id,
    )
    _start_runtime(
        public_api_client=public_api_client,
        workspace=_TerminalWorkspace(
            token=workspace.token,
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
        ),
        server_url=server_url,
    )
    return workspace


def _runtime_application_script() -> str:
    """Return the bounded loopback application executed by the real Runner."""
    script = """
import asyncio
import hashlib

from aiohttp import web

TRANSFER_BYTES = __TRANSFER_BYTES__
TRANSFER_CHUNK_BYTES = 256 * 1024
ASSET_BYTES = 32 * 1024
ASSET_COUNT = __ASSET_COUNT__
upload_invocations = 0
active_sse = 0
sse_connections = 0
active_websockets = 0
websocket_connections = 0

async def index(request):
    return web.Response(
        text=(
            '<!doctype html><title>Runtime Web E2E</title>'
            '<h1 id="ready">Runtime Web E2E ready</h1>'
        ),
        content_type='text/html',
        headers={'X-Runtime-App': 'loopback'},
    )

async def echo(request):
    body = await request.read()
    return web.json_response({'body': body.decode(), 'method': request.method})

async def upload(request):
    global upload_invocations
    upload_invocations += 1
    digest = hashlib.sha256()
    size = 0
    async for chunk in request.content.iter_chunked(TRANSFER_CHUNK_BYTES):
        digest.update(chunk)
        size += len(chunk)
    return web.json_response({
        'bytes': size,
        'sha256': digest.hexdigest(),
        'content_length': request.content_length,
        'transfer_encoding': request.headers.get('Transfer-Encoding'),
    })

async def download(request):
    digest = hashlib.sha256()
    chunk = b'd' * min(TRANSFER_CHUNK_BYTES, TRANSFER_BYTES)
    remaining = TRANSFER_BYTES
    while remaining:
        data = chunk[:remaining]
        digest.update(data)
        remaining -= len(data)
    response = web.StreamResponse(headers={
        'Content-Length': str(TRANSFER_BYTES),
        'Content-Type': 'application/octet-stream',
        'X-Content-Sha256': digest.hexdigest(),
    })
    await response.prepare(request)
    remaining = TRANSFER_BYTES
    while remaining:
        data = chunk[:remaining]
        await response.write(data)
        remaining -= len(data)
    await response.write_eof()
    return response

async def hold(request):
    response = web.StreamResponse(headers={'Content-Type': 'application/octet-stream'})
    await response.prepare(request)
    try:
        while True:
            await response.write(b'active\\n')
            await asyncio.sleep(0.05)
    except ConnectionResetError:
        return response

async def asset(request):
    asset_id = int(request.match_info['asset_id'])
    if not 0 <= asset_id < ASSET_COUNT:
        raise web.HTTPNotFound()
    return web.Response(
        body=bytes([asset_id % 256]) * ASSET_BYTES,
        content_type='application/octet-stream',
    )

async def state(request):
    return web.json_response({
        'upload_invocations': upload_invocations,
        'active_sse': active_sse,
        'sse_connections': sse_connections,
        'active_websockets': active_websockets,
        'websocket_connections': websocket_connections,
    })

async def events(request):
    response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
    await response.prepare(request)
    for event in (b'open', b'heartbeat', b'complete'):
        await response.write(b'data: ' + event + b'\\n\\n')
    await response.write_eof()
    return response

async def held_events(request):
    global active_sse, sse_connections
    active_sse += 1
    sse_connections += 1
    response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
    await response.prepare(request)
    try:
        while True:
            await response.write(b'data: active\\n\\n')
            await asyncio.sleep(0.05)
    except ConnectionResetError:
        return response
    finally:
        active_sse -= 1

async def redirect(request):
    raise web.HTTPFound('/')

async def failure(request):
    return web.Response(status=500, text=request.match_info['canary'])

async def websocket(request):
    global active_websockets, websocket_connections
    active_websockets += 1
    websocket_connections += 1
    socket = web.WebSocketResponse(autoping=False, compress=False)
    await socket.prepare(request)
    try:
        async for message in socket:
            if message.type is web.WSMsgType.TEXT:
                await socket.send_str('echo:' + message.data)
            elif message.type is web.WSMsgType.BINARY:
                await socket.send_bytes(message.data)
            elif message.type is web.WSMsgType.PING:
                await socket.pong(message.data)
        return socket
    finally:
        active_websockets -= 1

application = web.Application()
application.router.add_get('/', index)
application.router.add_post('/echo', echo)
application.router.add_post('/upload', upload)
application.router.add_get('/download', download)
application.router.add_get('/hold', hold)
application.router.add_get('/asset/{asset_id}', asset)
application.router.add_get('/state', state)
application.router.add_get('/events', events)
application.router.add_get('/events-held', held_events)
application.router.add_get('/redirect', redirect)
application.router.add_get('/failure/{canary}', failure)
application.router.add_get('/ws', websocket)
web.run_app(application, host='127.0.0.1', port=8765, handle_signals=False)
"""
    return (
        script.replace("__TRANSFER_BYTES__", str(_BROWSER_TRANSFER_BYTES))
        .replace("__ASSET_COUNT__", str(_BROWSER_ASSET_COUNT))
        .strip()
    )


@contextmanager
def _runtime_application(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _RuntimeWebWorkspace,
    server_url: str,
) -> Generator[_RuntimeApplicationCommands, None, None]:
    """Start the fixture app without retaining an unread Terminal attachment."""
    terminal_workspace = _TerminalWorkspace(
        token=workspace.token,
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
    )
    commands = _RuntimeApplicationCommands(
        public_api_client=public_api_client,
        workspace=terminal_workspace,
        server_url=server_url,
    )
    encoded = base64.b64encode(
        zlib.compress(_runtime_application_script().encode(), level=9)
    ).decode()
    commands.command(
        (
            f'{_RUNTIME_RUNNER_PYTHON} -c "import base64,zlib;'
            "exec(zlib.decompress(base64.b64decode('"
            f"{encoded}')))\" >/tmp/runtime-web-e2e.log 2>&1 & disown"
        ),
        f"APP_STARTED_{unique()}",
    )
    ready_marker = f"APP_READY_{unique()}"
    probe_script = f"""
import socket
import time

deadline = time.monotonic() + 30
while True:
    try:
        connection = socket.create_connection(("127.0.0.1", {_RUNTIME_WEB_PORT}), 1)
    except OSError:
        if time.monotonic() >= deadline:
            raise
        time.sleep(0.1)
    else:
        connection.close()
        print("{ready_marker}")
        break
""".strip()
    encoded_probe = base64.b64encode(probe_script.encode()).decode()
    probe_output = commands.command(
        f"python -c \"import base64;exec(base64.b64decode('{encoded_probe}'))\"",
        f"APP_PROBE_DONE_{unique()}",
    )
    assert ready_marker.encode() in probe_output, probe_output[-4_096:]
    yield commands


@pytest.fixture(scope="module")
def runtime_web_application(
    azents_public_server_url: str,
    azents_admin_server_url: str,
    system_bootstrap_evidence: SystemBootstrapEvidence,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_runtime_control_container: DockerContainer,
) -> Generator[_RuntimeWebApplication, None, None]:
    """Start one real Runtime application for isolated Gateway scenarios."""
    del azents_runtime_provider_docker_container, azents_runtime_control_container
    public_api_client = azentspublicclient.ApiClient(
        configuration=azentspublicclient.Configuration(host=azents_public_server_url)
    )
    admin_api_client = azentsadminclient.ApiClient(
        configuration=azentsadminclient.Configuration(
            host=azents_admin_server_url,
            access_token=system_bootstrap_evidence.access_token,
        )
    )
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    with _runtime_application(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    ) as commands:
        yield _RuntimeWebApplication(
            workspace=workspace,
            commands=commands,
        )


def _browser(
    *,
    selenium_url: str,
    edge_ip: str,
) -> WebDriver:
    """Create Chromium with deterministic wildcard DNS mapped to the TLS edge."""
    options = ChromeOptions()
    options.accept_insecure_certs = True
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1440,1000")
    options.add_argument(
        f"--host-resolver-rules=MAP *.runtime-e2e.test {edge_ip},EXCLUDE localhost"
    )
    driver = webdriver.Remote(
        command_executor=selenium_url,
        options=options,
    )
    driver.set_script_timeout(_BROWSER_SCRIPT_TIMEOUT_SECONDS)
    return driver


def _login(driver: WebDriver, *, email: str) -> None:
    """Authenticate through the exact configured Main Web origin."""
    wait = WebDriverWait(driver, 30)
    driver.get(f"{_MAIN_ORIGIN}/login")
    email_input = wait.until(ec.element_to_be_clickable((By.NAME, "email")))
    email_input.send_keys(email, Keys.ENTER)
    wait.until(ec.url_contains("/login/password"))
    password = wait.until(ec.element_to_be_clickable((By.NAME, "password")))
    password.send_keys(_SIGNUP_PASSWORD, Keys.ENTER)
    wait.until(ec.url_contains("/workspaces"))


def _activate_in_browser(driver: WebDriver, *, service_url: str) -> None:
    """Turn On one Off service through its authenticated public URL."""
    wait = WebDriverWait(driver, 60)
    driver.get(service_url)
    try:
        wait.until(
            ec.visibility_of_element_located(
                (By.XPATH, "//*[normalize-space()='Turn on web service']")
            )
        )
    except TimeoutException as error:
        current_url = driver.current_url.split("?", maxsplit=1)[0]
        body_text = driver.find_element(By.TAG_NAME, "body").text[:2_000]
        raise AssertionError(
            "Runtime Web activation did not become visible: "
            f"url={current_url!r}, title={driver.title!r}, body={body_text!r}"
        ) from error
    wait.until(
        ec.element_to_be_clickable((By.XPATH, "//button[normalize-space()='Turn On']"))
    ).click()
    wait.until(ec.url_to_be(service_url))


def _wait_for_active_service(
    *,
    api: RuntimeWebV1Api,
    workspace: _RuntimeWebWorkspace,
    service_id: str,
) -> RuntimeWebServiceResponse:
    """Poll the authoritative Public API until the service is On."""
    deadline = time.monotonic() + 30
    while True:
        service = api.runtime_web_v1_get_runtime_web_service_projection(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            service_id=service_id,
            _headers=_headers(workspace.token),
        )
        if service.on:
            return service
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Runtime Web activation did not reach authoritative On state: "
                f"on={service.on!r}, revision={service.revision!r}"
            )
        time.sleep(0.1)


def _delete_existing_runtime_web_services(
    *,
    api: RuntimeWebV1Api,
    workspace: _RuntimeWebWorkspace,
) -> None:
    """Reset Agent-owned service state while reusing the Runtime application."""
    existing = api.runtime_web_v1_list_runtime_web_services(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        _headers=_headers(workspace.token),
    )
    for service in existing.items:
        deleted = api.runtime_web_v1_delete_runtime_web_service(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            service_id=service.id,
            runtime_web_expected_revision_request=RuntimeWebExpectedRevisionRequest(
                expected_revision=service.revision,
                operation_key=f"scenario-cleanup-{unique()}",
            ),
            _headers=_headers(workspace.token),
        )
        assert deleted.deleted

    current = api.runtime_web_v1_list_runtime_web_services(
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        _headers=_headers(workspace.token),
    )
    assert current.total_count == 0


def _assert_operations_ready(stack: _RuntimeWebStack) -> str:
    """Wait for exact replacement readiness and return its metrics."""
    deadline = time.monotonic() + 30
    while True:
        live = requests.get(f"{stack.operations_url}/__azents/live", timeout=5)
        ready = requests.get(f"{stack.operations_url}/__azents/ready", timeout=5)
        metrics = requests.get(f"{stack.operations_url}/__azents/metrics", timeout=5)
        owner_ready = requests.get(
            (f"{stack.owner_control_operations_url}/__azents/runtime-web/ready"),
            timeout=5,
        )
        accepting_live = requests.get(
            (f"{stack.accepting_control_operations_url}/__azents/runtime-web/live"),
            timeout=5,
        )
        if (
            live.status_code == 200
            and ready.status_code == 200
            and metrics.status_code == 200
            and owner_ready.status_code == 200
            and accepting_live.status_code == 200
            and "runtime_web_gateway_ready 1" in metrics.text
        ):
            break
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Runtime Web exact replacement readiness was not observed: "
                + json.dumps(
                    {
                        "gateway_live_status": live.status_code,
                        "gateway_ready_status": ready.status_code,
                        "gateway_metrics": metrics.text,
                        "owner_ready_status": owner_ready.status_code,
                        "owner_metrics": _control_metrics(
                            stack.owner_control_operations_url
                        ),
                        "accepting_live_status": accepting_live.status_code,
                        "accepting_metrics": _control_metrics(
                            stack.accepting_control_operations_url
                        ),
                    },
                    sort_keys=True,
                )
            )
        time.sleep(0.1)

    assert "runtime_web_gateway_live 1" in metrics.text
    owner_metrics = _control_metrics(stack.owner_control_operations_url)
    accepting_metrics = _control_metrics(stack.accepting_control_operations_url)
    assert (
        _metric_value(
            owner_metrics,
            'runtime_web_control_sessions{role="runner"} ',
        )
        >= 1
    )
    assert (
        _metric_value(
            owner_metrics,
            (
                "runtime_web_control_capacity_backend_info"
                f'{{backend="{stack.capacity_backend}"}} '
            ),
        )
        == 1
    )
    assert (
        _metric_value(
            accepting_metrics,
            'runtime_web_control_sessions{role="gateway"} ',
        )
        >= 1
    )
    return metrics.text


def _assert_content_free_metrics(
    stack: _RuntimeWebStack,
    *,
    sensitive_values: tuple[str, ...],
) -> str:
    """Reject concrete authority, secret, URL path, body, and error canaries."""
    metrics = _gateway_metrics(stack)
    for line in metrics.splitlines():
        if line.startswith("#") or "{" not in line:
            continue
        label_set = line.split("{", maxsplit=1)[1].split("}", maxsplit=1)[0]
        label_names = {
            item.split("=", maxsplit=1)[0].strip()
            for item in label_set.split(",")
            if item
        }
        assert label_names <= {
            "backend",
            "direction",
            "path",
            "protocol",
            "reason",
            "route",
        }
    for forbidden_label in (
        "user=",
        "session_id=",
        "service_id=",
        'path="/',
        "query=",
        "cookie=",
        "authorization=",
    ):
        assert forbidden_label not in metrics.lower()
    for sensitive_value in sensitive_values:
        assert sensitive_value
        assert sensitive_value not in metrics
    return metrics


def _route_open_count(metrics: str, route: str) -> float:
    """Return the bounded local-or-relay accepted-open counter."""
    prefix = f'runtime_web_gateway_open_total{{route="{route}"}} '
    for line in metrics.splitlines():
        if line.startswith(prefix):
            _, value = line.rsplit(" ", maxsplit=1)
            return float(value)
    return 0.0


def _drain_gateway(stack: _RuntimeWebStack) -> None:
    """Withdraw readiness while preserving process-only liveness."""
    drained = requests.post(f"{stack.operations_url}/__azents/drain", timeout=10)
    assert drained.status_code == 200

    deadline = time.monotonic() + 10
    while True:
        ready = requests.get(f"{stack.operations_url}/__azents/ready", timeout=5)
        if ready.status_code >= 400:
            break
        if time.monotonic() >= deadline:
            raise AssertionError("Runtime Web Gateway readiness remained active")
        time.sleep(0.1)

    live = requests.get(f"{stack.operations_url}/__azents/live", timeout=5)
    assert live.status_code == 200


def _assert_maintenance_preflight(stack: _RuntimeWebStack) -> None:
    """Keep the process live while maintenance withdraws public readiness."""
    live = requests.get(f"{stack.operations_url}/__azents/live", timeout=5)
    ready = requests.get(f"{stack.operations_url}/__azents/ready", timeout=5)
    metrics = requests.get(f"{stack.operations_url}/__azents/metrics", timeout=5)

    assert live.status_code == 200
    assert ready.status_code >= 400
    assert metrics.status_code == 200
    assert "runtime_web_gateway_live 1" in metrics.text
    assert "runtime_web_gateway_ready 0" in metrics.text
    assert _metric_value(metrics.text, "runtime_web_gateway_active_exchanges ") == 0


def _open_application_in_browser(
    driver: WebDriver,
    *,
    endpoint_url: str,
) -> None:
    """Open the application after authoritative approval synchronization."""
    wait = WebDriverWait(driver, 60)
    driver.get(endpoint_url)
    try:
        wait.until(
            ec.visibility_of_element_located(
                (
                    By.XPATH,
                    "//*[@id='ready' and normalize-space()='Runtime Web E2E ready']",
                )
            )
        )
    except TimeoutException as error:
        current_url = driver.current_url.split("?", maxsplit=1)[0]
        body_text = driver.find_element(By.TAG_NAME, "body").text[:2_000]
        raise AssertionError(
            "Runtime Web application did not become visible after approval: "
            f"url={current_url!r}, title={driver.title!r}, body={body_text!r}"
        ) from error


def _browser_transport_evidence(
    driver: WebDriver,
) -> dict[str, object]:
    """Exercise bounded browser transfer, fan-out, SSE, and WebSocket behavior."""
    result = driver.execute_async_script(
        """
const transferBytes = arguments[0];
const assetCount = arguments[1];
const done = arguments[arguments.length - 1];
(async () => {
  const checkedFetch = async (url, init = undefined) => {
    const response = await fetch(url, init);
    if (!response.ok) {
      const body = await response.text();
      throw new Error(`${url} returned ${response.status}: ${body}`);
    }
    return response;
  };
  const echo = await checkedFetch(
    '/echo',
    {method: 'POST', body: 'runtime-web-body'},
  );
  const echoBody = await echo.json();
  const uploadBody = new Uint8Array(transferBytes);
  uploadBody.fill(0x75);
  const expectedUploadDigest = Array.from(
    new Uint8Array(await crypto.subtle.digest('SHA-256', uploadBody)),
    value => value.toString(16).padStart(2, '0'),
  ).join('');
  const upload = await checkedFetch(
    '/upload',
    {method: 'POST', body: uploadBody},
  );
  const uploadEvidence = await upload.json();
  const events = await checkedFetch('/events');
  const eventsBody = await events.text();
  const redirected = await checkedFetch('/redirect');
  const redirectedBody = await redirected.text();
  const download = await checkedFetch('/download');
  const reader = download.body.getReader();
  let bytes = 0;
  while (true) {
    const part = await reader.read();
    if (part.done) break;
    bytes += part.value.byteLength;
  }
  const assets = await Promise.all(
    Array.from({length: assetCount}, async (_, assetId) => {
      const response = await checkedFetch(`/asset/${assetId}`);
      const body = new Uint8Array(await response.arrayBuffer());
      return body.length === 32 * 1024 && body[0] === assetId % 256;
    }),
  );
  const websocket = await new Promise((resolve, reject) => {
    const socket = new WebSocket(`${location.origin.replace('https:', 'wss:')}/ws`);
    socket.binaryType = 'arraybuffer';
    const received = {};
    let completed = false;
    const timeout = setTimeout(
      () => fail(new Error('websocket evidence timed out')),
      10000,
    );
    const finish = result => {
      if (completed) return;
      completed = true;
      clearTimeout(timeout);
      resolve(result);
    };
    const fail = error => {
      if (completed) return;
      completed = true;
      clearTimeout(timeout);
      reject(error);
    };
    socket.onopen = () => {
      socket.send('runtime-web-socket');
      socket.send(new Uint8Array([0, 1, 2, 255]));
    };
    socket.onmessage = event => {
      if (typeof event.data === 'string') {
        received.text = event.data;
      } else {
        received.binary = Array.from(new Uint8Array(event.data));
      }
      if (received.text !== undefined && received.binary !== undefined) {
        socket.close();
        finish(received);
      }
    };
    socket.onerror = () => fail(new Error('websocket failed'));
    socket.onclose = event => {
      if (!completed) {
        fail(
          new Error(
            'websocket closed before evidence: '
              + `code=${event.code} reason=${event.reason}`,
          ),
        );
      }
    };
  });
  done({
    echoBody,
    expectedUploadDigest,
    uploadEvidence,
    eventsBody,
    redirectStatus: redirected.status,
    redirectedBody,
    redirectedUrl: redirected.url,
    bytes,
    assetCount: assets.length,
    assetsValid: assets.every(Boolean),
    websocket,
  });
})().catch(error => done({error: String(error)}));
""",
        _BROWSER_TRANSFER_BYTES,
        _BROWSER_ASSET_COUNT,
    )
    if not isinstance(result, dict):
        raise AssertionError(f"Browser transport evidence was invalid: {result!r}")
    return result


def _runtime_application_state(
    *,
    stack: _RuntimeWebStack,
    headers: dict[str, str],
) -> _RuntimeApplicationState:
    """Read typed content-free state through the product transport."""
    response = requests.get(
        f"{stack.edge_host_url}/state",
        headers=headers,
        verify=False,
        timeout=10,
    )
    response.raise_for_status()
    return _decode_runtime_application_state(response.json())


def _decode_runtime_application_state(payload: object) -> _RuntimeApplicationState:
    """Decode the fixture state instead of retaining raw JSON primitives."""
    if not isinstance(payload, dict):
        raise AssertionError(f"Runtime application state was invalid: {payload!r}")

    values: dict[str, int] = {}
    for key in (
        "upload_invocations",
        "active_sse",
        "sse_connections",
        "active_websockets",
        "websocket_connections",
    ):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise AssertionError(f"Runtime application state omitted {key!r}")
        values[key] = value
    return _RuntimeApplicationState(**values)


def _runtime_application_state_via_terminal(
    terminal: _RuntimeApplicationCommands,
) -> _RuntimeApplicationState:
    """Read loopback fixture state after public admission has been drained."""
    label = f"RUNTIME_WEB_STATE_{unique()}"
    script = (
        "import base64,urllib.request;"
        "payload=urllib.request.urlopen("
        f"'http://127.0.0.1:{_RUNTIME_WEB_PORT}/state',timeout=5"
        ").read();"
        f"print('__{label}__'+base64.b64encode(payload).decode()+'__')"
    )
    encoded = base64.b64encode(script.encode()).decode()
    output = terminal.command(
        f"python -c \"import base64;exec(base64.b64decode('{encoded}'))\"",
        f"STATE_DONE_{unique()}",
    )
    prefix = f"__{label}__".encode()
    start = output.rfind(prefix)
    if start < 0:
        raise AssertionError("Runtime application state marker was not observed")
    encoded_payload = output[start + len(prefix) :].split(b"__", maxsplit=1)[0]
    payload = json.loads(base64.b64decode(encoded_payload))
    return _decode_runtime_application_state(payload)


def _gateway_metrics(stack: _RuntimeWebStack) -> str:
    """Return the internal bounded Gateway metrics text."""
    response = requests.get(f"{stack.operations_url}/__azents/metrics", timeout=5)
    response.raise_for_status()
    return response.text


def _control_metrics(operations_url: str) -> str:
    """Return one internal Runtime Web Control metrics projection."""
    response = requests.get(
        f"{operations_url}/__azents/runtime-web/metrics",
        timeout=5,
    )
    response.raise_for_status()
    return response.text


def _metric_value(metrics: str, prefix: str) -> float:
    """Return one exact scalar OpenMetrics sample."""
    for line in metrics.splitlines():
        if line.startswith(prefix):
            _, value = line.rsplit(" ", maxsplit=1)
            return float(value)
    raise AssertionError(f"Runtime Web metric was not observed: {prefix!r}")


def _wait_for_runtime_web_stream_release(stack: _RuntimeWebStack) -> None:
    """Wait for authoritative stream and capacity gauges to reach zero."""
    deadline = time.monotonic() + 10
    while True:
        gateway_active = _metric_value(
            _gateway_metrics(stack),
            "runtime_web_gateway_active_exchanges ",
        )
        owner_metrics = _control_metrics(stack.owner_control_operations_url)
        accepting_metrics = _control_metrics(stack.accepting_control_operations_url)
        owner_active = _metric_value(
            owner_metrics,
            "runtime_web_control_active_streams ",
        )
        accepting_active = _metric_value(
            accepting_metrics,
            "runtime_web_control_active_streams ",
        )
        owner_capacity_active = _metric_value(
            owner_metrics,
            "runtime_web_control_capacity_active_streams ",
        )
        accepting_capacity_active = _metric_value(
            accepting_metrics,
            "runtime_web_control_capacity_active_streams ",
        )
        if (
            gateway_active
            == owner_active
            == accepting_active
            == owner_capacity_active
            == accepting_capacity_active
            == 0
        ):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                "Runtime Web streams or capacity were not released before "
                "drain verification: "
                f"gateway={gateway_active}, owner={owner_active}, "
                f"accepting={accepting_active}, "
                f"owner_capacity={owner_capacity_active}, "
                f"accepting_capacity={accepting_capacity_active}"
            )
        time.sleep(0.1)


def _request_rejection_without_body(
    *,
    stack: _RuntimeWebStack,
    endpoint_host: str,
    cookie: str,
) -> bytes:
    """Send only a large request head and return the bounded response head."""
    edge_address = stack.edge_host_url.removeprefix("https://")
    edge_host, edge_port_text = edge_address.rsplit(":", maxsplit=1)
    raw_socket = socket.create_connection((edge_host, int(edge_port_text)), timeout=10)
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE
    with tls_context.wrap_socket(
        raw_socket,
        server_hostname=endpoint_host,
    ) as connection:
        request_head = (
            "POST /upload HTTP/1.1\r\n"
            f"Host: {endpoint_host}\r\n"
            f"Cookie: {cookie}\r\n"
            f"Origin: https://{endpoint_host}\r\n"
            "User-Agent: Mozilla/5.0 Firefox/143.0\r\n"
            "Sec-Fetch-Site: same-origin\r\n"
            "Sec-Fetch-Mode: cors\r\n"
            "Sec-Fetch-Dest: empty\r\n"
            f"Content-Length: {_REJECTED_REQUEST_CONTENT_LENGTH}\r\n"
            "Content-Type: application/octet-stream\r\n"
            "Connection: close\r\n"
            "\r\n"
        ).encode()
        connection.sendall(request_head)
        response = bytearray()
        while True:
            chunk = connection.recv(1024)
            if not chunk:
                break
            response.extend(chunk)
            if len(response) > 8 * 1024:
                raise AssertionError("Hard-limit response exceeded its bound")
    return bytes(response)


def _browser_neutral_transport_evidence(
    *,
    stack: _RuntimeWebStack,
    endpoint_url: str,
    identity_secret: str,
) -> None:
    """Exercise application errors and WebSocket controls without browser signals."""
    endpoint_host = endpoint_url.removeprefix("https://").rstrip("/")
    cookie = f"__Http-Azents-Runtime-Web={identity_secret}"
    firefox_user_agent = "Mozilla/5.0 Firefox/143.0"
    request_headers = {
        "Host": endpoint_host,
        "Cookie": cookie,
        "User-Agent": firefox_user_agent,
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
    }
    response = requests.post(
        f"{stack.edge_host_url}/echo",
        headers=request_headers,
        data="browser-neutral-body",
        verify=False,
        timeout=10,
    )
    assert response.status_code == 200
    assert response.json() == {
        "body": "browser-neutral-body",
        "method": "POST",
    }
    failure = requests.get(
        f"{stack.edge_host_url}/failure/application-error-canary",
        headers=request_headers,
        verify=False,
        timeout=10,
    )
    assert failure.status_code == 500
    assert failure.text == "application-error-canary"

    asyncio.run(
        _browser_neutral_websocket_evidence(
            stack=stack,
            endpoint_url=endpoint_url,
            cookie=cookie,
            user_agent=firefox_user_agent,
        )
    )


async def _browser_neutral_websocket_evidence(
    *,
    stack: _RuntimeWebStack,
    endpoint_url: str,
    cookie: str,
    user_agent: str,
) -> None:
    """Exercise browser-neutral WebSocket frames without a receiver thread."""
    endpoint_host = endpoint_url.removeprefix("https://").rstrip("/")
    edge_address = stack.edge_host_url.removeprefix("https://")
    edge_host, edge_port_text = edge_address.rsplit(":", maxsplit=1)
    raw_socket = socket.create_connection((edge_host, int(edge_port_text)), timeout=10)
    raw_socket.setblocking(False)
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE

    async with async_connect(
        f"wss://{endpoint_host}/ws",
        sock=raw_socket,
        ssl=tls_context,
        server_hostname=endpoint_host,
        origin=Origin(endpoint_url.rstrip("/")),
        additional_headers={"Cookie": cookie},
        user_agent_header=user_agent,
        proxy=None,
        open_timeout=10,
    ) as websocket:
        await websocket.send("browser-neutral-socket")
        async with asyncio.timeout(10):
            assert await websocket.recv() == "echo:browser-neutral-socket"
        await websocket.send(bytes([0, 1, 2, 255]))
        async with asyncio.timeout(10):
            assert await websocket.recv() == bytes([0, 1, 2, 255])
        pong = await websocket.ping(b"runtime-web-ping")
        async with asyncio.timeout(10):
            await pong


def _assert_redis_capacity_fallback(
    *,
    stack: _RuntimeWebStack,
    endpoint_url: str,
    identity_secret: str,
    valkey: DockerContainer,
) -> None:
    """Keep one Web session alive across Redis fallback and empty recovery."""
    if stack.capacity_backend != "redis":
        return

    endpoint_host = endpoint_url.removeprefix("https://").rstrip("/")
    cookie = f"__Http-Azents-Runtime-Web={identity_secret}"
    headers = {
        "Host": endpoint_host,
        "Cookie": cookie,
        "User-Agent": "Mozilla/5.0 Firefox/143.0",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
    }
    edge_address = stack.edge_host_url.removeprefix("https://")
    edge_host, edge_port_text = edge_address.rsplit(":", maxsplit=1)
    raw_socket = socket.create_connection((edge_host, int(edge_port_text)), timeout=10)
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE
    wrapped_valkey = valkey.get_wrapped_container()

    with connect(
        f"wss://{endpoint_host}/ws",
        sock=raw_socket,
        ssl=tls_context,
        server_hostname=endpoint_host,
        origin=Origin(endpoint_url.rstrip("/")),
        additional_headers={"Cookie": cookie},
        user_agent_header=headers["User-Agent"],
        proxy=None,
        open_timeout=10,
    ) as websocket:
        websocket.send("before-redis-loss")
        assert websocket.recv(timeout=10) == "echo:before-redis-loss"
        wrapped_valkey.stop(timeout=5)
        try:
            deadline = time.monotonic() + 20
            while True:
                fallback = requests.post(
                    f"{stack.edge_host_url}/echo",
                    headers=headers,
                    data="during-redis-loss",
                    verify=False,
                    timeout=5,
                )
                degraded = _metric_value(
                    _control_metrics(stack.owner_control_operations_url),
                    "runtime_web_control_capacity_degraded ",
                )
                if fallback.status_code == 200 and degraded == 1:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        "Runtime Web did not converge to in-memory capacity fallback"
                    )
                time.sleep(0.1)
            assert fallback.json() == {
                "body": "during-redis-loss",
                "method": "POST",
            }
            websocket.send("during-redis-loss")
            assert websocket.recv(timeout=10) == "echo:during-redis-loss"
        finally:
            wrapped_valkey.start()

        deadline = time.monotonic() + 30
        while True:
            recovered = requests.post(
                f"{stack.edge_host_url}/echo",
                headers=headers,
                data="after-redis-recovery",
                verify=False,
                timeout=5,
            )
            degraded = _metric_value(
                _control_metrics(stack.owner_control_operations_url),
                "runtime_web_control_capacity_degraded ",
            )
            if recovered.status_code == 200 and degraded == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Runtime Web Redis capacity recovery did not converge"
                )
            time.sleep(0.1)
        assert recovered.json() == {
            "body": "after-redis-recovery",
            "method": "POST",
        }
        websocket.send("after-redis-recovery")
        assert websocket.recv(timeout=10) == "echo:after-redis-recovery"


@pytest.mark.parametrize("auth_mode", ["shared_cookie", "separate_domain"])
def test_runtime_web_gateway_real_runtime_browser_and_cross_replica_relay(
    auth_mode: str,
    valkey_container: DockerContainer,
    runtime_web_application: _RuntimeWebApplication,
    runtime_web_stack_factory: _RuntimeWebStackFactory,
) -> None:
    """Prove both auth modes, relay, revision fencing, and streamed transport."""
    workspace = runtime_web_application.workspace
    with runtime_web_stack_factory.start(
        auth_mode,
        maximum_active_exchanges=512,
        maximum_application_buffer_bytes=16 * 1024 * 1024,
        maintenance=False,
        relay_path=True,
    ) as stack:
        runtime_web_api_client = azentspublicclient.ApiClient(
            configuration=azentspublicclient.Configuration(host=stack.public_api_url)
        )
        api = RuntimeWebV1Api(runtime_web_api_client)
        _delete_existing_runtime_web_services(api=api, workspace=workspace)
        service = api.runtime_web_v1_create_runtime_web_service(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            runtime_web_create_request=RuntimeWebCreateRequest(
                port=_RUNTIME_WEB_PORT,
                label=f"Gateway {auth_mode}",
                selected_duration_seconds=3_600,
                turn_on=False,
                operation_key=f"request-{unique()}",
            ),
            _headers=_headers(workspace.token),
        )
        assert not service.on
        assert service.url is not None
        service_url = service.url
        assert service_url.startswith("https://")
        assert "?" not in service_url
        assert "ticket" not in service_url.lower()
        stable_service_id = service.id

        driver = _browser(
            selenium_url=stack.selenium_url,
            edge_ip=stack.edge_ip,
        )
        try:
            _login(driver, email=workspace.email)
            _activate_in_browser(driver, service_url=service_url)
            active = _wait_for_active_service(
                api=api,
                workspace=workspace,
                service_id=stable_service_id,
            )
            assert active.on
            assert active.id == stable_service_id
            assert active.url == service_url
            metrics_before = _assert_operations_ready(stack)
            relay_opens_before = _route_open_count(metrics_before, "relay")
            _open_application_in_browser(driver, endpoint_url=service_url)

            evidence = _browser_transport_evidence(driver)
            assert "error" not in evidence, evidence
            assert evidence["echoBody"] == {
                "body": "runtime-web-body",
                "method": "POST",
            }
            upload_evidence = evidence["uploadEvidence"]
            assert isinstance(upload_evidence, dict)
            assert upload_evidence["bytes"] == _BROWSER_TRANSFER_BYTES
            assert upload_evidence["sha256"] == evidence["expectedUploadDigest"]
            assert upload_evidence["content_length"] == _BROWSER_TRANSFER_BYTES
            assert upload_evidence["transfer_encoding"] is None
            assert evidence["eventsBody"] == (
                "data: open\n\ndata: heartbeat\n\ndata: complete\n\n"
            )
            assert evidence["redirectStatus"] == 200
            assert evidence["redirectedUrl"] == service_url
            redirected_body = evidence["redirectedBody"]
            assert isinstance(redirected_body, str)
            assert "Runtime Web E2E ready" in redirected_body
            assert evidence["bytes"] == _BROWSER_TRANSFER_BYTES
            assert evidence["assetCount"] == _BROWSER_ASSET_COUNT
            assert evidence["assetsValid"] is True
            assert evidence["websocket"] == {
                "text": "echo:runtime-web-socket",
                "binary": [0, 1, 2, 255],
            }
            _wait_for_runtime_web_stream_release(stack)
            assert driver.current_url == service_url
            assert "ticket" not in driver.current_url.lower()
            identity_cookie = driver.get_cookie("__Http-Azents-Runtime-Web")
            assert identity_cookie is not None
            identity_secret = identity_cookie.get("value")
            assert isinstance(identity_secret, str)
            _browser_neutral_transport_evidence(
                stack=stack,
                endpoint_url=service_url,
                identity_secret=identity_secret,
            )
            if auth_mode == "shared_cookie":
                _assert_redis_capacity_fallback(
                    stack=stack,
                    endpoint_url=service_url,
                    identity_secret=identity_secret,
                    valkey=valkey_container,
                )
            metrics_after = _assert_content_free_metrics(
                stack,
                sensitive_values=(
                    workspace.token,
                    workspace.email,
                    workspace.handle,
                    workspace.agent_id,
                    workspace.session_id,
                    service_url,
                    identity_secret,
                    "sk-runtime-web-gateway",
                    "runtime-web-body",
                    "browser-neutral-body",
                    "/echo",
                    "/upload",
                    "runtime-web-socket",
                    "application-error-canary",
                ),
            )
            assert _route_open_count(metrics_after, "relay") > relay_opens_before

            with pytest.raises(ApiException) as stale_reset:
                api.runtime_web_v1_reset_runtime_web_service_expiration(
                    handle=workspace.handle,
                    agent_id=workspace.agent_id,
                    service_id=stable_service_id,
                    runtime_web_expected_revision_request=(
                        RuntimeWebExpectedRevisionRequest(
                            expected_revision=active.revision + 1,
                            operation_key=f"stale-reset-{unique()}",
                        )
                    ),
                    _headers=_headers(workspace.token),
                )
            assert stale_reset.value.status == 409

            reset = api.runtime_web_v1_reset_runtime_web_service_expiration(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                service_id=stable_service_id,
                runtime_web_expected_revision_request=RuntimeWebExpectedRevisionRequest(
                    expected_revision=active.revision,
                    operation_key=f"reset-{unique()}",
                ),
                _headers=_headers(workspace.token),
            )
            assert reset.on
            assert reset.id == stable_service_id
            assert reset.url == service_url
            assert reset.revision == active.revision + 1
            assert reset.expires_at is not None

            turned_off = api.runtime_web_v1_turn_off_runtime_web_service(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                service_id=stable_service_id,
                runtime_web_expected_revision_request=RuntimeWebExpectedRevisionRequest(
                    expected_revision=reset.revision,
                    operation_key=f"turn-off-{unique()}",
                ),
                _headers=_headers(workspace.token),
            )
            assert not turned_off.on
            assert turned_off.id == stable_service_id
            assert turned_off.url == service_url
            status_after_close = driver.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "fetch('/', {cache: 'no-store'})"
                ".then(response => done(response.status))"
                ".catch(error => done(String(error)));"
            )
            assert status_after_close == 410
        finally:
            with suppress(WebDriverException):
                driver.quit()

        unauthenticated = requests.get(
            f"{stack.edge_host_url}/",
            headers={
                "Host": service_url.removeprefix("https://").rstrip("/"),
                "User-Agent": "Mozilla/5.0 Firefox/143.0",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            verify=False,
            timeout=10,
            allow_redirects=False,
        )
        assert unauthenticated.status_code == 401

        listed = api.runtime_web_v1_list_runtime_web_services(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            _headers=_headers(workspace.token),
        )
        assert listed.total_count == 1
        assert listed.items[0].id == stable_service_id
        serialized = json.dumps(listed.items[0].to_dict(), default=str)
        assert "sk-runtime-web-gateway" not in serialized
        assert "ticket_secret" not in serialized
        _drain_gateway(stack)


def test_runtime_web_gateway_hard_limit_rejects_before_body_admission(
    runtime_web_application: _RuntimeWebApplication,
    runtime_web_stack_factory: _RuntimeWebStackFactory,
) -> None:
    """Reject a second exchange and release the exact disconnected reservation."""
    workspace = runtime_web_application.workspace
    runtime_terminal = runtime_web_application.commands
    with runtime_web_stack_factory.start(
        "shared_cookie",
        maximum_active_exchanges=2,
        maximum_application_buffer_bytes=4 * 1024 * 1024,
        maintenance=False,
        relay_path=False,
    ) as stack:
        runtime_web_api_client = azentspublicclient.ApiClient(
            configuration=azentspublicclient.Configuration(host=stack.public_api_url)
        )
        api = RuntimeWebV1Api(runtime_web_api_client)
        _delete_existing_runtime_web_services(api=api, workspace=workspace)
        service = api.runtime_web_v1_create_runtime_web_service(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            runtime_web_create_request=RuntimeWebCreateRequest(
                port=_RUNTIME_WEB_PORT,
                label="Hard limit",
                selected_duration_seconds=3_600,
                turn_on=False,
                operation_key=f"hard-limit-{unique()}",
            ),
            _headers=_headers(workspace.token),
        )
        assert service.url is not None
        endpoint_url = service.url

        driver = _browser(
            selenium_url=stack.selenium_url,
            edge_ip=stack.edge_ip,
        )
        try:
            _login(driver, email=workspace.email)
            _activate_in_browser(driver, service_url=endpoint_url)
            _wait_for_active_service(
                api=api,
                workspace=workspace,
                service_id=service.id,
            )
            metrics_before = _assert_operations_ready(stack)
            local_opens_before = _route_open_count(metrics_before, "local")
            _open_application_in_browser(driver, endpoint_url=endpoint_url)
            identity_cookie = driver.get_cookie("__Http-Azents-Runtime-Web")
            assert identity_cookie is not None
            identity_secret = identity_cookie.get("value")
            assert isinstance(identity_secret, str)
        finally:
            with suppress(WebDriverException):
                driver.quit()

        endpoint_host = endpoint_url.removeprefix("https://").rstrip("/")
        headers = {
            "Host": endpoint_host,
            "Cookie": f"__Http-Azents-Runtime-Web={identity_secret}",
            "User-Agent": "Mozilla/5.0 Firefox/143.0",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
        }
        started = [threading.Event(), threading.Event()]
        release = threading.Event()

        def hold_exchange(started_event: threading.Event) -> None:
            with requests.get(
                f"{stack.edge_host_url}/hold",
                headers=headers,
                verify=False,
                timeout=30,
                stream=True,
            ) as held:
                held.raise_for_status()
                chunks = held.iter_content(chunk_size=7)
                assert next(chunks) == b"active\n"
                started_event.set()
                if not release.wait(timeout=20):
                    raise TimeoutError("Hard-limit exchange was not released")

        initial_state = _runtime_application_state(stack=stack, headers=headers)
        assert initial_state.active_sse == 0
        assert initial_state.active_websockets == 0
        with ThreadPoolExecutor(max_workers=2) as executor:
            held = [
                executor.submit(hold_exchange, started_event)
                for started_event in started
            ]
            assert all(started_event.wait(timeout=10) for started_event in started)
            rejected = _request_rejection_without_body(
                stack=stack,
                endpoint_host=endpoint_host,
                cookie=headers["Cookie"],
            )
            assert rejected.startswith(b"HTTP/1.1 429")
            assert len(rejected) <= 8 * 1024
            assert b"resource_exhausted" in rejected
            release.set()
            for future in held:
                future.result(timeout=10)

        state_after_rejection = _runtime_application_state(
            stack=stack,
            headers=headers,
        )
        assert state_after_rejection == initial_state

        deadline = time.monotonic() + 10
        while True:
            recovered = requests.post(
                f"{stack.edge_host_url}/echo",
                headers=headers,
                data="released",
                verify=False,
                timeout=5,
            )
            if recovered.status_code == 200:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Runtime Web hard-limit reservation was not released"
                )
            time.sleep(0.1)
        assert recovered.json() == {"body": "released", "method": "POST"}
        metrics_after_recovery = _assert_content_free_metrics(
            stack,
            sensitive_values=(
                workspace.token,
                workspace.email,
                workspace.handle,
                workspace.agent_id,
                workspace.session_id,
                endpoint_url,
                identity_secret,
                "sk-runtime-web-gateway",
                "released",
                "/hold",
                "/upload",
            ),
        )
        assert _route_open_count(metrics_after_recovery, "local") > local_opens_before
        _wait_for_runtime_web_stream_release(stack)

        stream_state_before = _runtime_application_state_via_terminal(runtime_terminal)
        assert stream_state_before.active_websockets == 0
        assert stream_state_before.active_sse == 0
        websocket_drained = threading.Event()
        sse_started = threading.Event()
        sse_drained = threading.Event()

        def hold_websocket(websocket: Connection) -> None:
            try:
                websocket.recv(timeout=15)
            except ConnectionClosed:
                websocket_drained.set()
            else:
                raise AssertionError(
                    "Runtime Web drain did not close the long-lived stream"
                )

        def hold_sse() -> None:
            try:
                with requests.get(
                    f"{stack.edge_host_url}/events-held",
                    headers=headers,
                    verify=False,
                    timeout=20,
                    stream=True,
                ) as response:
                    response.raise_for_status()
                    chunks = response.iter_content(chunk_size=14)
                    assert b"data: active" in next(chunks)
                    sse_started.set()
                    for _ in chunks:
                        pass
            except requests.RequestException:
                pass
            finally:
                sse_drained.set()

        edge_address = stack.edge_host_url.removeprefix("https://")
        edge_host, edge_port_text = edge_address.rsplit(":", maxsplit=1)
        tls_context = ssl.create_default_context()
        tls_context.check_hostname = False
        tls_context.verify_mode = ssl.CERT_NONE
        with socket.create_connection(
            (edge_host, int(edge_port_text)),
            timeout=10,
        ) as raw_socket:
            with ThreadPoolExecutor(max_workers=2) as executor:
                with connect(
                    f"wss://{endpoint_host}/ws",
                    sock=raw_socket,
                    ssl=tls_context,
                    server_hostname=endpoint_host,
                    origin=Origin(endpoint_url.rstrip("/")),
                    additional_headers={"Cookie": headers["Cookie"]},
                    user_agent_header=headers["User-Agent"],
                    proxy=None,
                    open_timeout=10,
                ) as websocket:
                    websocket_reader = executor.submit(hold_websocket, websocket)
                    sse = executor.submit(hold_sse)
                    assert sse_started.wait(timeout=10)
                    active_long_lived = _runtime_application_state_via_terminal(
                        runtime_terminal
                    )
                    assert active_long_lived.active_websockets == 1
                    assert (
                        active_long_lived.websocket_connections
                        == stream_state_before.websocket_connections + 1
                    )
                    assert active_long_lived.active_sse == 1
                    assert (
                        active_long_lived.sse_connections
                        == stream_state_before.sse_connections + 1
                    )
                    assert (
                        active_long_lived.upload_invocations
                        == stream_state_before.upload_invocations
                    )
                    _drain_gateway(stack)
                    assert websocket_drained.wait(timeout=10)
                    assert sse_drained.wait(timeout=10)
                    websocket_reader.result(timeout=10)
                    sse.result(timeout=10)

        deadline = time.monotonic() + 10
        while True:
            drained_state = _runtime_application_state_via_terminal(runtime_terminal)
            if drained_state.active_websockets == 0 and drained_state.active_sse == 0:
                break
            if time.monotonic() >= deadline:
                raise AssertionError(
                    "Runtime Web drain did not release application streams"
                )
            time.sleep(0.1)
        assert (
            drained_state.websocket_connections
            == stream_state_before.websocket_connections + 1
        )
        assert drained_state.sse_connections == stream_state_before.sse_connections + 1
        assert (
            drained_state.upload_invocations == stream_state_before.upload_invocations
        )

        refused = requests.post(
            f"{stack.edge_host_url}/echo",
            headers=headers,
            data="after-drain",
            verify=False,
            timeout=10,
        )
        assert refused.status_code >= 400
        assert len(refused.content) <= 4_096


def test_runtime_web_gateway_maintenance_preflight(
    runtime_web_application: _RuntimeWebApplication,
    runtime_web_stack_factory: _RuntimeWebStackFactory,
) -> None:
    """Preserve durable authority while maintenance refuses all public work."""
    workspace = runtime_web_application.workspace
    runtime_terminal = runtime_web_application.commands
    with runtime_web_stack_factory.start(
        "shared_cookie",
        maximum_active_exchanges=512,
        maximum_application_buffer_bytes=16 * 1024 * 1024,
        maintenance=True,
        relay_path=True,
    ) as stack:
        runtime_web_api_client = azentspublicclient.ApiClient(
            configuration=azentspublicclient.Configuration(host=stack.public_api_url)
        )
        api = RuntimeWebV1Api(runtime_web_api_client)
        _delete_existing_runtime_web_services(api=api, workspace=workspace)
        active = api.runtime_web_v1_create_runtime_web_service(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            runtime_web_create_request=RuntimeWebCreateRequest(
                port=_RUNTIME_WEB_PORT,
                label="Maintenance preflight",
                selected_duration_seconds=3_600,
                turn_on=True,
                operation_key=f"maintenance-{unique()}",
            ),
            _headers=_headers(workspace.token),
        )
        assert active.on
        assert active.url is not None
        _assert_maintenance_preflight(stack)
        state_before_refusal = _runtime_application_state_via_terminal(runtime_terminal)
        assert state_before_refusal.active_sse == 0
        assert state_before_refusal.active_websockets == 0

        endpoint_host = active.url.removeprefix("https://").rstrip("/")
        refused = requests.get(
            f"{stack.edge_host_url}/",
            headers={"Host": endpoint_host},
            verify=False,
            timeout=10,
            allow_redirects=False,
        )
        assert refused.status_code == 503
        refused_body = json.dumps(refused.json(), sort_keys=True)
        assert len(refused_body) <= 512
        assert "maintenance" in refused_body

        state = _runtime_application_state_via_terminal(runtime_terminal)
        assert state == state_before_refusal
        _drain_gateway(stack)
        assert (
            _runtime_application_state_via_terminal(runtime_terminal)
            == state_before_refusal
        )

        preserved = api.runtime_web_v1_get_runtime_web_service_projection(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            service_id=active.id,
            _headers=_headers(workspace.token),
        )
        assert preserved.on
        assert preserved.id == active.id
        assert preserved.revision == active.revision
