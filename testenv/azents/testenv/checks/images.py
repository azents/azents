"""Docker socket accessibility checks.

`docker-socket-accessible` complements the system-level `DockerRunning` check.
`DockerRunning` verifies that the daemon exists; this check verifies that the
current user can access the Docker socket, which is required for local testenv
containers.
"""

import subprocess

from .base import Check, CheckResult, RunContext, Status


class DockerSocketAccessible(Check):
    """Check whether the current user can access the Docker socket."""

    def __init__(self) -> None:
        super().__init__(
            id="docker-socket-accessible",
            name="Docker socket accessible",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        completed = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return CheckResult(status=Status.PASS)
        return CheckResult(
            status=Status.FAIL,
            message="`docker ps` failed — socket not accessible",
            fix_hint=(
                "Start Docker and ensure your user is in the docker group "
                "(e.g. `sudo usermod -aG docker $USER` then log out/in)"
            ),
        )
