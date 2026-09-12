"""Runtime Web Gateway browser, transport, and authority E2E journeys."""

from __future__ import annotations

import base64
import itertools
import json
import subprocess
import tempfile
import time
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

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
from azentspublicclient.models.runtime_web_approval_request import (
    RuntimeWebApprovalRequest,
)
from azentspublicclient.models.runtime_web_close_request import RuntimeWebCloseRequest
from azentspublicclient.models.runtime_web_exposure_request import (
    RuntimeWebExposureRequest,
)
from azentspublicclient.models.runtime_web_request_state import RuntimeWebRequestState
from azentspublicclient.models.secrets import Secrets
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import WebDriverWait
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network
from testcontainers.postgres import PostgresContainer

from support.runtime_profiles import create_workspace_runtime_profile
from support.utils import (
    authenticate_user,
    model_selection_from_first_candidate,
    unique,
)
from tests.required.public.test_runtime_terminal import (
    _start_runtime,
    _TerminalSocket,
    _TerminalWorkspace,
)

_RUNTIME_PROVIDER_ID = "system-docker"
_RUNTIME_WEB_PORT = 8765
_MAIN_ORIGIN = "https://web.runtime-e2e.test"
_BROKER_ORIGIN = "https://auth.services.runtime-e2e.test"
_SERVICE_SUFFIX = "services.runtime-e2e.test"
_SHARED_COOKIE_DOMAIN = "runtime-e2e.test"
_SEPARATE_COOKIE_DOMAIN = _SERVICE_SUFFIX
_TERMINAL_ORIGIN = "https://azents-web-gateway:8443"
_SIGNUP_PASSWORD = "TestPass123!"
_CONFIGURATION_REVISIONS = itertools.count(10_000)


@dataclass(frozen=True)
class _RuntimeWebWorkspace:
    """Product-created authority and browser identity for one journey."""

    token: str
    email: str
    handle: str
    agent_id: str
    session_id: str


@dataclass(frozen=True)
class _RuntimeWebStack:
    """Function-scoped Runtime Web browser topology."""

    main_origin: str
    edge_ip: str
    edge_host_url: str
    selenium_url: str


def _headers(token: str) -> dict[str, str]:
    """Return bearer authentication headers."""
    return {"Authorization": f"Bearer {token}"}


def _container_logs(container: DockerContainer) -> str:
    """Return combined bounded container logs."""
    stdout, stderr = container.get_logs()
    return (stdout + stderr).decode(errors="replace")[-12_000:]


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
) -> DockerContainer:
    """Create a second Control replica used only as the Gateway relay ingress."""
    base = (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-control-relay-{unique()}")
        .with_network_aliases("runtime-control-relay")
        .with_command(["python", "src/cli/runtime_control_server.py"])
        .with_exposed_ports(8031, 8033)
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
        .with_env("AZ_RUNTIME_CONTROL_INSTANCE_ID", "azents-e2e-runtime-control-relay")
        .with_env("AZ_RUNTIME_CONTROL_RECONCILE_INTERVAL_SECONDS", "60")
        .with_env("AZ_RUNTIME_CONTROL_WEB_ROUTE_LEASE_SECONDS", "10")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_BUCKET", s3_bucket_name)
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_PREFIX", "v1")
        .with_env("AZ_RUNTIME_CONTROL_WORKSPACE_S3_ENDPOINT_URL", "http://rustfs:9000")
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
    configuration_revision: int,
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
        .with_exposed_ports(8040)
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
        .with_env("AZ_RUNTIME_WEB_GATEWAY_AUTH_MODE", mode)
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_AUTH_CONFIGURATION_VERSION",
            str(configuration_revision),
        )
        .with_env("AZ_RUNTIME_WEB_GATEWAY_MAIN_WEB_ORIGIN", _MAIN_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_BROKER_ORIGIN", _BROKER_ORIGIN)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_SERVICE_SUFFIX", _SERVICE_SUFFIX)
        .with_env("AZ_RUNTIME_WEB_GATEWAY_COOKIE_DOMAIN", cookie_domain)
        .with_env(
            "AZ_RUNTIME_WEB_GATEWAY_CONTROL_ENDPOINT",
            "runtime-control-relay:8033",
        )
        .with_env("AZ_RUNTIME_WEB_GATEWAY_CONTROL_ALLOW_INSECURE", "true")
        .with_env("AZ_RUNTIME_WEB_GATEWAY_CHROMIUM_MIN_VERSION", "152")
        .with_env("AZ_RUNTIME_WEB_GATEWAY_CHROMIUM_MAX_VERSION", "152")
    )


