"""Append verified analysis records to a durable, deduplicated CI history."""

import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

from scripts.ci.workflow_report import integer, object_value, sequence, text


@dataclass(frozen=True)
class HistoryRecord:
    """Validated decision fields plus an opaque full report for lossless replay."""

    workflow_name: str
    run_id: int
    attempt: int
    cohort: str
    event: str
    head_branch: str
    created_at: str
    report: dict[str, object]

    @property
    def key(self) -> tuple[str, int, int, str]:
        return self.workflow_name, self.run_id, self.attempt, self.cohort

    @property
    def order(self) -> tuple[str, str, str, str]:
        return self.created_at, self.workflow_name, str(self.run_id), str(self.attempt)

    def for_cohort(self, cohort: str) -> HistoryRecord:
        return replace(self, cohort=cohort, report={**self.report, "cohort": cohort})


def decode_record(value: object, *, cohort: str | None = None) -> HistoryRecord:
    """Decode interpreted fields; remaining metric/extension values round-trip."""
    raw = object_value(value)
    return HistoryRecord(
        workflow_name=text(raw["workflow_name"]),
        run_id=integer(raw["workflow_run_id"]),
        attempt=integer(raw["workflow_attempt"]),
        cohort=text(raw["cohort"]) if cohort is None else cohort,
        event=text(raw["event"]),
        head_branch=text(raw["head_branch"]),
        created_at=text(raw["created_at_utc"]),
        report=raw,
    )


@dataclass(frozen=True)
class AnalysisHistory:
    cohort: str
    records: tuple[HistoryRecord, ...]


def decode_analysis(value: object) -> AnalysisHistory:
    raw = object_value(value)
    cohort = text(raw["cohort"])
    return AnalysisHistory(
        cohort=cohort,
        # Incoming record cohorts are replaced at append, not independently required.
        records=tuple(
            decode_record(r, cohort=cohort) for r in sequence(raw["records"])
        ),
    )


def append(analysis_path: Path, history: Path, cohort: str) -> int:
    analysis = decode_analysis(json.loads(analysis_path.read_text()))
    if cohort == "main" and analysis.cohort != "baseline":
        raise ValueError("Only baseline analysis may extend real main history")
    if cohort == "experiment" and analysis.cohort != "experiment":
        raise ValueError("Experiment history requires experiment analysis")
    existing = (
        [
            decode_record(json.loads(line))
            for line in history.read_text().splitlines()
            if line
        ]
        if history.exists()
        else []
    )
    by_key = {row.key: row for row in existing}
    for record in analysis.records:
        if cohort == "main" and (
            record.event != "push" or record.head_branch != "main"
        ):
            raise ValueError("Non-main CI attempt cannot enter main trend history")
        selected = record.for_cohort(cohort)
        if selected.key in by_key:
            stored = by_key[selected.key]
            # The local collection directory is a locator, not run evidence.
            # Keep the first locator while comparing every other opaque field.
            original = {k: v for k, v in stored.report.items() if k != "source"}
            incoming = {k: v for k, v in selected.report.items() if k != "source"}
            if original != incoming:
                raise ValueError("Conflicting evidence for an existing CI attempt")
            continue
        by_key[selected.key] = selected
    history.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(by_key.values(), key=lambda row: row.order)
    temporary = history.with_suffix(history.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row.report, sort_keys=True) + "\n" for row in ordered)
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
