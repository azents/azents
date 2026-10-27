#!/usr/bin/env python3
"""Plan and checkpoint bounded Living Spec audits."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, TypedDict

SCHEMA_VERSION = 1
DEFAULT_STATE_PATH = ".claude/living-spec-audit-state.json"
STATE_PATH_TO_EXCLUDE = PurePosixPath(DEFAULT_STATE_PATH)
SPEC_ROOT = PurePosixPath("docs/azents/spec")
DEFAULT_ROTATION_DAYS = 14
RANGE_BUCKET_COUNT = 32
LIST_ITEM_PATTERN = re.compile(r"\s+-\s+(.+)")


class AuditStateError(Exception):
    """Raised when an audit plan or state cannot be used safely."""


@dataclass(frozen=True)
class LivingSpec:
    """One Living Spec and its implementation path declarations."""

    path: str
    code_paths: tuple[str, ...]


@dataclass(frozen=True)
class AuditScope:
    """Current bounded audit ranges and structural path findings."""

    ranges: dict[str, dict[str, Any]]
    missing_code_paths: tuple[dict[str, str], ...]
    specs: tuple[LivingSpec, ...]


@dataclass(frozen=True)
class ChangedPaths:
    """Current and deleted paths changed between two commits."""

    current: tuple[str, ...]
    deleted: tuple[str, ...]


class ChangeCheckpoint(TypedDict):
    checked_at: str | None
    checked_through_commit: str | None


class RangeCheckpoint(ChangeCheckpoint):
    checked_scope_revision: str | None


class AuditState(TypedDict):
    """Validated persisted Living Spec audit state."""

    schema_version: int
    change_checkpoint: ChangeCheckpoint
    ranges: dict[str, RangeCheckpoint]


class PlannedRange(TypedDict):
    file_count: int
    file_specs: dict[str, list[str]]
    files: list[str]
    name: str
    reason: str
    scope_revision: str
    specs: list[str]
    unmapped_files: list[str]


class DeletedCheck(TypedDict):
    path: str
    specs: list[str]
    unmapped: bool


class MissingCodePath(TypedDict):
    pattern: str
    spec: str


class AuditPlan(TypedDict, total=False):
    """Validated disposable Living Spec audit execution plan."""

    schema_version: int
    change_checkpoint_before: str | None
    generated_at: str
    head_commit: str
    missing_code_paths: list[MissingCodePath]
    mode: str
    state_sha256: str
    plan_sha256: str
    bootstrap: bool
    changed_checks: list[PlannedRange]
    changed_specs: list[str]
    deleted_checks: list[DeletedCheck]
    deleted_specs: list[str]
    full_ranges: list[PlannedRange]
    range_limit: int
    rotation_days: int | None
    rotation_ranges: list[PlannedRange]


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


def empty_state() -> AuditState:
    """Return an empty versioned audit state."""
    return {
        "schema_version": SCHEMA_VERSION,
        "change_checkpoint": {
            "checked_at": None,
            "checked_through_commit": None,
        },
        "ranges": {},
    }


def _checkpoint_fields(value: object, fields: set[str]) -> dict[str, Any]:
    """Validate exact fields and nullable values before planner use."""
    if not isinstance(value, dict) or set(value) != fields:
        raise AuditStateError("Audit checkpoint has unknown or missing fields")
    for field in fields:
        item = value[field]
        if item is not None and (not isinstance(item, str) or not item.strip()):
            raise AuditStateError(f"Audit checkpoint has invalid {field}")
    timestamp = value["checked_at"]
    if timestamp is not None:
        try:
            parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AuditStateError("Audit checkpoint has invalid checked_at") from exc
        if parsed.tzinfo is None:
            raise AuditStateError("Audit checkpoint checked_at must include timezone")
    return value


def load_state(state_path: Path) -> AuditState:
    """Load and validate the audit state."""
    if not state_path.exists():
        return empty_state()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditStateError(f"Cannot read state file: {exc}") from exc
    if not isinstance(state, dict):
        raise AuditStateError("Audit state must be a JSON object")
    if set(state) != {"schema_version", "change_checkpoint", "ranges"}:
        raise AuditStateError("Audit state has unknown or missing fields")
    if (
        type(state.get("schema_version")) is not int
        or state["schema_version"] != SCHEMA_VERSION
    ):
        raise AuditStateError(
            f"Unsupported audit state schema: {state.get('schema_version')!r}"
        )
    checkpoint = state.get("change_checkpoint")
    ranges = state.get("ranges")
    checkpoint = _checkpoint_fields(
        checkpoint, {"checked_at", "checked_through_commit"}
    )
    if not isinstance(ranges, dict):
        raise AuditStateError("Audit state is missing ranges")
    decoded_ranges: dict[str, RangeCheckpoint] = {}
    for range_name, range_checkpoint in ranges.items():
        if not isinstance(range_name, str) or not range_name:
            raise AuditStateError("Audit state has an invalid range checkpoint")
        value = _checkpoint_fields(
            range_checkpoint,
            {"checked_at", "checked_through_commit", "checked_scope_revision"},
        )
        decoded_ranges[range_name] = RangeCheckpoint(
            checked_at=value["checked_at"],
            checked_through_commit=value["checked_through_commit"],
            checked_scope_revision=value["checked_scope_revision"],
        )
    return AuditState(
        schema_version=SCHEMA_VERSION,
        change_checkpoint=ChangeCheckpoint(
            checked_at=checkpoint["checked_at"],
            checked_through_commit=checkpoint["checked_through_commit"],
        ),
        ranges=decoded_ranges,
    )


def _plan_object(value: object, fields: set[str]) -> dict[str, object]:
    """Validate one exact JSON object at the plan boundary."""
    if not isinstance(value, dict) or set(value) != fields:
        raise AuditStateError("Audit plan has unknown or missing fields")
    return {key: value[key] for key in fields}


def _plan_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuditStateError("Audit plan requires a nonempty string")
    return value


def _plan_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise AuditStateError("Audit plan requires a list")
    return list(value)


def _plan_texts(value: object) -> list[str]:
    return [_plan_text(item) for item in _plan_list(value)]


def _plan_integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise AuditStateError("Audit plan requires a nonnegative integer")
    return value


def _plan_flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise AuditStateError("Audit plan requires a boolean")
    return value


def _decode_planned_range(value: object) -> PlannedRange:
    raw = _plan_object(
        value,
        {
            "file_count",
            "file_specs",
            "files",
            "name",
            "reason",
            "scope_revision",
            "specs",
            "unmapped_files",
        },
    )
    file_specs = raw["file_specs"]
    if not isinstance(file_specs, dict):
        raise AuditStateError("Audit plan requires a file-to-spec mapping")
    decoded_specs = {
        _plan_text(path): _plan_texts(specs) for path, specs in file_specs.items()
    }
    return PlannedRange(
        file_count=_plan_integer(raw["file_count"]),
        file_specs=decoded_specs,
        files=_plan_texts(raw["files"]),
        name=_plan_text(raw["name"]),
        reason=_plan_text(raw["reason"]),
        scope_revision=_plan_text(raw["scope_revision"]),
        specs=_plan_texts(raw["specs"]),
        unmapped_files=_plan_texts(raw["unmapped_files"]),
    )


def _decode_deleted_check(value: object) -> DeletedCheck:
    raw = _plan_object(value, {"path", "specs", "unmapped"})
    return DeletedCheck(
        path=_plan_text(raw["path"]),
        specs=_plan_texts(raw["specs"]),
        unmapped=_plan_flag(raw["unmapped"]),
    )


def _decode_missing_path(value: object) -> MissingCodePath:
    raw = _plan_object(value, {"pattern", "spec"})
    return MissingCodePath(
        pattern=_plan_text(raw["pattern"]), spec=_plan_text(raw["spec"])
    )


def load_plan(plan_path: Path) -> AuditPlan:
    """Decode the complete plan shape before any completion logic consumes it."""
    try:
        value = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AuditStateError(f"Cannot read plan file: {exc}") from exc
    if not isinstance(value, dict) or value.get("mode") not in ("full", "incremental"):
        raise AuditStateError("Unsupported or invalid audit plan")
    mode = value["mode"]
    fields = {
        "bootstrap",
        "change_checkpoint_before",
        "changed_checks",
        "changed_specs",
        "deleted_checks",
        "deleted_specs",
        "full_ranges",
        "generated_at",
        "head_commit",
        "missing_code_paths",
        "mode",
        "plan_sha256",
        "rotation_ranges",
        "schema_version",
        "state_sha256",
    }
    if mode == "incremental":
        fields |= {"range_limit", "rotation_days"}
    raw = _plan_object(value, fields)
    if _plan_integer(raw["schema_version"]) != SCHEMA_VERSION:
        raise AuditStateError("Unsupported or invalid audit plan")
    generated_at = _plan_text(raw["generated_at"])
    try:
        generated_time = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditStateError("Audit plan has invalid generated_at") from exc
    if generated_time.tzinfo is None:
        raise AuditStateError("Audit plan generated_at must include timezone")
    checkpoint = raw["change_checkpoint_before"]
    plan = AuditPlan(
        schema_version=SCHEMA_VERSION,
        bootstrap=_plan_flag(raw["bootstrap"]),
        change_checkpoint_before=None if checkpoint is None else _plan_text(checkpoint),
        generated_at=generated_at,
        head_commit=_plan_text(raw["head_commit"]),
        mode=mode,
        state_sha256=_plan_text(raw["state_sha256"]),
        plan_sha256=_plan_text(raw["plan_sha256"]),
        changed_checks=[
            _decode_planned_range(item) for item in _plan_list(raw["changed_checks"])
        ],
        changed_specs=_plan_texts(raw["changed_specs"]),
        deleted_checks=[
            _decode_deleted_check(item) for item in _plan_list(raw["deleted_checks"])
        ],
        deleted_specs=_plan_texts(raw["deleted_specs"]),
        full_ranges=[
            _decode_planned_range(item) for item in _plan_list(raw["full_ranges"])
        ],
        missing_code_paths=[
            _decode_missing_path(item) for item in _plan_list(raw["missing_code_paths"])
        ],
        rotation_ranges=[
            _decode_planned_range(item) for item in _plan_list(raw["rotation_ranges"])
        ],
    )
    if mode == "incremental":
        plan["range_limit"] = _plan_integer(raw["range_limit"])
        days = raw["rotation_days"]
        plan["rotation_days"] = None if days is None else _plan_integer(days)
    return plan


def serialize_json(value: Mapping[str, Any]) -> str:
    """Serialize JSON deterministically."""
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def emit_json(value: dict[str, Any]) -> None:
    """Write one compact JSON object to stdout."""
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")


def write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
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


def plan_sha256(plan: Mapping[str, Any]) -> str:
    """Hash a plan payload without its embedded integrity field."""
    payload = dict(plan)
    payload.pop("plan_sha256", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Attach a deterministic integrity hash to a completed plan."""
    plan["plan_sha256"] = plan_sha256(plan)
    return plan


