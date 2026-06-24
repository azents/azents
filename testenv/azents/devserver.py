#!/usr/bin/env python3
"""testenv/azents devserver CLI.

Manages the Azents devserver tmux session and health/state checks. See
`docs/azents/design/devserver-lifecycle.md` for details.

Usage (cwd: `testenv/azents`):
    cd testenv/azents
    uv run devserver.py COMMAND

The testenv CLI tools (`preflight.py`, `devserver.py`) assume `testenv/azents`
as the working directory. Internally they resolve paths from
`Path(__file__).resolve()`, but users should still run them from that cwd.
"""

import datetime as dt
import subprocess
import time

import typer

from testenv.devserverlib import tmux
from testenv.devserverlib.alembic import alembic_upgrade
from testenv.devserverlib.compose import compose_down, compose_up
from testenv.devserverlib.env import require_env
from testenv.devserverlib.paths import (
    AZENTS_DIR,
    DEFAULT_WEB_PORT,
    EXIT_ERROR,
    EXIT_NOT_RUNNING,
    EXIT_UNHEALTHY,
    LOG_FILE,
    SESSION_NAME,
    STATE_DIR,
    THIS_DIR,
    WEB_SESSION_NAME,
)
from testenv.devserverlib.readiness import probe_url, tail_log, wait_for_ready
from testenv.devserverlib.state import clear_state, read_state, write_state
from testenv.devserverlib.tmux import require_tmux
from testenv.devserverlib.web import (
    is_web_running,
    start_web,
    stop_web,
    wait_for_web_ready,
)
from testenv.fixture_worktree import current_worktree_fingerprint

app = typer.Typer(
    name="devserver",
    help="Azents testenv devserver lifecycle manager",
    no_args_is_help=True,
    add_completion=False,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _start_devserver(env: dict[str, str], *, reload: bool) -> None:
    """Create a tmux session, start devserver, and connect pipe-pane logging."""
    command = ["uv", "run", "python", "src/cli/devserver.py"]
    if reload:
        command.append("--reload")
    worktree = current_worktree_fingerprint(THIS_DIR)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)

    tmux.new_session(
        name=SESSION_NAME,
        cwd=AZENTS_DIR,
        env=env,
        command=command,
    )
    tmux.pipe_pane_to_file(SESSION_NAME, LOG_FILE)

    write_state(
        {
            "schema_version": 1,
            "session_name": SESSION_NAME,
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "command": command,
            "cwd": str(AZENTS_DIR),
            "reload": reload,
            "public_port": int(env.get("AZ_PUBLIC_API_PORT", "8010")),
            "admin_port": int(env.get("AZ_ADMIN_API_PORT", "8011")),
            "repo_root": worktree.repo_root,
            "head_sha": worktree.head_sha,
            "worktree_fingerprint": worktree.model_dump(mode="json"),
            "started_by": "devserver.py up",
        }
    )


def _graceful_shutdown(*, timeout: int) -> bool:
    """Send C-c, wait until timeout, then force-kill the tmux session."""
    if not tmux.has_session(SESSION_NAME):
        return True
    tmux.send_ctrl_c(SESSION_NAME)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not tmux.has_session(SESSION_NAME):
            return True
        time.sleep(0.5)
    typer.echo(
        f"warning: graceful shutdown timed out after {timeout}s, killing session",
        err=True,
    )
    tmux.kill_session(SESSION_NAME)
    return False


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def up(
    force: bool = typer.Option(False, "--force", help="restart even if already running"),
    timeout: int = typer.Option(60, "--timeout", help="readiness wait timeout (seconds)"),
    reload: bool = typer.Option(False, "--reload", help="run devserver with uvicorn --reload"),
    no_infra: bool = typer.Option(False, "--no-infra", help="skip docker compose up"),
    no_migrate: bool = typer.Option(False, "--no-migrate", help="skip alembic upgrade"),
    web: bool = typer.Option(False, "--web", help="also start azents-web (Next.js, port 3003)"),
) -> None:
    """Start infra and devserver, wait until ready."""
    require_tmux()
    env = require_env()
    public_port = int(env.get("AZ_PUBLIC_API_PORT", "8010"))
    admin_port = int(env.get("AZ_ADMIN_API_PORT", "8011"))

    running = tmux.has_session(SESSION_NAME)
    state = read_state()

    if running and not force:
        public_ok = probe_url(f"http://127.0.0.1:{public_port}/health/v1/readiness")
        admin_ok = probe_url(f"http://127.0.0.1:{admin_port}/health/v1/readiness")
        if public_ok and admin_ok:
            typer.echo(f"devserver already running and healthy (session: {SESSION_NAME})")
            return
        typer.echo(
            f"warning: session alive but unhealthy (public={public_ok} admin={admin_ok}),"
            " restarting",
            err=True,
        )
        _graceful_shutdown(timeout=30)
        running = False

    if running and force:
        typer.echo("--force: stopping existing session before restart", err=True)
        _graceful_shutdown(timeout=30)

    if not running and state is not None:
        typer.echo(
            "warning: stale state file detected (session missing), cleaning up",
            err=True,
        )
        clear_state()

    if not no_infra:
        try:
            compose_up()
        except subprocess.CalledProcessError as exc:
            typer.echo(f"error: docker compose up failed: {exc}", err=True)
            raise typer.Exit(code=EXIT_ERROR) from exc

    if not no_migrate:
        try:
            alembic_upgrade(env)
        except subprocess.CalledProcessError as exc:
            typer.echo(f"error: alembic upgrade failed: {exc}", err=True)
            raise typer.Exit(code=EXIT_ERROR) from exc

    _start_devserver(env, reload=reload)
    typer.echo(f"devserver started in tmux session '{SESSION_NAME}'")

    ok, reason = wait_for_ready(
        public_port=public_port,
        admin_port=admin_port,
        timeout=timeout,
        session_alive=lambda: tmux.has_session(SESSION_NAME),
    )
    if not ok:
        typer.echo(f"error: devserver not ready: {reason}", err=True)
        typer.echo("--- last 50 lines of devserver.log ---", err=True)
        typer.echo(tail_log(50), err=True)
        if tmux.has_session(SESSION_NAME):
            tmux.kill_session(SESSION_NAME)
        clear_state()
        raise typer.Exit(code=EXIT_ERROR)

    typer.echo(f"ready (public=http://localhost:{public_port} admin=http://localhost:{admin_port})")
    typer.echo(f"  attach: tmux attach -t {SESSION_NAME}")
    typer.echo("  logs:   (cd testenv/azents && uv run devserver.py logs -f)")

    if web:
        start_web(port=DEFAULT_WEB_PORT)
        typer.echo(f"web started in tmux session '{WEB_SESSION_NAME}'")
        if wait_for_web_ready(port=DEFAULT_WEB_PORT, timeout=timeout):
            typer.echo(f"  web:   http://localhost:{DEFAULT_WEB_PORT}")
        else:
            typer.echo("warning: azents-web did not become ready in time", err=True)
        typer.echo(f"  attach: tmux attach -t {WEB_SESSION_NAME}")


