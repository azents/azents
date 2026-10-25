"""Build-time installation of the pinned Camoufox/browser/model distribution."""

import argparse
import hashlib
import importlib.resources
import json
import platform
import stat
import subprocess
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path
from zipfile import ZipFile

from azents_runtime_runner.browser_camoufox import (
    CamoufoxInstallationError,
    camoufox_executable,
    require_camoufox_model,
)

CAMOUFOX_VERSION = "0.5.8"
# The SDK bundles an older default pin. The product pairs its interface-1 SDK
# with the audited interface-1 Firefox 158 build instead, including newer
# upstream security fixes. Native contract tests validate this exact pairing.
SDK_BROWSER_TAG = "v156.0.1-beta.36"
BROWSER_TAG = "v158.0-beta.40"
MODEL_SHA256 = "6530b8322cdaa4ec042921c8d9a0369a0e6e0269ba636c01a7203e4a2f109936"
# Official GitHub release-asset SHA256 digests, not unverified download metadata.
LINUX_ASSETS = {
    "x86_64": (
        "camoufox-158.0-beta.40-lin.x86_64.zip",
        "2ead498d4765394addd3278d6a663962f3f99b189a99d3f966de56656cefc823",
    ),
    "aarch64": (
        "camoufox-158.0-beta.40-lin.arm64.zip",
        "8a4dfdd85dfb5212dae716b4aa8e30041634edbbba6f6177a566a3ee6b1efe8c",
    ),
}


def verify_pairing() -> None:
    """Require the audited Python, driver, browser and fingerprint-model pair."""
    if version("camoufox") != CAMOUFOX_VERSION or version("playwright") != "1.62.0":
        raise CamoufoxInstallationError(
            "Camoufox SDK pairing differs from the build pin"
        )
    resources = importlib.resources.files("camoufox")
    pin = json.loads(resources.joinpath("browser-pin.json").read_text())
    model = json.loads(resources.joinpath("fpgen-model.json").read_text())
    if pin["tag"] != SDK_BROWSER_TAG or model["sha256"] != MODEL_SHA256:
        raise CamoufoxInstallationError(
            "Camoufox asset pairing differs from the build pin"
        )


def verify_archive(path: Path, expected: str) -> None:
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise CamoufoxInstallationError("Camoufox archive integrity check failed")


def unpack_archive(archive: Path, destination: Path) -> None:
    """Extract only regular files/directories under the owned build location."""
    with ZipFile(archive) as source:
        for member in source.infolist():
            target = destination / member.filename
            mode = member.external_attr >> 16
            if (
                not target.resolve().is_relative_to(destination.resolve())
                or stat.S_ISLNK(mode)
                or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR})
            ):
                raise CamoufoxInstallationError("Unsafe Camoufox archive member")
        for member in source.infolist():
            path = Path(source.extract(member, destination))
            if not member.is_dir():
                path.chmod(0o755 if member.external_attr >> 16 & 0o111 else 0o644)


def install(archive: Path | None) -> None:
    """Install at image build time; this entrypoint is never called by startup."""
    verify_pairing()
    if sys.platform != "linux" or platform.machine() not in LINUX_ASSETS:
        raise CamoufoxInstallationError("Unsupported Camoufox image architecture")
    name, digest = LINUX_ASSETS[platform.machine()]
    destination = Path(sys.prefix) / "share" / "azents-browsers" / "camoufox"
    if destination.exists():
        raise CamoufoxInstallationError("Camoufox build destination already exists")
    with tempfile.TemporaryDirectory(prefix="azents-browser-build-") as temporary:
        if archive is None:
            archive = Path(temporary) / name
            url = f"https://github.com/daijro/camoufox/releases/download/{BROWSER_TAG}/{name}"
            subprocess.run(
                [
                    "curl",
                    "--fail",
                    "--location",
                    "--silent",
                    "--show-error",
                    "--retry",
                    "5",
                    "--retry-all-errors",
                    "--connect-timeout",
                    "15",
                    "--max-time",
                    "600",
                    "--output",
                    str(archive),
                    url,
                ],
                check=True,
            )
        verify_archive(archive, digest)
        unpack_archive(archive, destination)
    camoufox_executable().chmod(0o755)
    # Upstream verifies the pinned archive and every model member. This is the
    # only build-time call allowed to provision the model; startup only checks.
    from camoufox.fpgen_model import ensure_fpgen_model  # noqa: PLC0415

    ensure_fpgen_model()
    require_camoufox_model()
    sys.stdout.write(
        json.dumps(
            {
                "camoufox": version("camoufox"),
                "playwright": version("playwright"),
                "browser": BROWSER_TAG,
                "archive_sha256": digest,
                "model_sha256": MODEL_SHA256,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    install(args.archive)


if __name__ == "__main__":
    main()
