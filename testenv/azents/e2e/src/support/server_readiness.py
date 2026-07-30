"""Readiness polling for E2E server containers."""

import time

import pytest
import requests
from testcontainers.core.container import DockerContainer

_SERVER_READY_TIMEOUT_SECONDS = 180.0
_SERVER_READY_REQUEST_TIMEOUT_SECONDS = 2.0
_SERVER_READY_POLL_INTERVAL_SECONDS = 1.0


def wait_for_server_ready(
    container: DockerContainer,
    port: int,
    server_name: str,
) -> str:
    """Wait for a running server container to report readiness."""
    host = container.get_container_host_ip()
    exposed_port = container.get_exposed_port(port)
    base_url = f"http://{host}:{exposed_port}"

    wrapped_container = container.get_wrapped_container()
    deadline = time.monotonic() + _SERVER_READY_TIMEOUT_SECONDS
    while True:
        wrapped_container.reload()
        if wrapped_container.status in {"exited", "dead"}:
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} exited\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        try:
            response = requests.get(
                f"{base_url}/health/v1/readiness",
                timeout=min(_SERVER_READY_REQUEST_TIMEOUT_SECONDS, remaining),
            )
            if response.status_code == 200:
                return base_url
        except requests.exceptions.RequestException:
            pass

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stdout, stderr = container.get_logs()
            pytest.fail(
                f"{server_name} did not start in time\n\n"
                f"stdout: {stdout.decode()}\n\nstderr: {stderr.decode()}"
            )
        time.sleep(min(_SERVER_READY_POLL_INTERVAL_SECONDS, remaining))
