"""Preflight check runner.

Runs the configured check list in order:

1. Print a category header when the category changes.
2. Skip later checks in a category after a category-level failure.
3. Skip checks whose ``depends_on`` checks did not pass.
4. Apply context side effects after checks such as ``env-file-exists`` pass.
5. Continue after failures so the user sees all relevant diagnostics.
6. Print a summary and return exit code 0 on success or 1 on failure.
"""

import os
from pathlib import Path

from .base import Check, CheckResult, RunContext, Status
from .output import Formatter


class Runner:
    """Run a configured list of preflight checks."""

    def __init__(self, checks: list[Check], formatter: Formatter) -> None:
        self._checks = checks
        self._fmt = formatter

    def run(self) -> int:
        """Run all checks and return the process exit code."""
        context = _make_initial_context()
        results: dict[str, CheckResult] = {}
        category_failed: set[str] = set()
        current_category: str | None = None

        passed = failed = skipped = 0

        for check in self._checks:
            # Print category header.
            if check.category != current_category:
                current_category = check.category
                print(self._fmt.category_header(current_category))

            # Skip checks after category failure or dependency failure.
            if check.category in category_failed:
                result = CheckResult(status=Status.SKIP, message="category failed")
            elif any(
                results.get(dep) is None or results[dep].status != Status.PASS
                for dep in check.depends_on
            ):
                missing = [
                    dep
                    for dep in check.depends_on
                    if results.get(dep) is None or results[dep].status != Status.PASS
                ]
                result = CheckResult(
                    status=Status.SKIP,
                    message=f"depends on: {', '.join(missing)}",
                )
            else:
                try:
                    result = check.run(context)
                except Exception as exc:  # pragma: no cover - safety net
                    result = CheckResult(
                        status=Status.FAIL,
                        message=f"unexpected error: {exc}",
                    )

            results[check.id] = result
            context.previous_results[check.id] = result
            self._print_result(check, result)

            # Apply side effects and category failure state.
            if result.status == Status.PASS:
                _apply_side_effects(check, context)
            elif result.status == Status.FAIL:
                category_failed.add(check.category)

            # Count result statuses.
            if result.status == Status.PASS:
                passed += 1
            elif result.status == Status.FAIL:
                failed += 1
            elif result.status == Status.SKIP:
                skipped += 1

        total = len(self._checks)
        print(self._fmt.summary(total, passed, failed, skipped))
        return 0 if failed == 0 else 1

    def _print_result(self, check: Check, result: CheckResult) -> None:
        """Print one check result."""
        symbol = self._fmt.status_symbol(result.status)
        line = f"  {symbol} {check.name}"
        if result.message:
            line += f" — {result.message}"
        print(line)
        if result.status == Status.FAIL and result.fix_hint:
            print(f"      fix: {result.fix_hint}")


def _make_initial_context() -> RunContext:
    """Create the initial preflight context.

    Paths are derived from ``Path(__file__).resolve()`` rather than the current
    working directory. ``runner.py`` lives under
    ``<repo>/testenv/azents/testenv/checks/runner.py``, so the package root is
    ``testenv/azents`` and the repository root is two levels above it.
    """
    checks_dir = Path(__file__).resolve().parent
    testenv_dir = checks_dir.parent.parent
    repo_root = testenv_dir.parent.parent
    return RunContext(
        repo_root=repo_root,
        azents_dir=repo_root / "python" / "apps" / "azents",
        env_file=testenv_dir / ".env",
    )


def _apply_side_effects(check: Check, context: RunContext) -> None:
    """Apply context side effects after a check passes.

    - ``repo-root``: no side effect; paths are already resolved from this file.
    - ``env-file-exists``: parse ``.env`` into ``context.env`` and fill missing
      ``os.environ`` entries for subprocess compatibility.
    """
    if check.id == "env-file-exists":
        try:
            parsed = _parse_env_file(context.env_file)
        except OSError:
            return
        context.env.update(parsed)
        for key, value in parsed.items():
            # Do not overwrite existing os.environ values set by the caller.
            os.environ.setdefault(key, value)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple ``.env`` file.

    Supports ``KEY=VALUE`` lines, ignores blank lines and comments, and removes
    matching single or double quotes around values. This intentionally avoids
    full shell-style expansion.
    """
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result
