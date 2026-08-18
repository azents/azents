#!/usr/bin/env python3
"""Plan and checkpoint bounded repository convention audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA_VERSION = 2
DEFAULT_STATE_PATH = ".claude/convention-audit-state.json"
DEFAULT_ROTATION_DAYS = 30
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
            "checked_ruleset_revisions": [],
            "checked_through_commit": None,
        },
        "ranges": {},
        "rulesets": {},
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
    if not isinstance(state.get("rulesets"), dict):
        raise AuditStateError("Audit state is missing rulesets")
    checked_ruleset_revisions = state["change_checkpoint"].get(
        "checked_ruleset_revisions"
    )
    if not isinstance(checked_ruleset_revisions, list) or any(
        not isinstance(revision, str) for revision in checked_ruleset_revisions
    ):
        raise AuditStateError(
            "Audit state change_checkpoint has invalid checked_ruleset_revisions"
        )
    for revision, conventions in state["rulesets"].items():
        if (
            not isinstance(revision, str)
            or not isinstance(conventions, list)
            or any(not isinstance(path, str) for path in conventions)
            or conventions != sorted(set(conventions))
        ):
            raise AuditStateError(f"Audit state has an invalid ruleset: {revision!r}")
    for range_name, checkpoint in state["ranges"].items():
        if not isinstance(range_name, str) or not isinstance(checkpoint, dict):
            raise AuditStateError("Audit state has an invalid range checkpoint")
        checked_revision = checkpoint.get("checked_ruleset_revision")
        if checked_revision is not None and checked_revision not in state["rulesets"]:
            raise AuditStateError(
                f"Range checkpoint references a missing ruleset: {range_name}"
            )
    for revision in checked_ruleset_revisions:
        if revision not in state["rulesets"]:
            raise AuditStateError(
                f"Change checkpoint references a missing ruleset: {revision}"
            )
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


def plan_sha256(plan: dict[str, Any]) -> str:
    """Hash a plan payload without its embedded integrity field."""
    payload = dict(plan)
    payload.pop("plan_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic integrity hash to a completed plan."""
    plan["plan_sha256"] = plan_sha256(plan)
    return plan


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


