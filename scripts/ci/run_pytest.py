"""Run an unchanged pytest selection with shared, safe CI timing evidence."""

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
    parser.add_argument("--system-python", action="store_true")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    artifacts = args.artifact_dir.resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    if any(
        (artifacts / name).exists()
        for name in (
            "junit.xml",
            "pytest-timings.jsonl",
            "test-run.json",
            "lane-duration-seconds.txt",
        )
    ):
        raise ValueError("CI evidence directory already contains a pytest execution")
    environment = dict(os.environ)
    environment["AZENTS_CI_ARTIFACT_DIR"] = str(artifacts)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root), environment["PYTHONPATH"]]
        if environment.get("PYTHONPATH")
        else [str(root)]
    )
    selection = args.pytest_args
    if selection[:1] == ["--"]:
        selection = selection[1:]
    command = ["python"] if args.system_python else ["uv", "run", "python"]
    command += [
        "-m",
        "pytest",
        "-p",
        "scripts.ci.pytest_timing",
        f"--junitxml={artifacts / 'junit.xml'}",
        *selection,
    ]
    started = time.monotonic()
    result = subprocess.run(command, cwd=args.project, env=environment, check=False)
    duration = time.monotonic() - started
    (artifacts / "lane-duration-seconds.txt").write_text(f"{duration:.6f}\n")
    (artifacts / "test-run.json").write_text(
        json.dumps(
            {
                "name": args.name,
                "head_sha": environment.get("CI_HEAD_SHA"),
                "run_id": environment.get("GITHUB_RUN_ID"),
                "attempt": environment.get("GITHUB_RUN_ATTEMPT"),
                "exit_code": result.returncode,
                "duration_seconds": duration,
            },
            indent=2,
        )
        + "\n"
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