def parse_code_paths(spec_text: str, spec_path: str) -> tuple[str, ...]:
    """Parse the `code_paths` list from Living Spec frontmatter."""
    lines = spec_text.splitlines()
    if not lines or lines[0] != "---":
        raise AuditStateError(f"Living Spec has no frontmatter: {spec_path}")
    code_paths: list[str] = []
    in_code_paths = False
    for line in lines[1:]:
        if line == "---":
            break
        if line == "code_paths:":
            in_code_paths = True
            continue
        if in_code_paths:
            match = LIST_ITEM_PATTERN.fullmatch(line)
            if match:
                code_paths.append(match.group(1).strip().strip("'\""))
                continue
            if line and not line.startswith((" ", "\t")):
                in_code_paths = False
    code_paths = list(dict.fromkeys(code_paths))
    if not code_paths:
        raise AuditStateError(f"Living Spec has no code_paths: {spec_path}")
    return tuple(code_paths)


def load_living_specs(repo_root: Path) -> tuple[LivingSpec, ...]:
    """Load current domain and flow Living Specs."""
    spec_root = repo_root / SPEC_ROOT
    specs: list[LivingSpec] = []
    for spec_dir in ("domain", "flow"):
        for spec_path in sorted((spec_root / spec_dir).glob("*.md")):
            relative_path = spec_path.relative_to(repo_root).as_posix()
            specs.append(
                LivingSpec(
                    path=relative_path,
                    code_paths=parse_code_paths(
                        spec_path.read_text(encoding="utf-8"),
                        relative_path,
                    ),
                )
            )
    if not specs:
        raise AuditStateError("No Living Specs found under docs/azents/spec")
    return tuple(specs)


