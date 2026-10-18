"""Run the selected browser component contracts with native, fail-closed evidence."""

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

from scripts.ci.component_portfolio import STORIES, portfolio_complete
from scripts.ci.observability import parse_junit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    artifacts = args.artifact_dir.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    if any(artifacts.iterdir()):
        raise ValueError("Component test evidence directory must be fresh")
    started = time.monotonic()
    result = subprocess.run(
        [
            "pnpm",
            "exec",
            "vitest",
            "run",
            "--config",
            ".storybook/vitest.config.ts",
            "--reporter=default",
            "--reporter=junit",
            f"--outputFile.junit={artifacts / 'junit.xml'}",
            *STORIES,
        ],
        cwd=args.project,
        check=False,
    )
    duration = time.monotonic() - started
    junit_path = artifacts / "junit.xml"
    junit = parse_junit(junit_path) if junit_path.is_file() else None
    valid = (
        junit is not None and portfolio_complete(junit) and junit.passed == junit.tests
    )
    status = result.returncode if result.returncode != 0 else 0 if valid else 1
    (artifacts / "lane-duration-seconds.txt").write_text(f"{duration:.6f}\n")
    (artifacts / "test-run.json").write_text(
        json.dumps(
            {
                "name": "typescript-web-components",
                "head_sha": os.environ.get("CI_HEAD_SHA"),
                "run_id": os.environ.get("GITHUB_RUN_ID"),
                "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                "exit_code": status,
                "duration_seconds": duration,
                "runner": "vitest-browser",
            },
            indent=2,
        )
        + "\n"
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
