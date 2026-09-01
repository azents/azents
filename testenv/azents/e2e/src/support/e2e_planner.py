"""Plan folder-owned E2E suites into timing-balanced CI lanes."""

import argparse
import ast
import json
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_EXTERNAL_CHANNEL_TIMING_FILES = {
    "test_http_admission_unknown_participant_and_approval_journey": (
        "test_external_channel_management.py"
    ),
    "test_connection_update_and_repeated_disconnect": (
        "test_external_channel_management.py"
    ),
    "test_slack_binding_response_modes_gate_and_preserve_context": (
        "test_external_channel_management.py"
    ),
    "test_multi_app_workspace_management_default_and_disconnect_journey": (
        "test_external_channel_management.py"
    ),
    "test_multi_app_mention_selector_deduplicates_and_binds_open_access_route": (
        "test_external_channel_management.py"
    ),
    "test_provider_native_channel_work_progress_journey": (
        "test_external_channel_management.py"
    ),
    "test_socket_mode_recovers_then_acknowledges_and_preserves_route": (
        "test_external_channel_slack_socket.py"
    ),
    "test_discord_gateway_message_waits_for_location_then_binds": (
        "test_external_channel_discord_provisioning.py"
    ),
    "test_discord_configured_message_durably_provisions_conversation": (
        "test_external_channel_discord_provisioning.py"
    ),
    "test_discord_single_activation_and_interaction_journey": (
        "test_external_channel_discord_journeys.py"
    ),
    "test_discord_message_command_selector_and_component_journey": (
        "test_external_channel_discord_journeys.py"
    ),
    "test_discord_multi_management_and_lifecycle_journey": (
        "test_external_channel_discord_journeys.py"
    ),
}