def path_matches(path: str, pattern: str) -> bool:
    """Return whether a repository path matches a `code_paths` pattern."""
    if pattern == "**":
        return True
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        if "*" not in prefix and "?" not in prefix:
            return path == prefix or path.startswith(f"{prefix}/")
        # Bracketed Next.js route directories are literal names, not character
        # classes. Only * and ? are wildcards in recursive directory prefixes.
        expression = re.escape(prefix).replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
        return re.fullmatch(rf"{expression}(?:/.*)?", path) is not None
    return PurePosixPath(path).match(pattern)


def tracked_files(repo_root: Path) -> tuple[str, ...]:
    """Return current tracked repository files."""
    output = run_git(repo_root, "ls-files", "-z")
    return tuple(
        path
        for path in output.split("\0")
        if path and PurePosixPath(path) != STATE_PATH_TO_EXCLUDE
    )


def is_default_implementation_path(path: str) -> bool:
    """Return whether a path belongs to the default product implementation scope."""
    if path.startswith("python/apps/"):
        return any(segment in path for segment in ("/src/", "/db-schemas/", "/bin/"))
    if path.startswith("python/libs/"):
        if path.startswith(
            (
                "python/libs/azents-admin-client/",
                "python/libs/azents-public-client/",
            )
        ):
            return False
        return "/src/" in path
    return path.startswith(
        (
            "typescript/apps/",
            "infra/charts/azents/",
            "proto/azents/",
        )
    )


