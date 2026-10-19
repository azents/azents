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

    def test_existing_ios_command_order_and_diagnostic_upload_are_preserved(
        self,
    ) -> None:
        script = (ROOT / "swift/scripts/ios.sh").read_text()
        positions = [
            script.index(f"simulator_stage {stage} xcrun simctl {command}")
            for stage, command in (
                ("list-runtimes", "list runtimes --json"),
                ("create", "create Azents-CI"),
                ("boot", 'boot "$simulator_id"'),
                ("bootstatus", 'bootstatus "$simulator_id" -b'),
            )
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(positions[-1], script.index("xcodebuild test"))
        workflow = (ROOT / ".github/workflows/ios.yaml").read_text()
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertIn("swift/.build/*.log", workflow)
        self.assertIn("if: always()", workflow)
        self.assertIn('source "$SWIFT_ROOT/scripts/simulator-diagnostics.sh"', script)
