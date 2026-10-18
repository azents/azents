"""Analyze whole-CI attempts while retaining E2E as a separately named subset."""

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.ci.evidence import (
    decode_native_node_run,
    decode_test_run,
    verify_collection,
)
from scripts.ci.observability import parse_junit, parse_timings
from scripts.ci.workflow_report import Run, decode_run, metrics


def analyze(roots: list[Path], cohort: str) -> dict[str, object]:
    runs: list[Run] = []
    records: list[dict[str, object]] = []
    slow_calls: dict[str, list[float]] = defaultdict(list)
    failures: Counter[str] = Counter()
    cases_by_scope: dict[str, Counter[tuple[str, str]]] = {}
    seen: set[tuple[int, int]] = set()
    for root in roots:
        run = decode_run(json.loads((root / "run.json").read_text()))
        key = (run.run_id, run.attempt)
        if key in seen:
            raise ValueError("Duplicate workflow attempt")
        seen.add(key)
        if run.status != "completed":
            raise ValueError("Analysis requires completed workflow attempts")
        collected_artifacts = verify_collection(root, run)
        evidence_complete = True
        failed_tests = False
        case_keys: Counter[tuple[str, str]] = Counter()
        expected = expected_test_artifacts(run)
        found: set[str] = set()
        for artifact in sorted((root / "artifacts").glob("*")):
            if not artifact.is_dir():
                continue
            junit = artifact / "junit.xml"
            timing = artifact / "pytest-timings.jsonl"
            if artifact.name.startswith("ci-observability-"):
                if not artifact.name.endswith(f"-{run.attempt}"):
                    raise ValueError("General CI artifact attempt mismatch")
                identity = artifact.name.removeprefix("ci-observability-").rsplit(
                    "-", 1
                )[0]
                receipt = (
                    json.loads((artifact / "test-run.json").read_text())
                    if (artifact / "test-run.json").is_file()
                    else None
                )
                native = (
                    decode_native_node_run(receipt)
                    if receipt is not None and identity == "typescript-web"
                    else None
                )
                if native is not None:
                    failed_tests = failed_tests or native.exit_code != 0
                test_run = (
                    native.identity
                    if native is not None
                    else decode_test_run(receipt)
                    if receipt is not None
                    else None
                )
                if test_run is None:
                    evidence_complete = False
                elif (
                    test_run.head_sha != run.head_sha
                    or test_run.run_id != str(run.run_id)
                    or test_run.attempt != str(run.attempt)
                    or test_run.name != identity
                ):
                    raise ValueError("Test evidence workflow identity mismatch")
            elif artifact.name.startswith("e2e-observability-"):
                identity = "e2e-" + artifact.name.removeprefix("e2e-observability-")
            else:
                continue
            found.add(identity)
            native_node = identity == "typescript-web"
            if not junit.is_file() or (not native_node and not timing.is_file()):
                evidence_complete = False
                continue
            summary = parse_junit(junit)
            if summary.tests == 0:
                evidence_complete = False
            failed_tests = failed_tests or bool(summary.failures or summary.errors)
            # The planner may rebalance numbered lanes without changing coverage.
            lane_scope, _, lane_number = identity.rpartition("-")
            coverage_identity = (
                lane_scope
                if lane_scope in {"e2e-required", "e2e-web"} and lane_number.isdecimal()
                else identity
            )
            for case in summary.cases:
                case_keys[(coverage_identity, case.node_id)] += 1
                if case.outcome in {"failed", "error"}:
                    failures[f"{identity}:{case.node_id}"] += 1
            timing_records = parse_timings(timing) if timing.is_file() else ()
            if not native_node and not timing_records:
                evidence_complete = False
            for entry in timing_records:
                if (
                    entry["record_type"] == "test_phase"
                    and entry["phase"] == "call"
                    and entry["outcome"] == "passed"
                    and run.conclusion == "success"
                ):
                    slow_calls[f"{identity}:{entry['node_id']}"].append(
                        entry["duration_seconds"]
                    )
        record = metrics(run)
        native_complete = (
            "ios-quality-build" not in {j.name for j in run.jobs}
            or f"ios-diagnostics-{run.head_sha}" in collected_artifacts
        )
        scope_key = "\n".join(
            sorted(j.name for j in run.jobs if j.conclusion != "skipped")
        )
        if (
            cohort == "experiment"
            and evidence_complete
            and expected <= found
            and scope_key in cases_by_scope
            and cases_by_scope[scope_key] != case_keys
        ):
            raise ValueError("Experiment testcase evidence changed between attempts")
        if evidence_complete and expected <= found:
            cases_by_scope[scope_key] = case_keys
        record.update(
            {
                "date_kst": run.created.astimezone(ZoneInfo("Asia/Seoul"))
                .date()
                .isoformat(),
                "cohort": cohort,
                "test_evidence_complete": evidence_complete and expected <= found,
                "native_evidence_complete": native_complete,
                "missing_test_artifacts": sorted(expected - found),
                "test_cases": sum(case_keys.values()),
                "source": str(root),
            }
        )
        if not record["test_evidence_complete"] or not native_complete or failed_tests:
            record["performance_eligible"] = False
        records.append(record)
        runs.append(run)
    if not records:
        raise ValueError("No CI samples found")
    shas = {r.head_sha for r in runs}
    scopes = {
        tuple(
            sorted(
                j.name
                for j in r.jobs
                if j.name != "ci-observability" and j.conclusion != "skipped"
            )
        )
        for r in runs
    }
    if cohort == "experiment" and (len(shas) != 1 or len(scopes) != 1):
        raise ValueError("Experiment needs one SHA and the same enabled CI scope")
    eligible = [
        float(r["gate_completion_elapsed_seconds"])
        for r in records
        if r["performance_eligible"]
        and isinstance(r["gate_completion_elapsed_seconds"], int | float)
    ]
    return {
        "cohort": cohort,
        "records": records,
        "sha_count": len(shas),
        "same_sha_acceptance_ready": cohort == "experiment" and len(eligible) >= 2,
        "successful_samples": len(eligible),
        "gate_completion_mean_seconds": statistics.mean(eligible) if eligible else None,
        "gate_completion_median_seconds": statistics.median(eligible)
        if eligible
        else None,
        "failures": dict(failures),
        "slow_calls": sorted(
            [
                {
                    "node_id": key,
                    "n": len(vals),
                    "mean": statistics.mean(vals),
                    "median": statistics.median(vals),
                }
                for key, vals in slow_calls.items()
            ],
            key=lambda item: item["median"],
            reverse=True,
        )[:30],
    }


