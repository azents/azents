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


def _lanes(root: Path, values: dict[str, str]) -> None:
    for lane, value in values.items():
        path = root / f"e2e-observability-{lane}" / "lane-duration-seconds.txt"
        path.parent.mkdir(parents=True)
        path.write_text(value, encoding="utf-8")


def test_uses_maximum_and_fails_exact_ten_percent() -> None:
    result = compare(
        {"required-1": Decimal("99"), "web-1": Decimal("110")},
        Sample(7, {"required-1": Decimal("100"), "web-1": Decimal("100")}),
        _HEAD,
        _BASE,
    )
    assert result["outcome"] == "regression"
    assert result["critical_lane"] == "web-1"
    assert result["threshold_seconds"] == "110"


def test_raw_lane_files_are_the_measurement_source(tmp_path: Path) -> None:
    _lanes(tmp_path, {"required-1": "315\n", "web-1": "367\n"})
    assert load_lanes(tmp_path) == {
        "required-1": Decimal("315"),
        "web-1": Decimal("367"),
    }


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-1"])
def test_invalid_duration_fails_closed(tmp_path: Path, value: str) -> None:
    _lanes(tmp_path, {"required-1": value})
    with pytest.raises(EvidenceError):
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
    assert "PASS" in visible
    assert "candidate `90s` vs base `100s`" in visible
    assert _HEAD not in visible
    assert markdown.count("<details>") == markdown.count("</details>") == 1


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
