"""Shared preflight check primitives."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Status(Enum):
    """Preflight check result state."""

    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    """Result of a single preflight check run."""

    status: Status
    message: str = ""
    fix_hint: str = ""


@dataclass
class RunContext:
    """Context shared across preflight check runs.

    ``repo_root`` is available after ``RepoRoot`` passes. The ``env`` mapping is
    populated from the ``.env`` file after ``EnvFileExists`` passes. It is not
    copied into ``os.environ`` directly; checks pass it explicitly to
    subprocesses when needed.
    """

    repo_root: Path
    azents_dir: Path
    env_file: Path
    env: dict[str, str] = field(default_factory=dict)
    previous_results: dict[str, "CheckResult"] = field(default_factory=dict)


class Check(ABC):
    """Base class for one preflight check.

    Subclasses configure metadata by calling ``super().__init__(...)`` and then
    implement ``run(context)``. ``depends_on`` names checks that must complete
    before this check should run.
    """

    def __init__(
        self,
        *,
        id: str,
        name: str,
        category: str,
        depends_on: list[str] | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.category = category
        self.depends_on: list[str] = list(depends_on) if depends_on else []

    @abstractmethod
    def run(self, context: RunContext) -> CheckResult: ...
