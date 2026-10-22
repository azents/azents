"""Malformed producer durations cannot become accepted timing measurements."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.ci.analyze import analyze
from scripts.ci.observability import (
    parse_image_build_timings,
    parse_junit,
    parse_timings,
    render_summary,
)
from scripts.ci.tests.test_observability import sample, stamp_provenance


class DurationEvidenceTest(unittest.TestCase):
    def test_junit_explicit_invalid_durations_fail_instead_of_becoming_zero(self):
        for value in ("invalid", "", "NaN", "Infinity", "-Infinity", "-0.1"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "junit.xml"
                path.write_text(
                    f'<testsuite><testcase classname="unit" name="test" '
                    f'time="{value}"/></testsuite>'
                )
                with self.assertRaises(ValueError):
                    parse_junit(path)

    def test_junit_zero_finite_and_optional_omission_retain_test_outcomes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "junit.xml"
            path.write_text(
                '<testsuite><testcase classname="unit" name="zero" time="0"/>'
                '<testcase classname="unit" name="finite" time="0.25"/>'
                '<testcase classname="unit" name="unspecified"/>'
                '<testcase classname="unit" name="failed" time="1">'
                "<failure/></testcase></testsuite>"
            )
            summary = parse_junit(path)
            self.assertEqual(summary.tests, 4)
            self.assertEqual(summary.passed, 3)
            self.assertEqual(summary.failures, 1)
            self.assertEqual(summary.duration_seconds, 1.25)

    def test_test_and_fixture_timing_reject_invalid_numeric_durations(self):
        for kind in ("test_phase", "fixture"):
            for value in (float("nan"), float("inf"), -float("inf"), -1, True):
                with (
                    self.subTest(kind=kind, value=value),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    path = Path(tmp) / "timings.jsonl"
                    record = {
                        "record_type": kind,
                        "node_id": "unit::test",
                        "phase": "setup",
                        "duration_seconds": value,
                        "outcome": "passed",
                    }
                    if kind == "fixture":
                        record.update(fixture="client", scope="function")
                    path.write_text(json.dumps(record) + "\n")
                    with self.assertRaises(ValueError):
                        parse_timings(path)
                    record["duration_seconds"] = 0.0
                    path.write_text(json.dumps(record) + "\n")
                    self.assertEqual(parse_timings(path)[0]["duration_seconds"], 0)

    def test_image_numeric_fields_reject_nonfinite_and_negative_measurements(self):
        record = {
            "image": "synthetic",
            "duration_seconds": 0.25,
            "completed": True,
            "cache_backend": "none",
            "cache_scope": None,
            "cache_export_enabled": False,
            "build_mode": "full",
            "started_at_monotonic": 1.0,
            "finished_at_monotonic": 1.25,
        }
        for field in (
            "duration_seconds",
            "started_at_monotonic",
            "finished_at_monotonic",
        ):
            for value in (float("nan"), float("inf"), -1):
                with (
                    self.subTest(field=field, value=value),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    path = Path(tmp) / "images.jsonl"
                    path.write_text(json.dumps({**record, field: value}) + "\n")
                    with self.assertRaises(ValueError):
                        parse_image_build_timings(path)
                    path.write_text(json.dumps(record) + "\n")
                    self.assertEqual(len(parse_image_build_timings(path)), 1)

    def test_lane_duration_rejected_before_rendering(self):
        for value in ("NaN", "Infinity", "-1", "invalid"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                duration = root / "duration.txt"
                duration.write_text(value)
                with self.assertRaises(ValueError):
                    render_summary(
                        lane="synthetic",
                        job_result="success",
                        junit_path=root / "missing.xml",
                        lane_duration_path=duration,
                    )
                duration.write_text("0")
                self.assertIn(
                    "Total 0s",
                    render_summary(
                        lane="synthetic",
                        job_result="success",
                        junit_path=root / "missing.xml",
                        lane_duration_path=duration,
                    ),
                )

    def test_authenticated_archive_cannot_make_invalid_measurements_eligible(self):
        for source in ("junit", "timing"):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "run.json").write_text(json.dumps(sample()))
                artifact = root / "artifacts/ci-observability-python-azents-1"
                artifact.mkdir(parents=True)
                (artifact / "junit.xml").write_text(
                    '<testsuite><testcase classname="unit" name="test" '
                    f'time="{"NaN" if source == "junit" else "0.25"}"/></testsuite>'
                )
                (artifact / "pytest-timings.jsonl").write_text(
                    json.dumps(
                        {
                            "record_type": "test_phase",
                            "node_id": "unit::test",
                            "phase": "call",
                            "duration_seconds": (
                                float("nan") if source == "timing" else 0.25
                            ),
                            "outcome": "passed",
                        }
                    )
                    + "\n"
                )
                # Synthetic producer archive and API fixture agree; content is invalid.
                stamp_provenance(root, 1)
                with self.assertRaises(ValueError):
                    analyze([root], "baseline")
