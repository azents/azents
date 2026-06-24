"""Runtime state preflight checks.

Checks whether the database migration state is at Alembic HEAD by comparing the
outputs of `alembic current` and `alembic heads`.
"""

import os
import re
import subprocess

from .base import Check, CheckResult, RunContext, Status

_REVISION_RE = re.compile(r"^([0-9a-f]{6,40})\b", re.MULTILINE)


class DbMigrationCurrent(Check):
    """`alembic current` == `alembic heads` check."""

    def __init__(self) -> None:
        super().__init__(
            id="db-migration-current",
            name="DB migration at head",
            category="runtime_state",
            depends_on=["python-deps-installed", "postgres-connectable"],
        )

    def run(self, context: RunContext) -> CheckResult:
        current = _alembic(context, "current")
        if current is None:
            return CheckResult(
                status=Status.FAIL,
                message="`alembic current` failed",
                fix_hint="Check Alembic configuration",
            )
        heads = _alembic(context, "heads")
        if heads is None:
            return CheckResult(
                status=Status.FAIL,
                message="`alembic heads` failed",
                fix_hint="Check Alembic configuration",
            )

        current_revs = set(_REVISION_RE.findall(current))
        head_revs = set(_REVISION_RE.findall(heads))

        if not head_revs:
            return CheckResult(
                status=Status.FAIL,
                message="no alembic heads found",
                fix_hint="Check migration scripts",
            )
        if current_revs == head_revs:
            return CheckResult(
                status=Status.PASS,
                message=f"head: {', '.join(sorted(head_revs))}",
            )
        missing = head_revs - current_revs
        return CheckResult(
            status=Status.FAIL,
            message=f"not at head (missing: {', '.join(sorted(missing))})",
            fix_hint="cd python/apps/azents && uv run alembic upgrade head",
        )


def _alembic(context: RunContext, subcommand: str) -> str | None:
    """Run Alembic in the Azents venv and return stdout.

    Uses `-c db-schemas/rdb/alembic.ini` as the settings file and passes
    `context.env` into the subprocess so pydantic-settings can load `AZ_*`
    values.
    """
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(context.azents_dir),
            "alembic",
            "-c",
            "db-schemas/rdb/alembic.ini",
            subcommand,
        ],
        capture_output=True,
        text=True,
        cwd=context.azents_dir,
        env={**dict(os.environ), **context.env},
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout
