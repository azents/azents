"""Execute simulator diagnostic plumbing without claiming native iOS coverage."""

import os
import select
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HELPER = ROOT / "swift/scripts/simulator-diagnostics.sh"


class SimulatorDiagnosticsTest(unittest.TestCase):
    def test_stage_preserves_stdout_and_exit_status(self) -> None:
        for status in (0, 37):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as tmp:
                result = subprocess.run(
                    [
                        "bash",
                        "-c",
                        'set -euo pipefail; source "$1"; '
                        "simulator_stage create bash -c "
                        """'printf "device-id\\n"; """
                        """printf "diagnostic\\n" >&2; exit "$1"' """
                        'child "$2"',
                        "test",
                        str(HELPER),
                        str(status),
                    ],
                    env={**os.environ, "BUILD_ROOT": tmp},
                    capture_output=True,
                    check=False,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, status)
                self.assertEqual(result.stdout, "device-id\n")
                self.assertIn("diagnostic", result.stderr)
                log = (Path(tmp) / "simulator-setup.log").read_text()
                self.assertRegex(
                    log,
                    r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ stage=create event=start\n",
                )
                self.assertIn(f"stage=create event=end exit_code={status}\n", log)
                self.assertNotIn("device-id", log)

    def test_interrupted_stage_retains_start_before_command_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            os.mkfifo(root / "barrier")
            process = subprocess.Popen(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; '
                    "simulator_stage list-runtimes bash -c "
                    """'printf "entered\\n"; """
                    """read -r release < "$BUILD_ROOT/barrier"'""",
                    "test",
                    str(HELPER),
                ],
                env={**os.environ, "BUILD_ROOT": tmp},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                assert process.stdout is not None
                self.assertTrue(select.select([process.stdout], [], [], 10)[0])
                self.assertEqual(process.stdout.readline(), "entered\n")
                log = (root / "simulator-setup.log").read_text()
                self.assertIn("stage=list-runtimes event=start\n", log)
                self.assertNotIn("event=end", log)
            finally:
                os.killpg(process.pid, signal.SIGTERM)
                process.communicate(timeout=10)
            self.assertNotIn("event=end", (root / "simulator-setup.log").read_text())

    def test_native_test_failure_through_tee_stops_before_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [
                    "bash",
                    "-c",
                    'set -euo pipefail; source "$1"; '
                    "simulator_stage test bash -c "
                    """'printf "test failed\\n"; exit 37' """
                    '| tee "$BUILD_ROOT/test.log"; '
                    'touch "$BUILD_ROOT/build-started"',
                    "test",
                    str(HELPER),
                ],
                env={**os.environ, "BUILD_ROOT": tmp},
                capture_output=True,
                check=False,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 37)
            root = Path(tmp)
            self.assertEqual((root / "test.log").read_text(), "test failed\n")
            self.assertFalse((root / "build-started").exists())
            self.assertIn(
                "stage=test event=end exit_code=37",
                (root / "simulator-setup.log").read_text(),
            )

    def test_native_test_owns_startup_and_diagnostic_upload_is_preserved(
        self,
    ) -> None:
        script = (ROOT / "swift/scripts/ios.sh").read_text()
        positions = [
            script.index(f"simulator_stage {stage} xcrun simctl {command}")
            for stage, command in (
                ("list-runtimes", "list runtimes --json"),
                ("create", "create Azents-CI"),
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(
            positions[-1], script.index("simulator_stage test xcodebuild test")
        )
        self.assertNotIn("simctl boot", script)
        self.assertIn('-destination "platform=iOS Simulator,id=$simulator_id"', script)
        self.assertIn('-resultBundlePath "$BUILD_ROOT/UITests.xcresult"', script)
        self.assertIn('xcrun simctl shutdown "$simulator_id"', script)
        self.assertIn('xcrun simctl delete "$simulator_id"', script)
        workflow = (ROOT / ".github/workflows/ios.yaml").read_text()
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertIn("swift/.build/*.log", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn('source "$SWIFT_ROOT/scripts/simulator-diagnostics.sh"', script)
