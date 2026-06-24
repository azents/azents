"""Alembic migration runner."""

import os
import subprocess

import typer

from .paths import ALEMBIC_INI, ALEMBIC_REVISION_FILE, AZENTS_DIR, EXIT_ERROR


def _read_target_revision() -> str:
    """Read the target revision from `db-schemas/rdb/revision`.

    This mirrors devserver.sh behavior: do not blindly migrate to "head"; use
    the revision file as the explicit target so local state follows the checked
    in schema revision.
    """
    if not ALEMBIC_REVISION_FILE.is_file():
        typer.echo(
            f"error: alembic revision file not found at {ALEMBIC_REVISION_FILE}",
            err=True,
        )
        raise typer.Exit(code=EXIT_ERROR)
    revision = ALEMBIC_REVISION_FILE.read_text(encoding="utf-8").strip()
    if not revision:
        typer.echo(f"error: alembic revision file is empty: {ALEMBIC_REVISION_FILE}", err=True)
        raise typer.Exit(code=EXIT_ERROR)
    return revision


def alembic_upgrade(env: dict[str, str]) -> None:
    """Run `uv run --project python/apps/azents alembic -c ... upgrade <revision>`.

    Pass `env` into the subprocess so pydantic-settings can read AZ_RDB_*
    values. The target revision comes from `db-schemas/rdb/revision`, matching
    devserver.sh behavior.
    """
    revision = _read_target_revision()
    typer.echo(f"[alembic] upgrade {revision}")
    merged_env = {**dict(os.environ), **env}
    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(AZENTS_DIR),
            "alembic",
            "-c",
            str(ALEMBIC_INI),
            "upgrade",
            revision,
        ],
        cwd=AZENTS_DIR,
        env=merged_env,
        check=True,
    )
