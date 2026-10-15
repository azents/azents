"""Contracts for general CI evidence, identity, bounded reports and safe hooks."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.ci.analyze import analyze, expected_test_artifacts
from scripts.ci.build_comment import LIMIT, combine, producer_summaries
from scripts.ci.chart import HistoryPoint, daily, decode_history
from scripts.ci.evidence import artifacts_for_run, file_hashes, verify_collection
from scripts.ci.history import append
from scripts.ci.workflow_report import decode_run, metrics, render

ROOT = Path(__file__).resolve().parents[3]


def job(
    name: str, start: str, end: str, conclusion: str = "success"
) -> dict[str, object]:
    return {
        "name": name,
        "startedAt": f"2026-10-15T{start}Z",
        "completedAt": f"2026-10-15T{end}Z",
        "status": "completed",
        "conclusion": conclusion,
        "steps": [
            {
                "name": "Test",
                "startedAt": f"2026-10-15T{start}Z",
                "completedAt": f"2026-10-15T{end}Z",
                "conclusion": conclusion,
            }
        ],
    }


def sample(attempt: int = 1, sha: str = "a" * 40) -> dict[str, object]:
    return {
        "databaseId": 100,
        "attempt": attempt,
        "headSha": sha,
        "workflowName": "CI",
        "event": "push",
        "headBranch": "main",
        "createdAt": "2026-10-15T00:00:00Z",
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            job("changes", "00:00:01", "00:00:10"),
            job(
                "ci-python-run (python/apps/azents, python-azents)",
                "00:00:10",
                "00:00:50",
            ),
            job("ci-python", "00:00:50", "00:00:55"),
            job("ci-typescript", "00:00:10", "00:00:12"),
            job("ci-observability", "00:00:55", "00:01:00"),
        ],
    }


def stamp_provenance(root: Path, attempt: int) -> None:
    name = f"ci-observability-python-azents-{attempt}"
    artifact = root / "artifacts" / name
    (artifact / "test-run.json").write_text(
        json.dumps(
            {
                "name": "python-azents",
                "head_sha": "a" * 40,
                "run_id": "100",
                "attempt": str(attempt),
            }
        )
    )
    (root / "artifact-inventory.json").write_text(
        json.dumps(
            [
                {
                    "artifacts": [
                        {
                            "id": attempt,
                            "name": name,
                            "created_at": "2026-10-15T00:00:49Z",
                            "expired": False,
                            "workflow_run": {"id": 100, "head_sha": "a" * 40},
                        }
                    ]
                }
            ]
        )
    )
    (root / "collection.json").write_text(
        json.dumps(
            {
                "workflow_run_id": 100,
                "workflow_attempt": attempt,
                "head_sha": "a" * 40,
                "artifact_names": [name],
                "artifact_identity_verified": True,
                "file_hashes": file_hashes(root / "artifacts"),
            }
        )
    )


class WorkflowReportTest(unittest.TestCase):
    def test_dependency_elapsed_is_not_longest_parallel_job(self) -> None:
        run = decode_run(sample())
        data = metrics(run)
        self.assertEqual(data["gate_completion_elapsed_seconds"], 55)
        self.assertEqual(data["maximum_job_wall_seconds"], 40)
        self.assertEqual(data["runner_job_seconds"], 56)
        self.assertEqual(data["observability_job_seconds"], 5)
        self.assertEqual(expected_test_artifacts(run), {"python-azents"})
        self.assertIn("CI observability", render(run))

    def test_failed_or_running_gate_is_not_success(self) -> None:
        raw = sample()
        raw["conclusion"] = "failure"
        self.assertFalse(metrics(decode_run(raw))["performance_eligible"])
        raw["status"] = "in_progress"
        raw["conclusion"] = ""
        self.assertFalse(metrics(decode_run(raw))["performance_eligible"])

    def test_invalid_sha_or_timestamp_is_rejected(self) -> None:
        raw = sample()
        raw["headSha"] = "different-commit"
        with self.assertRaises(ValueError):
            decode_run(raw)
        raw = sample()
        raw["createdAt"] = "2026-10-15T00:00:00"
        with self.assertRaises(ValueError):
            decode_run(raw)

    def test_comment_stays_bounded_with_all_job_statuses(self) -> None:
        summaries = [
            f"### python-{i} — passed\n\nn=100\n<details>"
            + "large timing" * 1000
            + "</details>"
            for i in range(20)
        ]
        output = combine("## CI observability", None, summaries)
        self.assertLessEqual(len(output), LIMIT)
        for i in range(20):
            self.assertIn(f"### python-{i} — passed", output)
        self.assertIn("Detailed timing omitted", output)
        self.assertIn("unavailable", combine("workflow", None, []))

    def test_partial_artifact_loss_lists_the_missing_producer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "ci-observability-testenv-support-1"
            artifact.mkdir()
            (artifact / "summary.md").write_text("### support — Passed")
            result = "\n".join(producer_summaries(decode_run(sample()), [root]))
            self.assertIn("support — Passed", result)
            self.assertIn("python-azents — ⚠️ Results unavailable", result)

    def test_stale_inventory_and_changed_bytes_are_rejected(self) -> None:
        run = decode_run(sample())
        stale = [
            {
                "artifacts": [
                    {
                        "id": 1,
                        "name": "e2e-observability-required-1",
                        "created_at": "2026-10-15T01:00:00Z",
                        "expired": False,
                        "workflow_run": {"id": 100, "head_sha": "a" * 40},
                    }
                ]
            }
        ]
        with self.assertRaises(ValueError):
            artifacts_for_run(stale, run)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifacts/ci-observability-python-azents-1"
            artifact.mkdir(parents=True)
            stamp_provenance(root, 1)
            self.assertEqual(verify_collection(root, run), {artifact.name})
            (artifact / "pytest-timings.jsonl").write_text("changed after collection")
            with self.assertRaises(ValueError):
                verify_collection(root, run)

    def test_thirty_days_and_missing_are_not_backfilled(self) -> None:
        points = daily(
            [
                HistoryPoint("2026-10-14", True, 100),
                HistoryPoint("2026-10-14", True, 120),
                HistoryPoint("2026-10-15", False, 99),
            ],
            date(2026, 10, 15),
        )
        self.assertEqual(len(points), 30)
        self.assertEqual(points[0].date_kst, "2026-09-16")
        self.assertEqual(points[-2].mean, 110)
        self.assertIsNone(points[-1].mean)
        self.assertEqual(points[-1].excluded, 1)
        with self.assertRaises(KeyError):
            decode_history(
                {"cohort": "main", "date_kst": "2026-10-15", "e2e_seconds": 100}, "CI"
            )

    def test_history_deduplicates_and_rejects_pr_as_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record = metrics(decode_run(sample()))
            record["cohort"] = "baseline"
            analysis = root / "analysis.json"
            history = root / "history.jsonl"
            analysis.write_text(json.dumps({"cohort": "baseline", "records": [record]}))
            self.assertEqual(append(analysis, history, "main"), 1)
            self.assertEqual(append(analysis, history, "main"), 1)
            record["event"] = "pull_request"
            analysis.write_text(json.dumps({"cohort": "baseline", "records": [record]}))
            with self.assertRaises(ValueError):
                append(analysis, history, "main")

    def test_wrapper_rejects_reused_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "junit.xml").write_text("previous execution")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/ci/run_pytest.py"),
                    "--project",
                    str(root),
                    "--name",
                    "example",
                    "--artifact-dir",
                    str(root),
                    "--",
                    "-q",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already contains a pytest execution", result.stderr)
            self.assertEqual((root / "junit.xml").read_text(), "previous execution")

    def test_attempt_scope_and_evidence_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roots = []
            for attempt in (1, 2):
                root = Path(tmp) / str(attempt)
                root.mkdir()
                roots.append(root)
                (root / "run.json").write_text(json.dumps(sample(attempt)))
                artifact = (
                    root / "artifacts" / f"ci-observability-python-azents-{attempt}"
                )
                artifact.mkdir(parents=True)
                (artifact / "junit.xml").write_text(
                    '<testsuite><testcase classname="x" name="test_x" time="1"/>'
                    "</testsuite>"
                )
                (artifact / "pytest-timings.jsonl").write_text(
                    json.dumps(
                        {
                            "record_type": "test_phase",
                            "node_id": "x::test_x",
                            "phase": "call",
                            "outcome": "passed",
                            "duration_seconds": 1,
                        }
                    )
                    + "\n"
                )
                stamp_provenance(root, attempt)
            self.assertTrue(analyze(roots, "experiment")["same_sha_acceptance_ready"])
            (roots[1] / "run.json").write_text(json.dumps(sample(2, "b" * 40)))
            with self.assertRaises(ValueError):
                analyze(roots, "experiment")
            (roots[1] / "run.json").write_text(json.dumps(sample(2)))
            (
                roots[1]
                / "artifacts"
                / "ci-observability-python-azents-2"
                / "junit.xml"
            ).unlink()
            stamp_provenance(roots[1], 2)
            self.assertFalse(analyze(roots, "experiment")["same_sha_acceptance_ready"])

    def test_shared_plugin_preserves_failure_and_safe_fixture_evidence(self) -> None:
        # An actual subprocess exercises plugin discovery outside the E2E conftest.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "test_example.py").write_text(
                'import pytest\n@pytest.fixture(scope="session")\ndef opaque():\n'
                '    yield "secret-fixture-value"\ndef test_ok(opaque):\n'
                "    assert opaque\ndef test_failed():\n"
                '    assert False, "secret-exception-value"\n'
            )
            evidence = root / "evidence"
            environment = dict(
                os.environ, PYTHONPATH=str(ROOT), AZENTS_CI_ARTIFACT_DIR=str(evidence)
            )
            # Select the project's pinned pytest interpreter when this test is run
            # through standard-library unittest in CI.
            interpreter = ROOT / "testenv/azents/e2e/.venv/bin/python"
            result = subprocess.run(
                [
                    str(interpreter),
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "scripts.ci.pytest_timing",
                    str(root / "test_example.py"),
                ],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            content = (evidence / "pytest-timings.jsonl").read_text()
            self.assertNotIn("secret-fixture-value", content)
            self.assertNotIn("secret-exception-value", content)
            records = [json.loads(line) for line in content.splitlines()]
            self.assertTrue(
                any(
                    r["record_type"] == "fixture" and r["scope"] == "session"
                    for r in records
                )
            )
            self.assertTrue(
                any(
                    r["record_type"] == "test_phase" and r["outcome"] == "failed"
                    for r in records
                )
            )


if __name__ == "__main__":
    unittest.main()
