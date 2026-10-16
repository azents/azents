"""Render a fixed 30-KST-day whole-CI chart from exact real main records."""

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from scripts.ci.workflow_report import object_value, text


@dataclass(frozen=True)
class HistoryPoint:
    date_kst: str
    eligible: bool
    elapsed: float | None


@dataclass(frozen=True)
class Day:
    date_kst: str
    n: int
    excluded: int
    mean: float | None
    median: float | None
    minimum: float | None
    maximum: float | None


def decode_history(value: object, workflow: str) -> HistoryPoint | None:
    """Accept general-CI main records, never infer them from old E2E rows."""
    raw = object_value(value)
    if raw["cohort"] != "main" or raw["workflow_name"] != workflow:
        return None
    elapsed = raw["gate_completion_elapsed_seconds"]
    if elapsed is not None and (
        isinstance(elapsed, bool)
        or not isinstance(elapsed, int | float)
        or not math.isfinite(elapsed)
        or elapsed < 0
    ):
        raise ValueError("Invalid gate elapsed duration")
    eligible = raw["performance_eligible"]
    if not isinstance(eligible, bool):
        raise ValueError("Invalid eligibility")
    day = text(raw["date_kst"])
    date.fromisoformat(day)
    return HistoryPoint(day, eligible, float(elapsed) if elapsed is not None else None)


def daily(records: list[HistoryPoint], report_date: date) -> list[Day]:
    days = []
    for offset in range(30):
        day = (report_date - timedelta(days=29 - offset)).isoformat()
        observed = [r for r in records if r.date_kst == day]
        values = [r.elapsed for r in observed if r.eligible and r.elapsed is not None]
        days.append(
            Day(
                day,
                len(values),
                len(observed) - len(values),
                statistics.mean(values) if values else None,
                statistics.median(values) if values else None,
                min(values) if values else None,
                max(values) if values else None,
            )
        )
    return days


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workflow", required=True)
    args = parser.parse_args()
    # Plotting uses the optional ci-report dependency group, not test producers.
    import matplotlib.pyplot as plt  # noqa: PLC0415 -- optional reporting dependency

    records = [
        point
        for line in args.history.read_text().splitlines()
        if line
        and (point := decode_history(json.loads(line), args.workflow)) is not None
    ]
    days = daily(records, args.date)
    x = list(range(30))
    fig, ax = plt.subplots(figsize=(15, 7.5), dpi=160)
    ax.fill_between(
        x,
        [d.minimum if d.minimum is not None else math.nan for d in days],
        [d.maximum if d.maximum is not None else math.nan for d in days],
        alpha=0.2,
        label="Main min–max",
    )
    ax.plot(
        x,
        [d.mean if d.mean is not None else math.nan for d in days],
        marker="o",
        label="Main mean",
    )
    ax.plot(
        x,
        [d.median if d.median is not None else math.nan for d in days],
        marker="s",
        label="Main median",
    )
    for i, point in enumerate(days):
        if point.maximum is not None:
            ax.annotate(f"n={point.n}", (i, point.maximum), fontsize=7)
        else:
            ax.annotate(
                "failed/unverified" if point.excluded else "missing",
                (i, 0.02),
                xycoords=("data", "axes fraction"),
                rotation=90,
                fontsize=7,
            )
        if point.excluded:
            ax.annotate(
                f"x={point.excluded}",
                (i, 0.15),
                xycoords=("data", "axes fraction"),
                fontsize=7,
                color="red",
            )
    ax.set_title(
        f"Whole CI gate completion | {days[0].date_kst} – {days[-1].date_kst} KST\n"
        "Lower is faster; workflow creation to gates (dependencies/queues included). "
        "Missing and failed dates are not interpolated."
    )
    ax.set_ylabel("Seconds (lower is faster)")
    ax.set_xticks(x, [d.date_kst[5:] for d in days], rotation=55)
    ax.legend()
    ax.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    fig.savefig(args.output)
    plt.close(fig)
    args.output.with_suffix(".json").write_text(
        json.dumps(
            {
                "days": [asdict(d) for d in days],
                "metric": "gate_completion_elapsed_seconds",
                "calendar_days": 30,
                "historical_e2e_not_relabelled": True,
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
