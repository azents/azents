"""Compare recorded E2E lane time with the current PR base."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

METRIC = "pytest-call-total-v1"
_LANE = re.compile(r"[a-z][a-z0-9-]*-[1-9][0-9]*")
_SUMMARY_LANE = re.compile(
    r"^### (?P<lane>[a-z][a-z0-9-]*-[1-9][0-9]*) — ",
    re.MULTILINE,
)
_SHA = re.compile(r"[0-9a-f]{40}")
Runner = Callable[[Sequence[str]], str]


class EvidenceError(ValueError):
    """Required comparison evidence is unavailable or invalid."""


@dataclass(frozen=True)
class Sample:
    """One recorded workflow execution's lane durations."""

    run_id: int
    lanes: Mapping[str, Decimal]
    diagnostics: Mapping[str, Mapping[str, Decimal]] = field(default_factory=dict)


@dataclass(frozen=True)
class LaneEvidence:
    """Blocking call totals plus non-blocking phase and wall diagnostics."""

    lanes: Mapping[str, Decimal]
    diagnostics: Mapping[str, Mapping[str, Decimal]]


def _run(arguments: Sequence[str]) -> str:
    result = subprocess.run(
        list(arguments), capture_output=True, text=True, check=False, timeout=90
    )
    if result.returncode != 0:
        raise EvidenceError("github_evidence_unavailable")
    return result.stdout


def _object(text: str) -> dict[str, object]:
    value: object = json.loads(text)
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise EvidenceError("invalid_json")
    return value


def _seconds(text: str) -> Decimal:
    try:
        value = Decimal(text.strip())
    except InvalidOperation as error:
        raise EvidenceError("invalid_duration") from error
    if not value.is_finite() or value < 0:
        raise EvidenceError("invalid_duration")
    return value


