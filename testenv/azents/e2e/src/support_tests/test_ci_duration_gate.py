"""Focused tests for the compact E2E duration gate."""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from support.ci_duration_gate import (
    EvidenceError,
    Sample,
    compare,
    evaluate,
    load_lanes,
    recheck,
    render,
)

_HEAD = "a" * 40
_BASE = "b" * 40


def _lane_files(directory: Path, lane: str, value: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    records = [
        {
            "record_type": "test_phase",
            "node_id": f"tests::{lane}",
            "phase": phase,
            "duration_seconds": duration,
            "outcome": "passed",
        }
        for phase, duration in (("setup", 10), ("call", value), ("teardown", 2))
    ]
    (directory / "pytest-timings.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records) + "\n",
        encoding="utf-8",
    )
    (directory / "junit.xml").write_text(
        f'<testsuite><testcase classname="tests" name="{lane}"/></testsuite>',
        encoding="utf-8",
    )
    (directory / "lane-duration-seconds.txt").write_text("999", encoding="utf-8")


def _lanes(root: Path, values: dict[str, str]) -> None:
    for lane, value in values.items():
        _lane_files(root / f"e2e-observability-{lane}", lane, value)


def test_uses_maximum_and_fails_exact_twenty_percent() -> None:
    result = compare(
        {"required-1": Decimal("99"), "web-1": Decimal("120")},
        Sample(7, {"required-1": Decimal("100"), "web-1": Decimal("100")}),
        _HEAD,
        _BASE,
    )
    assert result["outcome"] == "regression"
    assert result["critical_lane"] == "web-1"
    assert result["threshold_seconds"] == "120"


def test_call_phase_is_the_measurement_source(tmp_path: Path) -> None:
    _lanes(tmp_path, {"required-1": "315\n", "web-1": "367\n"})
    evidence = load_lanes(tmp_path)
    assert evidence.lanes == {
        "required-1": Decimal("315"),
        "web-1": Decimal("367"),
    }
    assert evidence.diagnostics["required-1"] == {
        "setup": Decimal("10"),
        "call": Decimal("315"),
        "teardown": Decimal("2"),
        "wall": Decimal("999"),
    }


def test_single_downloaded_artifact_uses_summary_lane(tmp_path: Path) -> None:
    _lane_files(tmp_path, "web-1", "367")
    (tmp_path / "summary.md").write_text(
        "### web-1 — ✅ Passed\n",
        encoding="utf-8",
    )
    evidence = load_lanes(tmp_path)
    assert evidence.lanes == {"web-1": Decimal("367")}
    assert evidence.diagnostics["web-1"]["wall"] == Decimal("999")


@pytest.mark.parametrize(
    "summary",
    [
        "",
        "### web-1 — ✅ Passed\n### web-2 — ✅ Passed\n",
    ],
)
def test_single_downloaded_artifact_requires_one_summary_lane(
    tmp_path: Path,
    summary: str,
) -> None:
    _lane_files(tmp_path, "web-1", "367")
    (tmp_path / "summary.md").write_text(summary, encoding="utf-8")
    with pytest.raises(EvidenceError, match="invalid_lane_artifacts"):
        load_lanes(tmp_path)


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-1"])
def test_invalid_duration_fails_closed(tmp_path: Path, value: str) -> None:
    _lanes(tmp_path, {"required-1": value})
    with pytest.raises(EvidenceError):
        load_lanes(tmp_path)


def test_missing_or_duplicate_call_timing_fails_closed(tmp_path: Path) -> None:
    _lanes(tmp_path, {"required-1": "10"})
    timing_path = tmp_path / "e2e-observability-required-1" / "pytest-timings.jsonl"
    records = timing_path.read_text(encoding="utf-8").splitlines()
    timing_path.write_text(
        "\n".join(record for record in records if '"phase": "call"' not in record),
        encoding="utf-8",
    )
    with pytest.raises(EvidenceError, match="incomplete_call_timing"):
        load_lanes(tmp_path)

    _lanes(tmp_path, {"required-1": "10"})
    records = timing_path.read_text(encoding="utf-8").splitlines()
    call = next(record for record in records if '"phase": "call"' in record)
    timing_path.write_text("\n".join((*records, call)) + "\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="invalid_test_phase_timing"):
        load_lanes(tmp_path)


def test_evaluate_skips_incomplete_base_runs(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _lanes(current, {"required-1": "100", "web-1": "100"})

    def command(args: Sequence[str]) -> str:
        joined = " ".join(args)
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps({"workflow_runs": [{"id": 10}, {"id": 9}]})
        if "gh run download 10" in joined:
            _lanes(tmp_path / "work/run-10", {"required-1": "100"})
            return ""
        if "gh run download 9" in joined:
            _lanes(
                tmp_path / "work/run-9",
                {"required-1": "100", "web-1": "100"},
            )
            return ""
        raise AssertionError(args)

    report = evaluate(
        current, "azents/azents", _BASE, _HEAD, 11, tmp_path / "work", command
    )
    assert report["outcome"] == "pass"
    assert report["base_run_id"] == 9
    diagnostics = report["lane_diagnostics"]
    assert isinstance(diagnostics, dict)
    required = diagnostics["required-1"]
    assert isinstance(required, dict)
    assert required["wall"] == "999"


def test_missing_base_evidence_reports_failure_with_current_time(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    _lanes(current, {"web-1": "123"})

    def command(args: Sequence[str]) -> str:
        return json.dumps({"workflow_runs": []})

    report = evaluate(
        current, "azents/azents", _BASE, _HEAD, 11, tmp_path / "work", command
    )
    assert report["outcome"] == "comparison_unavailable"
    assert report["observed_seconds"] == "123"
    assert "compatible_base_run_unavailable" in str(report["reason"])


def test_markdown_keeps_summary_visible_and_evidence_collapsed() -> None:
    report = compare(
        {"web-1": Decimal("90")},
        Sample(7, {"web-1": Decimal("100")}),
        _HEAD,
        _BASE,
    )
    markdown = render(report)
    visible = markdown.split("<details>", 1)[0]
    assert "✅ Within limit" in visible
    assert "Candidate test `90s` · Base test `100s`" in visible
    assert "Change `-10%` · Limit `120s`" in visible
    assert _HEAD not in visible
    assert "<summary>Details</summary>" in markdown
    assert "<summary>Raw JSON</summary>" in markdown
    assert markdown.count("<details>") == markdown.count("</details>") == 2


def test_regression_and_unavailable_are_explained_in_plain_language() -> None:
    regression = compare(
        {"web-1": Decimal("121")},
        Sample(7, {"web-1": Decimal("100")}),
        _HEAD,
        _BASE,
    )
    unavailable_report = {
        **regression,
        "outcome": "comparison_unavailable",
        "reason": "compatible_base_run_unavailable",
        "reference_seconds": None,
        "threshold_seconds": None,
        "increase_percent": None,
    }

    assert "❌ Over 20% limit" in render(regression)
    assert "Candidate test `121s` · Base test `100s`" in render(regression)
    unavailable_markdown = render(unavailable_report)
    assert "⚠️ Comparison unavailable" in unavailable_markdown
    assert "Base timing artifact unavailable" in unavailable_markdown


def test_recheck_uses_latest_candidate_values_with_new_base(tmp_path: Path) -> None:
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            return json.dumps({"head": {"sha": _HEAD}, "base": {"sha": _BASE}})
        if f"head_sha={_HEAD}" in joined:
            return json.dumps({"workflow_runs": [{"id": 20}]})
        if "gh run download 20" in joined and "e2e-duration-gate" in joined:
            path = tmp_path / "candidate-20/report.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"head_sha": _HEAD, "lanes": {"web-1": "109"}}),
                encoding="utf-8",
            )
            return ""
        if f"head_sha={_BASE}" in joined:
            return json.dumps({"workflow_runs": [{"id": 19}]})
        if "gh run download 19" in joined:
            _lanes(tmp_path / "base/run-19", {"web-1": "100"})
            return ""
        if "--method POST" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)
    assert "pass" in summary
    assert any("state=success" in item for item in posts[0])
    assert any(f"description=base={_BASE[:7]} pass" in item for item in posts[0])


def test_recheck_skips_prs_without_duration_evidence(tmp_path: Path) -> None:
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            return json.dumps({"head": {"sha": _HEAD}, "base": {"sha": _BASE}})
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps({"workflow_runs": []})
        if "--method POST" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)
    assert "no duration evidence" in summary
    assert posts == []
