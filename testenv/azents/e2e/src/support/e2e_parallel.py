"""Isolate per-worker E2E diagnostics and preserve validated controller evidence."""

import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, FiniteFloat, NonNegativeFloat
from scripts.ci.observability import parse_image_build_timings, parse_timings

_ARTIFACT_ENV = "AZENTS_E2E_ARTIFACT_DIR"


@dataclass(frozen=True)
class _Controller:
    root: Path
    workers: frozenset[str]


class _ImagePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    images: list[str]


class _TaskTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    duration_seconds: NonNegativeFloat
    outcome: str


class _CoreTiming(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    completed: bool
    wall_seconds: NonNegativeFloat
    task_seconds: NonNegativeFloat
    overlap_seconds: NonNegativeFloat
    readiness_scope: str
    readiness_timings: dict[str, FiniteFloat]
    tasks: dict[str, _TaskTiming]


_CONTROLLER = pytest.StashKey[_Controller]()
_SUCCESS = pytest.StashKey[bool]()


def worker_artifact_directory(root: Path, worker: str) -> Path:
    """Return a bounded worker-owned directory beneath the one lane artifact."""
    if re.fullmatch(r"gw[0-9]+", worker) is None:
        raise ValueError("Invalid E2E worker identity")
    return root / "workers" / worker


def record_worker_image_plan(images: list[str]) -> None:
    """Record the authoritative build selection before worker image tasks start."""
    artifact = os.environ.get(_ARTIFACT_ENV)
    if artifact is None or os.environ.get("PYTEST_XDIST_WORKER") is None:
        return
    with (Path(artifact) / "image-build-plan.json").open("x", encoding="utf-8") as out:
        out.write(_ImagePlan(images=sorted(images)).model_dump_json() + "\n")


def merge_worker_image_timings(
    root: Path, *, workers: frozenset[str], require_complete: bool
) -> None:
    """Validate every worker receipt before producing the existing aggregate file."""
    directories = {p.name: p for p in (root / "workers").iterdir()}
    if set(directories) - workers:
        raise ValueError("Unexpected E2E worker evidence")
    if require_complete and set(directories) != workers:
        raise ValueError("Missing E2E worker evidence")
    lines: list[str] = []
    for directory in sorted(directories.values()):
        source = directory / "image-build-timings.jsonl"
        receipts = parse_image_build_timings(source) if source.exists() else ()
        if require_complete:
            fixtures = parse_timings(root / f"fixture-timings-{directory.name}.jsonl")
            plan = _ImagePlan.model_validate_json(
                (directory / "image-build-plan.json").read_text(encoding="utf-8")
            )
            startup = _CoreTiming.model_validate_json(
                (directory / "core-prerequisite-timings.json").read_text(
                    encoding="utf-8"
                )
            )
            if (
                not startup.completed
                or startup.readiness_scope != "server"
                or not startup.tasks
                or any(task.outcome != "success" for task in startup.tasks.values())
                or not fixtures
                or any(x["record_type"] != "fixture" for x in fixtures)
                or Counter(plan.images) != Counter(x["image"] for x in receipts)
                or any(not x["completed"] for x in receipts)
            ):
                raise ValueError("Incomplete E2E worker image/startup evidence")
        if source.exists():
            lines.extend(source.read_text(encoding="utf-8").splitlines())
    if not lines:
        return
    # Publish only the complete validated payload; retain every raw receipt.
    temporary = root / ".image-build-timings.pending"
    try:
        with temporary.open("x", encoding="utf-8") as output:
            output.write("\n".join(lines) + "\n")
        os.link(temporary, root / "image-build-timings.jsonl")
    finally:
        temporary.unlink(missing_ok=True)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Bind E2E-only diagnostics without changing shared phase/fixture ownership."""
    artifact = os.environ.get(_ARTIFACT_ENV)
    if artifact is None:
        if config.getoption("numprocesses", default=None):
            raise pytest.UsageError(
                "Parallel E2E diagnostics require AZENTS_E2E_ARTIFACT_DIR"
            )
        return
    root = Path(artifact)
    worker = os.environ.get("PYTEST_XDIST_WORKER")
    if worker is not None:
        directory = worker_artifact_directory(root, worker)
        directory.mkdir(parents=True, exist_ok=False)
        os.environ[_ARTIFACT_ENV] = str(directory)
    elif config.getoption("numprocesses", default=None):
        if (
            (root / "workers").exists()
            or (root / "pytest-timings.jsonl").exists()
            or list(root.glob("fixture-timings-gw*.jsonl"))
            or (root / "image-build-timings.jsonl").exists()
        ):
            raise pytest.UsageError("Parallel E2E evidence directory is not fresh")
        count = config.getoption("numprocesses")
        if not isinstance(count, int) or count <= 0:
            raise pytest.UsageError("E2E workers require a positive explicit count")
        config.stash[_CONTROLLER] = _Controller(
            root, frozenset(f"gw{i}" for i in range(count))
        )


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Require complete receipts only when the testcase execution was successful."""
    session.config.stash[_SUCCESS] = exitstatus == 0


def pytest_unconfigure(config: pytest.Config) -> None:
    """Merge after all workers and their owned fixture resources have stopped."""
    controller = config.stash.get(_CONTROLLER, None)
    if controller is not None:
        merge_worker_image_timings(
            controller.root,
            workers=controller.workers,
            require_complete=config.stash.get(_SUCCESS, False),
        )
