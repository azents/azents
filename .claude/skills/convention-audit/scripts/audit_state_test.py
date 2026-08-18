from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import audit_state
import pytest


def _range(
    *,
    file_path: str,
    revision: str,
    conventions: tuple[str, ...] = (".claude/conventions/global/example.md",),
) -> dict[str, object]:
    return {
        "conventions": list(conventions),
        "file_count": 1,
        "files": [file_path],
        "ruleset_revision": revision,
    }


def test_resolve_incremental_range_limit_uses_rotation_target() -> None:
    assert audit_state.resolve_incremental_range_limit(
        170,
        range_limit=None,
        rotation_days=None,
    ) == (6, 30)
    assert audit_state.resolve_incremental_range_limit(
        170,
        range_limit=None,
        rotation_days=10,
    ) == (17, 10)
    assert audit_state.resolve_incremental_range_limit(
        170,
        range_limit=4,
        rotation_days=None,
    ) == (4, None)
    assert audit_state.resolve_incremental_range_limit(
        0,
        range_limit=None,
        rotation_days=None,
    ) == (0, 30)


@pytest.mark.parametrize(
    ("range_limit", "rotation_days"),
    [(0, None), (None, 0), (1, 30)],
)
def test_resolve_incremental_range_limit_rejects_invalid_options(
    range_limit: int | None,
    rotation_days: int | None,
) -> None:
    with pytest.raises(audit_state.AuditStateError):
        audit_state.resolve_incremental_range_limit(
            170,
            range_limit=range_limit,
            rotation_days=rotation_days,
        )


def test_reconcile_state_deduplicates_and_prunes_ruleset_manifests() -> None:
    state = audit_state.empty_state()
    state["rulesets"] = {
        "old": [".claude/conventions/global/old.md"],
        "unused": [".claude/conventions/global/unused.md"],
    }
    state["ranges"] = {
        "range-a": {
            "checked_at": "2026-08-01T00:00:00Z",
            "checked_ruleset_revision": "old",
            "checked_through_commit": "base",
        }
    }
    current_ranges = {
        "range-a": _range(file_path="a.py", revision="current"),
        "range-b": _range(file_path="b.py", revision="current"),
    }

    reconciled = audit_state.reconcile_state(state, current_ranges)

    assert reconciled["rulesets"] == {
        "current": [".claude/conventions/global/example.md"],
        "old": [".claude/conventions/global/old.md"],
    }

    reconciled["ranges"]["range-a"] = {
        "checked_at": "2026-08-18T00:00:00Z",
        "checked_ruleset_revision": "current",
        "checked_through_commit": "head",
    }
    pruned = audit_state.reconcile_state(reconciled, current_ranges)

    assert pruned["rulesets"] == {"current": [".claude/conventions/global/example.md"]}


def test_incremental_plan_bootstraps_without_a_full_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_ranges = {
        f"range-{index:03}": _range(
            file_path=f"src/file-{index:03}.py",
            revision="current",
        )
        for index in range(170)
    }
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(audit_state, "discover_ranges", lambda _root: current_ranges)
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")

    plan = audit_state.build_plan(
        tmp_path,
        tmp_path / "state.json",
        mode="incremental",
        range_limit=None,
        rotation_days=None,
    )

    assert plan["bootstrap"] is True
    assert plan["changed_checks"] == []
    assert plan["range_limit"] == 6
    assert plan["rotation_days"] == 30
    assert len(plan["legacy_ranges"]) == 6
    assert {item["reason"] for item in plan["legacy_ranges"]} == {"never_checked"}


def test_incremental_priority_is_never_checked_then_stale_then_oldest() -> None:
    current = _range(file_path="file.py", revision="current")

    assert audit_state.legacy_reason(audit_state.empty_range_checkpoint(), current) == (
        0,
        "never_checked",
    )
    assert audit_state.legacy_reason(
        {
            "checked_at": "2026-08-18T00:00:00Z",
            "checked_ruleset_revision": "old",
            "checked_through_commit": "base",
        },
        current,
    ) == (1, "ruleset_changed")
    assert audit_state.legacy_reason(
        {
            "checked_at": "2026-08-01T00:00:00Z",
            "checked_ruleset_revision": "current",
            "checked_through_commit": "base",
        },
        current,
    ) == (2, "least_recently_checked")


def test_status_reports_rotation_coverage() -> None:
    current_ranges = {
        "never": _range(file_path="never.py", revision="current"),
        "old": _range(file_path="old.py", revision="current"),
        "recent": _range(file_path="recent.py", revision="current"),
        "stale": _range(file_path="stale.py", revision="current"),
    }
    state = audit_state.empty_state()
    state["rulesets"] = {"old-revision": [".claude/conventions/global/old.md"]}
    state["ranges"] = {
        "old": {
            "checked_at": "2026-07-18T00:00:00Z",
            "checked_ruleset_revision": "current",
            "checked_through_commit": "base",
        },
        "recent": {
            "checked_at": "2026-08-17T00:00:00Z",
            "checked_ruleset_revision": "current",
            "checked_through_commit": "base",
        },
        "stale": {
            "checked_at": "2026-08-17T00:00:00Z",
            "checked_ruleset_revision": "old-revision",
            "checked_through_commit": "base",
        },
    }

    summary = audit_state.status_summary(
        state,
        current_ranges,
        rotation_days=30,
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert summary["never_checked_ranges"] == 1
    assert summary["stale_ranges"] == 1
    assert summary["overdue_ranges"] == 3
    assert summary["checked_within_rotation_ranges"] == 1
    assert summary["oldest_checked_at"] == "2026-07-18T00:00:00Z"
    assert summary["max_range_age_days"] == 31.0
    assert summary["rotation_range_limit"] == 1


def test_status_reports_zero_limit_without_ranges() -> None:
    summary = audit_state.status_summary(
        audit_state.empty_state(),
        {},
        rotation_days=30,
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert summary["current_ranges"] == 0
    assert summary["rotation_range_limit"] == 0


def test_complete_bootstrap_plan_records_only_completed_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_ranges = {
        "range-a": _range(file_path="a.py", revision="current"),
        "range-b": _range(file_path="b.py", revision="current"),
    }
    state_path = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(audit_state, "discover_ranges", lambda _root: current_ranges)
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")
    monkeypatch.setattr(audit_state, "utc_now", lambda: "2026-08-18T00:00:00Z")

    plan = audit_state.build_plan(
        tmp_path,
        state_path,
        mode="incremental",
        range_limit=1,
        rotation_days=None,
    )
    state_path.write_text(audit_state.serialize_json(audit_state.empty_state()))
    plan["state_sha256"] = audit_state.file_sha256(state_path)
    plan_path.write_text(json.dumps(plan))

    audit_state.complete_plan(tmp_path, state_path, plan_path)

    state = audit_state.load_state(state_path)
    assert state["change_checkpoint"] == {
        "checked_at": "2026-08-18T00:00:00Z",
        "checked_ruleset_revisions": [],
        "checked_through_commit": "head",
    }
    assert state["ranges"]["range-a"]["checked_at"] == "2026-08-18T00:00:00Z"
    assert state["ranges"]["range-b"] == audit_state.empty_range_checkpoint()
    assert state["rulesets"] == {"current": [".claude/conventions/global/example.md"]}
