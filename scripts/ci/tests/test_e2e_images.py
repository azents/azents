"""Image handoff requires the exact portfolio and bytes before Docker admission."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from scripts.ci.e2e_images import (
    CORE,
    IMAGES,
    REQUIRED,
    WEB,
    ActiveImageDownload,
    Identity,
    ImageLoad,
    ImageReceipt,
    _download,
    decode_receipt,
    digest,
    identity,
    load,
    prepare,
    verify_checkout,
)
from testenv.azents.e2e.src.support.e2e_snapshot_images import PREREQUISITE_IMAGES

ENV = {
    "GITHUB_REPOSITORY": "azents/azents",
    "CI_HEAD_SHA": "a" * 40,
    "GITHUB_RUN_ID": "100",
    "GITHUB_RUN_ATTEMPT": "2",
}
OWNER = Identity("azents/azents", "a" * 40, 100, 2)
IMAGE_ID = "sha256:" + "b" * 64


class DownloadProcess:
    """A command receipt whose wait operation runs in the owned I/O slot."""

    def __init__(self, command, run):
        self.command = command
        self.run = run
        self.returncode = None

    def wait(self):
        result = self.run(self.command)
        if self.returncode is None:
            self.returncode = result.returncode
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9


def portfolio(root: Path, selected: tuple[str, ...]) -> None:
    root.mkdir()
    for image in selected:
        directory = root / f"ci-e2e-image-{image}-100-2"
        directory.mkdir()
        archive = directory / "image.tar.zst"
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

    def test_snapshot_cli_runs_without_pythonpath_from_any_directory(self):
        root = Path(__file__).resolve().parents[3]
        script = root / "testenv/azents/e2e/src/support/e2e_snapshot_images.py"
        environment = {
            key: value for key, value in os.environ.items() if key != "PYTHONPATH"
        }
        with tempfile.TemporaryDirectory() as tmp:
            for cwd in (root, Path(tmp)):
                result = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    env=environment,
                    cwd=cwd,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("--artifact-dir", result.stdout)
                self.assertIn("--github-env", result.stdout)

    def test_required_and_web_admit_the_whole_exact_portfolio(self):
        for suite, selected in (("required", REQUIRED), ("web", WEB)):
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
                portfolio(root, WEB)
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
                        (last / "image.tar.zst").write_bytes(b"corrupt")
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
                        (last / "image.tar.zst").rename(target)
                        (last / "image.tar.zst").symlink_to(target)
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
            portfolio(root, REQUIRED)
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
                    REQUIRED if scenario != "extra_web_for_required" else tuple(IMAGES),
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

    def test_preparation_overlaps_download_and_pulls_but_joins_every_outcome(self):
        for scenario in ("passed", "download_failure", "pull_failure"):
            for suite, selected in (("required", REQUIRED), ("web", WEB)):
                with self.subTest(scenario=scenario, suite=suite):
                    self._check_preparation(scenario, suite, selected)

    def _check_preparation(self, scenario, suite, selected):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "images"
            evidence = Path(tmp) / "evidence"
            download_started = threading.Event()
            pull_started = threading.Event()
            pulls_finished = set()
            lock = threading.Lock()
            commands = []

            def run(command, **_kwargs):
                with lock:
                    commands.append(command)
                if command[0] == "gh":
                    download_started.set()
                    self.assertTrue(pull_started.wait(5))
                    self.assertEqual(command[1:4], ["run", "download", "100"])
                    self.assertIn("azents/azents", command)
                    self.assertIn("-100-2", command[command.index("--name") + 1])
                    status = int(scenario == "download_failure")
                else:
                    self.assertEqual(command[:2], ("docker", "pull"))
                    pull_started.set()
                    self.assertTrue(download_started.wait(5))
                    with lock:
                        pulls_finished.add(command[2])
                    status = int(
                        scenario == "pull_failure" and command[2] == "postgres:18"
                    )
                return subprocess.CompletedProcess(command, status, "", "")

            with (
                patch.dict("os.environ", ENV),
                patch(
                    "scripts.ci.e2e_images.subprocess.run", side_effect=run
                ) as docker,
                patch(
                    "scripts.ci.e2e_images.subprocess.Popen",
                    side_effect=lambda command: DownloadProcess(command, run),
                ),
            ):
                if scenario == "passed":
                    prepare(root, suite, evidence)
                else:
                    with self.assertRaisesRegex(RuntimeError, "preparation failed"):
                        prepare(root, suite, evidence)
                self.assertEqual(pulls_finished, set(PREREQUISITE_IMAGES))
                receipt = json.loads(
                    (evidence / "ci-image-preparation.json").read_text()
                )
                self.assertEqual(receipt["identity"], asdict(OWNER))
                self.assertEqual(
                    {x["image"] for x in receipt["prerequisite_pulls"]},
                    set(PREREQUISITE_IMAGES),
                )
                self.assertEqual(
                    {x["image"] for x in receipt["downloads"]},
                    set(selected),
                )
                self.assertLess(
                    max(
                        min(x["started_at_monotonic"] for x in receipt["downloads"]),
                        receipt["prerequisite_window"]["started_at_monotonic"],
                    ),
                    min(
                        max(x["finished_at_monotonic"] for x in receipt["downloads"]),
                        receipt["prerequisite_window"]["finished_at_monotonic"],
                    ),
                )
                self.assertTrue(
                    all(
                        tuple(command[:3]) != ("docker", "image", "load")
                        for command in commands
                    )
                )
                count = docker.call_count
                with self.assertRaises(FileExistsError):
                    prepare(root, suite, evidence)
                self.assertEqual(docker.call_count, count)

    def test_exact_download_requests_overlap_in_two_owned_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = threading.Lock()
            both_started = threading.Event()
            names = []
            active = 0
            peak = 0

            def run(command, **_kwargs):
                nonlocal active, peak
                with lock:
                    names.append(command[command.index("--name") + 1])
                    active += 1
                    peak = max(peak, active)
                    if len(names) >= 2:
                        both_started.set()
                self.assertTrue(both_started.wait(5), "downloads did not overlap")
                with lock:
                    active -= 1
                return subprocess.CompletedProcess(command, 0)

            with patch(
                "scripts.ci.e2e_images.subprocess.Popen",
                side_effect=lambda command: DownloadProcess(command, run),
            ):
                results = _download(Path(tmp), CORE, OWNER)
            self.assertEqual(peak, 2)
            self.assertEqual(
                sorted(names),
                sorted(f"ci-e2e-image-{image}-100-2" for image in CORE),
            )
            self.assertTrue(all(item.completed for item in results))
            self.assertTrue(all(item.outcome == "passed" for item in results))
            self.assertTrue(
                all(
                    item.finished_at_monotonic > item.started_at_monotonic
                    for item in results
                )
            )

    def test_failed_download_reaps_its_real_sibling_and_never_starts_queued_work(self):
        self._check_real_download_failure(startup_failure=False, later_failure=False)

    def test_later_download_failure_stops_refill_and_reaps_running_sibling(self):
        self._check_real_download_failure(startup_failure=False, later_failure=True)

    def test_startup_failure_reaps_the_child_already_started(self):
        self._check_real_download_failure(startup_failure=True, later_failure=False)

    def _check_real_download_failure(self, *, startup_failure, later_failure):
        children = []
        started = []
        real_popen = subprocess.Popen

        def child(exit_code):
            process = real_popen(
                [
                    sys.executable,
                    "-c",
                    "import sys; print('ready', flush=True); "
                    f"sys.stdin.read(); sys.exit({exit_code})",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
            children.append(process)
            self.assertEqual(process.stdout.readline(), b"ready\n")
            return process

        # This unrelated child must survive the download owner's failure.
        unrelated = child(23)

        def start(_root, image, _owner):
            started.append(image)
            if startup_failure and len(started) == 2:
                raise OSError("synthetic gh spawn failure")
            process = child(0 if later_failure and len(started) == 1 else 23)
            if len(started) == 2:
                # Both native processes are running before the first fails.
                children[1].stdin.close()
            elif later_failure and len(started) == 3:
                process.stdin.close()
            return ActiveImageDownload(image, process, time.monotonic())

        try:
            with (
                tempfile.TemporaryDirectory() as tmp,
                patch("scripts.ci.e2e_images._start_download", side_effect=start),
                ThreadPoolExecutor(max_workers=1) as executor,
            ):
                future = executor.submit(_download, Path(tmp), REQUIRED, OWNER)
                try:
                    if startup_failure:
                        with self.assertRaisesRegex(OSError, "synthetic"):
                            future.result(timeout=5)
                    else:
                        results = future.result(timeout=5)
                        self.assertEqual(
                            [item.outcome for item in results],
                            ["passed", "cancelled", "failed", "not_started"]
                            if later_failure
                            else ["failed", "cancelled", "not_started", "not_started"],
                        )
                        self.assertEqual(
                            [item.completed for item in results],
                            [later_failure, False, False, False],
                        )
                        if not later_failure:
                            self.assertEqual(results[2].duration_seconds, 0)
                        self.assertEqual(results[3].duration_seconds, 0)
                    self.assertEqual(
                        started, list(REQUIRED[: 3 if later_failure else 2])
                    )
                    self.assertIsNone(unrelated.poll())
                    self.assertTrue(
                        all(process.returncode is not None for process in children[1:])
                    )
                finally:
                    # Bound the test even if the owner's drain regresses.
                    for process in children[1:]:
                        if process.poll() is None:
                            process.kill()
                        process.wait()
        finally:
            for process in children:
                if process.poll() is None:
                    process.kill()
                process.wait()
                if not process.stdin.closed:
                    process.stdin.close()
                process.stdout.close()

    def test_finished_batch_is_checked_before_any_successful_slot_is_refilled(self):
        started = []

        def start(_root, image, _owner):
            started.append(image)
            code = int(image == REQUIRED[1])
            process = DownloadProcess(
                [image], lambda command: subprocess.CompletedProcess(command, code)
            )
            return ActiveImageDownload(image, process, time.monotonic())

        def whole_batch(futures, **_kwargs):
            for future in futures:
                future.result(timeout=5)
            return set(futures), set()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("scripts.ci.e2e_images._start_download", side_effect=start),
            patch("scripts.ci.e2e_images.wait", side_effect=whole_batch),
        ):
            results = _download(Path(tmp), REQUIRED, OWNER)
        self.assertEqual(started, list(REQUIRED[:2]))
        self.assertEqual(
            [item.outcome for item in results],
            ["passed", "failed", "not_started", "not_started"],
        )

    def test_natural_exit_during_kill_retains_the_actual_outcome(self):
        for exit_code in (0, 23):
            with self.subTest(exit_code=exit_code):
                self._check_natural_exit_during_kill(exit_code)

    def _check_natural_exit_during_kill(self, exit_code):
        both_started = threading.Event()
        finishing = threading.Event()
        started = []

        class ExitingProcess:
            def wait(self):
                if not finishing.wait(5):
                    raise AssertionError("owner did not drain sibling")
                return exit_code

            def poll(self):
                return None

            def kill(self):
                # CPython kill may repoll and return after natural exit.
                finishing.set()

        def fail(command):
            self.assertTrue(both_started.wait(5))
            return subprocess.CompletedProcess(command, 1)

        def start(_root, image, _owner):
            started.append(image)
            if len(started) == 1:
                process = DownloadProcess([image], fail)
            else:
                process = ExitingProcess()
                both_started.set()
            return ActiveImageDownload(image, process, time.monotonic())

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("scripts.ci.e2e_images._start_download", side_effect=start),
        ):
            results = _download(Path(tmp), REQUIRED, OWNER)
        self.assertEqual(started, list(REQUIRED[:2]))
        self.assertEqual(
            [item.outcome for item in results],
            [
                "failed",
                "passed" if exit_code == 0 else "failed",
                "not_started",
                "not_started",
            ],
        )
        self.assertEqual(results[1].completed, exit_code == 0)

    def test_complete_validation_precedes_two_slot_import_and_environment_publication(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "images"
            portfolio(root, WEB)
            env = Path(tmp) / "env"
            evidence = Path(tmp) / "evidence"
            lock = threading.Lock()
            both_started = threading.Event()
            started = set()
            finished = set()

            def import_image(archive, receipt):
                self.assertTrue(archive.is_file())
                self.assertFalse(env.exists())
                with lock:
                    started.add(receipt.image)
                    if len(started) >= 2:
                        both_started.set()
                self.assertTrue(both_started.wait(5), "imports did not overlap")
                with lock:
                    finished.add(receipt.image)
                return ImageLoad(receipt.image, 1.0, 1.0, 2.0)

            with (
                patch.dict("os.environ", ENV),
                patch("scripts.ci.e2e_images._load_image", side_effect=import_image),
            ):
                load(root, "web", env, evidence)
            self.assertEqual(finished, set(WEB))
            self.assertEqual(len(env.read_text().splitlines()), len(WEB))
            receipt = json.loads((evidence / "ci-image-handoff.json").read_text())
            self.assertEqual({x["image"] for x in receipt["image_loads"]}, set(WEB))
