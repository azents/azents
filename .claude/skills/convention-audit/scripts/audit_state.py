#!/usr/bin/env python3
"""Plan and checkpoint bounded repository convention audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = ".claude/convention-audit-state.json"
STATE_PATH_TO_EXCLUDE = PurePosixPath(DEFAULT_STATE_PATH)
RANGE_BUCKET_COUNT = 8
CONVENTION_LINK_PATTERN = re.compile(r"\]\((\.\./conventions/[^)]+\.md)\)")


class AuditStateError(Exception):
    """Raised when an audit plan or state cannot be used safely."""


@dataclass(frozen=True)
class ConventionIndex:
    """One convention index and the code paths to which it applies."""

    relative_path: str
    paths: tuple[str, ...]
    convention_paths: tuple[str, ...]


def run_git(repo_root: Path, *args: str) -> str:
    """Run Git and return decoded stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AuditStateError(result.stderr.strip() or "Git command failed")
    return result.stdout


def find_repo_root() -> Path:
    """Return the current repository root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AuditStateError("Run this command inside a Git repository")
    return Path(result.stdout.strip()).resolve()


def utc_now() -> str:
    """Return a second-precision UTC timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def empty_state() -> dict[str, Any]:
    """Return an empty versioned state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "change_checkpoint": {
            "checked_at": None,
            "checked_through_commit": None,
        },
        "ranges": {},
    }


def load_state(state_path: Path) -> dict[str, Any]:
    """Load and minimally validate the state file."""
    if not state_path.exists():
        return empty_state()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditStateError(f"Cannot read state file: {exc}") from exc
    if not isinstance(state, dict):
        raise AuditStateError("Audit state must be a JSON object")
    if state.get("schema_version") != SCHEMA_VERSION:
        raise AuditStateError(
            f"Unsupported audit state schema: {state.get('schema_version')!r}"
        )
    if not isinstance(state.get("change_checkpoint"), dict):
        raise AuditStateError("Audit state is missing change_checkpoint")
    if not isinstance(state.get("ranges"), dict):
        raise AuditStateError("Audit state is missing ranges")
    return state


def serialize_json(value: dict[str, Any]) -> str:
    """Serialize JSON deterministically."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def emit_json(value: dict[str, Any]) -> None:
    """Write one compact JSON object to stdout."""
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace a JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(serialize_json(value))
        temporary_path = Path(handle.name)
    temporary_path.replace(path)


def file_sha256(path: Path) -> str:
    """Hash a file, treating a missing file as empty."""
    content = path.read_bytes() if path.exists() else b""
    return hashlib.sha256(content).hexdigest()


def parse_frontmatter_paths(index_text: str) -> tuple[str, ...]:
    """Parse the simple paths list from a convention index frontmatter."""
    lines = index_text.splitlines()
    if not lines or lines[0] != "---":
        return ("**",)

    paths: list[str] = []
    in_paths = False
    for line in lines[1:]:
        if line == "---":
            break
        if line == "paths:":
            in_paths = True
            continue
        if in_paths:
            match = re.fullmatch(r"\s+-\s+(.+)", line)
            if match:
                paths.append(match.group(1).strip().strip("'\""))
                continue
            if line and not line.startswith((" ", "\t")):
                in_paths = False
    return tuple(paths) or ("**",)


