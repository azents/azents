"""Port preflight checks.

Checks whether the devserver ports (8010, 8011) are free. Container ports such
as 5433, 6379, and 9000 are validated by Docker Compose health/status checks.
"""

import socket

from .base import Check, CheckResult, RunContext, Status

_DEVSERVER_PORTS = (8010, 8011)


class DevserverPortsFree(Check):
    """Check whether devserver ports are free."""

    def __init__(self) -> None:
        super().__init__(
            id="devserver-ports-free",
            name="Devserver ports free (8010, 8011)",
            category="ports",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        busy: list[int] = []
        for port in _DEVSERVER_PORTS:
            if not _port_available(port):
                busy.append(port)
        if not busy:
            return CheckResult(status=Status.PASS)
        return CheckResult(
            status=Status.FAIL,
            message=f"ports in use: {', '.join(str(p) for p in busy)}",
            fix_hint=f"Stop existing devserver. `lsof -i :{busy[0]}`",
        )


def _port_available(port: int) -> bool:
    """Return whether a local bind to the port succeeds."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True
    finally:
        sock.close()