def audit_base_range_for_path(path: str) -> str:
    """Return the human-readable base range for one implementation path."""
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
    """Assign an implementation path to a deterministic bounded range."""
    base_range = audit_base_range_for_path(path)
    bucket = int(hashlib.sha256(path.encode()).hexdigest()[:8], 16)
    bucket_number = bucket % RANGE_BUCKET_COUNT + 1
    return f"{base_range}::bucket-{bucket_number}-of-{RANGE_BUCKET_COUNT}"


def scope_revision(
    range_files: tuple[str, ...],
    file_specs: dict[str, list[str]],
    spec_by_path: dict[str, LivingSpec],
) -> str:
    """Hash one range's file-to-spec scope declarations."""
    digest = hashlib.sha256()
    for file_path in range_files:
        digest.update(file_path.encode())
        digest.update(b"\0")
        digest.update(json.dumps(file_specs[file_path], sort_keys=True).encode())
        digest.update(b"\0")
    matched_specs = {item for values in file_specs.values() for item in values}
    for spec_path in sorted(matched_specs):
        digest.update(spec_path.encode())
        digest.update(b"\0")
        digest.update(
            json.dumps(spec_by_path[spec_path].code_paths, sort_keys=True).encode()
        )
        digest.update(b"\0")
    return digest.hexdigest()


def discover_audit_scope(repo_root: Path) -> AuditScope:
    """Discover current bounded implementation ranges and structural drift."""
    specs = load_living_specs(repo_root)
    spec_by_path = {spec.path: spec for spec in specs}
    files = tracked_files(repo_root)
    file_specs: dict[str, list[str]] = {path: [] for path in files}
    covered_files: set[str] = set()
    missing_code_paths: list[dict[str, str]] = []

    for spec in specs:
        for pattern in spec.code_paths:
            matches = tuple(path for path in files if path_matches(path, pattern))
            if not matches:
                missing_code_paths.append({"pattern": pattern, "spec": spec.path})
                continue
            covered_files.update(matches)
            for path in matches:
                file_specs[path].append(spec.path)

    candidate_files = sorted(covered_files)
    files_by_range: dict[str, list[str]] = {}
    for path in candidate_files:
        files_by_range.setdefault(audit_range_for_path(path), []).append(path)

    ranges: dict[str, dict[str, Any]] = {}
    for range_name, range_file_list in sorted(files_by_range.items()):
        range_files = tuple(sorted(range_file_list))
        range_file_specs = {path: sorted(file_specs[path]) for path in range_files}
        matched_specs = sorted(
            {spec_path for values in range_file_specs.values() for spec_path in values}
        )
        ranges[range_name] = {
            "file_count": len(range_files),
            "file_specs": range_file_specs,
            "files": list(range_files),
            "scope_revision": scope_revision(
                range_files,
                range_file_specs,
                spec_by_path,
            ),
            "specs": matched_specs,
            "unmapped_files": [
                path for path in range_files if not range_file_specs[path]
            ],
        }

    return AuditScope(
        ranges=ranges,
        missing_code_paths=tuple(
            sorted(
                missing_code_paths,
                key=lambda item: (item["spec"], item["pattern"]),
            )
        ),
        specs=specs,
    )


