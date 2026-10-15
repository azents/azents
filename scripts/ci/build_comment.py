"""Combine bounded safe CI summaries without exceeding GitHub comment limits."""

import argparse
import json
from pathlib import Path

from scripts.ci.analyze import expected_test_artifacts
from scripts.ci.workflow_report import Run, decode_run

LIMIT = 60_000


def combine(workflow: str, duration: str | None, summaries: list[str]) -> str:
    parts = [workflow]
    if duration is not None:
        parts.append(duration)
    parts.append("\n## Test results\n")
    if not summaries:
        parts.append(
            "Test evidence unavailable; inspect workflow job results. "
            "No test success is inferred.\n"
        )
    for index, summary in enumerate(summaries):
        # Reserve space for terse status lines of all remaining test producers.
        remaining_budget = (
            LIMIT - sum(len(p) for p in parts) - 2_000 - 300 * (len(summaries) - index)
        )
        if len(summary) <= remaining_budget:
            parts.append(summary)
        else:
            heading = summary.split("<details>", 1)[0]
            parts.append(
                heading[:1000] + "\nDetailed timing omitted from this bounded comment; "
                "use workflow artifacts.\n"
            )
    parts.append("\nThis comment is updated in place for each CI run.\n")
    output = "\n".join(parts)
    if len(output) > LIMIT:
        raise ValueError("CI report exceeds the safe comment budget")
    return output


def producer_summaries(run: Run, roots: list[Path]) -> list[str]:
    """Account explicitly for every enabled producer, including missing uploads."""
    found: dict[str, str] = {}
    for root in roots:
        for path in sorted(root.glob("*/summary.md")):
            name = path.parent.name
            if name.startswith("e2e-observability-"):
                identity = "e2e-" + name.removeprefix("e2e-observability-")
            elif name.startswith("ci-observability-") and name.endswith(
                f"-{run.attempt}"
            ):
                identity = name.removeprefix("ci-observability-").rsplit("-", 1)[0]
            else:
                continue
            found[identity] = path.read_text()
    summaries = []
    for identity in sorted(expected_test_artifacts(run) | set(found)):
        summaries.append(
            found.get(identity)
            or f"### {identity} — ⚠️ Results unavailable\n\n"
            "Expected test evidence was not uploaded or could not be downloaded. "
            "Job success is not proof of available test evidence.\n"
        )
    return summaries


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--duration", type=Path, required=True)
    parser.add_argument("--test-roots", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = decode_run(json.loads(args.run.read_text()))
    summaries = producer_summaries(run, args.test_roots)
    args.output.write_text(
        combine(
            args.workflow.read_text(),
            args.duration.read_text() if args.duration.is_file() else None,
            summaries,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
