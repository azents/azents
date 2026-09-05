"""Tests for required E2E predecessor-snapshot image preparation."""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Sequence

from support.e2e_snapshot_images import prepare_required_snapshot_images

_BASE_SHA = "a" * 40
_ANCESTOR_SHA = "b" * 40


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
        candidate_shas=(_BASE_SHA,),
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
        candidate_shas=(_BASE_SHA,),
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    assert result.login_completed
    assert not result.all_images_prepared
    assert "AZENTS_E2E_SERVER_IMAGE" not in result.environment
    assert len(result.environment) == 2
    assert all(
        pull.source is None or "azents-server-snapshot" not in pull.source
        for pull in result.pulls
    )
    assert not result.fallback_required


def test_prepares_changed_server_as_source_overlay_base() -> None:
    runner = FakeCommandRunner(frozenset())
    environment = _unchanged_environment()
    environment.update(
        {
            "AZENTS_E2E_SERVER_IMAGE_CHANGED": "true",
            "AZENTS_E2E_SERVER_SOURCE_OVERLAY_ELIGIBLE": "true",
        }
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA,),
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    assert result.login_completed
    assert not result.all_images_prepared
    assert not result.fallback_required
    assert result.environment == {
        "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE": (
            "azents-runtime-provider-docker:e2e-base-snapshot"
        ),
        "AZENTS_E2E_RUNTIME_RUNNER_IMAGE": ("azents-runtime-runner:e2e-base-snapshot"),
        "AZENTS_E2E_SERVER_SOURCE_OVERLAY_BASE": ("azents-server:e2e-base-snapshot"),
    }
    overlay_pull = next(
        pull for pull in result.pulls if pull.purpose == "source_overlay_base"
    )
    assert overlay_pull.image == "azents-server"
    assert overlay_pull.environment_variable == "AZENTS_E2E_SERVER_SOURCE_OVERLAY_BASE"
    assert overlay_pull.completed


def test_source_overlay_pull_failure_requires_full_build_fallback() -> None:
    runner = FakeCommandRunner(frozenset({"azents-server-snapshot"}))
    environment = _unchanged_environment()
    environment.update(
        {
            "AZENTS_E2E_SERVER_IMAGE_CHANGED": "true",
            "AZENTS_E2E_SERVER_SOURCE_OVERLAY_ELIGIBLE": "true",
        }
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA,),
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    assert not result.all_images_prepared
    assert result.fallback_required
    assert "AZENTS_E2E_SERVER_SOURCE_OVERLAY_BASE" not in result.environment
    failed_pull = next(
        pull for pull in result.pulls if pull.purpose == "source_overlay_base"
    )
    assert not failed_pull.completed
    assert failed_pull.failure_stage == "pull"


def test_source_overlay_uses_dependency_compatible_ancestor() -> None:
    runner = FakeCommandRunner(frozenset({f"azents-server-snapshot:sha-{_BASE_SHA}"}))
    environment = _unchanged_environment()
    environment.update(
        {
            "AZENTS_E2E_SERVER_IMAGE_CHANGED": "true",
            "AZENTS_E2E_SERVER_SOURCE_OVERLAY_ELIGIBLE": "true",
        }
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA, _ANCESTOR_SHA),
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    overlay_pull = next(
        pull for pull in result.pulls if pull.purpose == "source_overlay_base"
    )
    assert overlay_pull.completed
    assert overlay_pull.candidate_sha == _ANCESTOR_SHA
    assert not result.fallback_required
    assert (
        (
            "git",
            "diff",
            "--quiet",
            _ANCESTOR_SHA,
            _BASE_SHA,
            "--",
            ".dockerignore",
            "azents.Dockerfile",
            "python/apps/azents/pyproject.toml",
            "python/apps/azents/uv.lock",
            "python/libs/az-common",
            "python/libs/azents-runtime-control",
        ),
        None,
    ) in runner.commands


def test_pull_failure_falls_back_to_build() -> None:
    runner = FakeCommandRunner(frozenset({"azents-runtime-runner-snapshot"}))

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA,),
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
    assert result.fallback_required
    assert failed_pull.attempted_sources == (
        f"ghcr.io/azents/azents-runtime-runner-snapshot:sha-{_BASE_SHA}",
    )


def test_missing_base_snapshot_uses_compatible_ancestor() -> None:
    runner = FakeCommandRunner(
        frozenset({f"azents-runtime-runner-snapshot:sha-{_BASE_SHA}"})
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA, _ANCESTOR_SHA),
        github_token="token",
        github_actor="github-actions",
        environment=_unchanged_environment(),
        command_runner=runner,
    )

    assert result.all_images_prepared
    assert not result.fallback_required
    fallback_pull = next(
        pull for pull in result.pulls if pull.image == "azents-runtime-runner"
    )
    assert fallback_pull.completed
    assert fallback_pull.candidate_sha == _ANCESTOR_SHA
    assert fallback_pull.attempted_sources == (
        f"ghcr.io/azents/azents-runtime-runner-snapshot:sha-{_BASE_SHA}",
        f"ghcr.io/azents/azents-runtime-runner-snapshot:sha-{_ANCESTOR_SHA}",
    )


def test_fallback_preserves_directly_prepared_images() -> None:
    runner = FakeCommandRunner(frozenset())
    environment = _unchanged_environment()
    environment.update(
        {
            "AZENTS_E2E_SERVER_IMAGE": "azents-server:e2e-base-snapshot",
            "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE": (
                "azents-runtime-provider-docker:e2e-base-snapshot"
            ),
        }
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_ANCESTOR_SHA,),
        github_token="token",
        github_actor="github-actions",
        environment=environment,
        command_runner=runner,
    )

    assert result.all_images_prepared
    assert not result.fallback_required
    assert result.environment == {
        "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE": (
            "azents-runtime-provider-docker:e2e-base-snapshot"
        ),
        "AZENTS_E2E_RUNTIME_RUNNER_IMAGE": "azents-runtime-runner:e2e-base-snapshot",
        "AZENTS_E2E_SERVER_IMAGE": "azents-server:e2e-base-snapshot",
    }
    assert [pull.image for pull in result.pulls] == ["azents-runtime-runner"]


def test_incompatible_ancestor_falls_back_to_build() -> None:
    runner = FakeCommandRunner(
        frozenset(
            {
                f"azents-runtime-runner-snapshot:sha-{_BASE_SHA}",
                (
                    f"git diff --quiet {_ANCESTOR_SHA} {_BASE_SHA} -- "
                    ".dockerignore python/apps/azents-runtime-runner "
                    "python/libs/azents-runtime-control"
                ),
            }
        )
    )

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA, _ANCESTOR_SHA),
        github_token="token",
        github_actor="github-actions",
        environment=_unchanged_environment(),
        command_runner=runner,
    )

    assert not result.all_images_prepared
    assert result.fallback_required
    failed_pull = next(
        pull for pull in result.pulls if pull.image == "azents-runtime-runner"
    )
    assert not failed_pull.completed
    assert failed_pull.candidate_sha is None
    assert failed_pull.attempted_sources == (
        f"ghcr.io/azents/azents-runtime-runner-snapshot:sha-{_BASE_SHA}",
    )


def test_login_failure_falls_back_without_pull_attempts() -> None:
    runner = FakeCommandRunner(frozenset({"docker login"}))

    result = prepare_required_snapshot_images(
        base_sha=_BASE_SHA,
        candidate_shas=(_BASE_SHA,),
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