@app.command()
def down(
    all_services: bool = typer.Option(False, "--all", help="also stop docker compose (Phase 4)"),
    force: bool = typer.Option(False, "--force", help="kill immediately without graceful wait"),
) -> None:
    """Graceful stop devserver."""
    require_tmux()

    if not tmux.has_session(SESSION_NAME):
        if read_state() is not None:
            clear_state()
        typer.echo("devserver not running")
        return

    if force:
        tmux.kill_session(SESSION_NAME)
        typer.echo(f"devserver killed (session: {SESSION_NAME})")
    else:
        _graceful_shutdown(timeout=30)
        typer.echo(f"devserver stopped (session: {SESSION_NAME})")

    clear_state()

    if is_web_running():
        stop_web()
        typer.echo(f"web stopped (session: {WEB_SESSION_NAME})")

    if all_services:
        compose_down()


@app.command()
def restart(
    web: bool = typer.Option(False, "--web", help="also restart azents-web"),
) -> None:
    """Alias for `up --force` (optionally with --web)."""
    up(
        force=True,
        timeout=60,
        reload=False,
        no_infra=False,
        no_migrate=False,
        web=web,
    )


@app.command()
def status() -> None:
    """Show devserver status (exit 0 ready / 1 unhealthy / 2 not running)."""
    require_tmux()

    running = tmux.has_session(SESSION_NAME)
    state = read_state()

    if not running:
        if state is not None:
            typer.echo("devserver: not running (stale state file present)")
        else:
            typer.echo("devserver: not running")
        raise typer.Exit(code=EXIT_NOT_RUNNING)

    public_port = 8010
    admin_port = 8011
    if state is not None:
        public_port_val = state.get("public_port", public_port)
        admin_port_val = state.get("admin_port", admin_port)
        if isinstance(public_port_val, int):
            public_port = public_port_val
        if isinstance(admin_port_val, int):
            admin_port = admin_port_val

    public_ok = probe_url(f"http://127.0.0.1:{public_port}/health/v1/readiness")
    admin_ok = probe_url(f"http://127.0.0.1:{admin_port}/health/v1/readiness")

    if public_ok and admin_ok:
        typer.echo("devserver: running")
        exit_code = 0
    else:
        typer.echo("devserver: unhealthy")
        exit_code = EXIT_UNHEALTHY

    typer.echo(f"  session: {SESSION_NAME}")
    if state is not None:
        started = state.get("started_at")
        if isinstance(started, str):
            typer.echo(f"  started: {started}")
        reload_flag = state.get("reload")
        if reload_flag is not None:
            typer.echo(f"  reload:  {reload_flag}")
    public_mark = "200 OK" if public_ok else "unreachable"
    admin_mark = "200 OK" if admin_ok else "unreachable"
    typer.echo(f"  public:  http://localhost:{public_port}  ({public_mark})")
    typer.echo(f"  admin:   http://localhost:{admin_port}  ({admin_mark})")

    if is_web_running():
        web_ok = probe_url(f"http://127.0.0.1:{DEFAULT_WEB_PORT}/")
        web_mark = "200 OK" if web_ok else "unreachable"
        typer.echo(f"  web:     http://localhost:{DEFAULT_WEB_PORT}  ({web_mark})")
    else:
        typer.echo("  web:     not running")

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


@app.command()
def logs(
    follow: bool = typer.Option(False, "-f", "--follow", help="follow log output"),
    lines: int = typer.Option(50, "-n", "--lines", help="number of last lines to show"),
) -> None:
    """Tail .state/devserver.log."""
    if not LOG_FILE.is_file():
        typer.echo(f"no log file at {LOG_FILE}", err=True)
        raise typer.Exit(code=EXIT_ERROR)

    if not follow:
        typer.echo(tail_log(lines))
        return

    # Follow mode uses POSIX `tail -f` directly.
    try:
        subprocess.run(
            ["tail", "-n", str(lines), "-f", str(LOG_FILE)],
            check=False,
        )
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    app()
