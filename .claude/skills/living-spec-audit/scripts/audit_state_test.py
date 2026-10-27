from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import audit_state
import pytest


@pytest.mark.parametrize("target", ["change", "range"])
@pytest.mark.parametrize(
    "field,value",
    [
        ("checked_through_commit", ["not", "a", "commit"]),
        ("checked_through_commit", ""),
        ("checked_at", True),
        ("checked_at", "not-a-date"),
        ("checked_at", "2026-10-24T07:00:00"),
        ("unexpected", None),
    ],
)
def test_load_state_rejects_invalid_nested_checkpoint(
    tmp_path: Path, target: str, field: str, value: object
) -> None:
    state = audit_state.empty_state()
    state["ranges"]["sample"] = audit_state.empty_range_checkpoint()
    raw = json.loads(json.dumps(state))
    checkpoint = (
        raw["change_checkpoint"] if target == "change" else raw["ranges"]["sample"]
    )
    checkpoint[field] = value
    path = tmp_path / "state.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(audit_state.AuditStateError):
        audit_state.load_state(path)


def test_load_state_roundtrips_checked_in_snapshot_and_empty_state(
    tmp_path: Path,
) -> None:
    for state in (
        audit_state.empty_state(),
        json.loads(
            (Path(__file__).parents[3] / "living-spec-audit-state.json").read_text()
        ),
    ):
        path = tmp_path / "state.json"
        path.write_text(json.dumps(state))
        assert audit_state.load_state(path) == state


def _range(
    *,
    file_path: str,
    scope_revision: str = "current",
    specs: tuple[str, ...] = ("docs/azents/spec/domain/example.md",),
) -> dict[str, object]:
    return {
        "file_count": 1,
        "file_specs": {file_path: list(specs)},
        "files": [file_path],
        "scope_revision": scope_revision,
        "specs": list(specs),
        "unmapped_files": [] if specs else [file_path],
    }


def _scope(ranges: dict[str, dict[str, object]]) -> audit_state.AuditScope:
    return audit_state.AuditScope(
        ranges=ranges,
        missing_code_paths=(),
        specs=(
            audit_state.LivingSpec(
                path="docs/azents/spec/domain/example.md",
                code_paths=("python/apps/example/src/**",),
            ),
        ),
    )


def test_parse_code_paths_reads_frontmatter_list() -> None:
    assert audit_state.parse_code_paths(
        """---
title: Example
code_paths:
  - python/apps/example/src/**
  - "typescript/apps/example/**"
last_verified_at: 2026-08-18
---
""",
        "docs/azents/spec/domain/example.md",
    ) == (
        "python/apps/example/src/**",
        "typescript/apps/example/**",
    )


def test_path_matches_directory_glob() -> None:
    assert audit_state.path_matches(
        "python/apps/example/src/service.py",
        "python/apps/example/src/**",
    )
    assert not audit_state.path_matches(
        "python/apps/other/src/service.py",
        "python/apps/example/src/**",
    )


def test_recursive_prefix_globs_preserve_literal_bracket_segments() -> None:
    pattern = "web/(app)/agents/*/workspace/[handle]?/**"
    assert audit_state.path_matches(
        "web/(app)/agents/[agentId]/workspace/[handle]1/route.ts", pattern
    )
    assert audit_state.path_matches(
        "web/(app)/agents/[agentId]/workspace/[handle]1/deep/route.ts", pattern
    )
    assert not audit_state.path_matches(
        "web/(app)/agents/a/b/workspace/[handle]1/route.ts", pattern
    )
    assert not audit_state.path_matches(
        "web/(app)/agents/a/workspace/h1/route.ts", pattern
    )
    assert audit_state.path_matches(
        "web/(app)/w/[handle]/route.ts", "web/(app)/w/[handle]/**"
    )


def test_recursive_wildcard_maps_file_and_is_not_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_path = "typescript/apps/example/src/agents/[agentId]/download/route.ts"
    spec_path = "docs/azents/spec/flow/example.md"
    specs = (
        audit_state.LivingSpec(
            path=spec_path,
            code_paths=("typescript/apps/example/src/agents/*/download/**",),
        ),
    )
    monkeypatch.setattr(audit_state, "load_living_specs", lambda _root: specs)
    monkeypatch.setattr(audit_state, "tracked_files", lambda _root: (file_path,))

    scope = audit_state.discover_audit_scope(tmp_path)

    assert scope.missing_code_paths == ()
    assert audit_state.specs_for_path(file_path, specs) == [spec_path]
    assert any(
        item["file_specs"].get(file_path) == [spec_path]
        for item in scope.ranges.values()
    )


