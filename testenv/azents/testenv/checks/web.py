"""Stage 4 azents-web preflight checks.

`devserver.py up --web` starts the azents-web Next.js app and needs:

- node and pnpm installed
- ``typescript/apps/azents-web/node_modules`` from pnpm install
- port 3003 available

Stage 4 may also use Playwright MCP through Claude Code (Discussion #2441 P1),
including the Playwright MCP HTTP server, port 8931, and Chromium. Playwright is
configured separately in ``testenv/azents/.claude/settings.json``.
"""

import shutil
import socket
import subprocess

from testenv.devserverlib.paths import AZENTS_WEB_DIR, DEFAULT_WEB_PORT

from .base import Check, CheckResult, RunContext, Status


class NodeInstalled(Check):
    """Check whether Node.js exists in PATH and is at least v22."""

    def __init__(self) -> None:
        super().__init__(
            id="node-installed",
            name="Node.js installed (>=22)",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        if shutil.which("node") is None:
            return CheckResult(
                status=Status.FAIL,
                message="node not found in PATH",
                fix_hint="Install Node.js 22+ (https://nodejs.org)",
            )
        completed = subprocess.run(
            ["node", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return CheckResult(
                status=Status.FAIL,
                message="`node --version` failed",
                fix_hint="Reinstall Node.js",
            )
        version = completed.stdout.strip().lstrip("v")
        major_str = version.split(".", 1)[0]
        try:
            major = int(major_str)
        except ValueError:
            return CheckResult(
                status=Status.FAIL,
                message=f"unrecognized node version: {version}",
            )
        if major < 22:
            return CheckResult(
                status=Status.FAIL,
                message=f"node {version} (need >=22)",
                fix_hint="Upgrade to Node.js 22+",
            )
        return CheckResult(status=Status.PASS, message=f"v{version}")


class PnpmInstalled(Check):
    """Check whether pnpm is installed and executable."""

    def __init__(self) -> None:
        super().__init__(
            id="pnpm-installed",
            name="pnpm installed",
            category="system",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        if shutil.which("pnpm") is None:
            return CheckResult(
                status=Status.FAIL,
                message="pnpm not found in PATH",
                fix_hint="Install with `npm install -g pnpm` or `corepack enable`",
            )
        completed = subprocess.run(
            ["pnpm", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return CheckResult(status=Status.FAIL, message="`pnpm --version` failed")
        return CheckResult(status=Status.PASS, message=completed.stdout.strip())


class NointernWebDepsInstalled(Check):
    """Check whether azents-web node_modules are installed."""

    def __init__(self) -> None:
        super().__init__(
            id="azents-web-deps-installed",
            name="azents-web node_modules installed",
            category="config",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        node_modules = AZENTS_WEB_DIR / "node_modules"
        if not node_modules.is_dir():
            return CheckResult(
                status=Status.FAIL,
                message=f"node_modules missing at {node_modules}",
                fix_hint="cd typescript && pnpm install --filter @azents/web...",
            )
        return CheckResult(status=Status.PASS)


class NointernWebPortFree(Check):
    """Check whether the azents-web port is free."""

    def __init__(self) -> None:
        super().__init__(
            id="azents-web-port-free",
            name=f"azents-web port free ({DEFAULT_WEB_PORT})",
            category="ports",
        )

    def run(self, context: RunContext) -> CheckResult:
        del context
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", DEFAULT_WEB_PORT))
            except OSError:
                return CheckResult(
                    status=Status.FAIL,
                    message=f"port {DEFAULT_WEB_PORT} in use",
                    fix_hint=f"Stop existing process. `lsof -i :{DEFAULT_WEB_PORT}`",
                )
            return CheckResult(status=Status.PASS)
        finally:
            sock.close()
