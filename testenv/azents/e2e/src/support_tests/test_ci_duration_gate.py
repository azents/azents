"""Focused tests for the compact E2E duration gate."""

import json
import subprocess
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pytest

from support import ci_duration_gate
from support.ci_duration_gate import (
    CandidateTiming,
    DurationReport,
    EvidenceError,
    InvalidCandidateTiming,
    Sample,
    _candidate_report,
    _decode_candidate,
    _decode_comments,
    _decode_pull_text,
    _decode_runs,
    _decode_test_phase,
    affected_pull_numbers,
    compare,
    evaluate,
    load_lanes,
    main,
    recheck,
    render,
)

_HEAD = "a" * 40
_BASE = "b" * 40


@pytest.mark.parametrize(
    ("completed_sha", "expected"),
    [
        (_BASE, (2020, 2026)),
        (_HEAD, (2026, 2028)),
        ("d" * 40, (2020, 2031)),
        ("f" * 40, ()),
    ],
)
def test_completed_sha_selects_candidate_and_stacked_dependents(
    completed_sha: str, expected: tuple[int, ...]
) -> None:
    def row(
        number: int, head_sha: str, base_sha: str, repository: str
    ) -> dict[str, object]:
        return {
            "number": number,
            "state": "open",
            "head": {"sha": head_sha, "repo": {"full_name": repository}},
            "base": {"sha": base_sha},
        }

    pages = [
        [
            row(2020, _BASE, "d" * 40, "azents/azents"),
            row(2031, "e" * 40, "d" * 40, "azents/azents"),
        ],
        [
            row(2026, _HEAD, _BASE, "azents/azents"),
            row(2028, "c" * 40, _HEAD, "azents/azents"),
            row(77, _BASE, _BASE, "someone/fork"),
            {**row(78, _BASE, _BASE, "azents/azents"), "state": "closed"},
        ],
    ]

    def command(args: Sequence[str]) -> str:
        assert list(args) == [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            "repos/azents/azents/pulls?state=open&per_page=100",
        ]
        return json.dumps(pages)

    assert affected_pull_numbers("azents/azents", completed_sha, command) == expected


def test_targets_cli_emits_dependent_pull_numbers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = [
        [
            {
                "number": 2026,
                "state": "open",
                "head": {"sha": _HEAD, "repo": {"full_name": "azents/azents"}},
                "base": {"sha": _BASE},
            }
        ]
    ]
    assert (
        main(
            ["targets", "--repository", "azents/azents", "--completed-sha", _BASE],
            command_runner=lambda args: json.dumps(payload),
        )
        == 0
    )
    assert capsys.readouterr().out == "2026\n"


def test_target_selection_rejects_invalid_sha_before_listing() -> None:
    def command(args: Sequence[str]) -> str:
        raise AssertionError("Invalid completion events must not query GitHub.")

    with pytest.raises(EvidenceError, match="completed_sha_unavailable"):
        affected_pull_numbers("azents/azents", "invalid", command)


@pytest.mark.parametrize("valid_conclusion", ["success", "failure"])
def test_candidate_skips_cancelled_duplicate_without_hiding_failures(
    tmp_path: Path, valid_conclusion: str
) -> None:
    """Cancelled diagnostics cannot supersede real same-head evidence."""
    downloads: list[int] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if f"head_sha={_HEAD}" in joined:
            return json.dumps(
                {
                    "workflow_runs": [
                        {"id": 30, "status": "completed", "conclusion": "cancelled"},
                        {
                            "id": 20,
                            "status": "completed",
                            "conclusion": valid_conclusion,
                        },
                    ]
                }
            )
        if "gh run download 20" in joined:
            downloads.append(20)
            destination = Path(values[values.index("--dir") + 1])
            destination.mkdir(parents=True)
            (destination / "report.json").write_text(
                json.dumps({"head_sha": _HEAD, "lanes": {"web-1": "109"}}),
                encoding="utf-8",
            )
            return ""
        raise AssertionError(values)

    candidate = _candidate_report("azents/azents", _HEAD, tmp_path, command)

    assert candidate.run_id == 20
    assert downloads == [20]