def empty_range_checkpoint() -> RangeCheckpoint:
    """Return an unchecked range checkpoint."""
    return {
        "checked_at": None,
        "checked_scope_revision": None,
        "checked_through_commit": None,
    }


def reconcile_state(
    state: Mapping[str, Any],
    current_ranges: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Add current ranges, prune removed ranges, and preserve checkpoints."""
    existing_ranges = state["ranges"]
    return {
        "schema_version": SCHEMA_VERSION,
        "change_checkpoint": {
            "checked_at": state["change_checkpoint"].get("checked_at"),
            "checked_through_commit": state["change_checkpoint"].get(
                "checked_through_commit"
            ),
        },
        "ranges": {
            range_name: existing_ranges.get(range_name, empty_range_checkpoint())
            for range_name in sorted(current_ranges)
        },
    }


def current_head(repo_root: Path) -> str:
    """Return the current HEAD commit."""
    return run_git(repo_root, "rev-parse", "HEAD").strip()


def ensure_tracked_tree_clean(repo_root: Path) -> None:
    """Reject planning and completion from a dirty tracked checkout."""
    status = run_git(repo_root, "status", "--porcelain", "--untracked-files=no")
    if status:
        raise AuditStateError(
            "Tracked working-tree or index changes exist; use a clean audit checkout"
        )


def range_plan(
    range_name: str,
    current_range: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Return one exact bounded range inspection plan."""
    return {
        "file_count": current_range["file_count"],
        "file_specs": current_range["file_specs"],
        "files": current_range["files"],
        "name": range_name,
        "reason": reason,
        "scope_revision": current_range["scope_revision"],
        "specs": current_range["specs"],
        "unmapped_files": current_range["unmapped_files"],
    }


def changed_range_plan(
    range_name: str,
    current_range: dict[str, Any],
    files: list[str],
) -> dict[str, Any]:
    """Return one exact changed-file inspection plan."""
    selected_files = sorted(files)
    selected_file_specs = {
        path: current_range["file_specs"][path] for path in selected_files
    }
    return {
        "file_count": len(selected_files),
        "file_specs": selected_file_specs,
        "files": selected_files,
        "name": range_name,
        "reason": "changed_files",
        "scope_revision": current_range["scope_revision"],
        "specs": sorted(
            {spec for values in selected_file_specs.values() for spec in values}
        ),
        "unmapped_files": [
            path for path in selected_files if not selected_file_specs[path]
        ],
    }


def changed_paths_in_day(
    repo_root: Path, head_commit: str, generated_at: str
) -> ChangedPaths:
    """Collect paths touched by commits in the 24 hours ending at planning time."""
    try:
        end = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditStateError("Invalid plan time") from exc
    if end.tzinfo is None:
        raise AuditStateError("Plan time must include timezone")
    start = end - timedelta(hours=24)
    commits = run_git(
        repo_root,
        "log",
        "--since-as-filter=" + start.isoformat(),
        "--until=" + end.isoformat(),
        "--format=%H",
        head_commit,
    ).splitlines()
    touched: set[str] = set()
    for commit in commits:
        output = run_git(
            repo_root,
            "diff-tree",
            "--root",
            "--first-parent",
            "-m",
            "-r",
            "--no-commit-id",
            "--no-renames",
            "--name-only",
            "-z",
            commit,
        )
        touched.update(path for path in output.split("\0") if path)
    touched.discard(str(STATE_PATH_TO_EXCLUDE))
    current = set(tracked_files(repo_root))
    return ChangedPaths(
        current=tuple(sorted(touched & current)),
        deleted=tuple(sorted(touched - current)),
    )


def is_living_spec_path(path: str) -> bool:
    """Return whether a path is a domain or flow Living Spec."""
    pure_path = PurePosixPath(path)
    return (
        len(pure_path.parts) == 5
        and pure_path.parts[:3] == SPEC_ROOT.parts
        and pure_path.parts[3] in {"domain", "flow"}
        and pure_path.suffix == ".md"
    )


def specs_for_path(path: str, specs: tuple[LivingSpec, ...]) -> list[str]:
    """Return Living Specs whose current declarations match a path."""
    return sorted(
        spec.path
        for spec in specs
        if any(path_matches(path, pattern) for pattern in spec.code_paths)
    )


def changed_work_plans(
    scope: AuditScope,
    changes: ChangedPaths,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]]:
    """Return exact changed implementation and Living Spec work."""
    spec_by_path = {spec.path: spec for spec in scope.specs}
    changed_by_range: dict[str, dict[str, list[str]]] = {}
    changed_specs: list[str] = []
    for path in changes.current:
        if is_living_spec_path(path):
            changed_specs.append(path)
            continue
        matched_specs = specs_for_path(path, scope.specs)
        if not is_default_implementation_path(path) and not matched_specs:
            continue
        range_name = audit_range_for_path(path)
        changed_by_range.setdefault(range_name, {})[path] = matched_specs

    deleted_checks = []
    deleted_specs = []
    for path in changes.deleted:
        if is_living_spec_path(path):
            deleted_specs.append(path)
            continue
        matched_specs = specs_for_path(path, scope.specs)
        if is_default_implementation_path(path) or matched_specs:
            deleted_checks.append(
                {
                    "path": path,
                    "specs": matched_specs,
                    "unmapped": not matched_specs,
                }
            )

    changed_checks = []
    for range_name, changed_file_specs in sorted(changed_by_range.items()):
        changed_files = tuple(sorted(changed_file_specs))
        current_range = {
            "file_count": len(changed_files),
            "file_specs": changed_file_specs,
            "files": list(changed_files),
            "scope_revision": scope_revision(
                changed_files,
                changed_file_specs,
                spec_by_path,
            ),
            "specs": sorted(
                {spec for values in changed_file_specs.values() for spec in values}
            ),
            "unmapped_files": [
                path for path in changed_files if not changed_file_specs[path]
            ],
        }
        changed_checks.append(
            changed_range_plan(
                range_name,
                current_range,
                list(changed_files),
            )
        )
    return (
        changed_checks,
        sorted(changed_specs),
        sorted(deleted_checks, key=lambda item: item["path"]),
        sorted(deleted_specs),
    )


