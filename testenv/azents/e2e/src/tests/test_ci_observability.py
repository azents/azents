"""Unit tests for E2E CI observability summaries."""

from pathlib import Path

from support.ci_observability import parse_junit, render_summary


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


def test_render_summary_reports_missing_junit(tmp_path: Path) -> None:
    """Explain setup failures when pytest cannot produce JUnit XML."""
    rendered = render_summary(
        lane="Web Surface E2E",
        job_result="failure",
        junit_path=tmp_path / "missing.xml",
    )

    assert "JUnit XML was not produced" in rendered
    assert "setup or infrastructure failures" in rendered
