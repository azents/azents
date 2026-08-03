"""Render bounded E2E CI observability summaries from pytest JUnit output."""

import argparse
import html
import xml.etree.ElementTree as element_tree
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


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
) -> str:
    """Render one lane summary without including failure messages or logs."""
    lines = [
        f"### {_escape_text(lane)}",
        "",
        f"Job result: `{_escape_text(job_result)}`",
        "",
    ]
    if not junit_path.is_file():
        lines.extend(
            [
                "JUnit XML was not produced. Inspect the workflow log and uploaded "
                "diagnostics for setup or infrastructure failures.",
                "",
            ]
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
        summary.cases,
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

    return "\n".join(lines)


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
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
