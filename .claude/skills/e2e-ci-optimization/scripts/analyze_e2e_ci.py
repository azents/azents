#!/usr/bin/env python3
"""Analyze local Azents E2E observability samples."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LaneSample:
    """One required E2E lane from one preserved CI sample."""

    sample: str
    lane: str
    conclusion: str
    wall_seconds: float
    test_calls: dict[str, float]
    fixture_setups: dict[str, float]
    image_builds: dict[str, float]
    failures: tuple[str, ...]


@dataclass(frozen=True)
class RunSample:
    """One preserved required-E2E workflow attempt."""

    head_sha: str
    lanes: dict[str, LaneSample]


def percentile(values: list[float], fraction: float) -> float:
    """Return a nearest-rank percentile."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[index]


def _job_wall_seconds(job: dict[str, Any]) -> float:
    started_at = job.get("startedAt")
    completed_at = job.get("completedAt")
    if (
        not isinstance(started_at, str)
        or not isinstance(completed_at, str)
        or completed_at == "0001-01-01T00:00:00Z"
    ):
        return 0.0
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    return (end - start).total_seconds()


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _parse_lane(
    *,
    sample: str,
    artifact_dir: Path,
    job: dict[str, Any],
) -> LaneSample:
    required_paths = (
        artifact_dir / "pytest-timings.jsonl",
        artifact_dir / "junit.xml",
    )
    missing_paths = [path.name for path in required_paths if not path.is_file()]
    if missing_paths:
        raise ValueError(
            f"{sample}/{artifact_dir.name} is missing required evidence: "
            f"{', '.join(missing_paths)}"
        )

    timings = _read_json_lines(artifact_dir / "pytest-timings.jsonl")
    test_calls: dict[str, float] = defaultdict(float)
    fixture_setups: dict[str, float] = defaultdict(float)
    for timing in timings:
        duration = timing.get("duration_seconds")
        if not isinstance(duration, int | float):
            continue
        if timing.get("record_type") == "test_phase" and timing.get("phase") == "call":
            node_id = timing.get("node_id")
            if isinstance(node_id, str) and node_id:
                test_calls[node_id] += float(duration)
        if timing.get("record_type") == "fixture" and timing.get("phase") == "setup":
            fixture = timing.get("fixture")
            if isinstance(fixture, str) and fixture:
                fixture_setups[fixture] += float(duration)

    image_builds: dict[str, float] = defaultdict(float)
    for image in _read_json_lines(artifact_dir / "image-build-timings.jsonl"):
        name = image.get("image")
        duration = image.get("duration_seconds")
        if isinstance(name, str) and isinstance(duration, int | float):
            image_builds[name] += float(duration)

    if not test_calls:
        raise ValueError(
            f"{sample}/{artifact_dir.name} has no test call timing evidence."
        )

    junit_path = artifact_dir / "junit.xml"
    failures: list[str] = []
    test_cases = list(ET.parse(junit_path).iter("testcase"))
    if not test_cases:
        raise ValueError(f"{sample}/{artifact_dir.name} has no JUnit test cases.")
    for test_case in test_cases:
        if test_case.find("failure") is not None or test_case.find("error") is not None:
            failures.append(
                f"{test_case.attrib.get('classname')}::{test_case.attrib.get('name')}"
            )

    lane = artifact_dir.name.removeprefix("e2e-observability-")
    return LaneSample(
        sample=sample,
        lane=lane,
        conclusion=str(job.get("conclusion") or ""),
        wall_seconds=_job_wall_seconds(job),
        test_calls=dict(test_calls),
        fixture_setups=dict(fixture_setups),
        image_builds=dict(image_builds),
        failures=tuple(failures),
    )


