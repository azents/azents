"""Image handoff requires the exact portfolio and bytes before Docker admission."""

import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from scripts.ci.e2e_images import (
    CORE,
    IMAGES,
    Identity,
    ImageReceipt,
    decode_receipt,
    digest,
    identity,
    load,
    verify_checkout,
)

ENV = {
    "GITHUB_REPOSITORY": "azents/azents",
    "CI_HEAD_SHA": "a" * 40,
    "GITHUB_RUN_ID": "100",
    "GITHUB_RUN_ATTEMPT": "2",
}
OWNER = Identity("azents/azents", "a" * 40, 100, 2)
IMAGE_ID = "sha256:" + "b" * 64


def portfolio(root: Path, selected: tuple[str, ...]) -> None:
    root.mkdir()
    for image in selected:
        directory = root / f"ci-e2e-image-{image}-100-2"
        directory.mkdir()
        archive = directory / "image.tar.gz"
        archive.write_bytes(image.encode())
        receipt = ImageReceipt(
            OWNER, image, IMAGE_ID, digest(archive), archive.stat().st_size, 1.0
        )
        (directory / "receipt.json").write_text(json.dumps(asdict(receipt)))


class ImageHandoffTest(unittest.TestCase):
    def setUp(self):
        checkout = patch("scripts.ci.e2e_images.verify_checkout")
        checkout.start()
        self.addCleanup(checkout.stop)

    def test_real_checkout_validation_rejects_merge_or_other_source(self):
        for source in ("a" * 40, "b" * 40):
            with (
                self.subTest(source=source),
                patch(
                    "scripts.ci.e2e_images.subprocess.check_output",
                    return_value=source + "\n",
                ),
            ):
                if source == OWNER.head_sha:
                    verify_checkout(OWNER)
                else:
                    with self.assertRaisesRegex(ValueError, "checkout"):
                        verify_checkout(OWNER)

    def test_current_identity_is_tested_head_and_rejects_invalid_metadata(self):
        with patch.dict("os.environ", ENV):
            self.assertEqual(identity(), OWNER)
        for field, value in (
            ("CI_HEAD_SHA", "merge-ref"),
            ("GITHUB_RUN_ID", "0"),
            ("GITHUB_RUN_ATTEMPT", "-1"),
            ("GITHUB_REPOSITORY", "unsafe\n=value"),
        ):
            with (
                self.subTest(field=field),
                patch.dict("os.environ", {**ENV, field: value}),
            ):
                with self.assertRaises(ValueError):
                    identity()

    def test_required_and_web_admit_the_whole_exact_portfolio(self):
        for suite, selected in (("required", CORE), ("web", tuple(IMAGES))):
            with self.subTest(suite=suite), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "artifacts"
                portfolio(root, selected)
                env = Path(tmp) / "github-env"
                evidence = Path(tmp) / "evidence"
                with (
                    patch.dict("os.environ", ENV),
                    patch("scripts.ci.e2e_images.subprocess.run") as docker,
                    patch("scripts.ci.e2e_images.inspect", return_value=IMAGE_ID),
                ):
                    load(root, suite, env, evidence)
                self.assertEqual(docker.call_count, 2 * len(selected))
                self.assertEqual(
                    env.read_text().splitlines(),
                    [f"{IMAGES[name]}={name}:ci" for name in selected],
                )
                receipt = json.loads((evidence / "ci-image-handoff.json").read_text())
                self.assertEqual(receipt["identity"], asdict(OWNER))
                self.assertEqual(
                    [r["image"] for r in receipt["images"]], list(selected)
                )

    def test_invalid_last_artifact_never_loads_even_the_first_image(self):
        for scenario in (
            "missing",
            "extra",
            "stale_sha",
            "stale_run",
            "stale_attempt",
            "wrong_repo",
            "corrupt_bytes",
            "wrong_size",
            "unsafe_image",
            "bad_image_id",
            "unknown_field",
            "symlink",
            "unexpected_root_file",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "artifacts"
                portfolio(root, tuple(IMAGES))
                last = root / "ci-e2e-image-azents-admin-web-100-2"
                path = last / "receipt.json"
                receipt = json.loads(path.read_text())
                match scenario:
                    case "missing":
                        path.unlink()
                    case "extra":
                        (last / "extra.txt").write_text("unexpected")
                    case "stale_sha":
                        receipt["identity"]["head_sha"] = "c" * 40
                    case "stale_run":
                        receipt["identity"]["run_id"] = 101
                    case "stale_attempt":
                        receipt["identity"]["attempt"] = 1
                    case "wrong_repo":
                        receipt["identity"]["repository"] = "foreign/repository"
                    case "corrupt_bytes":
                        (last / "image.tar.gz").write_bytes(b"corrupt")
                    case "wrong_size":
                        receipt["archive_bytes"] += 1
                    case "unsafe_image":
                        receipt["image"] = "../../wrong"
                    case "bad_image_id":
                        receipt["image_id"] = "not-an-image-id"
                    case "unknown_field":
                        receipt["future"] = True
                    case "symlink":
                        target = Path(tmp) / "elsewhere"
                        (last / "image.tar.gz").rename(target)
                        (last / "image.tar.gz").symlink_to(target)
                    case "unexpected_root_file":
                        (root / "unexpected.txt").write_text("unexpected")
                if scenario != "missing":
                    path.write_text(json.dumps(receipt))
                env = Path(tmp) / "github-env"
                evidence = Path(tmp) / "evidence"
                with (
                    patch.dict("os.environ", ENV),
                    patch("scripts.ci.e2e_images.subprocess.run") as docker,
                    self.assertRaises(ValueError),
                ):
                    load(root, "web", env, evidence)
                docker.assert_not_called()
                self.assertFalse(env.exists())
                self.assertFalse(evidence.exists())

    def test_wrong_loaded_image_cannot_publish_environment_or_success_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "artifacts"
            portfolio(root, CORE)
            env = Path(tmp) / "github-env"
            evidence = Path(tmp) / "evidence"
            with (
                patch.dict("os.environ", ENV),
                patch("scripts.ci.e2e_images.subprocess.run"),
                patch(
                    "scripts.ci.e2e_images.inspect", return_value="sha256:" + "c" * 64
                ),
                self.assertRaisesRegex(ValueError, "Loaded"),
            ):
                load(root, "required", env, evidence)
            self.assertFalse(env.exists())
            self.assertFalse(evidence.exists())

    def test_missing_and_duplicate_portfolios_fail_closed(self):
        for scenario in ("missing", "duplicate", "extra_web_for_required"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "artifacts"
                portfolio(
                    root,
                    CORE if scenario != "extra_web_for_required" else tuple(IMAGES),
                )
                if scenario == "missing":
                    last = root / "ci-e2e-image-azents-runtime-runner-100-2"
                    for path in last.iterdir():
                        path.unlink()
                    last.rmdir()
                elif scenario == "duplicate":
                    (root / "ci-e2e-image-azents-runtime-runner-100-2").rename(
                        root / "ci-e2e-image-azents-server-100-1"
                    )
                with (
                    patch.dict("os.environ", ENV),
                    patch("scripts.ci.e2e_images.subprocess.run") as docker,
                    self.assertRaises(ValueError),
                ):
                    load(root, "required", Path(tmp) / "env", Path(tmp) / "evidence")
                docker.assert_not_called()

    def test_native_receipt_rejects_missing_or_invalid_duration(self):
        receipt = asdict(ImageReceipt(OWNER, "azents-web", IMAGE_ID, "d" * 64, 1, 1.0))
        for invalid in (None, True, 0, -1, float("nan"), float("inf")):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                decode_receipt({**receipt, "export_seconds": invalid})
