"""Resolve the upload gateway image before Testcontainers can pull it implicitly."""

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter

GATEWAY_IMAGE = "nginx:1.29-alpine"
_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]


def run_gateway_image_command(
    command: Sequence[str],
    remaining: float,
) -> subprocess.CompletedProcess[str]:
    """Use the existing Docker budget as one overall subprocess deadline."""
    return subprocess.run(
        command,
        timeout=remaining,
        capture_output=True,
        text=True,
        check=False,
    )


def prepare_gateway_image(
    *,
    artifact_dir: Path | None,
    budget_seconds: float,
    command_runner: CommandRunner,
) -> str:
    """Resolve a local image ID with one acquisition and a shared deadline.

    No registry output or credentials enter diagnostics. Passing the immutable local
    ID to Testcontainers removes its unbounded, implicit streamed pull fallback.
    """
    started = perf_counter()
    deadline = started + budget_seconds

    def evidence(stage: str, outcome: str) -> None:
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            with (artifact_dir / "gateway-image-preparation.jsonl").open("a") as out:
                out.write(
                    json.dumps(
                        {
                            "image": GATEWAY_IMAGE,
                            "stage": stage,
                            "outcome": outcome,
                            "duration_seconds": round(perf_counter() - started, 6),
                        }
                    )
                    + "\n"
                )

    def command(
        stage: str, arguments: Sequence[str]
    ) -> subprocess.CompletedProcess[str]:
        remaining = deadline - perf_counter()
        if remaining <= 0:
            evidence(stage, "deadline_exceeded")
            raise TimeoutError(
                f"Gateway image preparation exceeded its budget at {stage}"
            )
        evidence(stage, "started")
        try:
            result = command_runner(arguments, remaining)
        except subprocess.TimeoutExpired:
            evidence(stage, "deadline_exceeded")
            raise TimeoutError(
                f"Gateway image preparation exceeded its budget at {stage}"
            ) from None
        if result.returncode != 0:
            evidence(stage, "failed")
            raise RuntimeError(f"Gateway image preparation failed at {stage}")
        evidence(stage, "completed")
        return result

    inspect_command = ("docker", "image", "ls", "--quiet", "--no-trunc", GATEWAY_IMAGE)

    def inspect(stage: str) -> str | None:
        result = command(stage, inspect_command)
        identities = set(result.stdout.split())
        if not identities:
            return None
        if len(identities) != 1 or _IMAGE_ID.fullmatch(next(iter(identities))) is None:
            evidence(stage, "invalid_identity")
            raise ValueError(
                "Gateway image listing did not yield one immutable local ID"
            )
        return next(iter(identities))

    image_id = inspect("local_image")
    if image_id is None:
        command("pull", ("docker", "pull", GATEWAY_IMAGE))
        image_id = inspect("pulled_image")
        if image_id is None:
            evidence("pulled_image", "missing_identity")
            raise RuntimeError("Gateway image pull completed without a local image")
    return image_id
