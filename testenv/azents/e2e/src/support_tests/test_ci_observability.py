"""Unit tests for E2E CI observability summaries."""

from pathlib import Path

import pytest

from support.ci_observability import (
    aggregate_timings,
    parse_image_build_timings,
    parse_junit,
    parse_timings,
    render_summary,
)


def _timing_line(node_id: str) -> str:
    return (
        '{"duration_seconds": 1.0, "node_id": "'
        + node_id
        + '", "outcome": "passed", "phase": "call", '
        '"record_type": "test_phase"}\n'
    )


def test_aggregate_timings_validates_and_orders_lane_files(tmp_path: Path) -> None:
    """Build one deterministic cache input from complete downloaded artifacts."""
    root = tmp_path / "artifacts"
    for lane, node_id in (("required-2", "test_b"), ("required-1", "test_a")):
        lane_root = root / f"e2e-observability-{lane}"
        path = lane_root / "pytest-timings.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(_timing_line(node_id), encoding="utf-8")
        (lane_root / "lane-duration-seconds.txt").write_text("1\n", encoding="utf-8")
    output = tmp_path / "current.jsonl"

    assert aggregate_timings(root, output) == 2
    assert [record["node_id"] for record in parse_timings(output)] == [
        "test_a",
        "test_b",
    ]


