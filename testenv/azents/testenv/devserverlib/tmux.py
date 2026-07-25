"""tmux session helpers.

Calls the tmux CLI through subprocesses. Paths passed to tmux should be absolute
so calls are independent of pane cwd; see the paths module.
"""

import shutil
import subprocess
from pathlib import Path

import typer

from .paths import EXIT_ERROR


def require_tmux() -> None:
    """Require tmux or raise typer.Exit with user guidance."""
    if shutil.which("tmux") is None:
        typer.echo(
            "error: tmux not found in PATH. Install with `brew install tmux` (macOS)"
            " or `sudo apt install tmux` (Debian/Ubuntu).",
            err=True,
        )
        raise typer.Exit(code=EXIT_ERROR)


def has_session(name: str) -> bool:
    """Return whether a named tmux session exists when tmux is available."""
    if shutil.which("tmux") is None:
        return False
    completed = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def new_session(
    *,
    name: str,
    cwd: Path,
    env: dict[str, str],
    command: list[str],
) -> None:
    """Create a detached tmux session with `tmux new-session -d`.

    - Run the command directly so the pane foreground process receives SIGINT
      when `send-keys C-c` is used.
    - Pass environment values with `-e KEY=VAL` so they are scoped to the tmux
      session rather than inherited only from the subprocess environment.
    """
    args = ["tmux", "new-session", "-d", "-s", name, "-c", str(cwd.resolve())]
    for key, value in env.items():
        args.extend(["-e", f"{key}={value}"])
    args.extend(command)
    subprocess.run(args, check=True)


def pipe_pane_to_file(name: str, log_path: Path) -> None:
    """Append pane stdout/stderr to a file.

    Resolve `log_path` to an absolute path so logging does not depend on the
    tmux pane cwd.
    """
    subprocess.run(
        ["tmux", "pipe-pane", "-t", name, "-o", f"cat >> {log_path.resolve()}"],
        check=True,
    )


def send_ctrl_c(name: str) -> None:
    """Send SIGINT to the pane foreground process."""
    subprocess.run(
        ["tmux", "send-keys", "-t", name, "C-c"],
        check=False,
    )


def kill_session(name: str) -> None:
    """Kill the session immediately as a fallback."""
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        capture_output=True,
        check=False,
    )
