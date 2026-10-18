"""Native Node evidence cannot hide a missing producer or invent pytest phases."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci.analyze import analyze, expected_test_artifacts
from scripts.ci.evidence import decode_native_node_run, file_hashes
from scripts.ci.run_node_tests import main
from scripts.ci.tests.test_observability import job, sample
from scripts.ci.workflow_report import decode_run, object_value, sequence


class NodeObservabilityTest(unittest.TestCase):
    def test_native_runner_preserves_command_exit_identity_and_stale_rejection(self):
        for exit_code in (0, 1):
            with (
                self.subTest(exit_code=exit_code),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp) / "evidence"
                argv = [
                    "run_node_tests",
                    "--project",
                    tmp,
                    "--artifact-dir",
                    str(root),
                    "--name",
                    "typescript-web",
                    "src/**/*.test.mts",
                ]
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
                        "scripts.ci.run_node_tests.subprocess.run",
                        return_value=subprocess.CompletedProcess([], exit_code),
                    ) as run,
                ):
                    self.assertEqual(main(), exit_code)
                    command = run.call_args.args[0]
                    self.assertIn("--test-reporter=junit", command)
                    self.assertEqual(command[-1], "src/**/*.test.mts")
                    evidence = json.loads((root / "test-run.json").read_text())
                    self.assertEqual(evidence["exit_code"], exit_code)
                    self.assertEqual(evidence["runner"], "node")
                    self.assertEqual(evidence["head_sha"], "a" * 40)
                    self.assertEqual(evidence["attempt"], "2")
                    self.assertFalse((root / "pytest-timings.jsonl").exists())
                    with self.assertRaisesRegex(ValueError, "fresh"):
                        main()
                    self.assertEqual(run.call_count, 1)

    def test_enabled_node_step_requires_native_artifact_without_pytest_phases(self):
        for scenario in (
            "missing_artifact",
            "passed",
            "junit_failure",
            "native_failure",
            "missing_receipt",
            "missing_status",
            "missing_duration",
            "wrong_runner",
            "invalid_duration",
            "stale_sha",
            "stale_run",
            "stale_attempt",
        ):
            available = scenario != "missing_artifact"
            fails = scenario == "junit_failure"
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    raw = sample()
                    producer = job("ci-typescript-run", "00:00:10", "00:00:50")
                    object_value(sequence(producer["steps"])[0])["name"] = (
                        "Web Node contracts"
                    )
                    raw["jobs"] = [
                        producer,
                        job("ci-typescript", "00:00:50", "00:00:55"),
                    ]
                    self.assertEqual(
                        expected_test_artifacts(decode_run(raw)), {"typescript-web"}
                    )
                    (root / "run.json").write_text(json.dumps(raw))
                    artifacts = root / "artifacts"
                    artifacts.mkdir()
                    name = "ci-observability-typescript-web-1"
                    inventory = []
                    if available:
                        artifact = artifacts / name
                        artifact.mkdir()
                        failure = (
                            "<failure>synthetic failure</failure>" if fails else ""
                        )
                        (artifact / "junit.xml").write_text(
                            '<testsuite><testcase name="native hook" time="0.1">'
                            f"{failure}</testcase></testsuite>"
                        )
                        receipt = {
                            "name": "typescript-web",
                            "head_sha": "a" * 40,
                            "run_id": "100",
                            "attempt": "1",
                            "runner": "node",
                            "exit_code": 1 if scenario == "native_failure" else 0,
                            "duration_seconds": 0.25,
                        }
                        match scenario:
                            case "missing_status":
                                del receipt["exit_code"]
                            case "missing_duration":
                                del receipt["duration_seconds"]
                            case "wrong_runner":
                                receipt["runner"] = "pytest"
                            case "invalid_duration":
                                receipt["duration_seconds"] = -1
                            case "stale_sha":
                                receipt["head_sha"] = "b" * 40
                            case "stale_run":
                                receipt["run_id"] = "101"
                            case "stale_attempt":
                                receipt["attempt"] = "2"
                        if scenario != "missing_receipt":
                            (artifact / "test-run.json").write_text(json.dumps(receipt))
                        inventory.append(
                            {
                                "id": 1,
                                "name": name,
                                "created_at": "2026-10-15T00:00:49Z",
                                "expired": False,
                                "workflow_run": {"id": 100, "head_sha": "a" * 40},
                            }
                        )
                    (root / "artifact-inventory.json").write_text(
                        json.dumps([{"artifacts": inventory}])
                    )
                    (root / "collection.json").write_text(
                        json.dumps(
                            {
                                "workflow_run_id": 100,
                                "workflow_attempt": 1,
                                "head_sha": "a" * 40,
                                "artifact_identity_verified": True,
                                "artifact_names": [name] if available else [],
                                "file_hashes": file_hashes(artifacts),
                            }
                        )
                    )
                    if scenario in {"missing_status", "missing_duration"}:
                        with self.assertRaises(KeyError):
                            analyze([root], "experiment")
                        continue
                    if scenario in {
                        "wrong_runner",
                        "invalid_duration",
                        "stale_sha",
                        "stale_run",
                        "stale_attempt",
                    }:
                        with self.assertRaises(ValueError):
                            analyze([root], "experiment")
                        continue
                    result = analyze([root], "experiment")
                    [record] = [
                        object_value(value) for value in sequence(result["records"])
                    ]
                    self.assertEqual(
                        record["test_evidence_complete"],
                        available and scenario != "missing_receipt",
                    )
                    self.assertEqual(
                        record["performance_eligible"], scenario == "passed"
                    )
                    self.assertEqual(record["test_cases"], 1 if available else 0)
                    self.assertEqual(result["slow_calls"], [])

    def test_native_receipt_rejects_missing_or_invalid_execution_fields(self):
        receipt = {
            "name": "typescript-web",
            "head_sha": "a" * 40,
            "run_id": "100",
            "attempt": "1",
            "runner": "node",
            "exit_code": 0,
            "duration_seconds": 0.25,
        }
        for field in ("runner", "exit_code", "duration_seconds"):
            with self.subTest(missing=field):
                incomplete = {k: v for k, v in receipt.items() if k != field}
                with self.assertRaises(KeyError):
                    decode_native_node_run(incomplete)
        for field, value in (
            ("runner", "pytest"),
            ("exit_code", None),
            ("exit_code", True),
            ("exit_code", 0.0),
            ("duration_seconds", None),
            ("duration_seconds", True),
            ("duration_seconds", 0),
            ("duration_seconds", -1),
            ("duration_seconds", float("inf")),
            ("duration_seconds", float("nan")),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    decode_native_node_run({**receipt, field: value})