def current_ruleset_manifests(
    current_ranges: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Return deduplicated current ruleset manifests."""
    manifests: dict[str, list[str]] = {}
    for current_range in current_ranges.values():
        revision = current_range["ruleset_revision"]
        conventions = current_range["conventions"]
        existing = manifests.get(revision)
        if existing is not None and existing != conventions:
            raise AuditStateError(
                f"Ruleset revision has inconsistent conventions: {revision}"
            )
        manifests[revision] = conventions
    return dict(sorted(manifests.items()))


def reconcile_state(
    state: dict[str, Any], current_ranges: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Add current ranges, prune removed ranges, and preserve checkpoints."""
    existing_ranges = state["ranges"]
    reconciled_ranges = {
        range_name: existing_ranges.get(range_name, empty_range_checkpoint())
        for range_name in sorted(current_ranges)
    }
    current_manifests = current_ruleset_manifests(current_ranges)
    referenced_revisions = set(current_manifests)
    referenced_revisions.update(
        checkpoint["checked_ruleset_revision"]
        for checkpoint in reconciled_ranges.values()
        if checkpoint.get("checked_ruleset_revision") is not None
    )
    referenced_revisions.update(
        state["change_checkpoint"].get("checked_ruleset_revisions", [])
    )
    rulesets = dict(current_manifests)
    for revision in sorted(referenced_revisions - set(current_manifests)):
        conventions = state["rulesets"].get(revision)
        if conventions is None:
            raise AuditStateError(f"Referenced ruleset manifest is missing: {revision}")
        rulesets[revision] = conventions
    return {
        "schema_version": SCHEMA_VERSION,
        "change_checkpoint": {
            "checked_at": state["change_checkpoint"].get("checked_at"),
            "checked_ruleset_revisions": list(
                state["change_checkpoint"].get("checked_ruleset_revisions", [])
            ),
            "checked_through_commit": state["change_checkpoint"].get(
                "checked_through_commit"
            ),
        },
        "ranges": reconciled_ranges,
        "rulesets": dict(sorted(rulesets.items())),
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
    if checked_at is None:
        return 0, "never_checked"
    if checked_revision != current_range["ruleset_revision"]:
        return 1, "ruleset_changed"
    return 2, "least_recently_checked"


def resolve_incremental_range_limit(
    range_count: int,
    *,
    range_limit: int | None,
    rotation_days: int | None,
) -> tuple[int, int | None]:
    """Resolve a fixed limit or a target rotation period."""
    if range_limit is not None and rotation_days is not None:
        raise AuditStateError(
            "--range-limit and --rotation-days are mutually exclusive"
        )
    if range_limit is not None:
        if range_limit < 1:
            raise AuditStateError("--range-limit must be at least 1")
        return range_limit, None
    effective_rotation_days = (
        rotation_days if rotation_days is not None else DEFAULT_ROTATION_DAYS
    )
    if effective_rotation_days < 1:
        raise AuditStateError("--rotation-days must be at least 1")
    return math.ceil(range_count / effective_rotation_days), effective_rotation_days


def changed_check_plans(
    repo_root: Path,
    current_ranges: dict[str, dict[str, Any]],
    base_commit: str | None,
    head_commit: str,
) -> list[dict[str, Any]]:
    """Return the exact changed-file checks required for a checkpoint."""
    changed_by_range: dict[str, list[str]] = {}
    if base_commit:
        for path in changed_files_since(repo_root, base_commit, head_commit):
            changed_by_range.setdefault(audit_range_for_path(path), []).append(path)
    return [
        changed_range_plan(range_name, current_ranges[range_name], files)
        for range_name, files in sorted(changed_by_range.items())
    ]


def rotation_range_plans(
    reconciled: dict[str, Any],
    current_ranges: dict[str, dict[str, Any]],
    range_limit: int,
) -> list[dict[str, Any]]:
    """Return the exact prioritized full ranges for one rotation step."""
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
    return [
        range_plan(range_name, current_range, reason)
        for _, _, range_name, reason, current_range in candidates[:range_limit]
    ]


def validated_plan_range_limit(plan: dict[str, Any], range_count: int) -> int:
    """Validate and return the rotation limit encoded in a plan."""
    range_limit = plan.get("range_limit")
    rotation_days = plan.get("rotation_days")
    if (
        not isinstance(range_limit, int)
        or isinstance(range_limit, bool)
        or not isinstance(rotation_days, (int, type(None)))
        or isinstance(rotation_days, bool)
    ):
        raise AuditStateError("Incremental audit plan has invalid rotation settings")
    if rotation_days is None:
        if range_limit < 1:
            raise AuditStateError("Incremental audit plan has invalid range_limit")
        return range_limit
    if rotation_days < 1:
        raise AuditStateError("Incremental audit plan has invalid rotation_days")
    expected_limit = math.ceil(range_count / rotation_days)
    if range_limit != expected_limit:
        raise AuditStateError("Incremental audit plan has inconsistent rotation limit")
    return range_limit


def build_plan(
    repo_root: Path,
    state_path: Path,
    mode: str,
    range_limit: int | None,
    rotation_days: int | None,
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
        if range_limit is not None or rotation_days is not None:
            raise AuditStateError(
                "--range-limit and --rotation-days apply only to incremental mode"
            )
        plan["changed_checks"] = []
        plan["legacy_ranges"] = []
        plan["full_ranges"] = [
            range_plan(range_name, current_range, "full_audit")
            for range_name, current_range in current_ranges.items()
        ]
        return seal_plan(plan)

    resolved_range_limit, effective_rotation_days = resolve_incremental_range_limit(
        len(current_ranges),
        range_limit=range_limit,
        rotation_days=rotation_days,
    )
    plan["range_limit"] = resolved_range_limit
    plan["rotation_days"] = effective_rotation_days
    base_commit = reconciled["change_checkpoint"].get("checked_through_commit")
    plan["bootstrap"] = base_commit is None
    plan["changed_checks"] = changed_check_plans(
        repo_root,
        current_ranges,
        base_commit,
        head_commit,
    )
    plan["full_ranges"] = []
    plan["legacy_ranges"] = rotation_range_plans(
        reconciled,
        current_ranges,
        resolved_range_limit,
    )
    return seal_plan(plan)


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
    if plan.get("plan_sha256") != plan_sha256(plan):
        raise AuditStateError("Audit plan payload changed after planning")
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
        expected_ranges = [
            range_plan(range_name, current_range, "full_audit")
            for range_name, current_range in current_ranges.items()
        ]
        if (
            planned_ranges != expected_ranges
            or plan.get("changed_checks") != []
            or plan.get("legacy_ranges") != []
        ):
            raise AuditStateError(
                "Full audit plan does not exactly match current ranges"
            )
        ranges_to_complete = planned_ranges
        changed_ruleset_revisions = sorted(
            {item["ruleset_revision"] for item in planned_ranges}
        )
    elif mode == "incremental":
        base_commit = reconciled["change_checkpoint"].get("checked_through_commit")
        if plan.get("change_checkpoint_before") != base_commit:
            raise AuditStateError(
                "Incremental change checkpoint changed after planning"
            )
        changed_checks = plan.get("changed_checks")
        legacy_ranges = plan.get("legacy_ranges")
        if not isinstance(changed_checks, list) or not isinstance(legacy_ranges, list):
            raise AuditStateError("Incremental audit plan is incomplete")
        expected_bootstrap = base_commit is None
        if (
            not isinstance(plan.get("bootstrap"), bool)
            or plan["bootstrap"] != expected_bootstrap
        ):
            raise AuditStateError("Incremental audit plan has invalid bootstrap state")
        expected_changed_checks = changed_check_plans(
            repo_root,
            current_ranges,
            base_commit,
            plan["head_commit"],
        )
        if changed_checks != expected_changed_checks:
            raise AuditStateError(
                "Incremental audit plan does not exactly cover changed files"
            )
        range_limit = validated_plan_range_limit(plan, len(current_ranges))
        expected_legacy_ranges = rotation_range_plans(
            reconciled,
            current_ranges,
            range_limit,
        )
        if legacy_ranges != expected_legacy_ranges:
            raise AuditStateError(
                "Incremental audit plan does not exactly match rotation ranges"
            )
        if plan.get("full_ranges") != []:
            raise AuditStateError("Incremental audit plan has unexpected full_ranges")
        ranges_to_complete = legacy_ranges
        changed_ruleset_revisions = sorted(
            {item["ruleset_revision"] for item in changed_checks}
        )
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
        "checked_ruleset_revisions": changed_ruleset_revisions,
        "checked_through_commit": head_commit,
    }
    reconciled = reconcile_state(reconciled, current_ranges)
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
    state: dict[str, Any],
    current_ranges: dict[str, dict[str, Any]],
    *,
    rotation_days: int = DEFAULT_ROTATION_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a concise state summary."""
    if rotation_days < 1:
        raise AuditStateError("--rotation-days must be at least 1")
    reconciled = reconcile_state(state, current_ranges)
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=rotation_days)
    checked_times: list[tuple[str, datetime]] = []
    never_checked = 0
    overdue = 0
    stale = 0
    for range_name, current_range in current_ranges.items():
        checkpoint = reconciled["ranges"][range_name]
        checked_at = checkpoint.get("checked_at")
        if checked_at is None:
            never_checked += 1
            overdue += 1
            continue
        try:
            checked_time = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise AuditStateError(
                f"Range checkpoint has an invalid checked_at: {range_name}"
            ) from exc
        checked_times.append((checked_at, checked_time))
        ruleset_stale = (
            checkpoint.get("checked_ruleset_revision")
            != current_range["ruleset_revision"]
        )
        if ruleset_stale:
            stale += 1
        if ruleset_stale or checked_time < cutoff:
            overdue += 1
    oldest_checked_at = (
        min(checked_times, key=lambda item: item[1])[0] if checked_times else None
    )
    max_range_age_days = (
        round(
            (
                current_time - min(checked_times, key=lambda item: item[1])[1]
            ).total_seconds()
            / 86400,
            2,
        )
        if checked_times
        else None
    )
    return {
        "change_checkpoint": reconciled["change_checkpoint"],
        "checked_within_rotation_ranges": len(current_ranges) - overdue,
        "current_ranges": len(current_ranges),
        "max_range_age_days": max_range_age_days,
        "never_checked_ranges": never_checked,
        "oldest_checked_at": oldest_checked_at,
        "overdue_ranges": overdue,
        "rotation_range_limit": math.ceil(len(current_ranges) / rotation_days),
        "rotation_target_days": rotation_days,
        "stale_ranges": stale,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "sync", help="Reconcile current ranges without marking checks"
    )
    status_parser = subparsers.add_parser(
        "status", help="Summarize current checkpoint coverage"
    )
    status_parser.add_argument(
        "--rotation-days",
        type=int,
        default=DEFAULT_ROTATION_DAYS,
        help=(
            "Rotation target used for coverage status "
            f"(default: {DEFAULT_ROTATION_DAYS})"
        ),
    )

    plan_parser = subparsers.add_parser("plan", help="Create a disposable audit plan")
    plan_parser.add_argument("--mode", choices=("full", "incremental"), required=True)
    limit_group = plan_parser.add_mutually_exclusive_group()
    limit_group.add_argument(
        "--range-limit",
        type=int,
        help="Fixed number of full ranges selected in incremental mode",
    )
    limit_group.add_argument(
        "--rotation-days",
        type=int,
        help=(
            "Target days for one full range rotation in incremental mode "
            f"(default: {DEFAULT_ROTATION_DAYS})"
        ),
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
            emit_json(
                status_summary(
                    state,
                    current_ranges,
                    rotation_days=args.rotation_days,
                )
            )
            return 0
        if args.command == "plan":
            plan = build_plan(
                repo_root,
                state_path,
                mode=args.mode,
                range_limit=args.range_limit,
                rotation_days=args.rotation_days,
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
                    "range_limit": plan.get("range_limit"),
                    "rotation_days": plan.get("rotation_days"),
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
