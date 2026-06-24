"""Load `testenv/azents/.env`.

Uses python-dotenv to parse the KEY=VALUE file into a dict. The resulting dict
is later passed to tmux sessions as `-e KEY=VAL` environment values.
"""

import typer
from dotenv import dotenv_values

from .paths import ENV_FILE, EXIT_ERROR


def load_env() -> dict[str, str] | None:
    """Load `testenv/azents/.env` as a dict, or return None when missing."""
    if not ENV_FILE.is_file():
        return None
    values = dotenv_values(ENV_FILE)
    # python-dotenv may return None values, so keep only concrete strings.
    return {key: value for key, value in values.items() if value is not None}


def require_env() -> dict[str, str]:
    """Load `.env` or raise typer.Exit with user-facing guidance."""
    env = load_env()
    if env is None:
        typer.echo(
            f"error: {ENV_FILE} not found. Run:\n"
            f"  cp testenv/azents/.env.example testenv/azents/.env\n"
            f"Then edit and try again.",
            err=True,
        )
        raise typer.Exit(code=EXIT_ERROR)
    return env