def _runtime_web_main_container(
    *,
    image: str,
    network: Network,
    mode: str,
) -> DockerContainer:
    """Create Main Web with the exact Runtime Web browser configuration."""
    cookie_domain = (
        _SHARED_COOKIE_DOMAIN if mode == "shared_cookie" else _SEPARATE_COOKIE_DOMAIN
    )
    return (
        DockerContainer(image=image)
        .with_name(f"azents-runtime-web-main-{mode}-{unique()}")
        .with_network(network)
        .with_network_aliases("runtime-web-main")
        .with_env("PUBLIC_API_URL", _MAIN_ORIGIN)
        .with_env("INTERNAL_API_URL", "http://azents-public-server:8010")
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


def _runtime_web_selenium_container(
    *,
    network: Network,
) -> DockerContainer:
    """Create Chromium after the function-scoped TLS edge is available."""
    return (
        DockerContainer(image="selenium/standalone-chromium:4.45.0-20260606")
        .with_name(f"azents-runtime-web-selenium-{unique()}")
        .with_network(network)
        .with_env("SE_NODE_SESSION_TIMEOUT", "120")
        .with_exposed_ports(4444)
        .with_kwargs(shm_size="2g")
    )


def _write_tls_edge_files(root: Path) -> tuple[Path, Path, Path]:
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
    web.runtime-e2e.test runtime-web-main:3000;
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
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_pass http://$runtime_web_upstream;
    }
}
""".replace(
            "map $host $runtime_web_upstream {",
            "map $http_upgrade $connection_upgrade { default upgrade; '' close; }\n\n"
            "map $host $runtime_web_upstream {",
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return certificate_path, private_key_path, config_path


@contextmanager
def _runtime_web_stack(
    *,
    mode: str,
    network: Network,
    postgres: PostgresContainer,
    server_image: str,
    web_image: str,
    runner_image: str,
    credential_encryption_key: str,
    s3_bucket_name: str,
    s3_access_key: str,
    s3_secret_key: str,
) -> Generator[_RuntimeWebStack, None, None]:
    """Start two-Control relay, Gateway, Main Web, and TLS edge."""
    configuration_revision = next(_CONFIGURATION_REVISIONS)
    with tempfile.TemporaryDirectory(prefix="runtime-web-e2e-") as temporary_root:
        certificate_path, private_key_path, config_path = _write_tls_edge_files(
            Path(temporary_root)
        )
        relay = _runtime_control_relay_container(
            image=server_image,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
            runner_image=runner_image,
            s3_bucket_name=s3_bucket_name,
            s3_access_key=s3_access_key,
            s3_secret_key=s3_secret_key,
        )
        gateway = _runtime_web_gateway_container(
            image=server_image,
            network=network,
            postgres=postgres,
            credential_encryption_key=credential_encryption_key,
            mode=mode,
            configuration_revision=configuration_revision,
        )
        main_web = _runtime_web_main_container(
            image=web_image,
            network=network,
            mode=mode,
        )
        edge = _runtime_web_edge_container(
            network=network,
            certificate_path=certificate_path,
            private_key_path=private_key_path,
            config_path=config_path,
        )
        selenium = _runtime_web_selenium_container(network=network)
        containers = [relay, gateway, main_web, edge, selenium]
        with ExitStack() as stack:
            stack.enter_context(relay)
            _wait_for_log(
                relay,
                "Runtime Control gRPC server started",
                name="Runtime Control relay",
            )
            stack.enter_context(gateway)
            _wait_for_http(
                gateway,
                port=8040,
                path="/__azents/ready",
                name="Runtime Web Gateway",
            )
            stack.enter_context(main_web)
            _wait_for_http(
                main_web,
                port=3000,
                path="/login",
                name="Runtime Web Main Web",
            )
            stack.enter_context(edge)
            stack.enter_context(selenium)
            try:
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
                selenium_host = selenium.get_container_host_ip()
                selenium_port = selenium.get_exposed_port(4444)
                selenium_url = f"http://{selenium_host}:{selenium_port}"
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        status = requests.get(
                            f"{selenium_url}/status",
                            timeout=2,
                        ).json()
                        if status.get("value", {}).get("ready") is True:
                            break
                    except requests.RequestException, ValueError:
                        pass
                    time.sleep(0.5)
                else:
                    selenium_logs = _container_logs(selenium)
                    raise AssertionError(
                        f"Runtime Web Selenium did not become ready:\n{selenium_logs}"
                    )
                yield _RuntimeWebStack(
                    main_origin=_MAIN_ORIGIN,
                    edge_ip=edge_ip,
                    edge_host_url=f"https://{edge_host}:{edge_port}",
                    selenium_url=selenium_url,
                )
            finally:
                for container in reversed(containers):
                    container.get_wrapped_container().reload()


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
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
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
    return """
