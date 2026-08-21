"""Tests for required E2E base-snapshot image preparation."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Sequence

from support.e2e_snapshot_images import prepare_required_snapshot_images

_BASE_SHA = "a" * 40


class FakeCommandRunner:
    """Record Docker commands and return configured failures."""

    def __init__(self, failing_fragments: frozenset[str]) -> None:
        self.failing_fragments = failing_fragments
        self.commands: list[tuple[tuple[str, ...], str | None]] = []
        self.lock = threading.Lock()

    def __call__(
        self,
        command: Sequence[str],
        input_text: str | None,
    ) -> subprocess.CompletedProcess[str]:
        normalized = tuple(command)
        with self.lock:
            self.commands.append((normalized, input_text))
        failed = any(
            fragment in " ".join(normalized) for fragment in self.failing_fragments
        )
        return subprocess.CompletedProcess(
            args=normalized,
            returncode=1 if failed else 0,
            stdout="",
            stderr="failed" if failed else "",
        )


def _unchanged_environment() -> dict[str, str]:
    return {
        "AZENTS_E2E_SERVER_IMAGE_CHANGED": "false",
        "AZENTS_E2E_RUNTIME_RUNNER_IMAGE_CHANGED": "false",
        "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE_CHANGED": "false",
    }


def test_prepares_all_unchanged_images() -> None:
    runner = FakeCommandRunner(frozenset())

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        github_token="token",
        github_actor="github-actions",
        environment=_unchanged_environment(),
        command_runner=runner,
    )

    assert result.login_completed
    assert result.all_images_prepared
    assert result.environment == {
        "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE": (
            "azents-runtime-provider-docker:e2e-base-snapshot"
        ),
        "AZENTS_E2E_RUNTIME_RUNNER_IMAGE": ("azents-runtime-runner:e2e-base-snapshot"),
        "AZENTS_E2E_SERVER_IMAGE": "azents-server:e2e-base-snapshot",
    }
    assert len(result.pulls) == 3
    assert all(pull.completed for pull in result.pulls)
    assert sum(command[0][1] == "pull" for command in runner.commands) == 3
    assert sum(command[0][1] == "tag" for command in runner.commands) == 3


def test_builds_changed_image_and_prepares_unchanged_images() -> None:
    runner = FakeCommandRunner(frozenset())
    environment = _unchanged_environment()
    environment["AZENTS_E2E_SERVER_IMAGE_CHANGED"] = "true"

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    assert result.login_completed
    assert not result.all_images_prepared
    assert "AZENTS_E2E_SERVER_IMAGE" not in result.environment
    assert len(result.environment) == 2
    assert all("azents-server-snapshot" not in pull.source for pull in result.pulls)


def test_pull_failure_falls_back_to_build() -> None:
    runner = FakeCommandRunner(frozenset({"azents-runtime-runner-snapshot"}))

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        github_token="token",
        github_actor="github-actions",
        environment=_unchanged_environment(),
        command_runner=runner,
    )

    assert result.login_completed
    assert not result.all_images_prepared
    assert "AZENTS_E2E_RUNTIME_RUNNER_IMAGE" not in result.environment
    failed_pull = next(
        pull for pull in result.pulls if pull.image == "azents-runtime-runner"
    )
    assert not failed_pull.completed
    assert failed_pull.failure_stage == "pull"


def test_login_failure_falls_back_without_pull_attempts() -> None:
    runner = FakeCommandRunner(frozenset({"docker login"}))

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        github_token="token",
        github_actor="github-actions",
        environment=_unchanged_environment(),
        command_runner=runner,
    )

    assert not result.login_completed
    assert not result.all_images_prepared
    assert result.environment == {}
    assert result.pulls == ()
    assert len(runner.commands) == 1
