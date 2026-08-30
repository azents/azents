"""Prepare unchanged required E2E images from immutable predecessor snapshots."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

_REGISTRY = "ghcr.io"
_OWNER = "azents"


@dataclass(frozen=True)
class SnapshotImage:
    """Describe one required E2E snapshot image."""

    image: str
    package: str
    local_tag: str
    environment_variable: str
    changed_environment_variable: str
    pathspecs: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotPull:
    """Record one snapshot pull and local tag result."""

    image: str
    source: str | None
    candidate_sha: str | None
    attempted_sources: tuple[str, ...]
    completed: bool
    duration_seconds: float
    failure_stage: str | None


@dataclass(frozen=True)
class SnapshotPreparation:
    """Return prepared image variables and complete preparation evidence."""

    environment: dict[str, str]
    pulls: tuple[SnapshotPull, ...]
    login_completed: bool
    all_images_prepared: bool
    fallback_required: bool


CommandRunner = Callable[
    [Sequence[str], str | None],
    subprocess.CompletedProcess[str],
]

_REQUIRED_IMAGES = (
    SnapshotImage(
        image="azents-server",
        package="azents-server-snapshot",
        local_tag="azents-server:e2e-base-snapshot",
        environment_variable="AZENTS_E2E_SERVER_IMAGE",
        changed_environment_variable="AZENTS_E2E_SERVER_IMAGE_CHANGED",
        pathspecs=(
            ".dockerignore",
            "azents.Dockerfile",
            "python/apps/azents",
            "python/libs/az-common",
            "python/libs/azents-runtime-control",
        ),
    ),
    SnapshotImage(
        image="azents-runtime-runner",
        package="azents-runtime-runner-snapshot",
        local_tag="azents-runtime-runner:e2e-base-snapshot",
        environment_variable="AZENTS_E2E_RUNTIME_RUNNER_IMAGE",
        changed_environment_variable="AZENTS_E2E_RUNTIME_RUNNER_IMAGE_CHANGED",
        pathspecs=(
            ".dockerignore",
            "python/apps/azents-runtime-runner",
            "python/libs/azents-runtime-control",
        ),
    ),
    SnapshotImage(
        image="azents-runtime-provider-docker",
        package="azents-runtime-provider-docker-snapshot",
        local_tag="azents-runtime-provider-docker:e2e-base-snapshot",
        environment_variable="AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE",
        changed_environment_variable=(
            "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE_CHANGED"
        ),
        pathspecs=(
            ".dockerignore",
            "python/apps/azents-runtime-provider-docker",
            "python/libs/azents-runtime-control",
        ),
    ),
)


def _run_command(
    command: Sequence[str],
    input_text: str | None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
    )


def _compatible_with_base(
    image: SnapshotImage,
    *,
    candidate_sha: str,
    base_sha: str,
    command_runner: CommandRunner,
) -> bool:
    """Return whether one ancestor has identical image-relevant content."""
    if candidate_sha == base_sha:
        return True
    comparison = command_runner(
        (
            "git",
            "diff",
            "--quiet",
            candidate_sha,
            base_sha,
            "--",
            *image.pathspecs,
        ),
        None,
    )
    return comparison.returncode == 0


def _pull_snapshot(
    image: SnapshotImage,
    *,
    base_sha: str,
    candidate_shas: Sequence[str],
    command_runner: CommandRunner,
) -> SnapshotPull:
    started_at = time.monotonic()
    attempted_sources: list[str] = []
    for candidate_sha in candidate_shas:
        if not _compatible_with_base(
            image,
            candidate_sha=candidate_sha,
            base_sha=base_sha,
            command_runner=command_runner,
        ):
            continue
        source = f"{_REGISTRY}/{_OWNER}/{image.package}:sha-{candidate_sha}"
        attempted_sources.append(source)
        pull = command_runner(("docker", "pull", source), None)
        if pull.returncode != 0:
            continue

        tag = command_runner(("docker", "tag", source, image.local_tag), None)
        return SnapshotPull(
            image=image.image,
            source=source,
            candidate_sha=candidate_sha,
            attempted_sources=tuple(attempted_sources),
            completed=tag.returncode == 0,
            duration_seconds=time.monotonic() - started_at,
            failure_stage=None if tag.returncode == 0 else "tag",
        )

    return SnapshotPull(
        image=image.image,
        source=None,
        candidate_sha=None,
        attempted_sources=tuple(attempted_sources),
        completed=False,
        duration_seconds=time.monotonic() - started_at,
        failure_stage="pull" if attempted_sources else "compatibility",
    )


def prepare_required_snapshot_images(
    *,
    base_sha: str,
    candidate_shas: Sequence[str],
    github_token: str | None,
    github_actor: str | None,
    environment: dict[str, str],
    command_runner: CommandRunner,
) -> SnapshotPreparation:
    """Pull unchanged required images from compatible immutable snapshots."""
    unchanged_required_images = tuple(
        image
        for image in _REQUIRED_IMAGES
        if environment.get(image.changed_environment_variable) == "false"
    )
    unchanged_images = tuple(
        image
        for image in unchanged_required_images
        if not environment.get(image.environment_variable)
    )
    prepared_environment = {
        image.environment_variable: value
        for image in _REQUIRED_IMAGES
        if (value := environment.get(image.environment_variable))
    }
    if not github_token or not github_actor or not unchanged_images:
        return SnapshotPreparation(
            environment=prepared_environment,
            pulls=(),
            login_completed=False,
            all_images_prepared=len(prepared_environment) == len(_REQUIRED_IMAGES),
            fallback_required=any(
                image.environment_variable not in prepared_environment
                for image in unchanged_required_images
            ),
        )

    login = command_runner(
        (
            "docker",
            "login",
            _REGISTRY,
            "--username",
            github_actor,
            "--password-stdin",
        ),
        github_token,
    )
    if login.returncode != 0:
        return SnapshotPreparation(
            environment=prepared_environment,
            pulls=(),
            login_completed=False,
            all_images_prepared=len(prepared_environment) == len(_REQUIRED_IMAGES),
            fallback_required=any(
                image.environment_variable not in prepared_environment
                for image in unchanged_required_images
            ),
        )

    with ThreadPoolExecutor(max_workers=len(unchanged_images)) as executor:
        pulls = tuple(
            executor.map(
                lambda image: _pull_snapshot(
                    image,
                    base_sha=base_sha,
                    candidate_shas=candidate_shas,
                    command_runner=command_runner,
                ),
                unchanged_images,
            )
        )

    pulls_by_image = {pull.image: pull for pull in pulls}
    prepared_environment.update(
        {
            image.environment_variable: image.local_tag
            for image in unchanged_images
            if pulls_by_image[image.image].completed
        }
    )
    return SnapshotPreparation(
        environment=prepared_environment,
        pulls=pulls,
        login_completed=True,
        all_images_prepared=len(prepared_environment) == len(_REQUIRED_IMAGES),
        fallback_required=any(
            image.environment_variable not in prepared_environment
            for image in unchanged_required_images
        ),
    )


def _write_github_environment(path: Path, environment: dict[str, str]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in sorted(environment.items()):
            output.write(f"{name}={value}\n")


def _write_github_output(path: Path, preparation: SnapshotPreparation) -> None:
    with path.open("a", encoding="utf-8") as output:
        output.write(
            f"all_images_prepared={str(preparation.all_images_prepared).lower()}\n"
        )
        output.write(
            f"fallback_required={str(preparation.fallback_required).lower()}\n"
        )


def _write_observability(
    artifact_dir: Path,
    preparation: SnapshotPreparation,
    base_sha: str,
    candidate_shas: Sequence[str],
    append: bool,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    status = {
        "base_sha": base_sha,
        "candidate_shas": list(candidate_shas),
        "login_completed": preparation.login_completed,
        "all_images_prepared": preparation.all_images_prepared,
        "fallback_required": preparation.fallback_required,
        "prepared_environment_variables": sorted(preparation.environment),
    }
    (artifact_dir / "snapshot-image-setup.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    mode = "a" if append else "w"
    with (artifact_dir / "snapshot-image-timings.jsonl").open(
        mode, encoding="utf-8"
    ) as output:
        for pull in preparation.pulls:
            output.write(
                json.dumps(
                    {
                        "image": pull.image,
                        "source": pull.source,
                        "candidate_sha": pull.candidate_sha,
                        "attempted_sources": list(pull.attempted_sources),
                        "completed": pull.completed,
                        "duration_seconds": round(pull.duration_seconds, 3),
                        "failure_stage": pull.failure_stage,
                    },
                    sort_keys=True,
                )
                + "\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    parser.add_argument("--append-observability", action="store_true")
    args = parser.parse_args()

    base_sha = os.environ["AZENTS_E2E_BASE_SHA"]
    candidate_shas = tuple(
        candidate_sha
        for candidate_sha in os.environ.get(
            "AZENTS_E2E_BASE_SHA_CANDIDATES",
            base_sha,
        ).split(",")
        if candidate_sha
    )
    preparation = prepare_required_snapshot_images(
        base_sha=base_sha,
        candidate_shas=candidate_shas,
        github_token=os.environ.get("GHCR_TOKEN"),
        github_actor=os.environ.get("GITHUB_ACTOR"),
        environment=dict(os.environ),
        command_runner=_run_command,
    )
    _write_github_environment(args.github_env, preparation.environment)
    _write_github_output(args.github_output, preparation)
    _write_observability(
        args.artifact_dir,
        preparation,
        base_sha,
        candidate_shas,
        args.append_observability,
    )


if __name__ == "__main__":
    main()