def rotation_reason(
    checkpoint: Mapping[str, Any],
    current_range: dict[str, Any],
) -> tuple[int, str]:
    """Return priority and reason for one recurring range."""
    if checkpoint.get("checked_at") is None:
        return 0, "never_checked"
    if checkpoint.get("checked_scope_revision") != current_range["scope_revision"]:
        return 1, "scope_changed"
    return 2, "least_recently_checked"


def resolve_rotation_limit(
    range_count: int,
    *,
    range_limit: int | None,
    rotation_days: int | None,
) -> tuple[int, int | None]:
    """Select one existing range without expanding work for a rotation target."""
    if (
        isinstance(range_limit, bool)
        or range_limit not in ((None, 0, 1) if range_count == 0 else (None, 1))
        or rotation_days is not None
    ):
        raise AuditStateError("Incremental audits select exactly one range")
    return min(1, range_count), None


def rotation_range_plans(
    reconciled: dict[str, Any],
    current_ranges: dict[str, dict[str, Any]],
    range_limit: int,
) -> list[dict[str, Any]]:
    """Return prioritized bounded ranges for one recurring audit."""
    candidates = []
    for range_name, current_range in current_ranges.items():
        checkpoint = reconciled["ranges"][range_name]
        priority, reason = rotation_reason(checkpoint, current_range)
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


def validated_plan_range_limit(plan: Mapping[str, Any], range_count: int) -> int:
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
    expected_limit, expected_days = resolve_rotation_limit(
        range_count,
        range_limit=range_limit if rotation_days is None else None,
        rotation_days=rotation_days,
    )
    if range_limit != expected_limit or rotation_days != expected_days:
        raise AuditStateError("Incremental audit plan has inconsistent rotation limit")
    return range_limit


def relevant_missing_paths(
    scope: AuditScope, plan: Mapping[str, Any]
) -> list[dict[str, str]]:
    """Limit structural findings to the selected range and daily changes."""
    specs = set(plan["changed_specs"])
    for item in (
        *plan["rotation_ranges"],
        *plan["changed_checks"],
        *plan["deleted_checks"],
    ):
        specs.update(item["specs"])
    return [item for item in scope.missing_code_paths if item["spec"] in specs]


