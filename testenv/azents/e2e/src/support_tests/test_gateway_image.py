"""Exercise explicit gateway image acquisition without Docker or network."""

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from unittest.mock import Mock

import pytest

from support.gateway_image import (
    GATEWAY_IMAGE,
    prepare_gateway_image,
    run_gateway_image_command,
)

_IMAGE_ID = "sha256:" + "a" * 64


def test_cached_gateway_never_pulls_and_returns_local_id(tmp_path: Path) -> None:
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, _IMAGE_ID + "\n", ""))
    assert (
        prepare_gateway_image(
            artifact_dir=tmp_path, budget_seconds=300, command_runner=runner
        )
        == _IMAGE_ID
    )
    assert runner.call_count == 1
    assert tuple(runner.call_args.args[0]) == (
        "docker",
        "image",
        "ls",
        "--quiet",
        "--no-trunc",
        GATEWAY_IMAGE,
    )
    assert 0 < runner.call_args.args[1] <= 300


def test_missing_gateway_is_acquired_once_with_shared_remaining_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ticks = iter([0, 1, 2, 3, 4, 200, 201, 202, 203, 204])
    monkeypatch.setattr("support.gateway_image.perf_counter", lambda: next(ticks))
    results = iter(
        [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "private-registry-output", ""),
            subprocess.CompletedProcess([], 0, _IMAGE_ID, ""),
        ]
    )
    calls = []

    def run(
        command: Sequence[str], remaining: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append((tuple(command), remaining))
        return next(results)

    assert (
        prepare_gateway_image(
            artifact_dir=tmp_path, budget_seconds=300, command_runner=run
        )
        == _IMAGE_ID
    )
    assert [c[0] for c in calls].count(("docker", "pull", GATEWAY_IMAGE)) == 1
    assert calls[-1][1] < calls[0][1]
    content = (tmp_path / "gateway-image-preparation.jsonl").read_text()
    assert "private-registry-output" not in content
    assert [json.loads(line)["outcome"] for line in content.splitlines()] == [
        "started",
        "completed",
    ] * 3


@pytest.mark.parametrize(
    "failure", ["timeout", "failure", "invalid", "missing_after_pull"]
)
def test_gateway_acquisition_failure_is_terminal_without_hidden_retry(
    tmp_path: Path, failure: str
) -> None:
    calls = []

    def run(
        command: Sequence[str], remaining: float
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if command[1] == "pull":
            if failure == "timeout":
                raise subprocess.TimeoutExpired(
                    command, remaining, output="secret-output"
                )
            if failure == "failure":
                return subprocess.CompletedProcess(
                    command, 1, "secret-output", "secret-error"
                )
        return subprocess.CompletedProcess(
            command, 0, "invalid" if failure == "invalid" else "", ""
        )

    expected = (
        TimeoutError
        if failure == "timeout"
        else ValueError
        if failure == "invalid"
        else RuntimeError
    )
    with pytest.raises(expected) as raised:
        prepare_gateway_image(
            artifact_dir=tmp_path, budget_seconds=300, command_runner=run
        )
    assert sum(command[1] == "pull" for command in calls) <= 1
    assert "secret" not in str(raised.value)
    assert "secret" not in (tmp_path / "gateway-image-preparation.jsonl").read_text()


def test_cli_acquisition_has_an_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
    monkeypatch.setattr("support.gateway_image.subprocess.run", runner)
    run_gateway_image_command(("docker", "pull", GATEWAY_IMAGE), 123)
    assert runner.call_args.kwargs["timeout"] == 123
    assert runner.call_args.kwargs["check"] is False