@dataclass(frozen=True)
class Suite:
    """One folder-owned E2E execution profile."""

    name: str
    root: Path
    lanes: int
    timeout_minutes: int
    cache_write_repositories: tuple[str, ...]
    split_test_files: tuple[str, ...]


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
        split_test_files = config.get("split_test_files", [])
        if not isinstance(split_test_files, list) or not all(
            isinstance(value, str) and value for value in split_test_files
        ):
            raise ValueError(f"{config_path}: split_test_files must be a string list")
        for relative_path in split_test_files:
            path = root / relative_path
            relative = Path(relative_path)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not path.is_file()
                or not path.name.startswith("test_")
                or path.suffix != ".py"
            ):
                raise ValueError(
                    f"{config_path}: invalid split test file {relative_path!r}"
                )
        suites.append(
            Suite(
                name=name,
                root=root,
                lanes=_required_positive_int(config, "lanes"),
                timeout_minutes=_required_positive_int(config, "timeout_minutes"),
                cache_write_repositories=tuple(repositories),
                split_test_files=tuple(split_test_files),
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


def load_file_timings(path: Path | None) -> dict[str, float]:
    """Aggregate prior successful call timings by test file."""
    totals: dict[str, float] = {}
    for node_id, duration in load_node_timings(path).items():
        file_path = node_id.split("::", 1)[0]
        totals[file_path] = totals.get(file_path, 0.0) + duration
    return totals


def load_node_timings(path: Path | None) -> dict[str, float]:
    """Aggregate prior successful call timings by pytest node."""
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
        current_node_id = _current_timing_node(node_id)
        totals[current_node_id] = totals.get(current_node_id, 0.0) + float(duration)
    return totals


def plan_suites(
    *,
    tests_root: Path,
    enabled_suites: set[str],
    timings_path: Path | None,
    output_dir: Path,
) -> dict[str, list[dict[str, Any]]]:
    """Create deterministic timing-balanced lane plans for enabled suites."""
    suites = load_suites(tests_root)
    unknown = enabled_suites - {suite.name for suite in suites}
    if unknown:
        raise ValueError(f"unknown enabled suites: {', '.join(sorted(unknown))}")

    node_timings = load_node_timings(timings_path)
    timings = load_file_timings(timings_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    matrix: list[dict[str, Any]] = []
    coverage: dict[str, list[str]] = {}

    for suite in suites:
        if suite.name not in enabled_suites:
            continue
        files = sorted(suite.root.rglob("test_*.py"))
        if not files:
            raise ValueError(f"suite {suite.name!r} contains no tests")
        weighted_items = sorted(
            _weighted_suite_items(
                suite=suite,
                files=files,
                file_timings=timings,
                node_timings=node_timings,
            ),
            key=lambda item: (-item[0], item[1]),
        )
        lane_count = min(suite.lanes, len(weighted_items))
        lanes: list[list[str]] = [[] for _ in range(lane_count)]
        lane_weights = [0.0] * lane_count
        for weight, selector in weighted_items:
            lane_index = min(
                range(lane_count),
                key=lambda index: (lane_weights[index], index),
            )
            lanes[lane_index].append(selector)
            lane_weights[lane_index] += weight

        coverage[suite.name] = [path.as_posix() for path in files]
        for index, lane_files in enumerate(lanes, start=1):
            lane_name = f"{suite.name}-{index}"
            plan_path = output_dir / f"{lane_name}.txt"
            plan_path.write_text(
                "".join(f"{selector}\n" for selector in sorted(lane_files)),
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


def _weighted_suite_items(
    *,
    suite: Suite,
    files: list[Path],
    file_timings: dict[str, float],
    node_timings: dict[str, float],
) -> list[tuple[float, str]]:
    """Return file or test-node selectors with representative weights."""
    split_paths = {suite.root / relative for relative in suite.split_test_files}
    items: list[tuple[float, str]] = []
    for path in files:
        if path not in split_paths:
            items.append((_file_weight(path, file_timings), path.as_posix()))
            continue
        selectors = _test_selectors(path)
        if not selectors:
            raise ValueError(f"split test file has no tests: {path}")
        fallback_weight = _file_weight(path, file_timings) / len(selectors)
        items.extend(
            (
                _node_weight(selector, node_timings, fallback_weight),
                selector,
            )
            for selector in selectors
        )
    return items


def _test_selectors(path: Path) -> tuple[str, ...]:
    """Return stable base pytest node IDs declared directly in one file."""
    module = ast.parse(path.read_text(encoding="utf-8"))
    selectors: list[str] = []
    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                selectors.append(f"{path.as_posix()}::{node.name}")
            continue
        if not isinstance(node, ast.ClassDef) or not node.name.startswith("Test"):
            continue
        selectors.extend(
            f"{path.as_posix()}::{node.name}::{method.name}"
            for method in node.body
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            and method.name.startswith("test_")
        )
    return tuple(selectors)


def _node_weight(
    selector: str,
    timings: dict[str, float],
    fallback: float,
) -> float:
    """Return prior duration for one base node including parametrizations."""
    exact = timings.get(selector)
    parametrized = sum(
        duration
        for node_id, duration in timings.items()
        if node_id.startswith(f"{selector}[")
    )
    if exact is not None or parametrized:
        return max((exact or 0.0) + parametrized, 0.001)
    return max(fallback, 0.001)


def _file_weight(path: Path, timings: dict[str, float]) -> float:
    exact = timings.get(path.as_posix())
    if exact is not None:
        return max(exact, 0.001)
    suffix_matches = [
        duration
        for prior_path, duration in timings.items()
        if prior_path.endswith(f"/{path.name}") or prior_path == path.name
    ]
    if len(suffix_matches) == 1:
        return max(suffix_matches[0], 0.001)
    source = path.read_text(encoding="utf-8")
    test_count = sum(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in ast.walk(ast.parse(source))
    )
    return max(float(test_count), len(source.splitlines()) / 100.0, 1.0)


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


def _current_timing_path(node_id: str) -> str:
    """Map historical timing nodes onto the file that currently collects them."""
    parts = node_id.split("::")
    path = _current_suite_path(parts[0])
    if not path.endswith("/test_external_channels.py") or len(parts) < 2:
        return path
    test_name = parts[1].split("[", 1)[0]
    current_name = _EXTERNAL_CHANNEL_TIMING_FILES.get(test_name)
    if current_name is None:
        return path
    return path.rsplit("/", 1)[0] + f"/{current_name}"


def _current_timing_node(node_id: str) -> str:
    """Map one historical pytest node onto its current collection path."""
    parts = node_id.split("::")
    return "::".join((_current_timing_path(node_id), *parts[1:]))


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
