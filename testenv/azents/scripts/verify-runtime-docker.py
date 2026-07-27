#!/usr/bin/env python3
"""Verify ordinary Docker workflows through the Runtime-private DIND socket."""

from __future__ import annotations

import shlex
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DOCKER_CLI_IMAGE = (
    "docker:28.5.2-cli@sha256:625d9431a9f54c5a2bc90f24f0e1c3d55b1349fd857dd85035f98c2c9acbdd4d"
)
PYTHON_IMAGE = (
    "python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6"
)
POSTGRES_IMAGE = (
    "postgres:17-alpine@sha256:742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)
ENGINE_SOCKET_PATH = "/var/run/azents-engine/docker.sock"


def _run(
    command: list[str],
    *,
    input_text: str | None = None,
    capture_output: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    print(f"+ {shlex.join(command)}", flush=True)
    return subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=capture_output,
        check=check,
    )


def _client_command(
    *,
    engine_name: str,
    socket_volume: str,
    image: str,
    connection_mode: bool = False,
) -> list[str]:
    command = [
        "docker",
        "run",
        "--rm",
        "--interactive",
        "--user",
        "1000:1000",
        "--network",
        f"container:{engine_name}",
        "--volume",
        f"{socket_volume}:/var/run/azents-engine:ro",
        "--env",
        "HOME=/tmp",
        "--env",
        f"DOCKER_HOST=unix://{ENGINE_SOCKET_PATH}",
    ]
    if connection_mode:
        command.extend(
            [
                "--env",
                "TESTCONTAINERS_HOST_OVERRIDE=127.0.0.1",
                "--env",
                "TESTCONTAINERS_CONNECTION_MODE=docker_host",
                "--env",
                f"TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE={ENGINE_SOCKET_PATH}",
            ]
        )
    return [*command, image]


def _wait_for_engine(client: list[str], engine_name: str) -> None:
    last_error = ""
    for _ in range(60):
        completed = _run(
            [*client, "docker", "version"],
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            print(completed.stdout, end="")
            return
        last_error = completed.stderr
        time.sleep(1)
    _run(["docker", "logs", "--tail", "200", engine_name], check=False)
    raise RuntimeError(f"DIND did not become ready: {last_error}")


def _verify_cli(client: list[str]) -> None:
    dockerfile = textwrap.dedent(
        """
        FROM alpine:3.22
        RUN printf azents-runtime-docker-ok > /proof
        CMD ["cat", "/proof"]
        """
    )
    _run(
        [*client, "docker", "build", "--tag", "azents-runtime-docker-proof:latest", "-"],
        input_text=dockerfile,
    )
    result = _run(
        [*client, "docker", "run", "--rm", "azents-runtime-docker-proof:latest"],
        capture_output=True,
    )
    if result.stdout.strip() != "azents-runtime-docker-ok":
        raise RuntimeError(f"Unexpected Docker run output: {result.stdout!r}")

    compose = textwrap.dedent(
        """
        services:
          proof:
            image: azents-runtime-docker-proof:latest
            command: ["cat", "/proof"]
        """
    )
    compose_command = [
        *client,
        "docker",
        "compose",
        "--project-name",
        "azents-runtime-docker-proof",
        "-f",
        "-",
    ]
    _run(
        [*compose_command, "up", "--abort-on-container-exit", "--exit-code-from", "proof"],
        input_text=compose,
    )
    _run([*compose_command, "down", "--remove-orphans"], input_text=compose)
    print("DOCKER_CLI_BUILD_RUN_COMPOSE_OK")


def _build_python_client(image: str) -> None:
    dockerfile = textwrap.dedent(
        f"""
        FROM {PYTHON_IMAGE}
        RUN pip install --no-cache-dir \
          'docker==7.1.0' \
          'testcontainers==4.14.0' \
          'psycopg[binary]==3.2.13'
        """
    )
    _run(["docker", "build", "--tag", image, "-"], input_text=dockerfile)


def _verify_python_clients(client: list[str]) -> None:
    script = textwrap.dedent(
        f"""
        import docker
        import psycopg
        from testcontainers.core.network import Network
        from testcontainers.postgres import PostgresContainer

        docker_client = docker.from_env()
        assert docker_client.ping()
        print(f"DOCKER_SDK_OK version={{docker_client.version()['Version']}}")

        with Network() as network:
            assert network.id is not None
            docker_client.networks.get(network.id)
        print("TESTCONTAINERS_NETWORK_OK")

        with PostgresContainer({POSTGRES_IMAGE!r}) as postgres:
            assert postgres.get_container_host_ip() == "127.0.0.1"
            with psycopg.connect(
                host="127.0.0.1",
                port=int(postgres.get_exposed_port(5432)),
                user=postgres.username,
                password=postgres.password,
                dbname=postgres.dbname,
            ) as connection:
                assert connection.execute("SELECT 1").fetchone() == (1,)
            ryuk = [
                container
                for container in docker_client.containers.list()
                if container.name.startswith("testcontainers-ryuk-")
            ]
            assert len(ryuk) == 1
        print("TESTCONTAINERS_POSTGRES_PORT_BINDING_RYUK_OK")
        """
    )
    _run([*client, "python", "-"], input_text=script)


def main() -> int:
    """Create an isolated DIND, verify clients, and remove owned resources."""
    _run(["docker", "info"], capture_output=True)
    suffix = uuid.uuid4().hex[:12]
    engine_name = f"azents-runtime-docker-verify-{suffix}"
    socket_volume = f"{engine_name}-socket"
    data_volume = f"{engine_name}-data"
    engine_image = f"{engine_name}-engine:latest"
    python_image = f"{engine_name}-python:latest"

    try:
        _run(
            [
                "docker",
                "build",
                "--tag",
                engine_image,
                str(REPOSITORY_ROOT / "images" / "azents-runtime-engine"),
            ]
        )
        _run(["docker", "volume", "create", socket_volume])
        _run(["docker", "volume", "create", data_volume])
        _run(
            [
                "docker",
                "run",
                "--detach",
                "--privileged",
                "--name",
                engine_name,
                "--volume",
                f"{socket_volume}:/var/run/azents-engine",
                "--volume",
                f"{data_volume}:/var/lib/docker",
                engine_image,
                f"--host=unix://{ENGINE_SOCKET_PATH}",
                "--group=azents-runner",
                "--data-root=/var/lib/docker",
            ]
        )

        cli_client = _client_command(
            engine_name=engine_name,
            socket_volume=socket_volume,
            image=DOCKER_CLI_IMAGE,
        )
        _wait_for_engine(cli_client, engine_name)
        _verify_cli(cli_client)

        _build_python_client(python_image)
        python_client = _client_command(
            engine_name=engine_name,
            socket_volume=socket_volume,
            image=python_image,
            connection_mode=True,
        )
        _verify_python_clients(python_client)
        print("RUNTIME_DOCKER_WORKFLOW_OK")
        return 0
    finally:
        _run(["docker", "rm", "--force", engine_name], check=False)
        _run(["docker", "volume", "rm", socket_volume], check=False)
        _run(["docker", "volume", "rm", data_volume], check=False)
        _run(["docker", "image", "rm", engine_image], check=False)
        _run(["docker", "image", "rm", python_image], check=False)


if __name__ == "__main__":
    sys.exit(main())