def test_aggregate_timings_rejects_missing_or_empty_lane_files(
    tmp_path: Path,
) -> None:
    """Fail visibly instead of publishing absent or partial current timing."""
    with pytest.raises(ValueError, match="no E2E lane artifact directories"):
        aggregate_timings(tmp_path / "missing", tmp_path / "output.jsonl")
    empty_root = tmp_path / "empty"
    empty = empty_root / "pytest-timings.jsonl"
    empty.parent.mkdir()
    empty.write_text("", encoding="utf-8")
    (empty_root / "lane-duration-seconds.txt").write_text("1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="timing file is empty"):
        aggregate_timings(tmp_path / "empty", tmp_path / "output.jsonl")


def test_aggregate_timings_rejects_a_partial_lane_set(tmp_path: Path) -> None:
    """Every downloaded lane artifact must contribute validated timing."""
    root = tmp_path / "artifacts"
    complete = root / "e2e-observability-required-1"
    missing = root / "e2e-observability-required-2"
    complete.mkdir(parents=True)
    missing.mkdir(parents=True)
    (complete / "lane-duration-seconds.txt").write_text("1\n", encoding="utf-8")
    (complete / "pytest-timings.jsonl").write_text(
        _timing_line("test_a"), encoding="utf-8"
    )
    (missing / "lane-duration-seconds.txt").write_text("1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="timing file is missing"):
        aggregate_timings(root, tmp_path / "output.jsonl")


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
    assert "### Deterministic E2E — ❌ Failed" in rendered
    assert "1 passed · 1 failed · time unavailable" in rendered
    assert "<summary>Details</summary>" in rendered


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

    assert "### Deterministic E2E — ✅ Passed" in rendered
    assert "1 test · 10m 5s" in rendered
    assert "| 1 | 1 | 0 | 0 | 0 | 100.0s |" in rendered
    assert "<summary>Details</summary>" in rendered
    assert rendered.count("<details>") == rendered.count("</details>")


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

    assert "### Web Surface E2E — ⚠️ Results unavailable" in rendered
    assert "Job `failure` · 1m 5s" in rendered
    assert "JUnit XML was not produced" in rendered
    assert "setup or infrastructure failures" in rendered
    assert "service_container (setup)" in rendered
    assert "<summary>Details</summary>" in rendered
    assert rendered.count("<details>") == rendered.count("</details>")


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


@pytest.mark.parametrize(
    "record",
    [
        (
            '{"duration_seconds":1.0,"node_id":"test_example",'
            '"outcome":"passed","phase":"call","record_type":"test_phase",'
            '"unknown":true}'
        ),
        (
            '{"duration_seconds":"1.0","node_id":"test_example",'
            '"outcome":"passed","phase":"call","record_type":"test_phase"}'
        ),
    ],
)
def test_parse_timings_rejects_unvalidated_records(
    tmp_path: Path,
    record: str,
) -> None:
    """Reject unknown fields and incorrectly typed timing values."""
    timings_path = tmp_path / "pytest-timings.jsonl"
    timings_path.write_text(record + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_timings(timings_path)


def test_render_summary_uses_call_time_for_slowest_tests(tmp_path: Path) -> None:
    """Do not attribute session fixture startup to the first reported slow test."""
    junit_path = tmp_path / "junit.xml"
    junit_path.write_text(
        """\
<testsuite>
  <testcase
    classname="src.tests.required.admin.test_workspace.TestWorkspaceCrud"
    name="test_create_get_update_workspace"
    time="162.77"
  />
  <testcase
    classname="src.tests.required.public.test_external_channel_discord_journeys"
    name="test_discord_message_command_selector_and_component_journey"
    time="17.29"
  />
  <testcase
    classname="tests.test_parameters"
    name="test_value[a::b/path]"
    time="100"
  />
</testsuite>
""",
        encoding="utf-8",
    )
    timings_path = tmp_path / "pytest-timings.jsonl"
    timings_path.write_text(
        "\n".join(
            [
                (
                    '{"duration_seconds": 162.62, "node_id": '
                    '"src/tests/required/admin/test_workspace.py::'
                    'TestWorkspaceCrud::test_create_get_update_workspace", '
                    '"outcome": "passed", "phase": "setup", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 0.16, "node_id": '
                    '"src/tests/required/admin/test_workspace.py::'
                    'TestWorkspaceCrud::test_create_get_update_workspace", '
                    '"outcome": "passed", "phase": "call", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 17.29, "node_id": '
                    '"src/tests/required/public/'
                    "test_external_channel_discord_journeys.py::"
                    'test_discord_message_command_selector_and_component_journey", '
                    '"outcome": "passed", "phase": "call", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 100.0, "node_id": '
                    '"tests/test_parameters.py::test_value[a::b/path]", '
                    '"outcome": "passed", "phase": "setup", '
                    '"record_type": "test_phase"}'
                ),
                (
                    '{"duration_seconds": 0.5, "node_id": '
                    '"tests/test_parameters.py::test_value[a::b/path]", '
                    '"outcome": "passed", "phase": "call", '
                    '"record_type": "test_phase"}'
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rendered = render_summary(
        lane="required-4",
        job_result="success",
        junit_path=junit_path,
        timings_path=timings_path,
    )

    discord_row = (
        "| <code>src.tests.required.public."
        "test_external_channel_discord_journeys::"
        "test_discord_message_command_selector_and_component_journey</code> "
        "| 17.29s | `passed` |"
    )
    workspace_row = (
        "| <code>src.tests.required.admin.test_workspace."
        "TestWorkspaceCrud::test_create_get_update_workspace</code> "
        "| 0.16s | `passed` |"
    )
    parameter_row = (
        "| <code>tests.test_parameters::test_value[a::b/path]</code> "
        "| 0.50s | `passed` |"
    )
    assert discord_row in rendered
    assert workspace_row in rendered
    assert parameter_row in rendered
    assert rendered.index(discord_row) < rendered.index(parameter_row)
    assert rendered.index(parameter_row) < rendered.index(workspace_row)
    assert "| `setup` | 262.62s | 2 |" in rendered


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
                    '{"build_mode":"source-overlay","cache_backend":"gha",'
                    '"cache_export_enabled":false,'
                    '"cache_scope":"e2e-server","completed":true,'
                    '"duration_seconds":80.5,"image":"azents-server"}'
                ),
                (
                    '{"build_mode":"full","cache_backend":"gha",'
                    '"cache_export_enabled":false,'
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
    assert "source-overlay" in rendered
    assert "80.50s" in rendered
    assert "**130.75s**" in rendered


@pytest.mark.parametrize(
    "record",
    [
        (
            '{"build_mode":"full","cache_backend":"gha",'
            '"cache_export_enabled":false,'
            '"cache_scope":"e2e-server","completed":true,'
            '"duration_seconds":80.5,"image":"azents-server","unknown":true}'
        ),
        (
            '{"build_mode":"full","cache_backend":"gha",'
            '"cache_export_enabled":false,'
            '"cache_scope":"e2e-server","completed":"true",'
            '"duration_seconds":80.5,"image":"azents-server"}'
        ),
    ],
)
def test_parse_image_build_timings_rejects_unvalidated_records(
    tmp_path: Path,
    record: str,
) -> None:
    """Reject unknown fields and incorrectly typed image timing values."""
    timings_path = tmp_path / "image-build-timings.jsonl"
    timings_path.write_text(record + "\n", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_image_build_timings(timings_path)


def test_parse_image_build_timings_rejects_unknown_build_mode(
    tmp_path: Path,
) -> None:
    """Reject image timing modes that the renderer cannot classify."""
    timings_path = tmp_path / "image-build-timings.jsonl"
    timings_path.write_text(
        (
            '{"build_mode":"incremental","cache_backend":"gha",'
            '"cache_export_enabled":false,"cache_scope":"e2e-server",'
            '"completed":true,"duration_seconds":80.5,"image":"azents-server"}\n'
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="build_mode"):
        parse_image_build_timings(timings_path)
