"""Compare recorded E2E lane time with the current PR base."""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

METRIC = "pytest-lane-wall-v1"
_LANE = re.compile(r"[a-z][a-z0-9-]*-[1-9][0-9]*")
_SHA = re.compile(r"[0-9a-f]{40}")
Runner = Callable[[Sequence[str]], str]


class EvidenceError(ValueError):
    """Required comparison evidence is unavailable or invalid."""


@dataclass(frozen=True)
class Sample:
    """One recorded workflow execution's lane durations."""

    run_id: int
    lanes: Mapping[str, Decimal]


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


def load_lanes(root: Path) -> dict[str, Decimal]:
    """Read the raw files already used by the sticky CI comment."""
    lanes: dict[str, Decimal] = {}
    for path in root.glob("**/lane-duration-seconds.txt"):
        lane = path.parent.name.removeprefix("e2e-observability-")
        if not _LANE.fullmatch(lane) or lane in lanes:
            raise EvidenceError("invalid_lane_artifacts")
        lanes[lane] = _seconds(path.read_text(encoding="utf-8"))
    if not lanes:
        raise EvidenceError("lane_evidence_unavailable")
    return lanes


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
            lanes = load_lanes(destination)
        except (EvidenceError, OSError):
            continue
        if expected_lanes <= set(lanes):
            return Sample(run_id, {lane: lanes[lane] for lane in expected_lanes})
    raise EvidenceError("compatible_base_run_unavailable")


def _number(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def compare(
    lanes: Mapping[str, Decimal], base: Sample, head_sha: str, base_sha: str
) -> dict[str, object]:
    """Compute the exact twenty-percent verdict."""
    critical = max(lanes, key=lambda lane: lanes[lane])
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
        "critical_lane": critical,
        "observed_seconds": _number(observed),
        "reference_seconds": _number(reference),
        "threshold_seconds": _number(threshold),
        "increase_percent": _number(increase.quantize(Decimal("0.01")))
        if increase is not None
        else None,
    }


def unavailable(
    lanes: Mapping[str, Decimal], reason: str, head: str, base: str
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
        "critical_lane": max(lanes.items(), key=lambda item: item[1])[0]
        if lanes
        else None,
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
    values = [
        f"Candidate `{observed}s`"
        if observed is not None
        else "Candidate `unavailable`",
        f"Base `{reference}s`" if reference is not None else "Base `unavailable`",
    ]
    if change is not None:
        values.append(f"Change `{change}%`")
    if threshold is not None:
        values.append(f"Limit `{threshold}s`")
    lines = ["## E2E duration", "", f"**{status}**", "", " · ".join(values)]
    if outcome == "comparison_unavailable":
        reason = {
            "compatible_base_run_unavailable": "Base timing artifact unavailable",
            "github_evidence_unavailable": "GitHub timing evidence unavailable",
            "lane_evidence_unavailable": "Current lane timing unavailable",
        }.get(str(report.get("reason")), "Required timing evidence unavailable")
        lines.extend(["", f"`{reason}`"])
    lines.extend(
        [
            "",
            "<details>",
            "<summary>Details</summary>",
            "",
            f"- Candidate maximum: **{observed or 'unavailable'}s** (`{lane}`)",
            f"- Base maximum: **{reference or 'unavailable'}s**",
            f"- Change: **{change if change is not None else 'unavailable'}%**",
            f"- Failure threshold: **{threshold or 'unavailable'}s**",
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
    lanes: dict[str, Decimal] = {}
    try:
        lanes = load_lanes(artifacts_root)
        base = find_sample(repository, base_sha, set(lanes), run_id, work_dir, command)
        return compare(lanes, base, head_sha, base_sha)
    except (EvidenceError, OSError, ValueError) as error:
        return unavailable(lanes, str(error), head_sha, base_sha)


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
