"""Validate exact-attempt GitHub artifact provenance shared by collect/analyze."""

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.ci.workflow_report import (
    Run,
    integer,
    object_value,
    sequence,
    text,
    timestamp,
)


@dataclass(frozen=True)
class Artifact:
    artifact_id: int
    name: str
    created: datetime
    head_sha: str
    run_id: int


@dataclass(frozen=True)
class TestRunIdentity:
    head_sha: str
    run_id: str
    attempt: str
    name: str


def decode_test_run(value: object) -> TestRunIdentity:
    """Project the interpreted producer identity; retain additive wire compatibility."""
    raw = object_value(value)
    return TestRunIdentity(
        head_sha=text(raw["head_sha"]),
        run_id=text(raw["run_id"]),
        attempt=text(raw["attempt"]),
        name=text(raw["name"]),
    )


@dataclass(frozen=True)
class NativeTestRun:
    identity: TestRunIdentity
    exit_code: int
    duration_seconds: float


def decode_native_run(value: object, runner: str) -> NativeTestRun:
    """Require the native execution receipt, not only its workflow identity."""
    raw = object_value(value)
    if text(raw["runner"]) != runner:
        raise ValueError("Native test evidence runner mismatch")
    status = raw["exit_code"]
    if isinstance(status, bool) or not isinstance(status, int):
        raise ValueError("Native test exit code must be an integer")
    duration = raw["duration_seconds"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("Native test duration must be finite and positive")
    return NativeTestRun(
        identity=decode_test_run(raw),
        exit_code=status,
        duration_seconds=float(duration),
    )


@dataclass(frozen=True)
class CollectionManifest:
    run_id: int
    attempt: int
    head_sha: str
    identity_verified: bool
    artifact_names: frozenset[str]
    file_hashes: dict[str, str]


def decode_collection(value: object) -> CollectionManifest:
    """Decode provenance and byte-hash fields once before collection verification."""
    raw = object_value(value)
    verified = raw["artifact_identity_verified"]
    if not isinstance(verified, bool):
        raise ValueError("Collection identity verification must be a boolean")
    return CollectionManifest(
        run_id=integer(raw["workflow_run_id"]),
        attempt=integer(raw["workflow_attempt"]),
        head_sha=text(raw["head_sha"]),
        identity_verified=verified,
        artifact_names=frozenset(text(n) for n in sequence(raw["artifact_names"])),
        file_hashes={
            name: text(digest)
            for name, digest in object_value(raw["file_hashes"]).items()
        },
    )


def artifacts_for_run(raw: object, run: Run) -> tuple[Artifact, ...]:
    """Decode extensible API pages but reject expired, ambiguous or stale evidence."""
    ends = [j.completed for j in run.jobs if j.completed is not None]
    starts = [
        j.started
        for j in run.jobs
        if j.started is not None and j.conclusion != "skipped"
    ]
    if not ends or not starts:
        raise ValueError("Missing attempt execution boundaries")
    selected = []
    for page in sequence(raw):
        for value in sequence(object_value(page)["artifacts"]):
            item = object_value(value)
            name = text(item["name"])
            if not (
                name.startswith("e2e-observability-")
                or name.startswith("ci-observability-")
                and name.endswith(f"-{run.attempt}")
                or name == f"ci-workflow-{run.attempt}"
                or name == f"ios-diagnostics-{run.head_sha}"
            ):
                continue
            if re.fullmatch("[a-z0-9][a-z0-9-]*", name) is None:
                raise ValueError("Unsafe artifact name")
            created = timestamp(item["created_at"])
            if (
                item["expired"] is not False
                or created is None
                or not min(starts) <= created <= max(ends)
            ):
                raise ValueError(f"Unavailable or different-attempt artifact: {name}")
            workflow = object_value(item["workflow_run"])
            artifact = Artifact(
                integer(item["id"]),
                name,
                created,
                text(workflow["head_sha"]),
                integer(workflow["id"]),
            )
            if artifact.head_sha != run.head_sha or artifact.run_id != run.run_id:
                raise ValueError("Artifact workflow identity mismatch")
            selected.append(artifact)
    if len({a.name for a in selected}) != len(selected):
        raise ValueError("Ambiguous duplicate artifact name")
    return tuple(selected)


def file_hashes(root: Path) -> dict[str, str]:
    hashes = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Artifact symlinks are not allowed")
        if path.is_file():
            with path.open("rb") as stream:
                hashes[path.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return hashes


def verify_collection(root: Path, run: Run) -> set[str]:
    """Verify stored provenance and bytes before any acceptance calculation."""
    manifest = decode_collection(json.loads((root / "collection.json").read_text()))
    if (
        manifest.run_id != run.run_id
        or manifest.attempt != run.attempt
        or manifest.head_sha != run.head_sha
        or not manifest.identity_verified
    ):
        raise ValueError("Collection identity mismatch")
    artifacts = artifacts_for_run(
        json.loads((root / "artifact-inventory.json").read_text()), run
    )
    expected = {a.name for a in artifacts}
    if manifest.artifact_names != expected:
        raise ValueError("Collection inventory mismatch")
    if manifest.file_hashes != file_hashes(root / "artifacts"):
        raise ValueError("Collected artifact bytes changed")
    found = {p.name for p in (root / "artifacts").iterdir() if p.is_dir()}
    if found != expected:
        raise ValueError("Artifact directory set differs from verified inventory")
    return expected
