"""One owned build archive serves producer smoke and exact image consumers."""

import io
import json
import subprocess
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.ci.e2e_images import ARCHIVE_NAME, _write_archive, build_runner, digest

ENV = {
    "GITHUB_REPOSITORY": "azents/azents",
    "CI_HEAD_SHA": "a" * 40,
    "GITHUB_RUN_ID": "100",
    "GITHUB_RUN_ATTEMPT": "2",
}
CONFIG = "sha256:" + "b" * 64
MANIFEST = "sha256:" + "c" * 64
PAYLOAD = b"completed-compressed-build-archive"


class DirectImageBuildTest(unittest.TestCase):
    def _exercise(self, directory, *, scenario="success", reported=CONFIG):
        process = Mock()
        process.stdout = io.BytesIO()
        process.poll.return_value = 1 if scenario == "build_failure" else None
        process.wait.return_value = 1 if scenario == "build_failure" else 0
        metadata_path = None

        def start(command, **kwargs):
            nonlocal metadata_path
            self.assertEqual(command[:3], ["docker", "buildx", "build"])
            self.assertEqual(kwargs, {"stdout": subprocess.PIPE})
            self.assertEqual(
                command[command.index("--output") + 1], "type=docker,dest=-"
            )
            self.assertNotIn("--load", command)
            self.assertEqual(command[-3:], ["-t", "azents-runtime-runner:ci", "."])
            metadata_path = Path(command[command.index("--metadata-file") + 1])
            self.assertFalse(metadata_path.is_relative_to(directory))
            if scenario != "missing_metadata":
                metadata_path.write_text(
                    json.dumps(
                        {
                            "containerimage.digest": MANIFEST,
                            "containerimage.config.digest": (
                                "invalid" if scenario == "bad_metadata" else CONFIG
                            ),
                            "unrelated.buildx.field": {"allowed": True},
                        }
                    )
                )
            return process

        def run(command, **kwargs):
            self.assertFalse((directory / "receipt.json").exists())
            if command[0] == "zstd":
                self.assertEqual(command, ["zstd", "-3", "-T1", "--stdout"])
                self.assertIs(kwargs["stdin"], process.stdout)
                if scenario == "compressor_launch_failure":
                    raise OSError("cannot start compressor")
                if scenario == "interrupted":
                    raise KeyboardInterrupt
                kwargs["stdout"].write(PAYLOAD)
                return subprocess.CompletedProcess(
                    command, 1 if scenario == "compressor_failure" else 0
                )
            self.assertEqual(
                command,
                ["docker", "image", "load", "--input", str(directory / ARCHIVE_NAME)],
            )
            self.assertTrue(kwargs["check"])
            self.assertEqual((directory / ARCHIVE_NAME).read_bytes(), PAYLOAD)
            if scenario == "load_failure":
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)

        with (
            patch.dict("os.environ", ENV),
            patch("scripts.ci.e2e_images.verify_checkout") as checkout,
            patch("scripts.ci.e2e_images.subprocess.Popen", side_effect=start) as build,
            patch(
                "scripts.ci.e2e_images.subprocess.run", side_effect=run
            ) as operations,
            patch("scripts.ci.e2e_images.inspect", return_value=reported),
            patch(
                "scripts.ci.e2e_images.time.monotonic", side_effect=[10, 30, 31, 40, 41]
            ),
        ):
            if scenario == "success":
                result = build_runner(directory)
                checkout.assert_called_once()
                self.assertEqual(result.receipt.image_id, reported)
                self.assertEqual(
                    result.receipt.archive_sha256, digest(directory / ARCHIVE_NAME)
                )
                self.assertEqual(result.receipt.archive_bytes, len(PAYLOAD))
                self.assertEqual(result.receipt.export_seconds, 20)
                self.assertEqual(result.producer_load_seconds, 9)
                self.assertEqual(result.total_seconds, 31)
                self.assertEqual(
                    json.loads((directory / "receipt.json").read_text()),
                    json.loads(json.dumps(asdict(result.receipt))),
                )
                self.assertEqual(
                    {path.name for path in directory.iterdir()},
                    {ARCHIVE_NAME, "receipt.json"},
                )
                self.assertEqual(build.call_count, 1)
                self.assertEqual(operations.call_count, 2)
                process.terminate.assert_not_called()
            else:
                with self.assertRaises(
                    (
                        RuntimeError,
                        ValueError,
                        OSError,
                        KeyboardInterrupt,
                        KeyError,
                        subprocess.CalledProcessError,
                    )
                ):
                    build_runner(directory)
                self.assertFalse((directory / "receipt.json").exists())
                if scenario in {
                    "compressor_failure",
                    "compressor_launch_failure",
                    "interrupted",
                }:
                    process.terminate.assert_called_once()
                if scenario in {
                    "build_failure",
                    "compressor_failure",
                    "compressor_launch_failure",
                    "interrupted",
                    "missing_metadata",
                    "bad_metadata",
                }:
                    self.assertTrue(
                        all(
                            call.args[0][0] == "zstd"
                            for call in operations.call_args_list
                        )
                    )
            process.wait.assert_called_once()
            self.assertTrue(process.stdout.closed)
        if metadata_path is not None:
            self.assertFalse(metadata_path.exists())

    def test_exact_completed_archive_and_native_docker_identity_forms(self):
        for image_id in (CONFIG, MANIFEST):
            with self.subTest(image_id=image_id), tempfile.TemporaryDirectory() as tmp:
                self._exercise(Path(tmp) / "image", reported=image_id)

    def test_each_failure_retains_evidence_without_publishing_receipt(self):
        for scenario in (
            "build_failure",
            "compressor_failure",
            "compressor_launch_failure",
            "interrupted",
            "missing_metadata",
            "bad_metadata",
            "load_failure",
            "identity_mismatch",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                self._exercise(
                    Path(tmp) / "image",
                    scenario=scenario,
                    reported="sha256:" + "d" * 64
                    if scenario == "identity_mismatch"
                    else CONFIG,
                )

    def test_stale_checkout_or_reused_output_never_starts_a_process(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", ENV):
            directory = Path(tmp) / "image"
            directory.mkdir()
            with (
                patch("scripts.ci.e2e_images.verify_checkout"),
                patch("scripts.ci.e2e_images.subprocess.Popen") as build,
                self.assertRaises(FileExistsError),
            ):
                build_runner(directory)
            build.assert_not_called()
            with (
                patch(
                    "scripts.ci.e2e_images.verify_checkout",
                    side_effect=ValueError("stale checkout"),
                ),
                patch("scripts.ci.e2e_images.subprocess.Popen") as build,
                self.assertRaisesRegex(ValueError, "stale checkout"),
            ):
                build_runner(Path(tmp) / "new")
            build.assert_not_called()
            self.assertFalse((Path(tmp) / "new").exists())

    def test_compressor_failure_escalates_only_the_owned_producer(self):
        process = Mock()
        process.stdout = io.BytesIO()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("owned", 5), -9]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("scripts.ci.e2e_images.subprocess.Popen", return_value=process),
            patch(
                "scripts.ci.e2e_images.subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ),
            self.assertRaisesRegex(RuntimeError, "archive production failed"),
        ):
            _write_archive(["owned-producer"], Path(tmp) / "archive")
        process.terminate.assert_called_once()
        process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)

    def test_interruption_during_producer_wait_still_reaps_it(self):
        process = Mock()
        process.stdout = io.BytesIO()
        process.poll.return_value = None
        process.wait.side_effect = [KeyboardInterrupt, -15]
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("scripts.ci.e2e_images.subprocess.Popen", return_value=process),
            patch(
                "scripts.ci.e2e_images.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            _write_archive(["owned-producer"], Path(tmp) / "archive")
        process.terminate.assert_called_once()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(process.stdout.closed)
