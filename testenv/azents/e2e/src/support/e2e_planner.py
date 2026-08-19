"""Plan folder-owned E2E suites into timing-balanced CI lanes."""

import argparse
import ast
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Suite:
    """One folder-owned E2E execution profile."""

    name: str
    root: Path
    lanes: int
    timeout_minutes: int
    cache_write_repositories: tuple[str, ...]


@dataclass(frozen=True)
class TestSelection:
    """One independently schedulable pytest selection."""

    selector: str
    path: Path
    source_line: int
    sibling_count: int


def load_suites(tests_root: Path) -> tuple[Suite, ...]:
    """Load every suite configuration and reject unowned E2E files."""
    suites: list[Suite] = []
    for config_path in sorted(tests_root.glob("*/suite.toml")):
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
        config = payload["suite"]
        root = config_path.parent
        name = _required_string(config, "name")
        if name != root.name:
            raise ValueError(
                f"suite name {name!r} must match directory name {root.name!r}"
            )
        repositories = config.get("cache_write_repositories", [])
        if not isinstance(repositories, list) or not all(
            isinstance(value, str) and value for value in repositories
        ):
            raise ValueError(
                f"{config_path}: cache_write_repositories must be a string list"
            )
        suites.append(
            Suite(
                name=name,
                root=root,
                lanes=_required_positive_int(config, "lanes"),
                timeout_minutes=_required_positive_int(config, "timeout_minutes"),
                cache_write_repositories=tuple(repositories),
            )
        )

    configured_roots = {suite.root for suite in suites}
    unowned = [
        path
        for path in tests_root.rglob("test_*.py")
        if not any(root in path.parents for root in configured_roots)
    ]
    if unowned:
        paths = ", ".join(str(path) for path in sorted(unowned))
        raise ValueError(f"E2E tests must belong to a configured suite: {paths}")
    return tuple(suites)


def load_test_timings(path: Path | None) -> dict[str, float]:
    """Aggregate prior successful call timings by selectable test node."""
    if path is None or not path.is_file():
        return {}
    totals: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        payload = json.loads(line)
        if payload.get("record_type") != "test_phase" or payload.get("phase") != "call":
            continue
        node_id = payload.get("node_id")
        duration = payload.get("duration_seconds")
        if not isinstance(node_id, str) or not isinstance(duration, int | float):
            raise ValueError("invalid test timing record")
        selector = _current_test_selector(node_id)
        totals[selector] = totals.get(selector, 0.0) + float(duration)
    return totals


