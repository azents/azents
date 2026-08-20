"""Unit tests for E2E CI observability summaries."""

from pathlib import Path

from support.ci_observability import (
    parse_image_build_timings,
    parse_junit,
    parse_timings,
    render_summary,
)


def test_parse_junit_counts_outcomes_and_durations(tmp_path: Path) -> None:
    """Parse bounded result metadata without retaining failure contents."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """\
<testsuites>
  <testsuite>
    <testcase classname="tests.test_example" name="test_pass" time="1.25" />
    <testcase classname="tests.test_example" name="test_fail" time="2.5">
      <failure message="secret failure detail">traceback</failure>
    </testcase>
    <testcase classname="tests.test_example" name="test_error" time="0.5">
      <error message="setup failed">traceback</error>
    </testcase>
    <testcase classname="tests.test_example" name="test_skip" time="0">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
""",
        encoding="utf-8",
    )

    summary = parse_junit(junit_path)

    assert summary.tests == 4
    assert summary.passed == 1
    assert summary.failures == 1
    assert summary.errors == 1
    assert summary.skipped == 1
    assert summary.duration_seconds == 4.25


def test_render_summary_lists_bounded_failures_and_slowest_tests(
    tmp_path: Path,
) -> None:
    """Render node IDs and timings without embedding JUnit failure messages."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """\
<testsuite>
  <testcase classname="tests.test_example" name="test_slow[param|value]" time="3">
    <failure message="do not publish this detail">traceback</failure>
  </testcase>
  <testcase classname="tests.test_example" name="test_fast" time="0.25" />
</testsuite>
""",
        encoding="utf-8",
    )

    rendered = render_summary(
        lane="Deterministic E2E",
        job_result="failure",
        junit_path=junit_path,
    )

    assert "Deterministic E2E" in rendered
    assert "| 2 | 1 | 1 | 0 | 0 | 3.2s |" in rendered
    assert "tests.test_example::test_slow[param&#124;value]" in rendered
    assert "3.00s" in rendered
    assert "do not publish this detail" not in rendered
    assert "traceback" not in rendered


def test_render_summary_reports_lane_execution_time(tmp_path: Path) -> None:
    """Report wall-clock pytest duration separately from summed test time."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        '<testsuite><testcase classname="tests.test_example" '
        'name="test_example" time="100" /></testsuite>',
        encoding="utf-8",
    )
    lane_duration_path = tmp_path / "lane-duration-seconds.txt"
    lane_duration_path.write_text("605\n", encoding="utf-8")

    rendered = render_summary(
        lane="Deterministic E2E",
        job_result="success",
        junit_path=junit_path,
        lane_duration_path=lane_duration_path,
    )

    assert "E2E execution time: **10m 5s**" in rendered
    assert "| 1 | 1 | 0 | 0 | 0 | 100.0s |" in rendered


def test_render_summary_reports_missing_junit(tmp_path: Path) -> None:
    """Explain setup failures when pytest cannot produce JUnit XML."""
    timings_path = tmp_path / "pytest-timings.jsonl"
    timings_path.write_text(
        (
            '{"duration_seconds": 3.0, "fixture": "service_container", '
            '"node_id": "", "outcome": "failed", "phase": "setup", '
            '"record_type": "fixture", "scope": "session"}\n'
        ),
        encoding="utf-8",
    )
    lane_duration_path = tmp_path / "lane-duration-seconds.txt"
    lane_duration_path.write_text("65\n", encoding="utf-8")
    rendered = render_summary(
        lane="Web Surface E2E",
        job_result="failure",
        junit_path=tmp_path / "missing.xml",
        timings_path=timings_path,
        lane_duration_path=lane_duration_path,
    )

    assert "E2E execution time: **1m 5s**" in rendered
    assert "JUnit XML was not produced" in rendered
    assert "setup or infrastructure failures" in rendered
    assert "service_container (setup)" in rendered


def test_parse_timings_and_render_detailed_summary(tmp_path: Path) -> None:
    """Render aggregate test phases and bounded slow fixture evidence."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        '<testsuite><testcase classname="tests.test_example" '
        'name="test_example" time="4" /></testsuite>',
        encoding="utf-8",
    )
    timings_path = tmp_path / "pytest-timings.jsonl"
    timings_path.write_text(
        "\n".join(
            [
                (
                    '{"duration_seconds": 1.5, "node_id": "tests/test_example.py'
                    '::test_example", "outcome": "passed", "phase": "setup", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 2.0, "node_id": "tests/test_example.py'
                    '::test_example", "outcome": "passed", "phase": "call", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 1.25, "fixture": "service_container", '
                    '"node_id": "tests/test_example.py::test_example", '
                    '"outcome": "passed", "phase": "setup", '
                    '"record_type": "fixture", "scope": "session"}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = parse_timings(timings_path)
    rendered = render_summary(
        lane="Deterministic E2E",
        job_result="success",
        junit_path=junit_path,
        timings_path=timings_path,
    )

    assert len(records) == 3
    assert "| `setup` | 1.50s | 1 |" in rendered
    assert "| `call` | 2.00s | 1 |" in rendered
    assert "| `teardown` | 0.00s | 0 |" in rendered
    assert "| `session` | `setup` | 1.25s | 1 |" in rendered
    assert "service_container (setup)" in rendered
    assert "`session`" in rendered


def test_parse_and_render_image_build_timings(tmp_path: Path) -> None:
    """Render each image build and the total build time."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        '<testsuite><testcase classname="tests.test_example" '
        'name="test_example" time="1" /></testsuite>',
        encoding="utf-8",
    )
    image_build_timings_path = tmp_path / "image-build-timings.jsonl"
    image_build_timings_path.write_text(
        "\n".join(
            [
                (
                    '{"cache_backend":"gha","cache_export_enabled":false,'
                    '"cache_scope":"e2e-server","completed":true,'
                    '"duration_seconds":80.5,"image":"azents-server"}'
                ),
                (
                    '{"cache_backend":"gha","cache_export_enabled":false,'
                    '"cache_scope":"e2e-runner","completed":true,'
                    '"duration_seconds":50.25,"image":"azents-runtime-runner"}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    records = parse_image_build_timings(image_build_timings_path)
    rendered = render_summary(
        lane="Deterministic E2E",
        job_result="success",
        junit_path=junit_path,
        image_build_timings_path=image_build_timings_path,
    )

    assert len(records) == 2
    assert "azents-server" in rendered
    assert "80.50s" in rendered
    assert "**130.75s**" in rendered
