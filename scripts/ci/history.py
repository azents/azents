"""Append verified analysis records to a durable, deduplicated CI history."""

import argparse
import json
from pathlib import Path

from scripts.ci.workflow_report import object_value, sequence, text


def append(analysis_path: Path, history: Path, cohort: str) -> int:
    analysis = object_value(json.loads(analysis_path.read_text()))
    if cohort == "main" and analysis["cohort"] != "baseline":
        raise ValueError("Only baseline analysis may extend real main history")
    if cohort == "experiment" and analysis["cohort"] != "experiment":
        raise ValueError("Experiment history requires experiment analysis")
    records = [object_value(r) for r in sequence(analysis["records"])]
    existing = (
        [
            object_value(json.loads(line))
            for line in history.read_text().splitlines()
            if line
        ]
        if history.exists()
        else []
    )

    def key(row: dict[str, object]) -> tuple[object, object, object, object]:
        return (
            row["workflow_name"],
            row["workflow_run_id"],
            row["workflow_attempt"],
            row["cohort"],
        )

    by_key = {key(row): row for row in existing}
    for record in records:
        if cohort == "main" and (
            record["event"] != "push" or record["head_branch"] != "main"
        ):
            raise ValueError("Non-main CI attempt cannot enter main trend history")
        record["cohort"] = cohort
        record_key = key(record)
        if record_key in by_key and by_key[record_key] != record:
            raise ValueError("Conflicting evidence for an existing CI attempt")
        by_key[record_key] = record
    history.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(
        by_key.values(),
        key=lambda r: (
            text(r["created_at_utc"]),
            text(r["workflow_name"]),
            str(r["workflow_run_id"]),
            str(r["workflow_attempt"]),
        ),
    )
    temporary = history.with_suffix(history.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in ordered)
    )
    temporary.replace(history)
    return len(ordered)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--cohort", choices=["main", "experiment"], required=True)
    args = parser.parse_args()
    append(args.analysis, args.history, args.cohort)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
