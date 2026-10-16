"""Validate exact-attempt GitHub artifact provenance shared by collect/analyze."""

import hashlib
import json
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
    manifest = object_value(json.loads((root / "collection.json").read_text()))
    if (
        manifest["workflow_run_id"] != run.run_id
        or manifest["workflow_attempt"] != run.attempt
        or manifest["head_sha"] != run.head_sha
        or manifest["artifact_identity_verified"] is not True
    ):
        raise ValueError("Collection identity mismatch")
    artifacts = artifacts_for_run(
        json.loads((root / "artifact-inventory.json").read_text()), run
    )
    expected = {a.name for a in artifacts}
    if {text(n) for n in sequence(manifest["artifact_names"])} != expected:
        raise ValueError("Collection inventory mismatch")
    hashes = object_value(manifest["file_hashes"])
    if hashes != file_hashes(root / "artifacts"):
        raise ValueError("Collected artifact bytes changed")
    found = {p.name for p in (root / "artifacts").iterdir() if p.is_dir()}
    if found != expected:
        raise ValueError("Artifact directory set differs from verified inventory")
    return expected