def load_convention_indexes(repo_root: Path) -> tuple[ConventionIndex, ...]:
    """Load convention paths and body links from generated indexes."""
    rules_root = repo_root / ".claude" / "rules"
    indexes: list[ConventionIndex] = []
    for index_path in sorted(rules_root.glob("*-conventions.md")):
        text = index_path.read_text(encoding="utf-8")
        bodies = []
        for match in CONVENTION_LINK_PATTERN.finditer(text):
            body_path = (index_path.parent / match.group(1)).resolve()
            if not body_path.is_file():
                raise AuditStateError(
                    f"Convention body referenced by {index_path} does not exist: "
                    f"{body_path}"
                )
            bodies.append(body_path.relative_to(repo_root).as_posix())
        indexes.append(
            ConventionIndex(
                relative_path=index_path.relative_to(repo_root).as_posix(),
                paths=parse_frontmatter_paths(text),
                convention_paths=tuple(sorted(set(bodies))),
            )
        )

    global_index_path = rules_root / "conventions.md"
    if global_index_path.is_file():
        text = global_index_path.read_text(encoding="utf-8")
        bodies = []
        for match in CONVENTION_LINK_PATTERN.finditer(text):
            body_path = (global_index_path.parent / match.group(1)).resolve()
            if not body_path.is_file():
                raise AuditStateError(
                    f"Global convention index references a missing body: {body_path}"
                )
            bodies.append(body_path.relative_to(repo_root).as_posix())
        indexes.append(
            ConventionIndex(
                relative_path=global_index_path.relative_to(repo_root).as_posix(),
                paths=("**",),
                convention_paths=tuple(sorted(set(bodies))),
            )
        )

    if not indexes:
        raise AuditStateError("No convention indexes found under .claude/rules")
    return tuple(sorted(indexes, key=lambda item: item.relative_path))


def path_matches(path: str, pattern: str) -> bool:
    """Return whether a repository path matches a convention path pattern."""
    if pattern == "**":
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(f"{prefix}/")
    return PurePosixPath(path).match(pattern)


def audit_base_range_for_path(path: str) -> str:
    """Return the human-readable base range for a tracked path."""
    parts = PurePosixPath(path).parts
    if len(parts) == 1:
        return "."
    if (
        len(parts) >= 3
        and parts[0] in {"python", "typescript"}
        and parts[1] in {"apps", "libs", "packages"}
    ):
        return f"{parts[0]}/{parts[1]}/{parts[2]}/**"
    return f"{parts[0]}/**"


def audit_range_for_path(path: str) -> str:
    """Assign a tracked path to a deterministic bounded audit range."""
    base_range = audit_base_range_for_path(path)
    bucket = int(hashlib.sha256(path.encode()).hexdigest()[:8], 16)
    bucket_number = bucket % RANGE_BUCKET_COUNT + 1
    return f"{base_range}::bucket-{bucket_number}-of-{RANGE_BUCKET_COUNT}"


def tracked_files(repo_root: Path) -> tuple[str, ...]:
    """Return tracked audit target files."""
    output = run_git(repo_root, "ls-files", "-z")
    return tuple(
        path
        for path in output.split("\0")
        if path and PurePosixPath(path) != STATE_PATH_TO_EXCLUDE
    )


def applicable_indexes(
    files: tuple[str, ...], indexes: tuple[ConventionIndex, ...]
) -> tuple[ConventionIndex, ...]:
    """Return convention indexes that apply to at least one file."""
    return tuple(
        index
        for index in indexes
        if any(
            path_matches(file_path, pattern)
            for file_path in files
            for pattern in index.paths
        )
    )


