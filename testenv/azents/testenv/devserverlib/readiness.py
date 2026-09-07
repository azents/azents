"""Readiness probes and log tail helpers."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from typing import Callable

from .paths import LOG_FILE


def probe_url(url: str, *, timeout: float = 2.0) -> bool:
    """Return True for HTTP 200 and False for all other outcomes."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code == 200
    except urllib.error.URLError, OSError:
        return False


def probe_port(host: str, port: int, *, timeout: float = 2.0) -> bool:
    """Return whether one TCP listener accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_ready(
    *,
    public_port: int,
    admin_port: int,
    runtime_control_port: int,
    timeout: int,
    session_alive: Callable[[], bool],
) -> tuple[bool, str]:
    """Wait for API and Runtime Control readiness while the session stays alive.

    - Poll every 0.5 seconds.
    - Both HTTP endpoints must return 200 and Runtime Control must accept TCP.
    - Fail early when `session_alive()` returns False, which usually means the
      devserver process exited.
    """
    public_url = f"http://127.0.0.1:{public_port}/health/v1/readiness"
    admin_url = f"http://127.0.0.1:{admin_port}/health/v1/readiness"
    deadline = time.monotonic() + timeout
    public_ok = False
    admin_ok = False
    runtime_control_ok = False

    while time.monotonic() < deadline:
        if not session_alive():
            return False, "devserver session died"
        public_ok = probe_url(public_url)
        admin_ok = probe_url(admin_url)
        runtime_control_ok = probe_port("127.0.0.1", runtime_control_port)
        if public_ok and admin_ok and runtime_control_ok:
            return True, ""
        time.sleep(0.5)

    return (
        False,
        f"readiness timeout after {timeout}s "
        f"(public={public_ok} admin={admin_ok} runtime_control={runtime_control_ok})",
    )


def tail_log(lines: int = 50) -> str:
    """Read the last N lines from `.state/devserver.log`."""
    if not LOG_FILE.is_file():
        return "(log file not found)"
    try:
        text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"(failed to read log: {exc})"
    tail = text.splitlines()[-lines:]
    return "\n".join(tail)
