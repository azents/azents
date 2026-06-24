"""System preflight checks."""

import shutil
import subprocess
import sys

from .base import Check, CheckResult, RunContext, Status


class RepoRoot(Check):
    """Check whether the current task is running inside the git repository.

    The `.git` marker may be a directory or a file. Worktrees use a `.git`
    file, while a normal clone usually has a `.git` directory.
    """

    def __init__(self) -> None:
        super().__init__(
            id="repo-root",
            name="Git repo root detected",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        marker = context.repo_root / ".git"
        if marker.exists():
            return CheckResult(status=Status.PASS, message=str(context.repo_root))
        return CheckResult(
            status=Status.FAIL,
            message=f".git not found in {context.repo_root}",
            fix_hint="Run from the monorepo root",
        )


class DockerRunning(Check):
    """Check whether the Docker daemon is running with `docker info`."""

    def __init__(self) -> None:
        super().__init__(
            id="docker-running",
            name="Docker daemon running",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        if shutil.which("docker") is None:
            return CheckResult(
                status=Status.FAIL,
                message="docker CLI not found",
                fix_hint="Install Docker Desktop or docker engine",
            )
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            return CheckResult(status=Status.PASS)
        return CheckResult(
            status=Status.FAIL,
            message="docker info failed",
            fix_hint="Start Docker Desktop or `sudo systemctl start docker`",
        )


class DockerComposeAvailable(Check):
    """Check whether Docker Compose v2 is available."""

    def __init__(self) -> None:
        super().__init__(
            id="docker-compose-available",
            name="Docker Compose v2 available",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        completed = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            message = completed.stdout.strip().splitlines()[0] if completed.stdout else ""
            return CheckResult(status=Status.PASS, message=message)
        return CheckResult(
            status=Status.FAIL,
            message="`docker compose version` failed",
            fix_hint="Install docker compose v2 plugin",
        )


class UvInstalled(Check):
    """Check whether `uv` is installed and in PATH."""

    def __init__(self) -> None:
        super().__init__(
            id="uv-installed",
            name="uv installed",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        path = shutil.which("uv")
        if path:
            return CheckResult(status=Status.PASS, message=path)
        return CheckResult(
            status=Status.FAIL,
            message="uv not in PATH",
            fix_hint="curl -LsSf https://astral.sh/uv/install.sh | sh",
        )


class TmuxInstalled(Check):
    """Check whether `tmux` is installed.

    The Stage 1b devserver runs in a tmux session, so the devserver lifecycle
    manager requires `tmux` to be available in PATH.
    """

    def __init__(self) -> None:
        super().__init__(
            id="tmux-installed",
            name="tmux installed",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        path = shutil.which("tmux")
        if path:
            return CheckResult(status=Status.PASS, message=path)
        return CheckResult(
            status=Status.FAIL,
            message="tmux not in PATH",
            fix_hint="brew install tmux (macOS) | sudo apt install tmux (Debian/Ubuntu)",
        )


class PythonVersion(Check):
    """Check whether Python 3.14 is available."""

    def __init__(self) -> None:
        super().__init__(
            id="python-version",
            name="Python 3.14 available",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        if sys.version_info[:2] == (3, 14):
            return CheckResult(
                status=Status.PASS,
                message=f"current interpreter {sys.version.split()[0]}",
            )
        if shutil.which("python3.14"):
            return CheckResult(
                status=Status.PASS,
                message="python3.14 found in PATH",
            )
        return CheckResult(
            status=Status.FAIL,
            message=f"Python 3.14 not available (current: {sys.version.split()[0]})",
            fix_hint="Install Python 3.14 via pyenv/mise/uv",
        )


class PythonDepsInstalled(Check):
    """Check whether Azents Python dependencies are installed.

    This first checks that `.venv` exists, then verifies the actual import path
    with `uv run --project <azents> python -c 'import azents'`. This catches
    broken editable installs or missing site-packages entries.
    """

    def __init__(self) -> None:
        super().__init__(
            id="python-deps-installed",
            name="azents python deps installed",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        venv = context.azents_dir / ".venv"
        if not venv.is_dir():
            return CheckResult(
                status=Status.FAIL,
                message=".venv not found",
                fix_hint="cd python/apps/azents && uv sync",
            )
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(context.azents_dir),
                "python",
                "-c",
                "import azents",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return CheckResult(
                status=Status.FAIL,
                message="`import azents` failed",
                fix_hint="cd python/apps/azents && uv sync",
            )
        return CheckResult(status=Status.PASS, message=str(venv))
