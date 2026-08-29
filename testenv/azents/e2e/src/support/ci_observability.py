"""Render bounded E2E CI observability summaries from pytest JUnit output."""

import argparse
import html
import json
import xml.etree.ElementTree as element_tree
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict, cast


@dataclass(frozen=True)
class TestCaseResult:
    """One parsed JUnit test case."""

    node_id: str
    duration_seconds: float
    outcome: str


@dataclass(frozen=True)
class JUnitSummary:
    """Aggregate JUnit result used by the CI Markdown renderer."""

    tests: int
    passed: int
    failures: int
    errors: int
    skipped: int
    duration_seconds: float
    cases: tuple[TestCaseResult, ...]


class _TestPhaseRecord(TypedDict):
    record_type: Literal["test_phase"]
    node_id: str
    phase: str
    duration_seconds: float
    outcome: str


class _FixtureRecord(TypedDict):
    record_type: Literal["fixture"]
    fixture: str
    scope: str
    node_id: str
    phase: str
    duration_seconds: float
    outcome: str


TimingRecord = _TestPhaseRecord | _FixtureRecord


class ImageBuildTiming(TypedDict):
    """One safe Docker image build timing record."""

    image: str
    duration_seconds: float
    completed: bool
    cache_backend: str
    cache_scope: str | None
    cache_export_enabled: bool


def parse_junit(path: Path) -> JUnitSummary:
    """Parse one pytest JUnit XML document."""
    root = element_tree.parse(path).getroot()
    cases = tuple(_parse_test_case(element) for element in root.iter("testcase"))
    failures = sum(case.outcome == "failed" for case in cases)
    errors = sum(case.outcome == "error" for case in cases)
    skipped = sum(case.outcome == "skipped" for case in cases)
    passed = len(cases) - failures - errors - skipped
    return JUnitSummary(
        tests=len(cases),
        passed=passed,
        failures=failures,
        errors=errors,
        skipped=skipped,
        duration_seconds=sum(case.duration_seconds for case in cases),
        cases=cases,
    )


def render_summary(
    *,
    lane: str,
    job_result: str,
    junit_path: Path,
    timings_path: Path | None = None,
    image_build_timings_path: Path | None = None,
    lane_duration_path: Path | None = None,
) -> str:
    """Render one lane summary without including failure messages or logs."""
    timing_records = (
        parse_timings(timings_path)
        if timings_path is not None and timings_path.is_file()
        else None
    )
    lines = [
        f"### {_escape_text(lane)}",
        "",
        f"Job result: `{_escape_text(job_result)}`",
        "",
    ]
    if lane_duration_path is not None and lane_duration_path.is_file():
        lines.extend(
            [
                "E2E execution time: "
                f"**{_format_duration(_parse_duration(lane_duration_path))}**",
                "",
            ]
        )
    if not junit_path.is_file():
        lines.extend(
            [
                "JUnit XML was not produced. Inspect the workflow log and uploaded "
                "diagnostics for setup or infrastructure failures.",
                "",
            ]
        )
        _append_optional_timing_summaries(
            lines=lines,
            timing_records=timing_records,
            image_build_timings_path=image_build_timings_path,
        )
        return "\n".join(lines)

    summary = parse_junit(junit_path)
    lines.extend(
        [
            "| Tests | Passed | Failed | Errors | Skipped | Test time |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
            (
                f"| {summary.tests} | {summary.passed} | {summary.failures} | "
                f"{summary.errors} | {summary.skipped} | "
                f"{summary.duration_seconds:.1f}s |"
            ),
            "",
        ]
    )

    unsuccessful = [
        case for case in summary.cases if case.outcome in {"failed", "error"}
    ]
    if unsuccessful:
        lines.extend(
            [
                "<details>",
                "<summary>Failed or errored tests</summary>",
                "",
            ]
        )
        for case in unsuccessful[:20]:
            lines.append(
                f"- {_inline_code(case.node_id)} — `{_escape_text(case.outcome)}`"
            )
        if len(unsuccessful) > 20:
            lines.append(f"- … and {len(unsuccessful) - 20} more")
        lines.extend(["", "</details>", ""])

    slowest = sorted(
        _test_cases_with_call_durations(summary.cases, timing_records),
        key=lambda case: case.duration_seconds,
        reverse=True,
    )[:10]
    if slowest:
        lines.extend(
            [
                "<details>",
                "<summary>Slowest tests</summary>",
                "",
                "| Test | Duration | Outcome |",
                "| --- | ---: | --- |",
            ]
        )
        for case in slowest:
            lines.append(
                f"| {_inline_code(case.node_id)} | {case.duration_seconds:.2f}s | "
                f"`{_escape_text(case.outcome)}` |"
            )
        lines.extend(["", "</details>", ""])

    _append_optional_timing_summaries(
        lines=lines,
        timing_records=timing_records,
        image_build_timings_path=image_build_timings_path,
    )

    return "\n".join(lines)