def plan_suites(
    *,
    tests_root: Path,
    enabled_suites: set[str],
    timings_path: Path | None,
    output_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Create deterministic test-level lane plans for enabled suites."""
    suites = load_suites(tests_root)
    unknown = enabled_suites - {suite.name for suite in suites}
    if unknown:
        raise ValueError(f"unknown enabled suites: {', '.join(sorted(unknown))}")

    timings = load_test_timings(timings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix: list[dict[str, Any]] = []
    coverage: dict[str, list[str]] = {}

    for suite in suites:
        if suite.name not in enabled_suites:
            continue
        files = sorted(suite.root.rglob("test_*.py"))
        if not files:
            raise ValueError(f"suite {suite.name!r} contains no tests")
        selections = [
            selection for path in files for selection in _test_selections(path)
        ]
        lane_count = min(suite.lanes, len(selections))
        lanes: list[list[TestSelection]] = [[] for _ in range(lane_count)]
        lane_weights = [0.0] * lane_count
        weighted_files = sorted(
            (
                (_selection_weight(selection, timings), selection)
                for selection in selections
            ),
            key=lambda item: (-item[0], item[1].selector),
        )
        for weight, selection in weighted_files:
            lane_index = min(
                range(lane_count),
                key=lambda index: (lane_weights[index], index),
            )
            lanes[lane_index].append(selection)
            lane_weights[lane_index] += weight

        coverage[suite.name] = [path.as_posix() for path in files]
        for index, lane_selections in enumerate(lanes, start=1):
            lane_name = f"{suite.name}-{index}"
            plan_path = output_dir / f"{lane_name}.txt"
            plan_path.write_text(
                "".join(
                    f"{selection.selector}\n"
                    for selection in sorted(
                        lane_selections,
                        key=lambda item: (item.path.as_posix(), item.source_line),
                    )
                ),
                encoding="utf-8",
            )
            matrix.append(
                {
                    "suite": suite.name,
                    "lane": lane_name,
                    "plan_file": plan_path.name,
                    "timeout_minutes": suite.timeout_minutes,
                    "cache_write_repositories": (
                        ",".join(suite.cache_write_repositories) if index == 1 else ""
                    ),
                }
            )

    (output_dir / "coverage.json").write_text(
        json.dumps(coverage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"include": matrix}


def _test_selections(path: Path) -> tuple[TestSelection, ...]:
    """Return statically discoverable pytest nodes, with a file fallback."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node_suffixes: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                node_suffixes.append((node.name, node.lineno))
            continue
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        node_suffixes.extend(
            (f"{node.name}::{member.name}", member.lineno)
            for member in node.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
            and member.name.startswith("test_")
        )

    if not node_suffixes:
        return (
            TestSelection(
                selector=path.as_posix(),
                path=path,
                source_line=0,
                sibling_count=1,
            ),
        )

    sibling_count = len(node_suffixes)
    return tuple(
        TestSelection(
            selector=f"{path.as_posix()}::{suffix}",
            path=path,
            source_line=source_line,
            sibling_count=sibling_count,
        )
        for suffix, source_line in node_suffixes
    )


def _selection_weight(
    selection: TestSelection,
    timings: dict[str, float],
) -> float:
    exact = timings.get(selection.selector)
    if exact is not None:
        return max(exact, 0.001)

    selector_path, separator, selector_suffix = selection.selector.partition("::")
    suffix_matches = [
        duration
        for prior_selector, duration in timings.items()
        if _selectors_match_by_filename(
            prior_selector=prior_selector,
            selector_path=selector_path,
            selector_suffix=selector_suffix if separator else None,
        )
    ]
    if len(suffix_matches) == 1:
        return max(suffix_matches[0], 0.001)
    source_lines = selection.path.read_text(encoding="utf-8").splitlines()
    return max(
        len(source_lines) / 100.0 / selection.sibling_count,
        1.0,
    )


def _selectors_match_by_filename(
    *,
    prior_selector: str,
    selector_path: str,
    selector_suffix: str | None,
) -> bool:
    prior_path, prior_separator, prior_suffix = prior_selector.partition("::")
    return (
        Path(prior_path).name == Path(selector_path).name
        and (prior_suffix if prior_separator else None) == selector_suffix
    )


def _current_test_selector(node_id: str) -> str:
    """Map one historical pytest node ID to its current base selector."""
    file_path, separator, node_suffix = node_id.partition("::")
    current_path = _current_suite_path(file_path)
    if not separator:
        return current_path
    base_node_suffix = node_suffix.split("[", 1)[0]
    return f"{current_path}::{base_node_suffix}"


def _current_suite_path(path: str) -> str:
    """Map pre-suite timing paths to their current required-suite location."""
    if path.startswith("src/tests/azents/admin/"):
        if path.endswith("/test_01_admin_web.py"):
            return path.replace("src/tests/azents/admin/", "src/tests/web/admin/", 1)
        return path.replace("src/tests/azents/admin/", "src/tests/required/admin/", 1)
    if path.startswith("src/tests/azents/public/"):
        return path.replace("src/tests/azents/public/", "src/tests/required/public/", 1)
    if path.startswith("src/tests/test_"):
        return path.replace("src/tests/", "src/tests/required/", 1)
    return path


def _required_string(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"suite {key!r} must be a non-empty string")
    return value


def _required_positive_int(config: dict[str, Any], key: str) -> int:
    value = config.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"suite {key!r} must be a positive integer")
    return value


def main() -> None:
    """CLI entry point used by GitHub Actions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests-root", type=Path, required=True)
    parser.add_argument("--enabled-suite", action="append", default=[])
    parser.add_argument("--timings", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    matrix = plan_suites(
        tests_root=args.tests_root,
        enabled_suites=set(args.enabled_suite),
        timings_path=args.timings,
        output_dir=args.output_dir,
    )
    matrix_json = json.dumps(matrix, separators=(",", ":"), sort_keys=True)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"matrix={matrix_json}\n")
    sys.stdout.write(f"{matrix_json}\n")


if __name__ == "__main__":
    main()