def test_load_state_rejects_unknown_fields(tmp_path: Path) -> None:
    state = dict(audit_state.empty_state())
    state["unexpected"] = True
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))

    with pytest.raises(
        audit_state.AuditStateError,
        match="unknown or missing fields",
    ):
        audit_state.load_state(state_path)


def test_load_plan_rejects_non_object_payload(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("[]")

    with pytest.raises(
        audit_state.AuditStateError,
        match="Unsupported or invalid audit plan",
    ):
        audit_state.load_plan(plan_path)


def test_discover_scope_rotates_only_declared_files_and_reports_missing_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapped = "python/apps/example/src/mapped.py"
    unmapped = "python/apps/other/src/unmapped.py"
    specs = (
        audit_state.LivingSpec(
            path="docs/azents/spec/domain/example.md",
            code_paths=(mapped, "python/apps/example/src/missing.py"),
        ),
    )
    monkeypatch.setattr(audit_state, "load_living_specs", lambda _root: specs)
    monkeypatch.setattr(
        audit_state,
        "tracked_files",
        lambda _root: (mapped, unmapped),
    )

    scope = audit_state.discover_audit_scope(tmp_path)

    assert sum(item["file_count"] for item in scope.ranges.values()) == 1
    assert all(unmapped not in item["files"] for item in scope.ranges.values())
    assert scope.missing_code_paths == (
        {
            "pattern": "python/apps/example/src/missing.py",
            "spec": "docs/azents/spec/domain/example.md",
        },
    )


def test_resolve_rotation_limit_selects_one_range() -> None:
    assert audit_state.resolve_rotation_limit(
        246,
        range_limit=None,
        rotation_days=None,
    ) == (1, None)
    for limit, days in ((20, None), (None, 14), (True, None)):
        with pytest.raises(audit_state.AuditStateError, match="exactly one range"):
            audit_state.resolve_rotation_limit(
                10,
                range_limit=limit,
                rotation_days=days,
            )


def test_rotation_priority_is_never_checked_scope_changed_then_oldest() -> None:
    current = _range(file_path="python/apps/example/src/service.py")
    assert audit_state.rotation_reason(
        audit_state.empty_range_checkpoint(),
        current,
    ) == (0, "never_checked")
    assert audit_state.rotation_reason(
        {
            "checked_at": "2026-08-18T00:00:00Z",
            "checked_scope_revision": "old",
            "checked_through_commit": "base",
        },
        current,
    ) == (1, "scope_changed")
    assert audit_state.rotation_reason(
        {
            "checked_at": "2026-08-18T00:00:00Z",
            "checked_scope_revision": "current",
            "checked_through_commit": "base",
        },
        current,
    ) == (2, "least_recently_checked")


def test_incremental_plan_bootstraps_with_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranges = {
        f"range-{index:03}": _range(
            file_path=f"python/apps/example/src/file-{index:03}.py",
        )
        for index in range(28)
    }
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(
        audit_state, "discover_audit_scope", lambda _root: _scope(ranges)
    )
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")
    monkeypatch.setattr(
        audit_state,
        "changed_paths_in_day",
        lambda *_args: audit_state.ChangedPaths(current=(), deleted=()),
    )

    plan = audit_state.build_plan(
        tmp_path,
        tmp_path / "state.json",
        mode="incremental",
        range_limit=None,
        rotation_days=None,
    )

    assert plan["bootstrap"] is False
    assert plan["changed_checks"] == []
    assert plan["range_limit"] == 1
    assert plan["rotation_days"] is None
    assert len(plan["rotation_ranges"]) == 1
    assert plan["plan_sha256"] == audit_state.plan_sha256(plan)


def test_changed_work_includes_unmapped_and_deleted_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mapped = "python/apps/example/src/mapped.py"
    unmapped = "python/apps/other/src/unmapped.py"
    ranges = {
        "range-mapped": _range(file_path=mapped),
        "range-unmapped": _range(file_path=unmapped, specs=()),
    }
    scope = _scope(ranges)
    changed_checks, changed_specs, deleted_checks, deleted_specs = (
        audit_state.changed_work_plans(
            scope,
            audit_state.ChangedPaths(
                current=(mapped, unmapped, "docs/azents/spec/domain/example.md"),
                deleted=("python/apps/example/src/deleted.py",),
            ),
        )
    )

    assert sum(item["file_count"] for item in changed_checks) == 2
    assert any(item["unmapped_files"] == [unmapped] for item in changed_checks)
    assert changed_specs == ["docs/azents/spec/domain/example.md"]
    assert deleted_checks == [
        {
            "path": "python/apps/example/src/deleted.py",
            "specs": ["docs/azents/spec/domain/example.md"],
            "unmapped": False,
        }
    ]
    assert deleted_specs == []


def test_complete_rejects_modified_plan_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranges = {
        "range-a": _range(file_path="python/apps/example/src/a.py"),
    }
    state_path = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(
        audit_state, "discover_audit_scope", lambda _root: _scope(ranges)
    )
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")
    monkeypatch.setattr(
        audit_state,
        "changed_paths_in_day",
        lambda *_args: audit_state.ChangedPaths(current=(), deleted=()),
    )

    plan = audit_state.build_plan(
        tmp_path,
        state_path,
        mode="incremental",
        range_limit=1,
        rotation_days=None,
    )
    plan["rotation_ranges"] = []
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(
        audit_state.AuditStateError,
        match="payload changed after planning",
    ):
        audit_state.complete_plan(tmp_path, state_path, plan_path)


def test_complete_rejects_rehashed_partial_rotation_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ranges = {
        "range-a": _range(file_path="python/apps/example/src/a.py"),
        "range-b": _range(file_path="python/apps/example/src/b.py"),
    }
    state_path = tmp_path / "state.json"
    plan_path = tmp_path / "plan.json"
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(
        audit_state,
        "discover_audit_scope",
        lambda _root: _scope(ranges),
    )
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")
    monkeypatch.setattr(
        audit_state,
        "changed_paths_in_day",
        lambda *_args: audit_state.ChangedPaths(current=(), deleted=()),
    )

    plan = audit_state.build_plan(
        tmp_path,
        state_path,
        mode="incremental",
        range_limit=None,
        rotation_days=None,
    )
    plan["rotation_ranges"] = []
    plan["plan_sha256"] = audit_state.plan_sha256(plan)
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(
        audit_state.AuditStateError,
        match="does not exactly match rotation ranges",
    ):
        audit_state.complete_plan(tmp_path, state_path, plan_path)


def test_recent_commits_collect_only_daily_paths_and_deleted_files(
    tmp_path: Path,
) -> None:
    def git(*args: str, date: str | None = None) -> str:
        env = os.environ.copy()
        if date:
            env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    (tmp_path / "old").write_text("old")
    (tmp_path / "deleted").write_text("old")
    git("add", ".")
    git("commit", "-m", "old", date="2026-10-25T00:00:00Z")
    (tmp_path / "new").write_text("new")
    (tmp_path / "deleted").unlink()
    git("add", "-A")
    git("commit", "-m", "recent", date="2026-10-27T00:00:00Z")
    (tmp_path / "future").write_text("future")
    git("add", ".")
    git("commit", "-m", "after window", date="2026-10-27T02:00:00Z")
    head = git("rev-parse", "HEAD")
    changes = audit_state.changed_paths_in_day(tmp_path, head, "2026-10-27T01:00:00Z")
    assert changes.current == ("new",)
    assert changes.deleted == ("deleted",)


def test_recent_merge_includes_old_branch_changes(tmp_path: Path) -> None:
    def git(*args: str, date: str) -> str:
        env = {
            **os.environ,
            "GIT_AUTHOR_DATE": date,
            "GIT_COMMITTER_DATE": date,
        }
        return subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    old = "2026-10-20T00:00:00Z"
    git("init", "-b", "main", date=old)
    git("config", "user.name", "Test", date=old)
    git("config", "user.email", "test@example.com", date=old)
    git("commit", "--allow-empty", "-m", "base", date=old)
    git("checkout", "-b", "feature", date=old)
    (tmp_path / "feature").write_text("feature")
    git("add", ".", date=old)
    git("commit", "-m", "old branch work", date=old)
    git("checkout", "main", date=old)
    git("merge", "--no-ff", "feature", "-m", "merge", date="2026-10-27T00:00:00Z")
    head = git("rev-parse", "HEAD", date=old)
    assert audit_state.changed_paths_in_day(
        tmp_path,
        head,
        "2026-10-27T01:00:00Z",
    ).current == ("feature",)


def test_missing_paths_are_scoped_to_selected_and_recent_specs() -> None:
    scope = audit_state.AuditScope(
        ranges={},
        missing_code_paths=(
            {"pattern": "a", "spec": "selected"},
            {"pattern": "b", "spec": "changed"},
            {"pattern": "c", "spec": "unrelated"},
        ),
        specs=(),
    )
    plan = {
        "rotation_ranges": [{"specs": ["selected"]}],
        "changed_specs": ["changed"],
        "changed_checks": [],
        "deleted_checks": [],
    }
    assert audit_state.relevant_missing_paths(scope, plan) == list(
        scope.missing_code_paths[:2]
    )


def test_completion_changes_only_selected_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ranges = {
        "a": _range(file_path="python/apps/example/src/a.py"),
        "b": _range(file_path="python/apps/example/src/b.py"),
    }
    state = audit_state.empty_state()
    state["change_checkpoint"] = {
        "checked_at": "2026-09-01T00:00:00Z",
        "checked_through_commit": "old",
    }
    state["ranges"]["b"] = {
        "checked_at": "2026-09-01T00:00:00Z",
        "checked_through_commit": "old",
        "checked_scope_revision": "current",
    }
    state["ranges"]["legacy"] = dict(state["ranges"]["b"])
    state_path, plan_path = tmp_path / "state.json", tmp_path / "plan.json"
    state_path.write_text(json.dumps(state))
    monkeypatch.setattr(audit_state, "ensure_tracked_tree_clean", lambda _root: None)
    monkeypatch.setattr(
        audit_state, "discover_audit_scope", lambda _root: _scope(ranges)
    )
    monkeypatch.setattr(audit_state, "current_head", lambda _root: "head")
    monkeypatch.setattr(
        audit_state,
        "changed_paths_in_day",
        lambda *_args: audit_state.ChangedPaths(current=(), deleted=()),
    )
    plan = audit_state.build_plan(
        tmp_path, state_path, mode="incremental", range_limit=None, rotation_days=None
    )
    plan_path.write_text(json.dumps(plan))
    audit_state.complete_plan(tmp_path, state_path, plan_path)
    result = json.loads(state_path.read_text())
    assert result["change_checkpoint"] == state["change_checkpoint"]
    assert result["ranges"]["b"] == state["ranges"]["b"]
    assert result["ranges"]["legacy"] == state["ranges"]["legacy"]
    assert result["ranges"]["a"]["checked_through_commit"] == "head"


def test_status_reports_rotation_health() -> None:
    ranges = {
        "never": _range(file_path="python/apps/example/src/never.py"),
        "recent": _range(file_path="python/apps/example/src/recent.py"),
        "stale": _range(file_path="python/apps/example/src/stale.py"),
    }
    state = audit_state.empty_state()
    state["ranges"] = {
        "recent": {
            "checked_at": "2026-08-17T00:00:00Z",
            "checked_scope_revision": "current",
            "checked_through_commit": "base",
        },
        "stale": {
            "checked_at": "2026-08-17T00:00:00Z",
            "checked_scope_revision": "old",
            "checked_through_commit": "base",
        },
    }

    summary = audit_state.status_summary(
        state,
        _scope(ranges),
        rotation_days=14,
        now=datetime(2026, 8, 18, tzinfo=UTC),
    )

    assert summary["never_checked_ranges"] == 1
    assert summary["stale_ranges"] == 1
    assert summary["overdue_ranges"] == 2
    assert summary["overdue_threshold_days"] == 14
    assert summary["rotation_range_limit"] == 1
    assert summary["daily_rotation_days"] == 3
