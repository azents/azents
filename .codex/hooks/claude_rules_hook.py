#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import frontmatter


RULE_ROOT_NAMES = (".claude", ".opencode")
MAX_WALK_UP = 200
RULE_BODY_CAP_BYTES = 32 * 1024
TOTAL_CONTEXT_CAP_BYTES = 96 * 1024
STATE_TTL_SECONDS = 7 * 24 * 60 * 60
TRANSCRIPT_SHRINK_RATIO = 0.70


@dataclass(frozen=True)
class Rule:
    real_path: Path
    rel_path: str
    body: str
    paths: tuple[str, ...]
    glob_base: Path
    subtree_base: Path | None
    raw_hash: str

    @property
    def unconditional(self) -> bool:
        return not self.paths and self.subtree_base is None

    def matches(self, target: Path) -> bool:
        if self.paths:
            return any(
                _matches_glob(pattern, self.glob_base, target) for pattern in self.paths
            )
        if self.subtree_base is not None:
            return _is_under(target, self.subtree_base)
        return False

    @property
    def content_hash(self) -> str:
        return self.raw_hash


def _realpath(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        return path.absolute()


def _is_under(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _display_path(path: Path, project_root: Path, home: Path | None) -> str:
    if _is_under(path, project_root):
        return path.relative_to(project_root).as_posix()
    if home is not None and _is_under(path, home):
        return "~/" + path.relative_to(home).as_posix()
    return str(path)


def _parse_frontmatter(text: str) -> tuple[tuple[str, ...], str]:
    try:
        post = frontmatter.loads(text)
    except Exception:
        return (), text.strip()
    return _extract_paths(post.metadata), post.content.strip()


def _extract_paths(data: dict[Any, Any]) -> tuple[str, ...]:
    raw = data.get("paths")
    if isinstance(raw, str):
        return (raw,) if raw else ()
    if isinstance(raw, list):
        return tuple(item for item in raw if isinstance(item, str) and item)
    return ()


def _walk_markdown(start: Path, visited: set[Path]) -> list[Path]:
    results: list[Path] = []
    queue = [start]
    while queue:
        current = queue.pop()
        real = _realpath(current)
        if real in visited:
            continue
        visited.add(real)
        try:
            current.stat()
        except OSError:
            continue
        if current.is_dir():
            try:
                queue.extend(current.iterdir())
            except OSError:
                continue
        elif current.suffix == ".md":
            results.append(real)
    return results


def _load_rules_from_base(
    base_dir: Path,
    glob_base: Path,
    subtree_base: Path | None,
    project_root: Path,
    home: Path | None,
    visited: set[Path],
) -> list[Rule]:
    rules: list[Rule] = []
    for root_name in RULE_ROOT_NAMES:
        rules_dir = base_dir / root_name / "rules"
        if not rules_dir.exists():
            continue
        for markdown in _walk_markdown(rules_dir, visited):
            try:
                raw = markdown.read_text(encoding="utf-8")
            except OSError:
                continue
            paths, body = _parse_frontmatter(raw)
            rules.append(
                Rule(
                    real_path=markdown,
                    rel_path=_display_path(markdown, project_root, home),
                    body=body,
                    paths=paths,
                    glob_base=glob_base,
                    subtree_base=subtree_base,
                    raw_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                )
            )
    return rules


def _load_top_level_rules(project_root: Path, home: Path | None) -> list[Rule]:
    visited: set[Path] = set()
    rules: list[Rule] = []
    if home is not None and home != project_root:
        rules.extend(
            _load_rules_from_base(
                base_dir=home,
                glob_base=project_root,
                subtree_base=None,
                project_root=project_root,
                home=home,
                visited=visited,
            )
        )
    rules.extend(
        _load_rules_from_base(
            base_dir=project_root,
            glob_base=project_root,
            subtree_base=None,
            project_root=project_root,
            home=home,
            visited=visited,
        )
    )
    return rules


def _ancestors_for_target(target: Path, project_root: Path) -> list[Path]:
    if not _is_under(target, project_root):
        return []
    ancestors: list[Path] = []
    current = target if target.is_dir() else target.parent
    for _ in range(MAX_WALK_UP):
        ancestors.append(current)
        if current == project_root:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    return ancestors


def _load_nested_rules(
    targets: list[Path], project_root: Path, home: Path | None
) -> list[Rule]:
    rules: list[Rule] = []
    seen_ancestors: set[Path] = set()
    for target in targets:
        for ancestor in _ancestors_for_target(target, project_root):
            if ancestor == project_root or ancestor in seen_ancestors:
                continue
            seen_ancestors.add(ancestor)
            rules.extend(
                _load_rules_from_base(
                    base_dir=ancestor,
                    glob_base=ancestor,
                    subtree_base=ancestor,
                    project_root=project_root,
                    home=home,
                    visited=set(),
                )
            )
    return rules


def _matches_glob(pattern: str, base: Path, target: Path) -> bool:
    if os.path.isabs(pattern):
        return _match_glob(Path(pattern).as_posix(), target.as_posix())
    if not _is_under(target, base):
        return False
    rel = target.relative_to(base).as_posix()
    return _match_glob(pattern, rel)


def _match_glob(pattern: str, value: str) -> bool:
    return _match_glob_parts(
        tuple(part for part in pattern.split("/") if part),
        tuple(part for part in value.split("/") if part),
    )


def _match_glob_parts(
    pattern_parts: tuple[str, ...], value_parts: tuple[str, ...]
) -> bool:
    if not pattern_parts:
        return not value_parts
    head = pattern_parts[0]
    tail = pattern_parts[1:]
    if head == "**":
        if _match_glob_parts(tail, value_parts):
            return True
        return bool(value_parts) and _match_glob_parts(pattern_parts, value_parts[1:])
    if not value_parts:
        return False
    return fnmatch.fnmatchcase(value_parts[0], head) and _match_glob_parts(
        tail, value_parts[1:]
    )


def _rules_for_targets(project_root: Path, targets: list[Path]) -> list[Rule]:
    home = _realpath(Path.home())
    rules = _load_top_level_rules(project_root, home)
    rules.extend(_load_nested_rules(targets, project_root, home))

    selected: list[Rule] = []
    seen: set[Path] = set()
    for rule in rules:
        if not rule.unconditional or rule.real_path in seen:
            continue
        selected.append(rule)
        seen.add(rule.real_path)
    for rule in rules:
        if rule.real_path in seen:
            continue
        if any(rule.matches(target) for target in targets):
            selected.append(rule)
            seen.add(rule.real_path)
    return selected


def _append_if_fits(parts: list[str], text: str, cap: int) -> bool:
    candidate = "\n\n".join([*parts, text]).rstrip()
    return len(candidate.encode("utf-8")) <= cap


def _format_rules(rules: list[Rule]) -> str:
    parts = [
        "# Project Rules",
        "",
        "These rules were loaded from `.claude/rules/` and `.opencode/rules/`. Apply them as active instructions for this task.",
    ]
    loaded: list[Rule] = []
    omitted: list[tuple[Rule, str]] = []
    for rule in rules:
        body_size = len(rule.body.encode("utf-8"))
        if body_size > RULE_BODY_CAP_BYTES:
            omitted.append((rule, f"body exceeds {RULE_BODY_CAP_BYTES} bytes"))
            continue
        if rule.paths:
            scope = ", ".join(rule.paths)
            block = f"## Rule: {rule.rel_path} (paths: {scope})\n\n{rule.body}"
        elif rule.subtree_base is not None:
            block = f"## Rule: {rule.rel_path} (nested)\n\n{rule.body}"
        else:
            block = f"## Rule: {rule.rel_path}\n\n{rule.body}"
        if not _append_if_fits(parts, block, TOTAL_CONTEXT_CAP_BYTES):
            omitted.append((rule, f"context exceeds {TOTAL_CONTEXT_CAP_BYTES} bytes"))
            continue
        parts.append(block)
        loaded.append(rule)

    tail_parts: list[str] = []
    if loaded:
        tail_parts.extend(
            [
                "## Loaded Rule Files",
                "",
                *[f"- {rule.real_path}" for rule in loaded],
            ]
        )
    if omitted:
        if tail_parts:
            tail_parts.append("")
        tail_parts.extend(
            [
                "## Omitted Rule Files",
                "",
                "The following matched rule files were omitted because the hook context size cap was reached. Read them manually if they are relevant:",
                "",
                *[f"- {rule.real_path} ({reason})" for rule, reason in omitted],
            ]
        )
    if tail_parts:
        tail = "\n".join(tail_parts)
        if _append_if_fits(parts, tail, TOTAL_CONTEXT_CAP_BYTES):
            parts.append(tail)
        else:
            compact_tail = [
                "## Rule File Summary",
                "",
                *[f"- loaded: {rule.real_path}" for rule in loaded],
                *[
                    f"- omitted: {rule.real_path} ({reason})"
                    for rule, reason in omitted
                ],
            ]
            parts.append("\n".join(compact_tail))
    return "\n".join(parts).rstrip()


def _read_hook_input() -> dict[str, Any]:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _project_root(payload: dict[str, Any]) -> Path:
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return _realpath(Path(cwd))
    return _realpath(Path.cwd())


def _session_id(payload: dict[str, Any]) -> str:
    for key in ("session_id", "sessionId", "sessionID"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return "__global__"


def _session_source(payload: dict[str, Any]) -> str:
    value = payload.get("source")
    if isinstance(value, str):
        return value
    return ""


def _transcript_path(payload: dict[str, Any]) -> Path | None:
    value = payload.get("transcript_path")
    if isinstance(value, str) and value:
        return Path(value)
    value = payload.get("transcriptPath")
    if isinstance(value, str) and value:
        return Path(value)
    return None


def _state_dir(project_root: Path) -> Path:
    digest = hashlib.sha256(str(project_root).encode("utf-8")).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "codex-claude-rules" / digest


def _state_path(project_root: Path, session_id: str) -> Path:
    safe_session = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]
    return _state_dir(project_root) / f"{safe_session}.json"


def _cleanup_old_states(project_root: Path) -> None:
    state_dir = _state_dir(project_root)
    now = time.time()
    try:
        for child in state_dir.glob("*.json"):
            try:
                if now - child.stat().st_mtime > STATE_TTL_SECONDS:
                    child.unlink()
            except OSError:
                continue
    except OSError:
        return


def _reset_state(project_root: Path, session_id: str) -> None:
    try:
        _state_path(project_root, session_id).unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _empty_state() -> dict[str, Any]:
    return {
        "active_rules": {},
        "last_transcript_size": None,
    }


def _read_state(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(parsed, dict):
        return _empty_state()
    active = parsed.get("active_rules")
    if not isinstance(active, dict):
        legacy = parsed.get("active_rule_realpaths")
        if isinstance(legacy, list):
            active = {item: "" for item in legacy if isinstance(item, str)}
        else:
            active = {}
    active_rules = {
        key: value
        for key, value in active.items()
        if isinstance(key, str) and isinstance(value, str)
    }
    last_transcript_size = parsed.get("last_transcript_size")
    if not isinstance(last_transcript_size, int):
        last_transcript_size = None
    return {
        "active_rules": active_rules,
        "last_transcript_size": last_transcript_size,
    }


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _update_transcript_state(payload: dict[str, Any], state: dict[str, Any]) -> bool:
    transcript = _transcript_path(payload)
    if transcript is None:
        return False
    try:
        current_size = transcript.stat().st_size
    except OSError:
        return False
    previous_size = state.get("last_transcript_size")
    state["last_transcript_size"] = current_size
    if not isinstance(previous_size, int) or previous_size <= 0:
        return False
    return current_size < int(previous_size * TRANSCRIPT_SHRINK_RATIO)


def _tool_input(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("tool_input")
    if isinstance(value, dict):
        return value
    value = payload.get("toolInput")
    if isinstance(value, dict):
        return value
    return {}


def _extract_patch_targets(command: str, project_root: Path) -> list[Path]:
    targets: list[Path] = []
    for line in command.splitlines():
        for prefix in (
            "*** Add File: ",
            "*** Update File: ",
            "*** Delete File: ",
            "*** Move to: ",
        ):
            if not line.startswith(prefix):
                continue
            raw = line.removeprefix(prefix).strip()
            if not raw:
                continue
            target = Path(raw) if os.path.isabs(raw) else project_root / raw
            targets.append(_realpath(target))
    return targets


def _looks_like_path(token: str) -> bool:
    if not token or token == "-":
        return False
    if token.startswith("-"):
        return False
    return "/" in token or "." in token


def _command_targets(tokens: list[str], project_root: Path) -> list[Path]:
    if not tokens:
        return []
    command = Path(tokens[0]).name
    if command in {"cat", "nl"}:
        candidates = [token for token in tokens[1:] if not token.startswith("-")]
    elif command in {"head", "tail"}:
        candidates = []
        skip_next = False
        options_with_values = {"-n", "-c", "-q", "-v"}
        for token in tokens[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in options_with_values:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            candidates.append(token)
    elif command == "sed":
        candidates = []
        skip_next = False
        options_with_values = {"-e", "-f", "-i", "-l"}
        script_seen = False
        for token in tokens[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in options_with_values:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            if not script_seen:
                script_seen = True
                continue
            candidates.append(token)
    elif command == "rg":
        candidates = []
        skip_next = False
        options_with_values = {
            "-A",
            "-B",
            "-C",
            "-e",
            "-f",
            "-g",
            "-m",
            "--after-context",
            "--before-context",
            "--context",
            "--glob",
            "--max-count",
            "--regexp",
            "--file",
        }
        pattern_seen = False
        for token in tokens[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in options_with_values:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            if not pattern_seen:
                pattern_seen = True
                continue
            candidates.append(token)
    else:
        return []

    targets: list[Path] = []
    for candidate in candidates:
        if not _looks_like_path(candidate):
            continue
        target = (
            Path(candidate) if os.path.isabs(candidate) else project_root / candidate
        )
        targets.append(_realpath(target))
    return targets


def _extract_bash_targets(command: str, project_root: Path) -> list[Path]:
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return []
    return _command_targets(tokens, project_root)


def _targets_from_payload(payload: dict[str, Any], project_root: Path) -> list[Path]:
    tool_input = _tool_input(payload)
    targets: list[Path] = []
    for key in ("filePath", "file_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            target = Path(value) if os.path.isabs(value) else project_root / value
            targets.append(_realpath(target))
    command = tool_input.get("command")
    if isinstance(command, str):
        targets.extend(_extract_patch_targets(command, project_root))
        tool_name = payload.get("tool_name") or payload.get("toolName")
        if tool_name == "Bash":
            targets.extend(_extract_bash_targets(command, project_root))
    deduped: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target in seen:
            continue
        deduped.append(target)
        seen.add(target)
    return deduped


def _tool_failed(payload: dict[str, Any]) -> bool:
    for key in ("tool_response", "toolResponse", "tool_output", "toolOutput", "result"):
        value = payload.get(key)
        if isinstance(value, dict):
            success = value.get("success")
            if success is False:
                return True
            is_error = value.get("is_error")
            if is_error is True:
                return True
            status = value.get("status")
            if isinstance(status, str) and status.lower() in {
                "error",
                "failed",
                "failure",
            }:
                return True
            error = value.get("error")
            if error:
                return True
    return False


def _emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _activate_new_rules(
    payload: dict[str, Any],
    project_root: Path,
    session_id: str,
    targets: list[Path],
) -> list[Rule]:
    _cleanup_old_states(project_root)
    state_path = _state_path(project_root, session_id)
    state = _read_state(state_path)
    if _update_transcript_state(payload, state):
        state["active_rules"] = {}
    rules = _rules_for_targets(project_root, targets)
    active_rules = state["active_rules"]
    new_rules = [
        rule
        for rule in rules
        if active_rules.get(str(rule.real_path)) != rule.content_hash
    ]
    for rule in rules:
        active_rules[str(rule.real_path)] = rule.content_hash
    _write_state(state_path, state)
    return new_rules


def session_start() -> int:
    payload = _read_hook_input()
    project_root = _project_root(payload)
    session_id = _session_id(payload)
    if _session_source(payload) == "clear":
        _reset_state(project_root, session_id)
    new_rules = _activate_new_rules(payload, project_root, session_id, [])
    if not new_rules:
        return 0
    return _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": _format_rules(new_rules),
            }
        }
    )


def post_tool_use() -> int:
    payload = _read_hook_input()
    if _tool_failed(payload):
        return 0
    project_root = _project_root(payload)
    session_id = _session_id(payload)
    targets = _targets_from_payload(payload, project_root)
    if not targets:
        return 0
    new_rules = _activate_new_rules(payload, project_root, session_id, targets)
    if not new_rules:
        return 0
    context = _format_rules(new_rules)
    return _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": context,
            },
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("event", choices=("session-start", "post-tool-use"))
    args = parser.parse_args()
    if args.event == "session-start":
        return session_start()
    return post_tool_use()


if __name__ == "__main__":
    raise SystemExit(main())