from aiohttp import web

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

async def large(request):
    response = web.StreamResponse(headers={'Content-Type': 'application/octet-stream'})
    await response.prepare(request)
    chunk = b'x' * 65536
    for _ in range(1025):
        await response.write(chunk)
    await response.write_eof()
    return response

async def events(request):
    response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
    await response.prepare(request)
    await response.write(b'data: runtime-web-e2e\\n\\n')
    await response.write_eof()
    return response

async def redirect(request):
    raise web.HTTPFound('/')

async def websocket(request):
    socket = web.WebSocketResponse()
    await socket.prepare(request)
    async for message in socket:
        if message.type is web.WSMsgType.TEXT:
            await socket.send_str('echo:' + message.data)
            await socket.close()
    return socket

application = web.Application()
application.router.add_get('/', index)
application.router.add_post('/echo', echo)
application.router.add_get('/large', large)
application.router.add_get('/events', events)
application.router.add_get('/redirect', redirect)
application.router.add_get('/ws', websocket)
web.run_app(application, host='127.0.0.1', port=8765, handle_signals=False)
""".strip()


def _start_runtime_application(
    *,
    public_api_client: azentspublicclient.ApiClient,
    workspace: _RuntimeWebWorkspace,
    server_url: str,
) -> None:
    """Launch the fixture app through the supported Runtime Terminal product API."""
    terminal_workspace = _TerminalWorkspace(
        token=workspace.token,
        handle=workspace.handle,
        agent_id=workspace.agent_id,
        session_id=workspace.session_id,
    )
    terminal = _TerminalSocket.connect(
        public_api_client=public_api_client,
        workspace=terminal_workspace,
        server_url=server_url,
        origin=_TERMINAL_ORIGIN,
    )
    encoded = base64.b64encode(_runtime_application_script().encode()).decode()
    terminal.command(
        (
            "python -c \"import base64;exec(base64.b64decode('"
            f"{encoded}'))\" >/tmp/runtime-web-e2e.log 2>&1 & disown"
        ),
        f"APP_STARTED_{unique()}",
    )
    terminal.close()


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
    driver.set_script_timeout(120)
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


def _approve_in_browser(driver: WebDriver, *, endpoint_url: str) -> None:
    """Complete browser authentication and exact pending-request approval."""
    wait = WebDriverWait(driver, 60)
    driver.get(endpoint_url)
    wait.until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[normalize-space()='Review web service access']")
        )
    )
    wait.until(
        ec.element_to_be_clickable(
            (By.XPATH, "//button[starts-with(normalize-space(), 'Approve for ')]")
        )
    ).click()
    wait.until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[contains(normalize-space(), 'currently exposed')]")
        )
    )
    driver.get(endpoint_url)
    wait.until(
        ec.visibility_of_element_located(
            (By.XPATH, "//*[@id='ready' and normalize-space()='Runtime Web E2E ready']")
        )
    )


def _browser_transport_evidence(driver: WebDriver) -> dict[str, object]:
    """Exercise HTTP, SSE, WebSocket, redirects, and a 64 MiB streamed response."""
    result = driver.execute_async_script(
        """
