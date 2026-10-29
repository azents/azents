"""Transfer exact existing CI Docker outputs to E2E without rebuilding images."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from scripts.ci.workflow_report import integer, object_value, text
from testenv.azents.e2e.src.support.e2e_snapshot_images import (
    PREREQUISITE_IMAGES,
    PrerequisiteImagePull,
    prepare_prerequisite_images,
)

IMAGES = {
    "azents-server": "AZENTS_E2E_SERVER_IMAGE",
    "azents-runtime-runner": "AZENTS_E2E_RUNTIME_RUNNER_IMAGE",
    "azents-runtime-provider-docker": "AZENTS_E2E_RUNTIME_PROVIDER_DOCKER_IMAGE",
    "azents-web": "AZENTS_E2E_WEB_IMAGE",
    "azents-admin-web": "AZENTS_E2E_ADMIN_WEB_IMAGE",
    "azents-llm-proxy": "AZENTS_E2E_LLM_PROXY_IMAGE",
}
CORE = tuple(IMAGES)[:3]
REQUIRED = (*CORE, "azents-llm-proxy")
WEB = (*CORE, "azents-web", "azents-admin-web")
ARCHIVE_NAME = "image.tar.zst"


@dataclass(frozen=True)
class Identity:
    repository: str
    head_sha: str
    run_id: int
    attempt: int


@dataclass(frozen=True)
class ImageReceipt:
    identity: Identity
    image: str
    image_id: str
    archive_sha256: str
    archive_bytes: int
    export_seconds: float


@dataclass(frozen=True)
class ImageDownload:
    image: str
    completed: bool
    duration_seconds: float
    started_at_monotonic: float
    finished_at_monotonic: float


@dataclass(frozen=True)
class ImageLoad:
    image: str
    duration_seconds: float
    started_at_monotonic: float
    finished_at_monotonic: float


@dataclass(frozen=True)
class PrerequisitePreparation:
    pulls: tuple[PrerequisiteImagePull, ...]
    started_at_monotonic: float
    finished_at_monotonic: float


def _download_one(root: Path, image: str, owner: Identity) -> ImageDownload:
    name = f"ci-e2e-image-{image}-{owner.run_id}-{owner.attempt}"
    started = time.monotonic()
    result = subprocess.run(
        [
            "gh",
            "run",
            "download",
            str(owner.run_id),
            "--repo",
            owner.repository,
            "--name",
            name,
            "--dir",
            str(root / name),
        ],
        check=False,
    )
    finished = time.monotonic()
    return ImageDownload(
        image, result.returncode == 0, finished - started, started, finished
    )


def _download(
    root: Path, selected: tuple[str, ...], owner: Identity
) -> tuple[ImageDownload, ...]:
    # gh downloads a multi-name request serially. Separate exact-name requests
    # retain two bounded I/O slots and explicit ownership of every result.
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_download_one, root, image, owner) for image in selected
        ]
    return tuple(future.result() for future in futures)


def _pull_command(
    command: Sequence[str], input_text: str | None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, input=input_text, text=True, check=False)


def _prerequisites() -> PrerequisitePreparation:
    started = time.monotonic()
    pulls = prepare_prerequisite_images(command_runner=_pull_command)
    return PrerequisitePreparation(pulls, started, time.monotonic())


def prepare(root: Path, suite: str, evidence: Path) -> None:
    """Own and join exact downloads and existing prerequisite pulls in one step."""
    owner = identity()
    verify_checkout(owner)
    selected = REQUIRED if suite == "required" else WEB
    root.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        downloads = executor.submit(_download, root, selected, owner)
        prerequisites = executor.submit(_prerequisites)
    downloaded = downloads.result()
    prerequisite = prerequisites.result()
    pulled = prerequisite.pulls
    evidence.mkdir(parents=True, exist_ok=True)
    with (evidence / "ci-image-preparation.json").open("x") as output:
        json.dump(
            {
                "identity": asdict(owner),
                "suite": suite,
                "duration_seconds": time.monotonic() - started,
                "downloads": [asdict(item) for item in downloaded],
                "prerequisite_pulls": [asdict(item) for item in pulled],
                "prerequisite_window": {
                    "started_at_monotonic": prerequisite.started_at_monotonic,
                    "finished_at_monotonic": prerequisite.finished_at_monotonic,
                },
            },
            output,
            indent=2,
        )
        output.write("\n")
    if (
        {item.image for item in downloaded} != set(selected)
        or len(downloaded) != len(selected)
        or not all(item.completed for item in downloaded)
        or {item.image for item in pulled} != set(PREREQUISITE_IMAGES)
        or len(pulled) != len(PREREQUISITE_IMAGES)
        or not all(item.completed for item in pulled)
    ):
        raise RuntimeError("Exact image download or prerequisite preparation failed")


def identity() -> Identity:
    """Read the current tested head, not the PR merge commit."""
    value = Identity(
        repository=os.environ["GITHUB_REPOSITORY"],
        head_sha=os.environ["CI_HEAD_SHA"],
        run_id=int(os.environ["GITHUB_RUN_ID"]),
        attempt=int(os.environ["GITHUB_RUN_ATTEMPT"]),
    )
    if (
        re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", value.repository) is None
        or re.fullmatch(r"[0-9a-f]{40}", value.head_sha) is None
        or value.run_id <= 0
        or value.attempt <= 0
    ):
        raise ValueError("Invalid CI image workflow identity")
    return value


def decode_receipt(value: object) -> ImageReceipt:
    raw = object_value(value)
    if set(raw) != {
        "identity",
        "image",
        "image_id",
        "archive_sha256",
        "archive_bytes",
        "export_seconds",
    }:
        raise ValueError("Unexpected image receipt fields")
    owner = object_value(raw["identity"])
    if set(owner) != {"repository", "head_sha", "run_id", "attempt"}:
        raise ValueError("Unexpected image identity fields")
    image = text(raw["image"])
    image_id = text(raw["image_id"])
    digest = text(raw["archive_sha256"])
    duration = raw["export_seconds"]
    if (
        image not in IMAGES
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or isinstance(duration, bool)
        or not isinstance(duration, int | float)
        or not 0 < duration < float("inf")
    ):
        raise ValueError("Invalid CI image receipt")
    size = integer(raw["archive_bytes"])
    if size <= 0:
        raise ValueError("Image archive must be nonempty")
    return ImageReceipt(
        identity=Identity(
            text(owner["repository"]),
            text(owner["head_sha"]),
            integer(owner["run_id"]),
            integer(owner["attempt"]),
        ),
        image=image,
        image_id=image_id,
        archive_sha256=digest,
        archive_bytes=size,
        export_seconds=float(duration),
    )


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_checkout(owner: Identity) -> None:
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if source != owner.head_sha:
        raise ValueError("CI image checkout differs from the tested head SHA")


def inspect(image: str) -> str:
    result = subprocess.check_output(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image], text=True
    ).strip()
    if re.fullmatch(r"sha256:[0-9a-f]{64}", result) is None:
        raise ValueError("Docker did not report one image ID")
    return result


def export(image: str, directory: Path) -> ImageReceipt:
    """Keep exactly one already-built image with immutable execution provenance."""
    if image not in IMAGES:
        raise ValueError("Image is outside the E2E portfolio")
    owner = identity()
    verify_checkout(owner)
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    image_id = inspect(f"{image}:ci")
    archive = directory / ARCHIVE_NAME
    with archive.open("xb") as output:
        save = subprocess.Popen(
            ["docker", "image", "save", image_id], stdout=subprocess.PIPE
        )
        assert save.stdout is not None
        try:
            compressed = subprocess.run(
                ["zstd", "-3", "-T1", "--stdout"],
                stdin=save.stdout,
                stdout=output,
                check=False,
            )
        finally:
            save.stdout.close()
            status = save.wait()
        if compressed.returncode != 0 or status != 0:
            raise RuntimeError("CI Docker image export failed")
    receipt = ImageReceipt(
        owner,
        image,
        image_id,
        digest(archive),
        archive.stat().st_size,
        time.monotonic() - started,
    )
    (directory / "receipt.json").write_text(
        json.dumps(asdict(receipt), indent=2) + "\n"
    )
    return receipt


def _load_image(archive: Path, receipt: ImageReceipt) -> ImageLoad:
    started = time.monotonic()
    subprocess.run(["docker", "image", "load", "--input", str(archive)], check=True)
    tag = f"{receipt.image}:ci"
    if inspect(receipt.image_id) != receipt.image_id:
        raise ValueError("Loaded CI Docker image identity mismatch")
    subprocess.run(["docker", "image", "tag", receipt.image_id, tag], check=True)
    if inspect(tag) != receipt.image_id:
        raise ValueError("Tagged CI Docker image identity mismatch")
    finished = time.monotonic()
    return ImageLoad(receipt.image, finished - started, started, finished)


def load(root: Path, suite: str, environment: Path, evidence: Path) -> None:
    """Validate the entire exact portfolio before admitting any image to Docker."""
    owner = identity()
    verify_checkout(owner)
    selected = REQUIRED if suite == "required" else WEB
    verification_started = time.monotonic()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("CI image artifact root must be a directory")
    directories = sorted(root.iterdir())
    receipts: dict[str, tuple[Path, ImageReceipt]] = {}
    for directory in directories:
        if (
            directory.is_symlink()
            or not directory.is_dir()
            or set(p.name for p in directory.iterdir())
            != {
                ARCHIVE_NAME,
                "receipt.json",
            }
        ):
            raise ValueError("Unexpected CI image artifact content")
        receipt = decode_receipt(json.loads((directory / "receipt.json").read_text()))
        expected_name = f"ci-e2e-image-{receipt.image}-{owner.run_id}-{owner.attempt}"
        archive = directory / ARCHIVE_NAME
        if (
            directory.name != expected_name
            or receipt.identity != owner
            or receipt.image in receipts
            or archive.is_symlink()
            or (directory / "receipt.json").is_symlink()
            or not archive.is_file()
            or not (directory / "receipt.json").is_file()
            or archive.stat().st_size != receipt.archive_bytes
            or digest(archive) != receipt.archive_sha256
        ):
            raise ValueError("CI image provenance or archive integrity mismatch")
        receipts[receipt.image] = (archive, receipt)
    if set(receipts) != set(selected):
        raise ValueError("CI image portfolio is incomplete or unexpected")
    verification_seconds = time.monotonic() - verification_started
    started = time.monotonic()
    # Complete validation above precedes every import. Leaving the owner drains
    # both import slots even when one fails; no partial portfolio publishes env.
    with ThreadPoolExecutor(max_workers=2) as executor:
        loaded = tuple(
            executor.map(
                _load_image,
                [receipts[image][0] for image in selected],
                [receipts[image][1] for image in selected],
            )
        )
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "ci-image-handoff.json").write_text(
        json.dumps(
            {
                "identity": asdict(owner),
                "suite": suite,
                "images": [asdict(receipts[name][1]) for name in selected],
                "verification_seconds": verification_seconds,
                "load_seconds": time.monotonic() - started,
                "image_loads": [asdict(item) for item in loaded],
            },
            indent=2,
        )
        + "\n"
    )
    with environment.open("a") as output:
        output.writelines(f"{IMAGES[image]}={image}:ci\n" for image in selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    producer = commands.add_parser("export")
    producer.add_argument("--image", choices=IMAGES, required=True)
    producer.add_argument("--directory", type=Path, required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--root", type=Path, required=True)
    preparation.add_argument("--suite", choices=["required", "web"], required=True)
    preparation.add_argument("--evidence", type=Path, required=True)
    consumer = commands.add_parser("load")
    consumer.add_argument("--root", type=Path, required=True)
    consumer.add_argument("--suite", choices=["required", "web"], required=True)
    consumer.add_argument("--github-env", type=Path, required=True)
    consumer.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.operation == "export":
        export(args.image, args.directory)
    elif args.operation == "prepare":
        prepare(args.root, args.suite, args.evidence)
    else:
        load(args.root, args.suite, args.github_env, args.evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
