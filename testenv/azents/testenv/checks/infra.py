"""Infrastructure preflight checks.

Checks whether Docker Compose-managed services (Postgres, Valkey, RustFS) are
running and reachable. These checks are read-only: they inspect state and probe
services, but do not start containers with `docker compose up`.
"""

from __future__ import annotations

import json
import socket
import subprocess
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .base import Check, CheckResult, RunContext, Status

# Use the testenv/azents compose file, not docker-compose.azents.yaml. Resolve the
# path from `Path(__file__).resolve()` so it does not depend on cwd.
_TESTENV_DIR = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = str(_TESTENV_DIR / "docker-compose.yaml")
_COMPOSE_PROJECT = "azents-testenv"
# Fix hints are written as commands users can run from the repository root.
_COMPOSE_UP_HINT = "docker compose -f testenv/azents/docker-compose.yaml up -d"


class PostgresContainerHealthy(Check):
    """Check whether `docker compose ps db` reports a running DB container."""

    def __init__(self) -> None:
        super().__init__(
            id="postgres-container-healthy",
            name="Postgres container running",
            category="infra",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        completed = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                _COMPOSE_FILE,
                "-p",
                _COMPOSE_PROJECT,
                "ps",
                "--format",
                "json",
                "db",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return CheckResult(
                status=Status.FAIL,
                message=completed.stderr.strip() or "docker compose ps failed",
                fix_hint=_COMPOSE_UP_HINT + " db",
            )
        stdout = completed.stdout.strip()
        if not stdout:
            return CheckResult(
                status=Status.FAIL,
                message="db service not found in compose project",
                fix_hint=_COMPOSE_UP_HINT + " db",
            )
        # Docker Compose v2 may return JSON lines or a JSON array. Handle both.
        try:
            if stdout.startswith("["):
                rows = json.loads(stdout)
            else:
                rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        except json.JSONDecodeError as exc:
            return CheckResult(
                status=Status.FAIL,
                message=f"failed to parse compose ps output: {exc}",
                fix_hint="Check docker compose version (v2 required)",
            )
        if not rows:
            return CheckResult(
                status=Status.FAIL,
                message="db container not present",
                fix_hint=_COMPOSE_UP_HINT + " db",
            )
        state = rows[0].get("State", "").lower()
        if state == "running":
            return CheckResult(status=Status.PASS)
        return CheckResult(
            status=Status.FAIL,
            message=f"db container state: {state or 'unknown'}",
            fix_hint=_COMPOSE_UP_HINT + " db",
        )


class PostgresConnectable(Check):
    """Use psycopg from the Azents venv to verify an actual DB connection."""

    def __init__(self) -> None:
        super().__init__(
            id="postgres-connectable",
            name="Postgres connectable",
            category="infra",
            depends_on=[
                "python-deps-installed",
                "postgres-container-healthy",
                "required-env-vars",
            ],
        )

    def run(self, context: RunContext) -> CheckResult:
        script = textwrap.dedent(
            """
            import os
            import psycopg

            psycopg.connect(
                host=os.environ["AZ_RDB_HOST"],
                port=int(os.environ["AZ_RDB_PORT"]),
                user=os.environ["AZ_RDB_USER"],
                password=os.environ["AZ_RDB_PASSWORD"],
                dbname=os.environ["AZ_RDB_DB_NAME"],
                connect_timeout=3,
            ).close()
            """
        )
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(context.azents_dir),
                "python",
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return CheckResult(status=Status.PASS)
        err = (
            completed.stderr.strip() or completed.stdout.strip() or "connection failed"
        ).splitlines()[-1]
        return CheckResult(
            status=Status.FAIL,
            message=err[:200],
            fix_hint="Verify AZ_RDB_* values and that the db container is healthy",
        )


class ValkeyReachable(Check):
    """Open a TCP connection to the host and port from `AZ_REDIS_URL`."""

    def __init__(self) -> None:
        super().__init__(
            id="valkey-reachable",
            name="Valkey reachable",
            category="infra",
        )

    def run(self, context: RunContext) -> CheckResult:
        url = context.env.get("AZ_REDIS_URL", "")
        if not url:
            return CheckResult(
                status=Status.FAIL,
                message="AZ_REDIS_URL not set",
                fix_hint="Set AZ_REDIS_URL in .env",
            )
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 6379
        try:
            with socket.create_connection((host, port), timeout=2):
                pass
        except OSError as exc:
            return CheckResult(
                status=Status.FAIL,
                message=f"{host}:{port} unreachable ({exc})",
                fix_hint=_COMPOSE_UP_HINT + " valkey",
            )
        return CheckResult(status=Status.PASS, message=f"{host}:{port}")


class RustfsReachable(Check):
    """Call the RustFS health endpoint and fall back to a TCP probe on failure."""

    def __init__(self) -> None:
        super().__init__(
            id="rustfs-reachable",
            name="RustFS reachable",
            category="infra",
        )

    def run(self, context: RunContext) -> CheckResult:
        endpoint = context.env.get("AZ_WORKSPACE_S3_ENDPOINT_URL", "")
        if not endpoint:
            return CheckResult(
                status=Status.FAIL,
                message="AZ_WORKSPACE_S3_ENDPOINT_URL not set",
                fix_hint="Set AZ_WORKSPACE_S3_ENDPOINT_URL in .env",
            )
        health_url = endpoint.rstrip("/") + "/minio/health/live"
        health_error: urllib.error.URLError | OSError | None = None
        try:
            with urllib.request.urlopen(health_url, timeout=2) as resp:
                if 200 <= resp.status < 500:
                    return CheckResult(status=Status.PASS, message=f"HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            if exc.code < 500:
                return CheckResult(status=Status.PASS, message=f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError) as exc:
            health_error = exc
        parsed = urllib.parse.urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((host, port), timeout=2):
                return CheckResult(
                    status=Status.WARN,
                    message=(f"health endpoint unreachable, TCP {host}:{port} ok ({health_error})"),
                )
        except OSError as exc:
            return CheckResult(
                status=Status.FAIL,
                message=f"{host}:{port} unreachable ({exc})",
                fix_hint=_COMPOSE_UP_HINT + " rustfs",
            )
