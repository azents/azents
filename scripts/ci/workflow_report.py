"""Decode GitHub CI metadata and report job/step walls without reading logs."""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

GATES = frozenset(
    {
        "ci-pre-commit",
        "ci-python",
        "ci-python-e2e",
        "ci-typescript",
        "ci-helm",
        "ci-docker-build",
        "ios-quality-build",
    }
)
REPORT_JOB = "ci-observability"


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("Expected a JSON object")
    return value


def text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a string")
    return value


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a list")
    return value


def integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("Expected a positive integer")
    return value


def timestamp(value: object) -> datetime | None:
    if value is None or value == "" or value == "0001-01-01T00:00:00Z":
        return None
    parsed = datetime.fromisoformat(text(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("CI timestamps must carry a timezone")
    return parsed


@dataclass(frozen=True)
class Step:
    name: str
    conclusion: str
    started: datetime | None
    completed: datetime | None

    @property
    def wall(self) -> float | None:
        if self.started is None or self.completed is None:
            return None
        duration = (self.completed - self.started).total_seconds()
        if duration < 0:
            raise ValueError("Negative CI duration")
        return duration


@dataclass(frozen=True)
class Job:
    name: str
    status: str
    conclusion: str
    started: datetime | None
    completed: datetime | None
    steps: tuple[Step, ...]

    @property
    def wall(self) -> float | None:
        if self.conclusion == "skipped":
            return None
        return Step(self.name, self.conclusion, self.started, self.completed).wall


@dataclass(frozen=True)
class Run:
    run_id: int
    attempt: int
    head_sha: str
    workflow_name: str
    event: str
    head_branch: str
    status: str
    conclusion: str
    created: datetime
    jobs: tuple[Job, ...]


def decode_run(value: object) -> Run:
    """Project GitHub's extensible response into only the fields we observe."""
    raw = object_value(value)
    jobs = []
    for item in sequence(raw["jobs"]):
        job = object_value(item)
        steps = []
        for entry in sequence(job["steps"]):
            step = object_value(entry)
            steps.append(
                Step(
                    text(step["name"]),
                    text(step["conclusion"]),
                    timestamp(step.get("startedAt")),
                    timestamp(step.get("completedAt")),
                )
            )
        jobs.append(
            Job(
                text(job["name"]),
                text(job["status"]),
                text(job["conclusion"]),
                timestamp(job.get("startedAt")),
                timestamp(job.get("completedAt")),
                tuple(steps),
            )
        )
    names = [j.name for j in jobs]
    if len(set(names)) != len(names):
        raise ValueError("Ambiguous duplicate CI job names")
    created = timestamp(raw["createdAt"])
    if created is None:
        raise ValueError("Missing workflow creation timestamp")
    sha = text(raw["headSha"])
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Invalid workflow SHA")
    return Run(
        integer(raw["databaseId"]),
        integer(raw["attempt"]),
        sha,
        text(raw["workflowName"]),
        text(raw["event"]),
        text(raw["headBranch"]),
        text(raw["status"]),
        text(raw["conclusion"]),
        created,
        tuple(jobs),
    )


def metrics(run: Run) -> dict[str, object]:
    """Keep dependency/queue-inclusive gate elapsed separate from parallel max."""
    gates = [j for j in run.jobs if j.name in GATES]
    complete = bool(gates) and all(
        j.status == "completed" and j.completed is not None for j in gates
    )
    finishes = [j.completed for j in gates if j.completed is not None]
    elapsed = (max(finishes) - run.created).total_seconds() if complete else None
    walls = {
        j.name: j.wall for j in run.jobs if j.name != REPORT_JOB and j.wall is not None
    }
    e2e = {
        name: wall
        for name, wall in walls.items()
        if name.startswith("ci-e2e-") and name.rsplit("-", 1)[-1].isdigit()
    }
    success = (
        run.status == "completed"
        and run.conclusion == "success"
        and complete
        and all(j.conclusion == "success" for j in gates)
    )
    return {
        "workflow_run_id": run.run_id,
        "workflow_attempt": run.attempt,
        "head_sha": run.head_sha,
        "workflow_name": run.workflow_name,
        "event": run.event,
        "head_branch": run.head_branch,
        "created_at_utc": run.created.isoformat(),
        "workflow_conclusion": run.conclusion,
        "performance_eligible": success,
        "gate_completion_elapsed_seconds": elapsed,
        "gate_completion_semantics": (
            "workflow creation to last configured gate completion; includes "
            "dependency scheduling and queues, not a causal DAG estimate"
        ),
        "job_wall_seconds": walls,
        "job_conclusions": {j.name: j.conclusion for j in run.jobs},
        "enabled_scope": sorted(
            j.name
            for j in run.jobs
            if j.name != REPORT_JOB and j.conclusion != "skipped"
        ),
        "maximum_job_wall_seconds": max(walls.values()) if walls else None,
        "runner_job_seconds": sum(w for w in walls.values() if w is not None),
        "observability_job_seconds": sum(
            j.wall or 0 for j in run.jobs if j.name == REPORT_JOB
        ),
        "e2e_lane_critical_seconds": max(e2e.values()) if e2e else None,
    }


def render(run: Run) -> str:
    data = metrics(run)
    lines = [
        "## CI observability",
        "",
        f"Commit: `{run.head_sha}` · Run {run.run_id} · Attempt {run.attempt}",
        "",
        (
            "[Workflow run and full artifacts](https://github.com/"
            f"${{REPOSITORY}}/actions/runs/{run.run_id}/attempts/{run.attempt})"
        ),
        "",
        (
            f"Gate completion elapsed: **{data['gate_completion_elapsed_seconds']}s** "
            "(workflow creation to last gate, including dependency scheduling/queues)."
        ),
        (
            f"Completed job runner time: **{data['runner_job_seconds']} job-seconds**; "
            f"maximum job wall: **{data['maximum_job_wall_seconds']}s**. "
            "Observability job overhead is separate."
        ),
        "",
        (
            "Job/step wall time is not test-call time. Missing, skipped and "
            "running jobs are not zero-duration successes."
        ),
        "",
        "<details>",
        "<summary>All CI jobs and slowest steps</summary>",
        "",
        "| Job | Result | Wall seconds |",
        "| --- | --- | ---: |",
    ]
    for job in run.jobs:
        wall = job.wall
        lines.append(
            f"| {html.escape(job.name)} | "
            f"{html.escape(job.conclusion or job.status)} | "
            f"{wall if wall is not None else 'unavailable'} |"
        )
    steps = sorted(
        (
            (s.wall, j.name, s.name)
            for j in run.jobs
            for s in j.steps
            if s.wall is not None
        ),
        reverse=True,
    )
    lines += ["", "| Job / step | Wall seconds |", "| --- | ---: |"]
    for wall, job, step in steps[:25]:
        lines.append(f"| {html.escape(job)} / {html.escape(step)} | {wall} |")
    lines += ["", "</details>", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    run = decode_run(json.loads(args.run.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(run).replace("${REPOSITORY}", args.repository))
    args.output.with_suffix(".json").write_text(
        json.dumps(metrics(run), indent=2) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
