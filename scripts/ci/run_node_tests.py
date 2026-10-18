"""Retain native Node JUnit and workflow identity without synthetic pytest phases."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("selection", nargs="+")
    args = parser.parse_args()
    artifacts = args.artifact_dir.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    if any(artifacts.iterdir()):
        raise ValueError("Node test evidence directory must be fresh")
    started = time.monotonic()
    result = subprocess.run(
        [
            "pnpm",
            "exec",
            "node",
            "--experimental-strip-types",
            "--test",
            "--test-reporter=junit",
            f"--test-reporter-destination={artifacts / 'junit.xml'}",
            *args.selection,
        ],
        cwd=args.project,
        check=False,
    )
    duration = time.monotonic() - started
    (artifacts / "lane-duration-seconds.txt").write_text(f"{duration:.6f}\n")
    (artifacts / "test-run.json").write_text(
        json.dumps(
            {
                "name": args.name,
                "head_sha": os.environ.get("CI_HEAD_SHA"),
                "run_id": os.environ.get("GITHUB_RUN_ID"),
                "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "exit_code": result.returncode,
                "duration_seconds": duration,
                "runner": "node",
            },
            indent=2,
        )
        + "\n"
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
