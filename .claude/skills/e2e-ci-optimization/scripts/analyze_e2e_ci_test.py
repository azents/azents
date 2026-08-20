"""Tests for the E2E CI artifact analyzer."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analyze_e2e_ci import analyze, load_samples


class AnalyzeE2ECITest(unittest.TestCase):
    """Verify critical-path and overlap calculations."""

    @staticmethod
    def _write_lane(
        sample: Path,
        lane: str,
        *,
        duration: float = 10,
        failed: bool = False,
    ) -> None:
        artifact = sample / f"e2e-observability-{lane}"
        artifact.mkdir()
        (artifact / "pytest-timings.jsonl").write_text(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": f"tests/test_{lane}.py::test_journey",
                    "duration_seconds": duration,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        failure = "<failure />" if failed else ""
        (artifact / "junit.xml").write_text(
            "<testsuites><testsuite>"
            f'<testcase classname="tests.test_{lane}" name="test_journey">'
            f"{failure}</testcase>"
            "</testsuite></testsuites>",
            encoding="utf-8",
        )

    def test_rejects_samples_missing_a_required_lane_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sample = Path(temporary_directory) / "incomplete"
            sample.mkdir()
            (sample / "run.json").write_text(
                json.dumps(
                    {
                        "headSha": "a" * 40,
                        "jobs": [
                            {
                                "name": f"ci-e2e-required-{index}",
                                "conclusion": "success",
                                "startedAt": "2026-08-20T00:00:00Z",
                                "completedAt": "2026-08-20T00:10:00Z",
                            }
                            for index in range(1, 4)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            self._write_lane(sample, "required-1")

            with self.assertRaisesRegex(ValueError, "missing required lane artifacts"):
                load_samples(Path(temporary_directory), "baseline")

    def test_rejects_missing_required_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sample = Path(temporary_directory) / "incomplete"
            sample.mkdir()
            (sample / "run.json").write_text(
                json.dumps(
                    {
                        "headSha": "a" * 40,
                        "jobs": [
                            {
                                "name": "ci-e2e-required-1",
                                "conclusion": "success",
                                "startedAt": "2026-08-20T00:00:00Z",
                                "completedAt": "2026-08-20T00:10:00Z",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            artifact = sample / "e2e-observability-required-1"
            artifact.mkdir()
            (artifact / "pytest-timings.jsonl").write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required evidence"):
                load_samples(Path(temporary_directory), "baseline")

    def test_rejects_mixed_experiment_shas(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for index, head_sha in enumerate(("a" * 40, "b" * 40), start=1):
                sample = root / f"attempt-{index}"
                sample.mkdir()
                (sample / "run.json").write_text(
                    json.dumps(
                        {
                            "headSha": head_sha,
                            "jobs": [
                                {
                                    "name": "ci-e2e-required-1",
                                    "conclusion": "success",
                                    "startedAt": "2026-08-20T00:00:00Z",
                                    "completedAt": "2026-08-20T00:10:00Z",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                self._write_lane(sample, "required-1")

            with self.assertRaisesRegex(ValueError, "one headSha"):
                load_samples(root, "experiment")

    def test_excludes_failed_attempts_from_performance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            for name, conclusion, duration in (
                ("success", "success", 20),
                ("failed", "failure", 200),
            ):
                sample = root / name
                sample.mkdir()
                (sample / "run.json").write_text(
                    json.dumps(
                        {
                            "headSha": "a" * 40,
                            "jobs": [
                                {
                                    "name": "ci-e2e-required-1",
                                    "conclusion": conclusion,
                                    "startedAt": "2026-08-20T00:00:00Z",
                                    "completedAt": "2026-08-20T00:10:00Z",
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                self._write_lane(
                    sample,
                    "required-1",
                    duration=duration,
                    failed=conclusion == "failure",
                )

            report = analyze(
                load_samples(root, "experiment"),
                "experiment",
            )

        self.assertEqual(report["tests"][0]["samples"], 1)
        self.assertEqual(report["tests"][0]["median_seconds"], 20)
        self.assertEqual(
            report["failures"],
            {"tests.test_required-1::test_journey": 1},
        )

    def test_recomputes_critical_path_and_parallel_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            sample = Path(temporary_directory) / "sample-1"
            sample.mkdir()
            jobs = []
            for lane, seconds in (
                ("required-1", 600),
                ("required-2", 550),
                ("required-3", 500),
            ):
                jobs.append(
                    {
                        "name": f"ci-e2e-{lane}",
                        "conclusion": "success",
                        "startedAt": "2026-08-20T00:00:00Z",
                        "completedAt": f"2026-08-20T00:{seconds // 60:02d}:"
                        f"{seconds % 60:02d}Z",
                    }
                )
                artifact = sample / f"e2e-observability-{lane}"
                artifact.mkdir()
                timings = [
                    {
                        "record_type": "test_phase",
                        "phase": "call",
                        "node_id": f"tests/test_{lane}.py::test_journey",
                        "duration_seconds": 100 if lane == "required-1" else 10,
                    },
                    {
                        "record_type": "fixture",
                        "phase": "setup",
                        "fixture": "e2e_images",
                        "duration_seconds": 40,
                    },
                ]
                (artifact / "pytest-timings.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in timings),
                    encoding="utf-8",
                )
                images = [
                    {"image": "azents-server", "duration_seconds": 40},
                    {"image": "azents-runtime-runner", "duration_seconds": 30},
                    {
                        "image": "azents-runtime-provider-docker",
                        "duration_seconds": 5,
                    },
                ]
                (artifact / "image-build-timings.jsonl").write_text(
                    "".join(json.dumps(row) + "\n" for row in images),
                    encoding="utf-8",
                )
                (artifact / "junit.xml").write_text(
                    "<testsuites><testsuite>"
                    f'<testcase classname="tests.test_{lane}" name="test_journey" />'
                    "</testsuite></testsuites>",
                    encoding="utf-8",
                )

            (sample / "run.json").write_text(
                json.dumps({"headSha": "a" * 40, "jobs": jobs}),
                encoding="utf-8",
            )

            report = analyze(
                load_samples(Path(temporary_directory), "experiment"),
                "experiment",
            )

        self.assertEqual(report["critical_paths"]["mean_seconds"], 600)
        candidate = next(
            row
            for row in report["tests"]
            if row["node"] == "tests/test_required-1.py::test_journey"
        )
        self.assertEqual(candidate["mean_critical_saving_50_seconds"], 50)
        lane_overlap = next(
            row
            for row in report["parallel_image_overlaps"]
            if row["lane"] == "required-1"
        )
        self.assertEqual(lane_overlap["overlap_seconds"], 35)


if __name__ == "__main__":
    unittest.main()
