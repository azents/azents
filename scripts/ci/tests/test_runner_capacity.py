"""Hosted E2E cleanup has one fixed deletion boundary and honest receipts."""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci import runner_capacity

HOSTED = {
    "GITHUB_ACTIONS": "true",
    "RUNNER_ENVIRONMENT": "github-hosted",
    "RUNNER_OS": "Linux",
}
SDK = Path("/usr/local/lib/android/sdk")


class RunnerCapacityTest(unittest.TestCase):
    def setUp(self):
        usage = type(shutil.disk_usage("/"))
        capacity = patch(
            "scripts.ci.runner_capacity.shutil.disk_usage",
            return_value=usage(100, 90, 10),
        )
        capacity.start()
        self.addCleanup(capacity.stop)

    def test_refuses_non_hosted_or_non_linux_execution_before_any_mutation(self):
        for field, value in (
            ("GITHUB_ACTIONS", "false"),
            ("RUNNER_ENVIRONMENT", "self-hosted"),
            ("RUNNER_OS", "macOS"),
            ("RUNNER_ENVIRONMENT", ""),
        ):
            with (
                self.subTest(field=field, value=value),
                patch.dict("os.environ", {**HOSTED, field: value}),
                patch("scripts.ci.runner_capacity.subprocess.run") as command,
                tempfile.TemporaryDirectory() as temporary,
            ):
                evidence = Path(temporary) / "evidence"
                with self.assertRaisesRegex(RuntimeError, "GitHub-hosted"):
                    runner_capacity.reclaim(evidence)
                command.assert_not_called()
                self.assertFalse(evidence.exists())

    def test_rejects_symlink_target_and_ancestors_even_when_dangling(self):
        for ancestor, dangling in (
            (False, False),
            (False, True),
            (True, False),
            (True, True),
        ):
            with (
                self.subTest(ancestor=ancestor, dangling=dangling),
                tempfile.TemporaryDirectory() as temporary,
            ):
                directory = Path(temporary)
                destination = directory / "destination"
                if not dangling:
                    destination.mkdir()
                symlink = directory / "symlink"
                symlink.symlink_to(destination)
                target = symlink / "sdk" if ancestor else symlink
                with (
                    patch.dict("os.environ", HOSTED),
                    patch("scripts.ci.runner_capacity.ANDROID_SDK", target),
                    patch("scripts.ci.runner_capacity.subprocess.run") as command,
                ):
                    with self.assertRaisesRegex(ValueError, "symlinks"):
                        runner_capacity.reclaim(directory / "evidence")
                    command.assert_not_called()

    def test_permission_errors_before_and_after_deletion_propagate(self):
        for fail_before in (True, False):
            with self.subTest(fail_before=fail_before):
                self._assert_permission_error(fail_before)

    def _assert_permission_error(self, fail_before):
        original = Path.lstat
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict("os.environ", HOSTED),
        ):
            target = Path(temporary) / "sdk"
            target.mkdir()
            inaccessible = fail_before

            def inspect(path):
                if path == target and inaccessible:
                    raise PermissionError("SDK inspection denied")
                return original(path)

            def remove(*args, **kwargs):
                nonlocal inaccessible
                inaccessible = True

            evidence = Path(temporary) / "evidence"
            with (
                patch("scripts.ci.runner_capacity.ANDROID_SDK", target),
                patch.object(Path, "lstat", inspect),
                patch("scripts.ci.runner_capacity.subprocess.run", side_effect=remove),
            ):
                with self.assertRaisesRegex(PermissionError, "inspection denied"):
                    runner_capacity.reclaim(evidence)
            self.assertFalse((evidence / "runner-capacity-cleanup.json").exists())

    def test_fixed_target_and_before_after_receipts(self):
        self.assertEqual(runner_capacity.ANDROID_SDK, SDK)
        usage = type(shutil.disk_usage("/"))
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.dict("os.environ", HOSTED),
        ):
            target = Path(temporary) / "sdk"
            target.mkdir()
            (target / "unused-tool").write_bytes(b"fixture")
            evidence = Path(temporary) / "evidence"
            with (
                patch("scripts.ci.runner_capacity.ANDROID_SDK", target),
                patch(
                    "scripts.ci.runner_capacity.shutil.disk_usage",
                    side_effect=[
                        usage(100, 90, 10),
                        usage(100, 70, 30),
                    ],
                ),
                patch(
                    "scripts.ci.runner_capacity.subprocess.run",
                    side_effect=lambda *args, **kwargs: shutil.rmtree(target),
                ) as command,
            ):
                runner_capacity.reclaim(evidence)
            command.assert_called_once_with(
                [
                    "sudo",
                    "--non-interactive",
                    "rm",
                    "--recursive",
                    "--force",
                    "--",
                    str(target),
                ],
                check=True,
            )
            before = json.loads((evidence / "runner-capacity-before.json").read_text())
            after = json.loads((evidence / "runner-capacity-cleanup.json").read_text())
            self.assertEqual(before["target"], str(target))
            self.assertEqual(before["available_bytes"], 10)
            self.assertTrue(after["removed"])
            self.assertEqual(after["available_delta_bytes"], 20)

    def test_refuses_file_target_or_incomplete_deletion(self):
        for directory in (True, False):
            with (
                self.subTest(directory=directory),
                tempfile.TemporaryDirectory() as temporary,
                patch.dict("os.environ", HOSTED),
                patch("scripts.ci.runner_capacity.subprocess.run"),
            ):
                target = Path(temporary) / "sdk"
                if directory:
                    target.mkdir()
                else:
                    target.write_bytes(b"not a directory")
                evidence = Path(temporary) / "evidence"
                with patch("scripts.ci.runner_capacity.ANDROID_SDK", target):
                    with self.assertRaises(RuntimeError if directory else ValueError):
                        runner_capacity.reclaim(evidence)
                self.assertFalse((evidence / "runner-capacity-cleanup.json").exists())

    def test_cleanup_eligibility_skips_roomy_workers_at_exact_boundary(self):
        usage = type(shutil.disk_usage("/"))
        threshold = runner_capacity.RECLAIM_BELOW_BYTES
        for free in (threshold - 1, threshold, threshold + 1):
            with (
                self.subTest(free=free),
                tempfile.TemporaryDirectory() as temporary,
                patch.dict("os.environ", HOSTED),
            ):
                target = Path(temporary) / "sdk"
                target.mkdir()
                evidence = Path(temporary) / "evidence"
                with (
                    patch("scripts.ci.runner_capacity.ANDROID_SDK", target),
                    patch(
                        "scripts.ci.runner_capacity.shutil.disk_usage",
                        return_value=usage(threshold * 3, threshold * 3 - free, free),
                    ),
                    patch(
                        "scripts.ci.runner_capacity.subprocess.run",
                        side_effect=lambda *args, target=target, **kwargs: (
                            shutil.rmtree(target)
                        ),
                    ) as command,
                ):
                    runner_capacity.reclaim(evidence)
                after = json.loads(
                    (evidence / "runner-capacity-cleanup.json").read_text()
                )
                self.assertEqual(command.call_count, int(free < threshold))
                self.assertEqual(after["removed"], free < threshold)
                self.assertEqual(
                    after["outcome"],
                    "removed" if free < threshold else "sufficient_capacity",
                )

    def test_missing_sdk_is_noop_and_errors_are_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "sdk"
            for failure in (False, True):
                with (
                    self.subTest(failure=failure),
                    patch.dict("os.environ", HOSTED),
                    patch("scripts.ci.runner_capacity.ANDROID_SDK", target),
                    patch("scripts.ci.runner_capacity.subprocess.run") as command,
                ):
                    evidence = Path(temporary) / str(failure)
                    if failure:
                        target.mkdir()
                        command.side_effect = subprocess.CalledProcessError(1, "rm")
                        with self.assertRaises(subprocess.CalledProcessError):
                            runner_capacity.reclaim(evidence)
                        self.assertFalse(
                            (evidence / "runner-capacity-cleanup.json").exists()
                        )
                    else:
                        runner_capacity.reclaim(evidence)
                        command.assert_not_called()
                        receipt = json.loads(
                            (evidence / "runner-capacity-cleanup.json").read_text()
                        )
                        self.assertFalse(receipt["removed"])
                    self.assertTrue((evidence / "runner-capacity-before.json").exists())

    def test_workflow_reclaims_only_e2e_job_before_image_downloads(self):
        workflow = (Path(__file__).parents[3] / ".github/workflows/ci.yaml").read_text()
        self.assertEqual(workflow.count("scripts.ci.runner_capacity"), 1)
        lane = workflow.split("\n  ci_e2e_run:", 1)[1].split("\n  ci_e2e_", 1)[0]
        self.assertLess(
            lane.index("scripts.ci.runner_capacity"),
            lane.index("scripts.ci.e2e_images prepare"),
        )