def _lane_name(path: Path, root: Path) -> str:
    lane = path.parent.name.removeprefix("e2e-observability-")
    if _LANE.fullmatch(lane):
        return lane
    if path.parent != root:
        raise EvidenceError("invalid_lane_artifacts")
    summary_path = path.with_name("summary.md")
    try:
        matches = _SUMMARY_LANE.findall(summary_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise EvidenceError("invalid_lane_artifacts") from error
    if len(matches) != 1:
        raise EvidenceError("invalid_lane_artifacts")
    return matches[0]


def load_lanes(root: Path) -> LaneEvidence:
    """Read complete pytest call totals and retain setup/wall diagnostics."""
    lanes: dict[str, Decimal] = {}
    diagnostics: dict[str, Mapping[str, Decimal]] = {}
    for path in root.glob("**/pytest-timings.jsonl"):
        lane = _lane_name(path, root)
        if lane in lanes:
            raise EvidenceError("invalid_lane_artifacts")
        phases = {phase: Decimal(0) for phase in ("setup", "call", "teardown")}
        seen: set[tuple[str, str]] = set()
        call_count = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            payload = _object(line)
            if payload.get("record_type") != "test_phase":
                continue
            node_id, phase = payload.get("node_id"), payload.get("phase")
            if (
                not isinstance(node_id, str)
                or not node_id
                or phase not in phases
                or (node_id, str(phase)) in seen
            ):
                raise EvidenceError("invalid_test_phase_timing")
            seen.add((node_id, str(phase)))
            phases[str(phase)] += _seconds(str(payload.get("duration_seconds")))
            if phase == "call":
                call_count += 1
        try:
            junit = element_tree.parse(path.parent / "junit.xml").getroot()
        except (OSError, element_tree.ParseError) as error:
            raise EvidenceError("junit_evidence_unavailable") from error
        expected_calls = sum(
            case.find("skipped") is None for case in junit.iter("testcase")
        )
        if not call_count or call_count != expected_calls:
            raise EvidenceError("incomplete_call_timing")
        wall = _seconds(
            (path.parent / "lane-duration-seconds.txt").read_text(encoding="utf-8")
        )
        lanes[lane] = phases["call"]
        diagnostics[lane] = {**phases, "wall": wall}
    if not lanes:
        raise EvidenceError("call_timing_unavailable")
    return LaneEvidence(lanes, diagnostics)


def _runs(repository: str, sha: str, command: Runner) -> list[int]:
    payload = _object(
        command(
            [
                "gh",
                "api",
                "--method",
                "GET",
                f"repos/{repository}/actions/workflows/ci.yaml/runs"
                f"?head_sha={sha}&status=completed&per_page=10",
            ]
        )
    )
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        raise EvidenceError("invalid_run_list")
    return [
        row["id"]
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    ]


def find_sample(
    repository: str,
    sha: str,
    expected_lanes: set[str],
    exclude_run_id: int,
    work_dir: Path,
    command: Runner,
) -> Sample:
    """Use the newest existing run with the same complete lane set."""
    if not _SHA.fullmatch(sha):
        raise EvidenceError("base_sha_unavailable")
    for run_id in _runs(repository, sha, command):
        if run_id == exclude_run_id:
            continue
        destination = work_dir / f"run-{run_id}"
        try:
            command(
                [
                    "gh",
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    repository,
                    "--pattern",
                    "e2e-observability-*",
                    "--dir",
                    str(destination),
                ]
            )
            evidence = load_lanes(destination)
        except (EvidenceError, OSError):
            continue
        if expected_lanes <= set(evidence.lanes):
            return Sample(
                run_id,
                {lane: evidence.lanes[lane] for lane in expected_lanes},
                {lane: evidence.diagnostics[lane] for lane in expected_lanes},
            )
    raise EvidenceError("compatible_base_run_unavailable")


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _diagnostics_wire(
    diagnostics: Mapping[str, Mapping[str, Decimal]],
) -> dict[str, dict[str, str | None]]:
    return {
        lane: {name: _number(value) for name, value in values.items()}
        for lane, values in sorted(diagnostics.items())
    }


def compare(
    lanes: Mapping[str, Decimal],
    base: Sample,
    head_sha: str,
    base_sha: str,
    diagnostics: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> dict[str, object]:
    """Compute the exact twenty-percent verdict."""
    critical = max(lanes.items(), key=lambda item: item[1])[0]
    base_critical = max(base.lanes.items(), key=lambda item: item[1])[0]
    observed = lanes[critical]
    reference = max(base.lanes.values())
    threshold = reference * Decimal("1.20")
    increase = (observed / reference - 1) * 100 if reference else None
    outcome = "regression" if observed >= threshold else "pass"
    return {
        "schema_version": 1,
        "metric": METRIC,
        "outcome": outcome,
        "reason": "at_or_above_twenty_percent"
        if outcome == "regression"
        else "below_twenty_percent",
        "head_sha": head_sha,
        "base_sha": base_sha,
        "base_run_id": base.run_id,
        "lanes": {lane: _number(value) for lane, value in sorted(lanes.items())},
        "base_lanes": {
            lane: _number(value) for lane, value in sorted(base.lanes.items())
        },
        "lane_diagnostics": _diagnostics_wire(diagnostics or {}),
        "base_lane_diagnostics": _diagnostics_wire(base.diagnostics),
        "critical_lane": critical,
        "base_critical_lane": base_critical,
        "observed_seconds": _number(observed),
        "reference_seconds": _number(reference),
        "threshold_seconds": _number(threshold),
        "increase_percent": _number(increase.quantize(Decimal("0.01")))
        if increase is not None
        else None,
    }


def unavailable(
    lanes: Mapping[str, Decimal],
    reason: str,
    head: str,
    base: str,
    diagnostics: Mapping[str, Mapping[str, Decimal]] | None = None,
) -> dict[str, object]:
    """Keep current measurements visible while failing closed."""
    return {
        "schema_version": 1,
        "metric": METRIC,
        "outcome": "comparison_unavailable",
        "reason": reason,
        "head_sha": head,
        "base_sha": base,
        "base_run_id": None,
        "lanes": {lane: _number(value) for lane, value in sorted(lanes.items())},
        "base_lanes": {},
        "lane_diagnostics": _diagnostics_wire(diagnostics or {}),
        "base_lane_diagnostics": {},
        "critical_lane": max(lanes.items(), key=lambda item: item[1])[0]
        if lanes
        else None,
        "base_critical_lane": None,
        "observed_seconds": _number(max(lanes.values())) if lanes else None,
        "reference_seconds": None,
        "threshold_seconds": None,
        "increase_percent": None,
    }


def render(report: Mapping[str, object]) -> str:
    """Render a scan-first verdict before exposing raw evidence."""
    outcome = str(report["outcome"])
    observed = report.get("observed_seconds")
    reference = report.get("reference_seconds")
    increase = report.get("increase_percent")
    threshold = report.get("threshold_seconds")
    lane = html.escape(str(report.get("critical_lane") or "unknown"))
    change = (
        f"{Decimal(str(increase)):+.2f}".rstrip("0").rstrip(".")
        if increase is not None
        else None
    )
    status = {
        "pass": "✅ Within limit",
        "regression": "❌ Over 20% limit",
        "comparison_unavailable": "⚠️ Comparison unavailable",
    }.get(outcome, "⚠️ Unknown result")
    observed_display = _display_seconds(observed)
    reference_display = _display_seconds(reference)
    threshold_display = _display_seconds(threshold)
    values = [
        f"Candidate test `{observed_display}s`"
        if observed is not None
        else "Candidate test `unavailable`",
        f"Base test `{reference_display}s`"
        if reference is not None
        else "Base test `unavailable`",
    ]
    if change is not None:
        values.append(f"Change `{change}%`")
    if threshold is not None:
        values.append(f"Limit `{threshold_display}s`")
    lines = ["## E2E duration", "", f"**{status}**", "", " · ".join(values)]
    if outcome == "comparison_unavailable":
        reason = {
            "compatible_base_run_unavailable": "Base timing artifact unavailable",
            "github_evidence_unavailable": "GitHub timing evidence unavailable",
            "lane_evidence_unavailable": "Current lane timing unavailable",
            "call_timing_unavailable": "Current test timing unavailable",
            "incomplete_call_timing": "Test timing evidence incomplete",
        }.get(str(report.get("reason")), "Required timing evidence unavailable")
        lines.extend(["", f"`{reason}`"])
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Details</summary>",
            "",
            "| Run | Lane | Test | Setup | Teardown | Total |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
            _diagnostic_row("Candidate", lane, report.get("lane_diagnostics")),
            _diagnostic_row(
                "Base",
                html.escape(str(report.get("base_critical_lane") or "unknown")),
                report.get("base_lane_diagnostics"),
            ),
            "",
            f"- Change: **{change if change is not None else 'unavailable'}%**",
            f"- Failure threshold: **{threshold_display}s**",
            f"- Base workflow run: `{report.get('base_run_id') or 'unavailable'}`",
            "",
            "<details>",
            "<summary>Raw JSON</summary>",
            "",
            "```json",
            json.dumps(report, indent=2, sort_keys=True),
            "```",
            "",
            "</details>",
            "",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def _diagnostic_row(label: str, lane: str, raw: object) -> str:
    values = raw.get(lane) if isinstance(raw, dict) else None
    if not isinstance(values, dict):
        unavailable = " | ".join(["unavailable"] * 4)
        return f"| {label} | `{lane}` | {unavailable} |"
    cells = [
        f"{_display_seconds(values.get(name))}s"
        if values.get(name) is not None
        else "unavailable"
        for name in ("call", "setup", "teardown", "wall")
    ]
    return f"| {label} | `{lane}` | " + " | ".join(cells) + " |"


def _display_seconds(value: object) -> str:
    if value is None:
        return "unavailable"
    number = Decimal(str(value)).quantize(Decimal("0.1"))
    return _number(number) or "0"


def evaluate(
    artifacts_root: Path,
    repository: str,
    base_sha: str,
    head_sha: str,
    run_id: int,
    work_dir: Path,
    command: Runner,
) -> dict[str, object]:
    """Evaluate current local artifacts against an existing base run."""
    evidence = LaneEvidence({}, {})
    try:
        evidence = load_lanes(artifacts_root)
        base = find_sample(
            repository, base_sha, set(evidence.lanes), run_id, work_dir, command
        )
        return compare(
            evidence.lanes,
            base,
            head_sha,
            base_sha,
            diagnostics=evidence.diagnostics,
        )
    except (EvidenceError, OSError, ValueError) as error:
        return unavailable(
            evidence.lanes,
            str(error),
            head_sha,
            base_sha,
            diagnostics=evidence.diagnostics,
        )


def _candidate_report(
    repository: str, head_sha: str, work_dir: Path, command: Runner
) -> tuple[int, dict[str, object]]:
    for run_id in _runs(repository, head_sha, command):
        destination = work_dir / f"candidate-{run_id}"
        try:
            command(
                [
                    "gh",
                    "run",
                    "download",
                    str(run_id),
                    "--repo",
                    repository,
                    "--name",
                    "e2e-duration-gate",
                    "--dir",
                    str(destination),
                ]
            )
            report = _object((destination / "report.json").read_text(encoding="utf-8"))
        except (EvidenceError, OSError):
            continue
        if report.get("head_sha") == head_sha and isinstance(report.get("lanes"), dict):
            return run_id, report
    raise EvidenceError("candidate_evidence_unavailable")


def recheck(repository: str, pull_number: int, work_dir: Path, command: Runner) -> str:
    """Recompare the last candidate measurement when its PR base changes."""
    pull = _object(command(["gh", "api", f"repos/{repository}/pulls/{pull_number}"]))
    head = pull.get("head")
    base = pull.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise EvidenceError("invalid_pull_request")
    head_sha, base_sha = head.get("sha"), base.get("sha")
    if not isinstance(head_sha, str) or not isinstance(base_sha, str):
        raise EvidenceError("invalid_pull_request")
    try:
        run_id, report = _candidate_report(repository, head_sha, work_dir, command)
    except (EvidenceError, OSError):
        return f"PR #{pull_number}: no duration evidence"
    outcome = "comparison_unavailable"
    reason = "evidence_unavailable"
    target = f"https://github.com/{repository}/actions/runs/{run_id}"
    try:
        raw = report["lanes"]
        if not isinstance(raw, dict):
            raise EvidenceError("invalid_candidate_lanes")
        lanes = {str(lane): _seconds(str(value)) for lane, value in raw.items()}
        sample = find_sample(
            repository, base_sha, set(lanes), run_id, work_dir / "base", command
        )
        result = compare(lanes, sample, head_sha, base_sha)
        outcome, reason = str(result["outcome"]), str(result["reason"])
    except (EvidenceError, OSError, ValueError) as error:
        reason = str(error)
    state = "success" if outcome == "pass" else "failure"
    command(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repository}/statuses/{head_sha}",
            "-f",
            "context=ci-python-e2e",
            "-f",
            f"state={state}",
            "-f",
            f"description=base={base_sha[:7]} {outcome}",
            "-f",
            f"target_url={target}",
        ]
    )
    return f"PR #{pull_number}: {outcome} ({reason})"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    gate = commands.add_parser("gate")
    for name in ("artifacts-root", "work-dir", "report-json", "report-markdown"):
        gate.add_argument(f"--{name}", type=Path, required=True)
    for name in ("repository", "base-sha", "head-sha"):
        gate.add_argument(f"--{name}", required=True)
    gate.add_argument("--run-id", type=int, required=True)
    check = commands.add_parser("recheck")
    check.add_argument("--repository", required=True)
    check.add_argument("--pull-number", type=int, required=True)
    check.add_argument("--work-dir", type=Path, required=True)
    return parser


def main(
    argv: Sequence[str] | None = None, *, command_runner: Runner | None = None
) -> int:
    """Run the workflow helper."""
    args = _parser().parse_args(argv)
    command = command_runner or _run
    if args.command == "recheck":
        sys.stdout.write(
            recheck(args.repository, args.pull_number, args.work_dir, command) + "\n"
        )
        return 0
    report = evaluate(
        args.artifacts_root,
        args.repository,
        args.base_sha,
        args.head_sha,
        args.run_id,
        args.work_dir,
        command,
    )
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    args.report_markdown.write_text(render(report), encoding="utf-8")
    return 0 if report["outcome"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