def _append_optional_timing_summaries(
    *,
    lines: list[str],
    timing_records: tuple[TimingRecord, ...] | None,
    image_build_timings_path: Path | None,
) -> None:
    if timing_records is not None:
        lines.extend(_render_timing_summary(timing_records))
    if image_build_timings_path is not None and image_build_timings_path.is_file():
        lines.extend(
            _render_image_build_summary(
                parse_image_build_timings(image_build_timings_path)
            )
        )


def parse_timings(path: Path) -> tuple[TimingRecord, ...]:
    """Parse safe timing records produced by the E2E pytest hooks."""
    records: list[TimingRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if payload["record_type"] == "test_phase":
            records.append(cast(_TestPhaseRecord, payload))
        elif payload["record_type"] == "fixture":
            records.append(cast(_FixtureRecord, payload))
        else:
            raise ValueError(f"unsupported timing record: {payload['record_type']}")
    return tuple(records)


def parse_image_build_timings(path: Path) -> tuple[ImageBuildTiming, ...]:
    """Parse safe image build timings produced by E2E fixtures."""
    return tuple(
        cast(ImageBuildTiming, json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
    )


def _render_timing_summary(records: tuple[TimingRecord, ...]) -> list[str]:
    test_phases = [
        record for record in records if record["record_type"] == "test_phase"
    ]
    fixtures = [record for record in records if record["record_type"] == "fixture"]
    lines = [
        "<details>",
        "<summary>Detailed timing</summary>",
        "",
        "| Test phase | Total | Count |",
        "| --- | ---: | ---: |",
    ]
    phase_durations: dict[str, list[float]] = defaultdict(list)
    for record in test_phases:
        phase_durations[record["phase"]].append(record["duration_seconds"])
    for phase in ("setup", "call", "teardown"):
        durations = phase_durations[phase]
        lines.append(f"| `{phase}` | {sum(durations):.2f}s | {len(durations)} |")

    fixture_durations: dict[tuple[str, str], list[float]] = defaultdict(list)
    for record in fixtures:
        fixture_durations[(record["scope"], record["phase"])].append(
            record["duration_seconds"]
        )
    lines.extend(
        [
            "",
            "| Fixture scope | Phase | Total | Count |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for scope in ("session", "package", "module", "class", "function"):
        for phase in ("setup", "teardown"):
            durations = fixture_durations[(scope, phase)]
            if durations:
                lines.append(
                    f"| `{scope}` | `{phase}` | "
                    f"{sum(durations):.2f}s | {len(durations)} |"
                )

    lines.extend(
        [
            "",
            "| Slow fixture phase | Scope | Duration | Requested by |",
            "| --- | --- | ---: | --- |",
        ]
    )
    slow_fixtures = sorted(
        fixtures,
        key=lambda record: record["duration_seconds"],
        reverse=True,
    )[:15]
    for record in slow_fixtures:
        label = f"{record['fixture']} ({record['phase']})"
        requested_by = record["node_id"] or "<session>"
        lines.append(
            f"| {_inline_code(label)} | `{_escape_text(record['scope'])}` | "
            f"{record['duration_seconds']:.2f}s | "
            f"{_inline_code(requested_by)} |"
        )
    lines.extend(["", "</details>", ""])
    return lines


def _render_image_build_summary(records: tuple[ImageBuildTiming, ...]) -> list[str]:
    lines = [
        "<details>",
        "<summary>Image build timing</summary>",
        "",
        "| Image | Duration | Cache | Completed |",
        "| --- | ---: | --- | --- |",
    ]
    for record in sorted(
        records,
        key=lambda item: item["duration_seconds"],
        reverse=True,
    ):
        lines.append(
            f"| {_inline_code(record['image'])} | "
            f"{record['duration_seconds']:.2f}s | "
            f"`{_escape_text(record['cache_backend'])}` | "
            f"`{str(record['completed']).lower()}` |"
        )
    total_duration = sum(record["duration_seconds"] for record in records)
    lines.extend(
        [
            f"| **Total** | **{total_duration:.2f}s** |  |  |",
            "",
            "</details>",
            "",
        ]
    )
    return lines


def _test_cases_with_call_durations(
    cases: tuple[TestCaseResult, ...],
    timing_records: tuple[TimingRecord, ...] | None,
) -> tuple[TestCaseResult, ...]:
    """Replace JUnit totals with authoritative pytest call durations when available."""
    if timing_records is None:
        return cases
    call_durations = {
        _canonical_node_id(record["node_id"]): record["duration_seconds"]
        for record in timing_records
        if record["record_type"] == "test_phase" and record["phase"] == "call"
    }
    return tuple(
        TestCaseResult(
            node_id=case.node_id,
            duration_seconds=call_durations.get(
                _canonical_node_id(case.node_id),
                case.duration_seconds,
            ),
            outcome=case.outcome,
        )
        for case in cases
    )


def _canonical_node_id(node_id: str) -> str:
    """Normalize pytest path and JUnit classname node IDs for timing correlation."""
    address, separator, parameter_suffix = node_id.partition("[")
    module, *segments = address.split("::")
    if module.endswith(".py"):
        module = module[:-3]
        if len(segments) > 1:
            module = ".".join((module, *segments[:-1]))
            segments = segments[-1:]
    normalized_module = module.replace("\\", ".").replace("/", ".")
    canonical_address = "::".join((normalized_module, *segments))
    return (
        f"{canonical_address}{separator}{parameter_suffix}"
        if separator
        else canonical_address
    )


def _parse_test_case(element: element_tree.Element) -> TestCaseResult:
    classname = element.attrib.get("classname", "unknown")
    name = element.attrib.get("name", "unknown")
    duration_text = element.attrib.get("time", "0")
    try:
        duration_seconds = float(duration_text)
    except ValueError:
        duration_seconds = 0.0

    if element.find("failure") is not None:
        outcome = "failed"
    elif element.find("error") is not None:
        outcome = "error"
    elif element.find("skipped") is not None:
        outcome = "skipped"
    else:
        outcome = "passed"

    return TestCaseResult(
        node_id=f"{classname}::{name}",
        duration_seconds=duration_seconds,
        outcome=outcome,
    )


def _escape_text(value: str) -> str:
    return html.escape(value, quote=False).replace("|", "&#124;")


def _inline_code(value: str) -> str:
    return f"<code>{_escape_text(value)}</code>"


def _parse_duration(path: Path) -> float:
    duration_seconds = float(path.read_text(encoding="utf-8").strip())
    if duration_seconds < 0:
        raise ValueError("lane duration must not be negative")
    return duration_seconds


def _format_duration(duration_seconds: float) -> str:
    rounded_seconds = round(duration_seconds)
    hours, remainder = divmod(rounded_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    summarize = subparsers.add_parser(
        "summarize",
        help="Render one E2E lane Markdown summary.",
    )
    summarize.add_argument("--lane", required=True)
    summarize.add_argument("--job-result", required=True)
    summarize.add_argument("--junit", type=Path, required=True)
    summarize.add_argument("--timings", type=Path)
    summarize.add_argument("--image-build-timings", type=Path)
    summarize.add_argument("--lane-duration", type=Path)
    summarize.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CI observability command."""
    args = _build_parser().parse_args(argv)
    if args.command != "summarize":
        raise AssertionError(f"unsupported command: {args.command}")

    output: Path = args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        render_summary(
            lane=args.lane,
            job_result=args.job_result,
            junit_path=args.junit,
            timings_path=args.timings,
            image_build_timings_path=args.image_build_timings,
            lane_duration_path=args.lane_duration,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
