from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import audit_state
import pytest


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


def test_resolve_rotation_limit_targets_fourteen_days() -> None:
    assert audit_state.resolve_rotation_limit(
        246,
        range_limit=None,
        rotation_days=None,
    ) == (18, 14)
    assert audit_state.resolve_rotation_limit(
        10,
        range_limit=20,
        rotation_days=None,
    ) == (10, None)


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

    plan = audit_state.build_plan(
        tmp_path,
        tmp_path / "state.json",
        mode="incremental",
        range_limit=None,
        rotation_days=None,
    )

    assert plan["bootstrap"] is True
    assert plan["changed_checks"] == []
    assert plan["range_limit"] == 2
    assert plan["rotation_days"] == 14
    assert len(plan["rotation_ranges"]) == 2
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
    monkeypatch.setattr(
        audit_state,
        "changed_paths_since",
        lambda _root, _base, _head: audit_state.ChangedPaths(
            current=(mapped, unmapped, "docs/azents/spec/domain/example.md"),
            deleted=("python/apps/example/src/deleted.py",),
        ),
    )

    changed_checks, changed_specs, deleted_checks, deleted_specs = (
        audit_state.changed_work_plans(
            tmp_path,
            scope,
            "base",
            "head",
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

    plan = audit_state.build_plan(
        tmp_path,
        state_path,
        mode="incremental",
        range_limit=None,
        rotation_days=1,
    )
    plan["rotation_ranges"] = plan["rotation_ranges"][:1]
    plan["plan_sha256"] = audit_state.plan_sha256(plan)
    plan_path.write_text(json.dumps(plan))

    with pytest.raises(
        audit_state.AuditStateError,
        match="does not exactly match rotation ranges",
    ):
        audit_state.complete_plan(tmp_path, state_path, plan_path)


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
    assert summary["rotation_target_days"] == 14