def build_plan(
    repo_root: Path,
    state_path: Path,
    *,
    mode: str,
    range_limit: int | None,
    rotation_days: int | None,
) -> dict[str, Any]:
    """Build a full or incremental Living Spec audit plan."""
    ensure_tracked_tree_clean(repo_root)
    state = load_state(state_path)
    scope = discover_audit_scope(repo_root)
    reconciled = reconcile_state(state, scope.ranges)
    head_commit = current_head(repo_root)
    plan: dict[str, Any] = {
        "change_checkpoint_before": reconciled["change_checkpoint"].get(
            "checked_through_commit"
        ),
        "generated_at": utc_now(),
        "head_commit": head_commit,
        "missing_code_paths": list(scope.missing_code_paths),
        "mode": mode,
        "schema_version": SCHEMA_VERSION,
        "state_sha256": file_sha256(state_path),
    }

    if mode == "full":
        if range_limit is not None or rotation_days is not None:
            raise AuditStateError(
                "--range-limit and --rotation-days apply only to incremental mode"
            )
        plan.update(
            {
                "bootstrap": False,
                "changed_checks": [],
                "changed_specs": [],
                "deleted_checks": [],
                "deleted_specs": [],
                "full_ranges": [
                    range_plan(range_name, current_range, "full_audit")
                    for range_name, current_range in scope.ranges.items()
                ],
                "rotation_ranges": [],
            }
        )
        return seal_plan(plan)

    resolved_limit, _ = resolve_rotation_limit(
        len(scope.ranges),
        range_limit=range_limit,
        rotation_days=rotation_days,
    )
    changed_checks, changed_specs, deleted_checks, deleted_specs = changed_work_plans(
        scope,
        changed_paths_in_day(repo_root, head_commit, plan["generated_at"]),
    )
    plan.update(
        {
            "bootstrap": False,
            "changed_checks": changed_checks,
            "changed_specs": changed_specs,
            "deleted_checks": deleted_checks,
            "deleted_specs": deleted_specs,
            "full_ranges": [],
            "range_limit": resolved_limit,
            "rotation_days": None,
            "rotation_ranges": rotation_range_plans(
                reconciled,
                scope.ranges,
                resolved_limit,
            ),
        }
    )
    plan["missing_code_paths"] = relevant_missing_paths(scope, plan)
    return seal_plan(plan)


def complete_plan(repo_root: Path, state_path: Path, plan_path: Path) -> None:
    """Advance state after one successfully executed exact plan."""
    ensure_tracked_tree_clean(repo_root)
    plan = load_plan(plan_path)
    if plan.get("plan_sha256") != plan_sha256(plan):
        raise AuditStateError("Audit plan payload changed after planning")
    if plan.get("state_sha256") != file_sha256(state_path):
        raise AuditStateError("Audit state changed after this plan was created")
    if plan.get("head_commit") != current_head(repo_root):
        raise AuditStateError("Repository HEAD changed after this plan was created")

    state = load_state(state_path)
    scope = discover_audit_scope(repo_root)
    reconciled = reconcile_state(state, scope.ranges)
    expected_missing = (
        relevant_missing_paths(scope, plan)
        if plan["mode"] == "incremental"
        else list(scope.missing_code_paths)
    )
    if plan.get("missing_code_paths") != expected_missing:
        raise AuditStateError("Living Spec code_paths changed after planning")

    mode = plan.get("mode")
    if mode == "full":
        expected_ranges = [
            range_plan(range_name, current_range, "full_audit")
            for range_name, current_range in scope.ranges.items()
        ]
        if (
            plan.get("full_ranges") != expected_ranges
            or plan.get("rotation_ranges") != []
            or plan.get("changed_checks") != []
            or plan.get("changed_specs") != []
            or plan.get("deleted_checks") != []
            or plan.get("deleted_specs") != []
            or plan.get("bootstrap") is not False
        ):
            raise AuditStateError(
                "Full audit plan does not exactly match current scope"
            )
        ranges_to_complete = expected_ranges
    elif mode == "incremental":
        expected_work = changed_work_plans(
            scope,
            changed_paths_in_day(repo_root, plan["head_commit"], plan["generated_at"]),
        )
        if (
            plan.get("bootstrap") is not False
            or plan.get("changed_checks") != expected_work[0]
            or plan.get("changed_specs") != expected_work[1]
            or plan.get("deleted_checks") != expected_work[2]
            or plan.get("deleted_specs") != expected_work[3]
            or plan.get("full_ranges") != []
        ):
            raise AuditStateError(
                "Incremental audit plan does not exactly cover changed work"
            )
        range_limit = validated_plan_range_limit(plan, len(scope.ranges))
        if (
            range_limit != min(1, len(scope.ranges))
            or plan.get("rotation_days") is not None
        ):
            raise AuditStateError("Incremental audits select exactly one range")
        expected_ranges = rotation_range_plans(
            reconciled,
            scope.ranges,
            range_limit,
        )
        if plan.get("rotation_ranges") != expected_ranges:
            raise AuditStateError(
                "Incremental audit plan does not exactly match rotation ranges"
            )
        ranges_to_complete = expected_ranges
    else:
        raise AuditStateError(f"Unknown audit mode: {mode!r}")

    completed_at = utc_now()
    head_commit = plan["head_commit"]
    for planned_range in ranges_to_complete:
        state["ranges"][planned_range["name"]] = {
            "checked_at": completed_at,
            "checked_scope_revision": planned_range["scope_revision"],
            "checked_through_commit": head_commit,
        }
    write_json_atomic(state_path, state)
    emit_json(
        {
            "change_checkpoint": state["change_checkpoint"]["checked_through_commit"],
            "completed_at": completed_at,
            "mode": mode,
            "ranges_completed": len(ranges_to_complete),
        }
    )


