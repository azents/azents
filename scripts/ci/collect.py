"""Preserve one exact CI attempt and its available observability artifacts."""

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

from scripts.ci.evidence import archive_file_hashes, artifacts_for_run, file_hashes
from scripts.ci.workflow_report import decode_run


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def collect(repository: str, run_id: int, attempt: int, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    raw = gh(
        "run",
        "view",
        str(run_id),
        "--attempt",
        str(attempt),
        "--repo",
        repository,
        "--json",
        "databaseId,attempt,status,conclusion,headSha,headBranch,event,"
        "workflowName,createdAt,jobs",
    )
    run = decode_run(json.loads(raw))
    if run.run_id != run_id or run.attempt != attempt or run.status != "completed":
        raise ValueError("Only the exact completed workflow attempt can be collected")
    (output / "run.json").write_text(raw)
    inventory_text = gh(
        "api",
        "--paginate",
        "--slurp",
        f"repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100",
    )
    (output / "artifact-inventory.json").write_text(inventory_text)
    selected = artifacts_for_run(json.loads(inventory_text), run)
    root = output / "artifacts"
    root.mkdir()
    for artifact in selected:
        archive = output / f"artifact-{artifact.artifact_id}.zip"
        # Download immutable artifact ID, not a mutable name after a concurrent rerun.
        with archive.open("wb") as stream:
            subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{repository}/actions/artifacts/{artifact.artifact_id}/zip",
                ],
                stdout=stream,
                check=True,
            )
        archive_file_hashes(archive, artifact)
        destination = root / artifact.name
        destination.mkdir()
        with zipfile.ZipFile(archive) as zipped:
            for item in zipped.infolist():
                target = (destination / item.filename).resolve()
                if (
                    not target.is_relative_to(destination.resolve())
                    or (item.external_attr >> 16) & 0o170000 == 0o120000
                ):
                    raise ValueError("Unsafe archive path or symlink")
            zipped.extractall(destination)
    (output / "collection.json").write_text(
        json.dumps(
            {
                "workflow_run_id": run_id,
                "workflow_attempt": attempt,
                "head_sha": run.head_sha,
                "artifact_names": [a.name for a in selected],
                "artifact_identity_verified": True,
                "file_hashes": file_hashes(root),
            },
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    collect(args.repository, args.run_id, args.attempt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