def load_samples(samples_root: Path, cohort: str) -> dict[str, RunSample]:
    """Load preserved run metadata and required-lane artifacts."""
    if cohort not in {"baseline", "experiment"}:
        raise ValueError(f"Unsupported cohort: {cohort}")

    sample_dirs = sorted(path for path in samples_root.iterdir() if path.is_dir())
    if (samples_root / "run.json").exists():
        sample_dirs = [samples_root]

    samples: dict[str, RunSample] = {}
    for sample_dir in sample_dirs:
        run_path = sample_dir / "run.json"
        if not run_path.exists():
            continue
        metadata = json.loads(run_path.read_text(encoding="utf-8"))
        head_sha = metadata.get("headSha")
        if not isinstance(head_sha, str) or not head_sha:
            raise ValueError(f"{run_path} is missing headSha.")
        jobs = {
            job["name"].removeprefix("ci-e2e-"): job
            for job in metadata.get("jobs", [])
            if isinstance(job, dict)
            and isinstance(job.get("name"), str)
            and job["name"].startswith("ci-e2e-required-")
        }
        if not jobs:
            raise ValueError(f"{run_path} has no required E2E jobs.")

        artifact_dirs = {
            path.name.removeprefix("e2e-observability-"): path
            for path in sample_dir.glob("e2e-observability-required-*")
        }
        missing_lanes = sorted(set(jobs) - set(artifact_dirs))
        if missing_lanes:
            raise ValueError(
                f"{sample_dir.name} is missing required lane artifacts: "
                f"{', '.join(missing_lanes)}"
            )

        lanes: dict[str, LaneSample] = {}
        for lane, job in sorted(jobs.items()):
            artifact_dir = artifact_dirs[lane]
            lanes[lane] = _parse_lane(
                sample=sample_dir.name,
                artifact_dir=artifact_dir,
                job=job,
            )
        invalid_wall_lanes = sorted(
            lane.lane for lane in lanes.values() if lane.wall_seconds <= 0
        )
        if invalid_wall_lanes:
            raise ValueError(
                f"{sample_dir.name} has invalid wall-time evidence for: "
                f"{', '.join(invalid_wall_lanes)}"
            )
        samples[sample_dir.name] = RunSample(
            head_sha=head_sha,
            lanes=lanes,
        )
    if not samples:
        raise ValueError(f"No complete E2E samples found below {samples_root}.")
    head_shas = {sample.head_sha for sample in samples.values()}
    if cohort == "experiment" and len(head_shas) != 1:
        raise ValueError(
            "Experiment samples must use one headSha; found "
            f"{', '.join(sorted(head_shas))}."
        )
    return samples


def analyze(samples: dict[str, RunSample], cohort: str) -> dict[str, Any]:
    """Calculate baseline, failure, test, image, and overlap evidence."""
    sample_rows: dict[str, dict[str, Any]] = {}
    successful_critical_paths: list[float] = []
    failure_counts: Counter[str] = Counter()
    nodes: set[str] = set()
    test_samples: dict[str, list[float]] = defaultdict(list)
    image_samples: dict[str, list[float]] = defaultdict(list)
    overlaps: list[dict[str, Any]] = []
    successful_lane_sets: list[dict[str, LaneSample]] = []

    for sample_name, sample in samples.items():
        lanes = sample.lanes
        critical = max(lanes.values(), key=lambda lane: lane.wall_seconds)
        successful = all(lane.conclusion == "success" for lane in lanes.values())
        if successful:
            successful_critical_paths.append(critical.wall_seconds)
            successful_lane_sets.append(lanes)
        sample_rows[sample_name] = {
            "head_sha": sample.head_sha,
            "successful": successful,
            "critical_lane": critical.lane,
            "critical_path_seconds": critical.wall_seconds,
            "lanes": {
                name: {
                    "wall_seconds": lane.wall_seconds,
                    "conclusion": lane.conclusion,
                }
                for name, lane in sorted(lanes.items())
            },
        }
        for lane in lanes.values():
            failure_counts.update(lane.failures)
            if not successful:
                continue
            nodes.update(lane.test_calls)
            for node, duration in lane.test_calls.items():
                test_samples[node].append(duration)
            for image, duration in lane.image_builds.items():
                image_samples[image].append(duration)
            batch_seconds = lane.fixture_setups.get("e2e_images")
            if batch_seconds is not None and lane.image_builds:
                image_sum = sum(lane.image_builds.values())
                overlaps.append(
                    {
                        "sample": sample_name,
                        "lane": lane.lane,
                        "image_sum_seconds": image_sum,
                        "batch_seconds": batch_seconds,
                        "overlap_seconds": max(0.0, image_sum - batch_seconds),
                    }
                )

    test_rows: list[dict[str, Any]] = []
    for node in nodes:
        durations = test_samples[node]
        savings_50: list[float] = []
        savings_100: list[float] = []
        critical_exposure = 0
        for lanes in successful_lane_sets:
            old_critical = max(lane.wall_seconds for lane in lanes.values())
            node_lane = next(
                (lane for lane in lanes.values() if node in lane.test_calls),
                None,
            )
            if node_lane is None:
                savings_50.append(0.0)
                savings_100.append(0.0)
                continue
            if node_lane.wall_seconds == old_critical:
                critical_exposure += 1
            duration = node_lane.test_calls[node]
            for fraction, target in (
                (0.5, savings_50),
                (1.0, savings_100),
            ):
                new_critical = max(
                    lane.wall_seconds
                    - (duration * fraction if lane is node_lane else 0.0)
                    for lane in lanes.values()
                )
                target.append(max(0.0, old_critical - new_critical))
        test_rows.append(
            {
                "node": node,
                "samples": len(durations),
                "median_seconds": statistics.median(durations),
                "p90_seconds": percentile(durations, 0.9),
                "critical_exposure": critical_exposure,
                "mean_critical_saving_50_seconds": (
                    statistics.mean(savings_50) if savings_50 else 0.0
                ),
                "mean_critical_saving_100_seconds": (
                    statistics.mean(savings_100) if savings_100 else 0.0
                ),
            }
        )

    critical_paths = {
        "successful_samples": len(successful_critical_paths),
        "mean_seconds": (
            statistics.mean(successful_critical_paths)
            if successful_critical_paths
            else 0.0
        ),
        "median_seconds": (
            statistics.median(successful_critical_paths)
            if successful_critical_paths
            else 0.0
        ),
        "p90_seconds": percentile(successful_critical_paths, 0.9),
    }
    images = [
        {
            "image": image,
            "samples": len(durations),
            "median_seconds": statistics.median(durations),
            "p90_seconds": percentile(durations, 0.9),
        }
        for image, durations in image_samples.items()
    ]
    head_shas = sorted({sample.head_sha for sample in samples.values()})
    experiment_ready = (
        cohort == "experiment"
        and len(head_shas) == 1
        and len(successful_critical_paths) >= 2
    )
    return {
        "cohort": {
            "type": cohort,
            "head_shas": head_shas,
            "same_sha_acceptance_ready": experiment_ready,
        },
        "samples": sample_rows,
        "critical_paths": critical_paths,
        "failures": dict(failure_counts),
        "tests": sorted(
            test_rows,
            key=lambda row: row["mean_critical_saving_50_seconds"],
            reverse=True,
        ),
        "images": sorted(
            images,
            key=lambda row: row["median_seconds"],
            reverse=True,
        ),
        "parallel_image_overlaps": overlaps,
    }