def status_summary(
    state: Mapping[str, Any],
    scope: AuditScope,
    *,
    rotation_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a concise coverage and structural-drift summary."""
    if rotation_days < 1:
        raise AuditStateError("--rotation-days must be at least 1")
    reconciled = reconcile_state(state, scope.ranges)
    current_time = now or datetime.now(UTC)
    cutoff = current_time - timedelta(days=rotation_days)
    checked_times: list[datetime] = []
    never_checked = 0
    stale = 0
    overdue = 0
    for range_name, current_range in scope.ranges.items():
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
        checked_times.append(checked_time)
        scope_stale = (
            checkpoint.get("checked_scope_revision") != current_range["scope_revision"]
        )
        if scope_stale:
            stale += 1
        if scope_stale or checked_time < cutoff:
            overdue += 1
    oldest = min(checked_times) if checked_times else None
    return {
        "change_checkpoint": reconciled["change_checkpoint"],
        "checked_within_rotation_ranges": len(scope.ranges) - overdue,
        "current_ranges": len(scope.ranges),
        "max_range_age_days": (
            round((current_time - oldest).total_seconds() / 86400, 2)
            if oldest
            else None
        ),
        "missing_code_paths": len(scope.missing_code_paths),
        "never_checked_ranges": never_checked,
        "overdue_ranges": overdue,
        "rotation_range_limit": 1,
        "daily_rotation_days": len(scope.ranges),
        "overdue_threshold_days": rotation_days,
        "stale_ranges": stale,
    }


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "sync",
        help="Reconcile current ranges without marking checks",
    )
    status_parser = subparsers.add_parser(
        "status",
        help="Summarize current checkpoint coverage",
    )
    status_parser.add_argument(
        "--rotation-days",
        type=int,
        default=DEFAULT_ROTATION_DAYS,
    )

    plan_parser = subparsers.add_parser(
        "plan",
        help="Create a disposable exact audit plan",
    )
    plan_parser.add_argument(
        "--mode",
        choices=("full", "incremental"),
        required=True,
    )
    limit_group = plan_parser.add_mutually_exclusive_group()
    limit_group.add_argument("--range-limit", type=int)
    limit_group.add_argument("--rotation-days", type=int)
    plan_parser.add_argument("--output", type=Path, required=True)

    complete_parser = subparsers.add_parser(
        "complete",
        help="Advance state after successful inspection and reporting",
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
        scope = discover_audit_scope(repo_root)

        if args.command == "sync":
            reconciled = reconcile_state(state, scope.ranges)
            write_json_atomic(state_path, reconciled)
            emit_json(
                status_summary(
                    reconciled,
                    scope,
                    rotation_days=DEFAULT_ROTATION_DAYS,
                )
            )
            return 0
        if args.command == "status":
            emit_json(
                status_summary(
                    state,
                    scope,
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
                    "changed_specs": len(plan["changed_specs"]),
                    "deleted_checks": len(plan["deleted_checks"]),
                    "full_ranges": len(plan["full_ranges"]),
                    "head_commit": plan["head_commit"],
                    "missing_code_paths": len(plan["missing_code_paths"]),
                    "mode": plan["mode"],
                    "output": str(args.output),
                    "range_limit": plan.get("range_limit"),
                    "rotation_days": plan.get("rotation_days"),
                    "rotation_ranges": len(plan["rotation_ranges"]),
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
