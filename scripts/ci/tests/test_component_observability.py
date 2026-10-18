"""The browser component producer must retain native evidence and fail closed."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci.component_portfolio import STORIES
from scripts.ci.run_component_tests import main


def component_junit(outcome: str) -> str:
    cases = "".join(
        f'<testcase classname="{path}" name="{name}" time="0.1">{outcome}</testcase>'
        for path, names in STORIES.items()
        for name in names
    )
    return f"<testsuite>{cases}</testsuite>"


class ComponentObservabilityTest(unittest.TestCase):
    def test_native_component_command_and_all_failure_modes(self):
        for scenario in (
            "passed",
            "native_failure",
            "missing",
            "empty",
            "skipped",
            "failed",
            "partial",
            "missing_suite",
            "missing_play",
            "duplicate",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "evidence"
                argv = [
                    "run_component_tests",
                    "--project",
                    tmp,
                    "--artifact-dir",
                    str(root),
                ]

                def run(
                    command: list[str],
                    *,
                    current_root: Path = root,
                    current_scenario: str = scenario,
                    **_kwargs: object,
                ) -> subprocess.CompletedProcess:
                    self.assertEqual(command[:3], ["pnpm", "exec", "vitest"])
                    self.assertNotIn("--", command)
                    self.assertIn("--reporter=junit", command)
                    self.assertEqual(
                        sum(p.endswith(".stories.tsx") for p in command), 3
                    )
                    if current_scenario != "missing":
                        outcome = {
                            "skipped": "<skipped/>",
                            "failed": "<failure/>",
                        }.get(current_scenario, "")
                        xml = component_junit(outcome)
                        match current_scenario:
                            case "empty":
                                xml = "<testsuite/>"
                            case "partial":
                                xml = (
                                    '<testsuite><testcase name="contract"/></testsuite>'
                                )
                            case "missing_suite":
                                xml = xml.replace(
                                    "ChatSessionView.stories.tsx", "Other.stories.tsx"
                                )
                            case "missing_play":
                                xml = xml.replace(
                                    'name="Reset Confirmation"', 'name="Wrong"'
                                )
                            case "duplicate":
                                xml = xml.replace(
                                    'name="Reset Confirmation"',
                                    'name="Restart Confirmation"',
                                )
                        (current_root / "junit.xml").write_text(xml)
                    return subprocess.CompletedProcess(
                        command, 2 if current_scenario == "native_failure" else 0
                    )

                with (
                    patch.object(sys, "argv", argv),
                    patch.dict(
                        "os.environ",
                        {
                            "CI_HEAD_SHA": "a" * 40,
                            "GITHUB_RUN_ID": "100",
                            "GITHUB_RUN_ATTEMPT": "2",
                        },
                    ),
                    patch(
                        "scripts.ci.run_component_tests.subprocess.run", side_effect=run
                    ) as execute,
                ):
                    status = main()
                    self.assertEqual(
                        status,
                        0
                        if scenario == "passed"
                        else 2
                        if scenario == "native_failure"
                        else 1,
                    )
                    receipt = json.loads((root / "test-run.json").read_text())
                    self.assertEqual(receipt["runner"], "vitest-browser")
                    self.assertEqual(receipt["name"], "typescript-web-components")
                    self.assertEqual(receipt["head_sha"], "a" * 40)
                    self.assertEqual(receipt["run_id"], "100")
                    self.assertEqual(receipt["attempt"], "2")
                    self.assertEqual(receipt["exit_code"], status)
                    self.assertGreater(receipt["duration_seconds"], 0)
                    self.assertFalse((root / "pytest-timings.jsonl").exists())
                    with self.assertRaisesRegex(ValueError, "fresh"):
                        main()
                    self.assertEqual(execute.call_count, 1)