def expected_test_artifacts(run: Run) -> set[str]:
    """Derive enabled test producers from the current CI job identities."""
    names = {j.name for j in run.jobs if j.conclusion != "skipped"}
    expected = {
        "e2e-" + n.removeprefix("ci-e2e-")
        for n in names
        if n.startswith("ci-e2e-") and n.rsplit("-", 1)[-1].isdigit()
    }
    projects = {
        "python/libs/az-common": "python-az-common",
        "python/libs/azents-runtime-control": "python-runtime-control",
        "python/apps/azents": "python-azents",
        "python/apps/azents-runtime-runner": "python-runtime-runner",
        "python/apps/azents-runtime-proxy": "python-runtime-proxy",
        "python/apps/azents-runtime-provider-kubernetes": "python-provider-kubernetes",
        "python/apps/azents-runtime-provider-docker": "python-provider-docker",
        "testenv/azents": "python-testenv",
    }
    for project, artifact in projects.items():
        if any(n.startswith("ci-python-run (") and project in n for n in names):
            expected.add(artifact)
    for name, artifact in {
        "ci-python-migrations-run": "python-migrations",
        "ci-testenv-support-run": "testenv-support",
        "ci-helm-run": "helm",
    }.items():
        if name in names:
            expected.add(artifact)
    if any(
        j.name == "ci-typescript-run"
        and any(s.name == "Web Node contracts" for s in j.steps)
        for j in run.jobs
        if j.conclusion != "skipped"
    ):
        expected.add("typescript-web")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--cohort", choices=["baseline", "experiment"], required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    args = parser.parse_args()
    roots = (
        [args.samples_root]
        if (args.samples_root / "run.json").is_file()
        else sorted(p.parent for p in args.samples_root.glob("*/run.json"))
    )
    result = analyze(roots, args.cohort)
    args.json_output.write_text(json.dumps(result, indent=2) + "\n")
    sys.stdout.write(
        json.dumps(
            {k: v for k, v in result.items() if k not in {"records", "slow_calls"}},
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