def ruleset_revision(
    repo_root: Path, indexes: tuple[ConventionIndex, ...]
) -> tuple[str, tuple[str, ...]]:
    """Hash applicable convention definitions and return their body paths."""
    digest = hashlib.sha256()
    convention_paths = sorted(
        {
            convention_path
            for index in indexes
            for convention_path in index.convention_paths
        }
    )
    for index in indexes:
        digest.update(index.relative_path.encode())
        digest.update(b"\0")
        digest.update(json.dumps(index.paths, sort_keys=True).encode())
        digest.update(b"\0")
    for convention_path in convention_paths:
        digest.update(convention_path.encode())
        digest.update(b"\0")
        digest.update((repo_root / convention_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest(), tuple(convention_paths)


def discover_ranges(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Discover current stable ranges and their applicable conventions."""
    files_by_range: dict[str, list[str]] = {}
    for path in tracked_files(repo_root):
        files_by_range.setdefault(audit_range_for_path(path), []).append(path)

    indexes = load_convention_indexes(repo_root)
    ranges: dict[str, dict[str, Any]] = {}
    for range_name, range_files_list in sorted(files_by_range.items()):
        range_files = tuple(sorted(range_files_list))
        selected_indexes = applicable_indexes(range_files, indexes)
        revision, convention_paths = ruleset_revision(repo_root, selected_indexes)
        ranges[range_name] = {
            "conventions": list(convention_paths),
            "file_count": len(range_files),
            "files": list(range_files),
            "ruleset_revision": revision,
        }
    return ranges


def empty_range_checkpoint() -> dict[str, Any]:
    """Return an unchecked range checkpoint."""
    return {
        "checked_at": None,
        "checked_ruleset_revision": None,
        "checked_through_commit": None,
    }


def reconcile_state(
    state: dict[str, Any], current_ranges: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Add current ranges, prune removed ranges, and preserve checkpoints."""
    existing_ranges = state["ranges"]
    reconciled_ranges = {
        range_name: existing_ranges.get(range_name, empty_range_checkpoint())
        for range_name in sorted(current_ranges)
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "change_checkpoint": {
            "checked_at": state["change_checkpoint"].get("checked_at"),
            "checked_through_commit": state["change_checkpoint"].get(
                "checked_through_commit"
            ),
        },
        "ranges": reconciled_ranges,
    }


def current_head(repo_root: Path) -> str:
    """Return the current HEAD commit."""
    return run_git(repo_root, "rev-parse", "HEAD").strip()


def ensure_tracked_tree_clean(repo_root: Path) -> None:
    """Reject plans and completion from a dirty tracked checkout."""
    status = run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise AuditStateError(
            "Tracked working-tree or index changes exist; use a clean audit checkout"
        )


def range_plan(
    range_name: str, current_range: dict[str, Any], reason: str
) -> dict[str, Any]:
    """Return a serializable range inspection plan."""
    return {
        "conventions": current_range["conventions"],
        "file_count": current_range["file_count"],
        "files": current_range["files"],
        "name": range_name,
        "reason": reason,
        "ruleset_revision": current_range["ruleset_revision"],
    }


def changed_range_plan(
    range_name: str, current_range: dict[str, Any], files: list[str]
) -> dict[str, Any]:
    """Return a changed-file-only inspection plan."""
    return {
        "conventions": current_range["conventions"],
        "file_count": len(files),
        "files": sorted(files),
        "name": range_name,
        "reason": "changed_files",
        "ruleset_revision": current_range["ruleset_revision"],
    }


def changed_files_since(
    repo_root: Path, base_commit: str, head_commit: str
) -> tuple[str, ...]:
    """Return current tracked files changed between two commits."""
    run_git(repo_root, "cat-file", "-e", f"{base_commit}^{{commit}}")
    output = run_git(
        repo_root,
        "diff",
        "--name-only",
        "-z",
        "--diff-filter=ACMR",
        f"{base_commit}..{head_commit}",
    )
    current_files = set(tracked_files(repo_root))
    return tuple(
        sorted(
            path
            for path in output.split("\0")
            if path
            and path in current_files
            and PurePosixPath(path) != STATE_PATH_TO_EXCLUDE
        )
    )


def legacy_reason(
    checkpoint: dict[str, Any], current_range: dict[str, Any]
) -> tuple[int, str]:
    """Return sort priority and reason for a full-range incremental check."""
    checked_at = checkpoint.get("checked_at")
    checked_revision = checkpoint.get("checked_ruleset_revision")
    if checked_at is not None and checked_revision != current_range["ruleset_revision"]:
        return 0, "ruleset_changed"
    if checked_at is None:
        return 1, "never_checked"
    return 2, "least_recently_checked"


def build_plan(
    repo_root: Path,
    state_path: Path,
    mode: str,
    range_limit: int,
) -> dict[str, Any]:
    """Build a full or incremental audit plan."""
    ensure_tracked_tree_clean(repo_root)
    original_state_sha256 = file_sha256(state_path)
    state = load_state(state_path)
    current_ranges = discover_ranges(repo_root)
    reconciled = reconcile_state(state, current_ranges)
    head_commit = current_head(repo_root)

    plan: dict[str, Any] = {
        "change_checkpoint_before": reconciled["change_checkpoint"].get(
            "checked_through_commit"
        ),
        "generated_at": utc_now(),
        "head_commit": head_commit,
        "mode": mode,
        "schema_version": SCHEMA_VERSION,
        "state_sha256": original_state_sha256,
    }

    if mode == "full":
        plan["changed_checks"] = []
        plan["legacy_ranges"] = []
        plan["full_ranges"] = [
            range_plan(range_name, current_range, "full_audit")
            for range_name, current_range in current_ranges.items()
        ]
        return plan

    base_commit = reconciled["change_checkpoint"].get("checked_through_commit")
    if not base_commit:
        raise AuditStateError(
            "Incremental mode requires a completed full audit checkpoint"
        )

    changed_by_range: dict[str, list[str]] = {}
    for path in changed_files_since(repo_root, base_commit, head_commit):
        changed_by_range.setdefault(audit_range_for_path(path), []).append(path)
    plan["changed_checks"] = [
        changed_range_plan(range_name, current_ranges[range_name], files)
        for range_name, files in sorted(changed_by_range.items())
    ]
    plan["full_ranges"] = []

    candidates = []
    for range_name, current_range in current_ranges.items():
        checkpoint = reconciled["ranges"][range_name]
        priority, reason = legacy_reason(checkpoint, current_range)
        candidates.append(
            (
                priority,
                checkpoint.get("checked_at") or "",
                range_name,
                reason,
                current_range,
            )
        )
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    plan["legacy_ranges"] = [
        range_plan(range_name, current_range, reason)
        for _, _, range_name, reason, current_range in candidates[:range_limit]
    ]
    return plan


def verify_range_plan(
    planned_range: dict[str, Any], current_ranges: dict[str, dict[str, Any]]
) -> None:
    """Reject a range whose files or convention revision changed."""
    range_name = planned_range.get("name")
    if range_name not in current_ranges:
        raise AuditStateError(f"Planned range no longer exists: {range_name}")
    current_range = current_ranges[range_name]
    for field in ("file_count", "files", "ruleset_revision", "conventions"):
        if planned_range.get(field) != current_range[field]:
            raise AuditStateError(
                f"Planned range changed after planning: {range_name} ({field})"
            )


def verify_changed_check(
    changed_check: dict[str, Any], current_ranges: dict[str, dict[str, Any]]
) -> None:
    """Reject changed-file work whose range or convention revision changed."""
    range_name = changed_check.get("name")
    if range_name not in current_ranges:
        raise AuditStateError(f"Changed-file range no longer exists: {range_name}")
    current_range = current_ranges[range_name]
    for field in ("ruleset_revision", "conventions"):
        if changed_check.get(field) != current_range[field]:
            raise AuditStateError(
                f"Changed-file range changed after planning: {range_name} ({field})"
            )
    files = changed_check.get("files")
    if not isinstance(files, list) or changed_check.get("file_count") != len(files):
        raise AuditStateError(
            f"Changed-file range has an invalid file list: {range_name}"
        )
    current_files = set(current_range["files"])
    if any(
        not isinstance(path, str)
        or path not in current_files
        or audit_range_for_path(path) != range_name
        for path in files
    ):
        raise AuditStateError(
            f"Changed-file range contains a stale or invalid path: {range_name}"
        )


def complete_plan(repo_root: Path, state_path: Path, plan_path: Path) -> None:
    """Advance state after a successfully executed plan."""
    ensure_tracked_tree_clean(repo_root)
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditStateError(f"Cannot read plan file: {exc}") from exc
    if not isinstance(plan, dict) or plan.get("schema_version") != SCHEMA_VERSION:
        raise AuditStateError("Unsupported or invalid audit plan")
    if plan.get("state_sha256") != file_sha256(state_path):
        raise AuditStateError("Audit state changed after this plan was created")
    if plan.get("head_commit") != current_head(repo_root):
        raise AuditStateError("Repository HEAD changed after this plan was created")

    state = load_state(state_path)
    current_ranges = discover_ranges(repo_root)
    reconciled = reconcile_state(state, current_ranges)

    mode = plan.get("mode")
    if mode == "full":
        planned_ranges = plan.get("full_ranges")
        if not isinstance(planned_ranges, list):
            raise AuditStateError("Full audit plan is missing full_ranges")
        if {item.get("name") for item in planned_ranges} != set(current_ranges):
            raise AuditStateError("Full audit plan does not cover every current range")
        ranges_to_complete = planned_ranges
    elif mode == "incremental":
        if plan.get("change_checkpoint_before") != reconciled["change_checkpoint"].get(
            "checked_through_commit"
        ):
            raise AuditStateError(
                "Incremental change checkpoint changed after planning"
            )
        changed_checks = plan.get("changed_checks")
        legacy_ranges = plan.get("legacy_ranges")
        if not isinstance(changed_checks, list) or not isinstance(legacy_ranges, list):
            raise AuditStateError("Incremental audit plan is incomplete")
        for changed_check in changed_checks:
            verify_changed_check(changed_check, current_ranges)
        ranges_to_complete = legacy_ranges
    else:
        raise AuditStateError(f"Unknown audit mode: {mode!r}")

    for planned_range in ranges_to_complete:
        verify_range_plan(planned_range, current_ranges)

    completed_at = utc_now()
    head_commit = plan["head_commit"]
    for planned_range in ranges_to_complete:
        range_name = planned_range["name"]
        reconciled["ranges"][range_name] = {
            "checked_at": completed_at,
            "checked_ruleset_revision": planned_range["ruleset_revision"],
            "checked_through_commit": head_commit,
        }
    reconciled["change_checkpoint"] = {
        "checked_at": completed_at,
        "checked_through_commit": head_commit,
    }
    write_json_atomic(state_path, reconciled)
    emit_json(
        {
            "change_checkpoint": head_commit,
            "completed_at": completed_at,
            "mode": mode,
            "ranges_completed": len(ranges_to_complete),
        }
    )


def status_summary(
    state: dict[str, Any], current_ranges: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Return a concise state summary."""
    reconciled = reconcile_state(state, current_ranges)
    never_checked = 0
    stale = 0
    for range_name, current_range in current_ranges.items():
        checkpoint = reconciled["ranges"][range_name]
        if checkpoint.get("checked_at") is None:
            never_checked += 1
        elif (
            checkpoint.get("checked_ruleset_revision")
            != current_range["ruleset_revision"]
        ):
            stale += 1
    return {
        "change_checkpoint": reconciled["change_checkpoint"],
        "current_ranges": len(current_ranges),
        "never_checked_ranges": never_checked,
        "stale_ranges": stale,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "sync", help="Reconcile current ranges without marking checks"
    )
    subparsers.add_parser("status", help="Summarize current checkpoint coverage")

    plan_parser = subparsers.add_parser("plan", help="Create a disposable audit plan")
    plan_parser.add_argument("--mode", choices=("full", "incremental"), required=True)
    plan_parser.add_argument(
        "--range-limit",
        type=int,
        default=1,
        help="Full legacy ranges selected in incremental mode (default: 1)",
    )
    plan_parser.add_argument("--output", type=Path, required=True)

    complete_parser = subparsers.add_parser(
        "complete", help="Advance state after successful inspection and reporting"
    )
    complete_parser.add_argument("--plan", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    """Run the selected audit state operation."""
    try:
        args = parse_args()
        repo_root = find_repo_root()
        state_path = repo_root / DEFAULT_STATE_PATH
        state = load_state(state_path)
        current_ranges = discover_ranges(repo_root)

        if args.command == "sync":
            reconciled = reconcile_state(state, current_ranges)
            write_json_atomic(state_path, reconciled)
            emit_json(status_summary(reconciled, current_ranges))
            return 0
        if args.command == "status":
            emit_json(status_summary(state, current_ranges))
            return 0
        if args.command == "plan":
            if args.range_limit < 1:
                raise AuditStateError("--range-limit must be at least 1")
            plan = build_plan(
                repo_root,
                state_path,
                mode=args.mode,
                range_limit=args.range_limit,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(args.output, plan)
            emit_json(
                {
                    "changed_checks": len(plan["changed_checks"]),
                    "full_ranges": len(plan["full_ranges"]),
                    "head_commit": plan["head_commit"],
                    "legacy_ranges": len(plan["legacy_ranges"]),
                    "mode": plan["mode"],
                    "output": str(args.output),
                }
            )
            return 0
        if args.command == "complete":
            complete_plan(repo_root, state_path, args.plan)
            return 0
        raise AuditStateError(f"Unsupported command: {args.command}")
    except AuditStateError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
