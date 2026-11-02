"""Reclaim the unused Android SDK on disposable Linux E2E hosted runners."""

import argparse
import json
import os
import shutil
import stat
import subprocess
import time
from pathlib import Path

ANDROID_SDK = Path("/usr/local/lib/android/sdk")
# Avoid expensive SDK deletion on roomy workers. This is cleanup eligibility,
# not a failing capacity gate or a guarantee of future workload disk usage.
RECLAIM_BELOW_BYTES = 32 * 1024**3


def _directory_exists(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(mode):
        raise ValueError("Android SDK cleanup path must not contain symlinks")
    if not stat.S_ISDIR(mode):
        raise ValueError("Android SDK cleanup path must be a directory")
    return True


def reclaim(evidence: Path) -> None:
    """Remove one fixed unused SDK, preserving capacity receipts and failures."""
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted"
        or os.environ.get("RUNNER_OS") != "Linux"
    ):
        raise RuntimeError("Capacity cleanup requires a GitHub-hosted Linux job")
    for path in (*reversed(ANDROID_SDK.parents), ANDROID_SDK):
        _directory_exists(path)
    present = _directory_exists(ANDROID_SDK)
    evidence.mkdir(parents=True, exist_ok=True)
    before = shutil.disk_usage("/")
    remove = present and before.free < RECLAIM_BELOW_BYTES
    with (evidence / "runner-capacity-before.json").open("x") as output:
        json.dump(
            {
                "target": str(ANDROID_SDK),
                "present": present,
                "total_bytes": before.total,
                "used_bytes": before.used,
                "available_bytes": before.free,
                "reclaim_below_bytes": RECLAIM_BELOW_BYTES,
            },
            output,
            indent=2,
        )
        output.write("\n")
    started = time.monotonic()
    if remove:
        subprocess.run(
            [
                "sudo",
                "--non-interactive",
                "rm",
                "--recursive",
                "--force",
                "--",
                str(ANDROID_SDK),
            ],
            check=True,
        )
        if _directory_exists(ANDROID_SDK):
            raise RuntimeError("Android SDK cleanup did not remove its target")
    after = shutil.disk_usage("/")
    with (evidence / "runner-capacity-cleanup.json").open("x") as output:
        json.dump(
            {
                "target": str(ANDROID_SDK),
                "removed": remove,
                "outcome": (
                    "removed"
                    if remove
                    else "missing"
                    if not present
                    else "sufficient_capacity"
                ),
                "total_bytes": after.total,
                "used_bytes": after.used,
                "available_bytes": after.free,
                "available_delta_bytes": after.free - before.free,
                "duration_seconds": time.monotonic() - started,
            },
            output,
            indent=2,
        )
        output.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    arguments = parser.parse_args()
    reclaim(arguments.evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