const done = arguments[arguments.length - 1];
(async () => {
  const echo = await fetch('/echo', {method: 'POST', body: 'runtime-web-body'});
  const echoBody = await echo.json();
  const events = await fetch('/events');
  const eventsBody = await events.text();
  const redirected = await fetch('/redirect', {redirect: 'manual'});
  const large = await fetch('/large');
  const reader = large.body.getReader();
  let bytes = 0;
  while (true) {
    const part = await reader.read();
    if (part.done) break;
    bytes += part.value.byteLength;
  }
  const websocket = await new Promise((resolve, reject) => {
    const socket = new WebSocket(`${location.origin.replace('https:', 'wss:')}/ws`);
    socket.onopen = () => socket.send('runtime-web-socket');
    socket.onmessage = event => resolve(event.data);
    socket.onerror = () => reject(new Error('websocket failed'));
  });
  done({echoBody, eventsBody, redirectStatus: redirected.status, bytes, websocket});
})().catch(error => done({error: String(error)}));
"""
    )
    if not isinstance(result, dict):
        raise AssertionError(f"Browser transport evidence was invalid: {result!r}")
    return result


@pytest.mark.parametrize("auth_mode", ["shared_cookie", "separate_domain"])
def test_runtime_web_gateway_real_runtime_browser_and_cross_replica_relay(
    auth_mode: str,
    public_api_client: azentspublicclient.ApiClient,
    admin_api_client: azentsadminclient.ApiClient,
    azents_public_server_url: str,
    azents_runtime_provider_docker_container: DockerContainer,
    azents_runtime_control_container: DockerContainer,
    container_network: Network,
    postgres_container: PostgresContainer,
    azents_server_image: str,
    azents_web_image: str,
    azents_runtime_runner_image: str,
    credential_encryption_key: str,
    s3_bucket_name: str,
    rustfs_access_key: str,
    rustfs_secret_key: str,
) -> None:
    """Prove both auth modes, relay, revision fencing, and streamed transport."""
    del azents_runtime_provider_docker_container, azents_runtime_control_container
    workspace = _create_workspace(
        public_api_client=public_api_client,
        admin_api_client=admin_api_client,
        server_url=azents_public_server_url,
    )
    _start_runtime_application(
        public_api_client=public_api_client,
        workspace=workspace,
        server_url=azents_public_server_url,
    )

    with _runtime_web_stack(
        mode=auth_mode,
        network=container_network,
        postgres=postgres_container,
        server_image=azents_server_image,
        web_image=azents_web_image,
        runner_image=azents_runtime_runner_image,
        credential_encryption_key=credential_encryption_key,
        s3_bucket_name=s3_bucket_name,
        s3_access_key=rustfs_access_key,
        s3_secret_key=rustfs_secret_key,
    ) as stack:
        api = RuntimeWebV1Api(public_api_client)
        requested = api.runtime_web_v1_request_runtime_web_exposure(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            port=_RUNTIME_WEB_PORT,
            runtime_web_exposure_request=RuntimeWebExposureRequest(
                label=f"Gateway {auth_mode}",
                operation_key=f"request-{unique()}",
            ),
            _headers=_headers(workspace.token),
        )
        assert requested.current_request is not None
        assert requested.current_request.state is RuntimeWebRequestState.PENDING
        assert requested.endpoint.url is not None
        endpoint_url = requested.endpoint.url
        assert endpoint_url.startswith("https://")
        assert "?" not in endpoint_url
        assert "ticket" not in endpoint_url.lower()
        stable_endpoint_id = requested.endpoint.id

        driver = _browser(
            selenium_url=stack.selenium_url,
            edge_ip=stack.edge_ip,
        )
        try:
            _login(driver, email=workspace.email)
            _approve_in_browser(driver, endpoint_url=endpoint_url)
            active = api.runtime_web_v1_get_runtime_web_service_projection(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                session_id=workspace.session_id,
                port=_RUNTIME_WEB_PORT,
                _headers=_headers(workspace.token),
            )
            assert active.active
            assert active.current_cycle is not None
            assert active.endpoint.id == stable_endpoint_id
            assert active.endpoint.url == endpoint_url

            evidence = _browser_transport_evidence(driver)
            assert "error" not in evidence, evidence
            assert evidence["echoBody"] == {
                "body": "runtime-web-body",
                "method": "POST",
            }
            assert evidence["eventsBody"] == "data: runtime-web-e2e\n\n"
            assert evidence["redirectStatus"] == 302
            assert evidence["bytes"] == 1025 * 65_536
            assert evidence["websocket"] == "echo:runtime-web-socket"
            assert driver.current_url == endpoint_url
            assert "ticket" not in driver.current_url.lower()

            replacement = api.runtime_web_v1_request_runtime_web_exposure(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                session_id=workspace.session_id,
                port=_RUNTIME_WEB_PORT,
                runtime_web_exposure_request=RuntimeWebExposureRequest(
                    label=f"Replacement {auth_mode}",
                    operation_key=f"replacement-{unique()}",
                ),
                _headers=_headers(workspace.token),
            )
            assert replacement.active
            assert replacement.current_request is not None
            assert replacement.current_request.state is RuntimeWebRequestState.PENDING
            assert replacement.endpoint.url == endpoint_url
            with pytest.raises(ApiException) as stale_approval:
                api.runtime_web_v1_approve_runtime_web_request(
                    handle=workspace.handle,
                    agent_id=workspace.agent_id,
                    session_id=workspace.session_id,
                    request_id=replacement.current_request.id,
                    runtime_web_approval_request=RuntimeWebApprovalRequest(
                        expected_revision=replacement.current_request.revision + 1,
                        duration_seconds=replacement.duration_seconds,
                        duration_configuration_revision=(
                            replacement.duration_configuration_revision
                        ),
                        operation_key=f"stale-approve-{unique()}",
                    ),
                    _headers=_headers(workspace.token),
                )
            assert stale_approval.value.status == 409

            replaced = api.runtime_web_v1_approve_runtime_web_request(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                session_id=workspace.session_id,
                request_id=replacement.current_request.id,
                runtime_web_approval_request=RuntimeWebApprovalRequest(
                    expected_revision=replacement.current_request.revision,
                    duration_seconds=replacement.duration_seconds,
                    duration_configuration_revision=(
                        replacement.duration_configuration_revision
                    ),
                    operation_key=f"approve-replacement-{unique()}",
                ),
                _headers=_headers(workspace.token),
            )
            assert replaced.active
            assert replaced.current_cycle is not None
            assert active.current_cycle.id != replaced.current_cycle.id
            assert replaced.endpoint.id == stable_endpoint_id
            assert replaced.endpoint.url == endpoint_url

            closed = api.runtime_web_v1_close_runtime_web_cycle(
                handle=workspace.handle,
                agent_id=workspace.agent_id,
                session_id=workspace.session_id,
                cycle_id=replaced.current_cycle.id,
                runtime_web_close_request=RuntimeWebCloseRequest(
                    expected_endpoint_revision=replaced.endpoint.authority_revision,
                    operation_key=f"close-{unique()}",
                ),
                _headers=_headers(workspace.token),
            )
            assert not closed.active
            assert closed.endpoint.id == stable_endpoint_id
            assert closed.endpoint.url == endpoint_url
            status_after_close = driver.execute_async_script(
                "const done = arguments[arguments.length - 1];"
                "fetch('/', {cache: 'no-store'})"
                ".then(response => done(response.status))"
                ".catch(error => done(String(error)));"
            )
            assert status_after_close == 410
        finally:
            driver.quit()

        unauthenticated = requests.get(
            f"{stack.edge_host_url}/",
            headers={
                "Host": endpoint_url.removeprefix("https://").rstrip("/"),
                "User-Agent": "not-a-browser",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
            },
            verify=False,
            timeout=10,
            allow_redirects=False,
        )
        assert unauthenticated.status_code == 403

        listed = api.runtime_web_v1_list_runtime_web_services(
            handle=workspace.handle,
            agent_id=workspace.agent_id,
            session_id=workspace.session_id,
            _headers=_headers(workspace.token),
        )
        assert listed.total_count == 1
        assert listed.items[0].endpoint.id == stable_endpoint_id
        serialized = json.dumps(listed.items[0].to_dict(), default=str)
        assert "sk-runtime-web-gateway" not in serialized
        assert "ticket_secret" not in serialized
