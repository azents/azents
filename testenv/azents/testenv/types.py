"""testenv fixture-first core data model.

- :class:`SetupSpec` — parsed setup frontmatter
- :class:`AssertionResult` — probe-local expect DSL run result
- :class:`SetupOutcome` — setup run result (ran / skipped / reclaimed / blocked)
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

SetupScope = Literal["run", "tc"]
"""Setup state scope: ``run`` for fixtures, ``tc`` for logical probes."""


@dataclass(frozen=True)
class SetupSpec:
    """Parsed setup frontmatter plus Markdown path.

    Attributes:
        id: kebab-case setup id matching the file name.
        handler: path to the executable handler (``setup_handlers/*.py``).
        requires: setup ids used for topological sorting.
        provides: state keys populated by this setup, e.g. ``["user.email"]``.
        idempotent: whether rerunning the setup is safe.
        verify: optional shell command that checks real-world state.
        reclaim: optional shell command that cleans up stale real-world state.
        teardown: shell command pushed to the finalizer stack after success.
        scope: ``run`` for fixtures or ``tc`` for logical probes.
        locks: unique resource lock tags.
        markdown_path: source .md file path.
    """

    id: str
    handler: Path | None
    requires: list[str]
    provides: list[str]
    idempotent: bool
    verify: str | None
    reclaim: str | None
    teardown: str | None
    scope: SetupScope
    locks: list[str]
    markdown_path: Path


@dataclass(frozen=True)
class AssertionResult:
    """Result of one deterministic assertion.

    Attributes:
        assertion_type: assertion kind, such as ``http_status``, ``not_contains``, or ``json_path``.
        passed: whether the assertion passed.
        expected: expected value.
        actual: actual value.
        detail: human-readable description for reports and failures.
    """

    assertion_type: str
    passed: bool
    expected: object
    actual: object
    detail: str


SetupOutcomeKind = Literal["ran", "skipped", "reclaimed", "blocked"]
"""Allowed setup run outcomes."""


@dataclass(frozen=True)
class SetupOutcome:
    """Setup run result.

    Attributes:
        setup_id: setup id.
        outcome: ``ran`` | ``skipped`` | ``reclaimed`` | ``blocked``.
        reason: human-readable description, especially for escalation.
        stdout: handler/shell stdout from the run, possibly truncated by callers.
        stderr: handler/shell stderr from the run.
    """

    setup_id: str
    outcome: SetupOutcomeKind
    reason: str
    stdout: str = ""
    stderr: str = ""