def test_cancelled_candidate_inventory_has_no_validation_evidence(
    tmp_path: Path,
) -> None:
    """Cancellation alone never fabricates a valid candidate or a pass."""

    def command(args: Sequence[str]) -> str:
        if f"head_sha={_HEAD}" in " ".join(args):
            return json.dumps(
                {
                    "workflow_runs": [
                        {"id": 30, "status": "completed", "conclusion": "cancelled"}
                    ]
                }
            )
        raise AssertionError(list(args))

    with pytest.raises(EvidenceError, match="candidate_evidence_unavailable"):
        _candidate_report("azents/azents", _HEAD, tmp_path, command)


def _pull(head_repository: str = "azents/azents") -> str:
    return json.dumps(
        {
            "head": {"sha": _HEAD, "repo": {"full_name": head_repository}},
            "base": {"sha": _BASE},
        }
    )


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


def test_missing_base_evidence_reports_neutral_with_current_time(
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
    assert "⚠️ Comparison unavailable" in render(report)


def test_terminal_missing_base_publishes_success(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _lanes(current, {"web-1": "123"})
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps({"workflow_runs": []})
        if "/statuses/" in joined and "--method POST" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    exit_code = main(
        [
            "gate",
            "--artifacts-root",
            str(current),
            "--repository",
            "azents/azents",
            "--base-sha",
            _BASE,
            "--head-sha",
            _HEAD,
            "--run-id",
            "11",
            "--work-dir",
            str(tmp_path / "work"),
            "--report-json",
            str(tmp_path / "report.json"),
            "--report-markdown",
            str(tmp_path / "summary.md"),
            "--publish-status",
        ],
        command_runner=command,
    )

    assert exit_code == 0
    assert any("state=success" in item for item in posts[0])
    assert "⚠️ Comparison unavailable" in (tmp_path / "summary.md").read_text()


def test_active_base_workflow_is_reported_with_its_link(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _lanes(current, {"web-1": "123"})
    run_url = "https://github.com/azents/azents/actions/runs/10"

    def command(args: Sequence[str]) -> str:
        joined = " ".join(args)
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps(
                {
                    "workflow_runs": [
                        {"id": 10, "status": "in_progress", "html_url": run_url}
                    ]
                }
            )
        if "gh run download 10" in joined:
            raise EvidenceError("github_evidence_unavailable")
        raise AssertionError(args)

    report = evaluate(
        current, "azents/azents", _BASE, _HEAD, 11, tmp_path / "work", command
    )

    assert report["outcome"] == "comparison_unavailable"
    assert report["reason"] == "base_workflow_running"
    assert report["base_run_id"] == 10
    assert report["base_run_status"] == "in_progress"
    assert report["base_run_url"] == run_url
    markdown = render(report)
    assert "Base CI is still running" in markdown
    assert f"[workflow run 10]({run_url})" in markdown


def test_invalid_candidate_evidence_remains_a_failure(tmp_path: Path) -> None:
    current = tmp_path / "current"
    _lanes(current, {"web-1": "123"})
    timing_path = current / "e2e-observability-web-1" / "pytest-timings.jsonl"
    timing_path.write_text("", encoding="utf-8")

    report = evaluate(
        current,
        "azents/azents",
        _BASE,
        _HEAD,
        11,
        tmp_path / "work",
        lambda args: "",
    )

    assert report["outcome"] == "evidence_invalid"
    assert "Candidate timing invalid" in render(report)


def test_gate_publishes_pending_without_failing_for_active_base(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    _lanes(current, {"web-1": "123"})
    run_url = "https://github.com/azents/azents/actions/runs/10"
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps(
                {
                    "workflow_runs": [
                        {"id": 10, "status": "in_progress", "html_url": run_url}
                    ]
                }
            )
        if "gh run download 10" in joined:
            raise EvidenceError("github_evidence_unavailable")
        if "/statuses/" in joined and "--method POST" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    exit_code = main(
        [
            "gate",
            "--artifacts-root",
            str(current),
            "--repository",
            "azents/azents",
            "--base-sha",
            _BASE,
            "--head-sha",
            _HEAD,
            "--run-id",
            "11",
            "--work-dir",
            str(tmp_path / "work"),
            "--report-json",
            str(tmp_path / "report.json"),
            "--report-markdown",
            str(tmp_path / "summary.md"),
            "--publish-status",
        ],
        command_runner=command,
    )

    assert exit_code == 0
    assert any("state=pending" in item for item in posts[0])
    assert any(f"target_url={run_url}" in item for item in posts[0])


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
    unavailable_report: DurationReport = {
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
    statuses: list[list[str]] = []
    patches: list[list[str]] = []
    comment_reads: list[list[str]] = []
    existing_body = "\n".join(
        [
            "## E2E CI observability",
            "",
            "## E2E duration",
            "",
            "old result",
            "",
            "### required-1 — ✅ Passed",
            "",
            "<!-- Sticky Pull Request Commente2e-observability -->",
        ]
    )

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            return _pull()
        if f"head_sha={_HEAD}" in joined:
            return json.dumps({"workflow_runs": [{"id": 20}]})
        if "gh run download 20" in joined and "e2e-duration-gate" in joined:
            path = tmp_path / "candidate-20/report.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "head_sha": _HEAD,
                        "lanes": {"web-1": "109"},
                        "lane_diagnostics": {
                            "web-1": {
                                "call": "109",
                                "setup": "10",
                                "teardown": "2",
                                "wall": "130",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            return ""
        if f"head_sha={_BASE}" in joined:
            return json.dumps({"workflow_runs": [{"id": 19}]})
        if "gh run download 19" in joined:
            _lanes(tmp_path / "base/run-19", {"web-1": "100"})
            return ""
        if "/statuses/" in joined and "--method POST" in joined:
            statuses.append(values)
            return ""
        if joined.endswith("issues/3/comments?per_page=100"):
            comment_reads.append(values)
            return json.dumps([[{"id": 42, "body": existing_body}]])
        if "/issues/comments/42" in joined and "--method PATCH" in joined:
            patches.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)

    assert "pass" in summary
    assert "--paginate" in comment_reads[0]
    assert "--slurp" in comment_reads[0]
    assert any("state=success" in item for item in statuses[0])
    assert any(f"description=base={_BASE[:7]} pass" in item for item in statuses[0])
    updated_body = next(
        item.removeprefix("body=") for item in patches[0] if item.startswith("body=")
    )
    assert "✅ Within limit" in updated_body
    assert "Candidate test `109s` · Base test `100s`" in updated_body
    assert "old result" not in updated_body
    assert "### required-1 — ✅ Passed" in updated_body


def test_recheck_marks_active_base_pending_and_links_it(tmp_path: Path) -> None:
    statuses: list[list[str]] = []
    patches: list[list[str]] = []
    run_url = "https://github.com/azents/azents/actions/runs/19"

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            return _pull()
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
            return json.dumps(
                {
                    "workflow_runs": [
                        {"id": 19, "status": "in_progress", "html_url": run_url}
                    ]
                }
            )
        if "gh run download 19" in joined:
            raise EvidenceError("github_evidence_unavailable")
        if "/statuses/" in joined and "--method POST" in joined:
            statuses.append(values)
            return ""
        if joined.endswith("issues/3/comments?per_page=100"):
            return json.dumps(
                [
                    [],
                    [
                        {
                            "id": 42,
                            "body": (
                                "## E2E duration\n\nold result\n\n"
                                "<!-- Sticky Pull Request Comment:e2e-observability -->"
                            ),
                        }
                    ],
                ]
            )
        if "/issues/comments/42" in joined and "--method PATCH" in joined:
            patches.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)

    assert "comparison_unavailable" in summary
    assert any("state=pending" in item for item in statuses[0])
    assert any(f"target_url={run_url}" in item for item in statuses[0])
    updated_body = next(
        item.removeprefix("body=") for item in patches[0] if item.startswith("body=")
    )
    assert "⏳ Base CI running" in updated_body
    assert f"[workflow run 19]({run_url})" in updated_body


def test_recheck_skips_prs_without_duration_evidence(tmp_path: Path) -> None:
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            return _pull()
        if "actions/workflows/ci.yaml/runs" in joined:
            return json.dumps({"workflow_runs": []})
        if "--method POST" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)
    assert "no duration evidence" in summary
    assert posts == []


def test_recheck_skips_fork_pull_requests(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        values = list(args)
        commands.append(values)
        if " ".join(values).endswith("pulls/3"):
            return _pull("someone/fork")
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)

    assert summary == "PR #3: fork pull request skipped"
    assert len(commands) == 1


@pytest.mark.parametrize("change_after_status", [False, True])
def test_recheck_drops_stale_head_before_publication(
    tmp_path: Path, change_after_status: bool
) -> None:
    pull_reads = 0
    posts: list[list[str]] = []

    def command(args: Sequence[str]) -> str:
        nonlocal pull_reads
        values = list(args)
        joined = " ".join(values)
        if joined.endswith("pulls/3"):
            pull_reads += 1
            pull = json.loads(_pull())
            if pull_reads >= (3 if change_after_status else 2):
                pull["head"]["sha"] = "c" * 40
            return json.dumps(pull)
        if f"head_sha={_HEAD}" in joined:
            return json.dumps({"workflow_runs": [{"id": 20}]})
        if "gh run download 20" in joined:
            path = tmp_path / "candidate-20/report.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"head_sha": _HEAD, "lanes": {"web-1": "109"}}),
                encoding="utf-8",
            )
            return ""
        if f"head_sha={_BASE}" in joined:
            return json.dumps({"workflow_runs": []})
        if "/statuses/" in joined:
            posts.append(values)
            return ""
        raise AssertionError(values)

    summary = recheck("azents/azents", 3, tmp_path, command)

    expected = (
        "stale comment skipped" if change_after_status else "stale publication skipped"
    )
    assert expected in summary
    assert len(posts) == int(change_after_status)


def test_phase_decoder_projects_only_gate_fields() -> None:
    record = _decode_test_phase(
        '{"record_type":"test_phase","node_id":"test::example",'
        '"phase":"call","duration_seconds":"1.25","outcome":"passed"}'
    )
    assert record is not None
    assert record.node_id == "test::example"
    assert record.phase == "call"
    assert record.duration_seconds == Decimal("1.25")
    assert _decode_test_phase('{"record_type":"fixture","fixture":"server"}') is None


@pytest.mark.parametrize(
    "changes",
    [
        {"node_id": ""},
        {"node_id": True},
        {"phase": "unknown"},
        {"duration_seconds": True},
        {"duration_seconds": None},
        {"duration_seconds": "NaN"},
        {"outcome": None},
        {"unknown": "value"},
    ],
)
def test_phase_decoder_rejects_invalid_contract_fields(
    changes: dict[str, object],
) -> None:
    payload = {
        "record_type": "test_phase",
        "node_id": "test::example",
        "phase": "call",
        "duration_seconds": 1.25,
        "outcome": "passed",
        **changes,
    }
    with pytest.raises(EvidenceError):
        _decode_test_phase(json.dumps(payload))


def test_current_and_compact_reports_decode_to_candidate_measurements() -> None:
    current = compare(
        {"web-1": Decimal("90")},
        Sample(7, {"web-1": Decimal("100")}),
        _HEAD,
        _BASE,
        diagnostics={"web-1": {"call": Decimal("90"), "wall": Decimal("110")}},
    )
    decoded = _decode_candidate(json.dumps(current))
    assert decoded.head_sha == _HEAD
    assert isinstance(decoded.timing, CandidateTiming)
    assert decoded.timing.lanes == {"web-1": Decimal("90")}
    assert decoded.timing.diagnostics["web-1"] == {
        "call": Decimal("90"),
        "wall": Decimal("110"),
    }
    compact = _decode_candidate(
        json.dumps({"head_sha": _HEAD, "lanes": {"web-1": "90"}})
    )
    assert isinstance(compact.timing, CandidateTiming)
    assert compact.timing.diagnostics == {}
    # Historic explicit null diagnostics and null diagnostic cells are absence.
    nullable = _decode_candidate(
        json.dumps(
            {"head_sha": _HEAD, "lanes": {"web-1": "90"}, "lane_diagnostics": None}
        )
    )
    assert isinstance(nullable.timing, CandidateTiming)
    assert nullable.timing.diagnostics == {}
    assert set(current) == set(DurationReport.__annotations__)


@pytest.mark.parametrize(
    "changes",
    [
        {"lanes": {}},
        {"lanes": {"web-1": True}},
        {"lanes": {"web-1": "-1"}},
        {"lanes": {"not-a-lane": "90"}},
        {"schema_version": True},
        {"schema_version": 1.0},
        {"schema_version": 2},
        {"metric": "other-metric"},
        {"unknown": True},
        {"lane_diagnostics": {"web-1": {"unexpected": 1}}},
    ],
)
def test_invalid_candidate_is_typed_failure_not_absent_evidence(
    changes: dict[str, object],
) -> None:
    decoded = _decode_candidate(
        json.dumps({"head_sha": _HEAD, "lanes": {"web-1": "90"}, **changes})
    )
    assert decoded.head_sha == _HEAD
    assert isinstance(decoded.timing, InvalidCandidateTiming)


@pytest.mark.parametrize("status", [None, False, 17, ""])
def test_run_decoder_does_not_turn_malformed_status_into_completed(
    status: object,
) -> None:
    with pytest.raises(EvidenceError, match="invalid_run_status"):
        _decode_runs(
            json.dumps({"workflow_runs": [{"id": 7, "status": status}]}),
            "azents/azents",
        )


def test_github_ingress_projects_extensible_fields_without_raw_payloads() -> None:
    runs = _decode_runs(
        '{"workflow_runs":[{"id":7,"extra":"GitHub-owned field"},{"id":true}]}',
        "azents/azents",
    )
    assert len(runs) == 1
    assert runs[0].status == "completed"
    assert runs[0].url == "https://github.com/azents/azents/actions/runs/7"
    pull = _decode_pull_text(_pull())
    assert pull.head_sha == _HEAD
    assert pull.base_sha == _BASE
    assert pull.head_repository == "azents/azents"
    comments = _decode_comments(
        '[[{"id":42,"body":"sticky","extra":true}],'
        '[{"id":true,"body":"invalid"},{"id":43,"body":null}]]'
    )
    assert len(comments) == 1
    assert comments[0].comment_id == 42
    assert comments[0].body == "sticky"


def test_gate_still_imports_without_site_packages_on_python312_syntax(
    tmp_path: Path,
) -> None:
    """The trusted workflow helper has no dependency on the E2E environment."""
    script = """
import ast
import pathlib
import runpy
import sys
path = pathlib.Path(sys.argv[1])
ast.parse(path.read_text(), feature_version=(3, 12))
namespace = runpy.run_path(str(path), run_name="duration_gate_stdlib_import")
assert "pydantic" not in sys.modules
assert namespace["METRIC"] == "pytest-call-total-v1"
"""
    subprocess.run(
        [sys.executable, "-I", "-S", "-c", script, ci_duration_gate.__file__],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
