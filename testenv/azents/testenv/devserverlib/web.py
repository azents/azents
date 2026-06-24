"""azents-web (Next.js) tmux session lifecycle helpers.

`devserver.py up --web` runs the azents-web dev server in a background tmux
session, mirroring the backend devserver pattern of tmux plus pipe-pane logging.

API:
- ``start_web(port=3003)`` — create tmux session and run ``turbo dev``
- ``stop_web(timeout=15)`` — graceful stop (SIGINT → fallback kill)
- ``is_web_running()`` — check tmux session existence
- ``wait_for_web_ready(port, timeout)`` — wait for HTTP 200

Stage 4 uses azents-web as the browser screen for Playwright MCP calls through
Claude Code. The devserver helper intentionally owns only the azents-web
lifecycle, not the MCP server lifecycle (Discussion #2441 P2).
"""

import time

import typer

from . import tmux
from .paths import (
    AZENTS_WEB_DIR,
    DEFAULT_WEB_PORT,
    STATE_DIR,
    TYPESCRIPT_DIR,
    WEB_LOG_FILE,
    WEB_SESSION_NAME,
)
from .readiness import probe_url


def is_web_running() -> bool:
    """Return whether the azents-web tmux session is running."""
    return tmux.has_session(WEB_SESSION_NAME)


def start_web(port: int = DEFAULT_WEB_PORT) -> None:  # noqa: ARG001 — port is fixed in package.json dev script
    """Start the azents-web dev server in a tmux session.

    Run ``turbo run dev --filter=@azents/web`` from the TypeScript
    monorepo root (``typescript/``). Turbo executes the ``generate → dev`` task
    chain, so generated clients such as ``azents-public-client/src/generated/``
    are refreshed before the dev server starts.
    """
    if is_web_running():
        typer.echo(f"web already running (session: {WEB_SESSION_NAME})")
        return

    if not AZENTS_WEB_DIR.is_dir():
        typer.echo(
            f"error: azents-web directory not found at {AZENTS_WEB_DIR}",
            err=True,
        )
        raise typer.Exit(code=1)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_LOG_FILE.touch(exist_ok=True)

    command = [
        "pnpm",
        "turbo",
        "run",
        "dev",
        "--filter=@azents/web",
    ]
    tmux.new_session(
        name=WEB_SESSION_NAME,
        cwd=TYPESCRIPT_DIR,
        env={
            # Default backend API URLs for azents-web development.
            "PUBLIC_API_URL": "http://localhost:8010",
            "INTERNAL_API_URL": "http://localhost:8010",
            "NODE_ENV": "development",
        },
        command=command,
    )
    tmux.pipe_pane_to_file(WEB_SESSION_NAME, WEB_LOG_FILE)


def stop_web(timeout: int = 15) -> None:
    """Gracefully stop the azents-web session, then kill on timeout."""
    if not is_web_running():
        return
    tmux.send_ctrl_c(WEB_SESSION_NAME)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_web_running():
            return
        time.sleep(0.5)
    tmux.kill_session(WEB_SESSION_NAME)


def wait_for_web_ready(port: int = DEFAULT_WEB_PORT, timeout: int = 60) -> bool:
    """Wait until ``http://localhost:{port}/`` returns HTTP 200."""
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.monotonic() < deadline:
        if probe_url(url):
            return True
        if not is_web_running():
            return False
        time.sleep(1.0)
    return False