def _print_report(report: dict[str, Any], top: int) -> None:
    cohort = report["cohort"]
    print(
        f"COHORT {cohort['type']} "
        f"sha_count={len(cohort['head_shas'])} "
        f"same_sha_acceptance_ready={str(cohort['same_sha_acceptance_ready']).lower()}"
    )

    print("SAMPLES")
    for sample, row in report["samples"].items():
        lane_text = ", ".join(
            f"{name}={lane['wall_seconds']:.0f}s/{lane['conclusion']}"
            for name, lane in row["lanes"].items()
        )
        print(
            f"{sample}: sha={row['head_sha']} critical={row['critical_lane']} "
            f"{row['critical_path_seconds']:.1f}s; {lane_text}"
        )

    critical_paths = report["critical_paths"]
    print("\nCRITICAL PATH SUMMARY")
    print(
        f"successful={critical_paths['successful_samples']} "
        f"mean={critical_paths['mean_seconds']:.1f}s "
        f"median={critical_paths['median_seconds']:.1f}s "
        f"p90={critical_paths['p90_seconds']:.1f}s"
    )

    print("\nFAILURES")
    if report["failures"]:
        for node, count in sorted(
            report["failures"].items(),
            key=lambda item: (-item[1], item[0]),
        ):
            print(f"{count} {node}")
    else:
        print("none")

    print("\nTOP TEST CANDIDATES")
    for row in report["tests"][:top]:
        print(
            f"save50={row['mean_critical_saving_50_seconds']:.1f}s "
            f"upper={row['mean_critical_saving_100_seconds']:.1f}s "
            f"median={row['median_seconds']:.1f}s "
            f"p90={row['p90_seconds']:.1f}s "
            f"critical={row['critical_exposure']} {row['node']}"
        )

    print("\nIMAGES")
    for row in report["images"]:
        print(
            f"median={row['median_seconds']:.1f}s "
            f"p90={row['p90_seconds']:.1f}s "
            f"n={row['samples']} {row['image']}"
        )

    print("\nPARALLEL IMAGE OVERLAP")
    if report["parallel_image_overlaps"]:
        for row in report["parallel_image_overlaps"]:
            print(
                f"{row['sample']} {row['lane']}: "
                f"sum={row['image_sum_seconds']:.1f}s "
                f"batch={row['batch_seconds']:.1f}s "
                f"overlap={row['overlap_seconds']:.1f}s"
            )
    else:
        print("none")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument(
        "--cohort",
        choices=("baseline", "experiment"),
        required=True,
    )
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    report = analyze(load_samples(args.samples_root, args.cohort), args.cohort)
    _print_report(report, args.top)
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
