"""Unit tests for folder-owned E2E suite planning."""

import json
import sys
from pathlib import Path

import pytest

from support.e2e_planner import load_file_timings, load_suites, main, plan_suites


@pytest.mark.parametrize("enabled", [(), ("required",), ("web",), ("required", "web")])
def test_cli_suite_projections_preserve_the_exact_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: tuple[str, ...]
) -> None:
    tests = tmp_path / "tests"
    for suite in ("required", "web"):
        directory = _write_suite(tests, suite)
        for name in ("first", "second"):
            (directory / f"test_{name}.py").write_text(
                f"def test_{name}(): pass\n", encoding="utf-8"
            )
    output = tmp_path / "github-output"
    plans = tmp_path / "plans"
    args = [
        "e2e_planner",
        "--tests-root",
        str(tests),
        "--output-dir",
        str(plans),
        "--github-output",
        str(output),
    ]
    for suite in enabled:
        args.extend(["--enabled-suite", suite])
    monkeypatch.setattr(sys, "argv", args)
    main()
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    full = json.loads(values["matrix"])["include"]
    projected = []
    for suite in ("required", "web"):
        lanes = json.loads(values[f"{suite}_matrix"])["include"]
        assert lanes == [lane for lane in full if lane["suite"] == suite]
        assert bool(lanes) is (suite in enabled)
        for lane in lanes:
            files = (plans / lane["plan_file"]).read_text().splitlines()
            assert files
            assert all(str(tests / suite) in name for name in files)
        projected.extend(lanes)
    assert sorted(projected, key=lambda lane: lane["lane"]) == sorted(
        full, key=lambda lane: lane["lane"]
    )


def _write_suite(root: Path, name: str, *, lanes: int = 2) -> Path:
    suite_root = root / name
    suite_root.mkdir(parents=True)
    (suite_root / "suite.toml").write_text(
        (f'[suite]\nname = "{name}"\nlanes = {lanes}\ntimeout_minutes = 30\n'),
        encoding="utf-8",
    )
    return suite_root


def _phase(node: str, phase: str, duration: float) -> dict[str, object]:
    return {
        "record_type": "test_phase",
        "node_id": node,
        "phase": phase,
        "duration_seconds": duration,
    }


def _fixture(
    node: str, phase: str, duration: float, *, scope: str, outcome: str
) -> dict[str, object]:
    return {
        **_phase(node, phase, duration),
        "record_type": "fixture",
        "scope": scope,
        "outcome": outcome,
    }


def test_planning_counts_function_cost_once_with_actual_phase_caps(
    tmp_path: Path,
) -> None:
    node = "src/tests/required/test_expensive.py::test_worker"
    rows = [
        _phase(node, "call", 10),
        _phase(node, "setup", 20),
        _phase(node, "teardown", 5),
        _fixture(node, "setup", 12, scope="function", outcome="passed"),
        _fixture(node, "setup", 8, scope="function", outcome="passed"),
        _fixture(node, "setup", 12, scope="function", outcome="passed"),
        _fixture(node, "teardown", 50, scope="function", outcome="completed"),
        _fixture(node, "setup", 1000, scope="session", outcome="passed"),
        _fixture(node, "setup", 1000, scope="module", outcome="passed"),
        _fixture(node, "setup", 1000, scope="class", outcome="passed"),
        _fixture(node, "setup", 1000, scope="function", outcome="failed"),
        _fixture(node, "teardown", 1000, scope="function", outcome="failed"),
    ]
    path = tmp_path / "timings.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert load_file_timings(path) == {"src/tests/required/test_expensive.py": 27}
    # Input order cannot double-count nested or duplicated fixture observations.
    path.write_text("\n".join(json.dumps(row) for row in reversed(rows)))
    assert load_file_timings(path) == {"src/tests/required/test_expensive.py": 27}


@pytest.mark.parametrize("missing", ["call", "phase_wall"])
def test_fixture_observation_alone_cannot_create_planning_cost(
    tmp_path: Path, missing: str
) -> None:
    node = "src/tests/required/test_worker.py::test_worker"
    rows = [_fixture(node, "setup", 30, scope="function", outcome="passed")]
    if missing != "call":
        rows.append(_phase(node, "call", 4))
    if missing != "phase_wall":
        rows.append(_phase(node, "setup", 40))
    path = tmp_path / "timings.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    expected = {} if missing == "call" else {"src/tests/required/test_worker.py": 4}
    assert load_file_timings(path) == expected


def test_function_cost_high_watermark_is_computed_per_sample_not_by_field(
    tmp_path: Path,
) -> None:
    node = "src/tests/required/test_worker.py::test_worker"
    for name, call, fixture in (("first", 100, 1), ("second", 10, 20)):
        rows = [
            _phase(node, "call", call),
            _phase(node, "setup", fixture),
            _fixture(node, "setup", fixture, scope="function", outcome="passed"),
        ]
        (tmp_path / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows)
        )
    assert load_file_timings(tmp_path) == {"src/tests/required/test_worker.py": 101}


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf"), True, None])
def test_planner_rejects_invalid_recognized_function_fixture_cost(
    tmp_path: Path, duration: object
) -> None:
    row = {
        **_fixture(
            "src/tests/required/test_worker.py::test_worker",
            "setup",
            1,
            scope="function",
            outcome="passed",
        ),
        "duration_seconds": duration,
    }
    path = tmp_path / "timings.jsonl"
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="invalid test timing record"):
        load_file_timings(path)


def test_function_cost_changes_balance_without_shared_startup_or_coverage_loss(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "src/tests"
    suite = _write_suite(tests, "required")
    rows = []
    for name, call, fixture in (("a", 10, 50), ("b", 20, 0), ("c", 20, 0)):
        file = suite / f"test_{name}.py"
        file.write_text("def test_worker(): pass\n")
        node = f"{file}::test_worker"
        rows.extend(
            [
                _phase(node, "call", call),
                _phase(node, "setup", fixture),
                _fixture(node, "setup", fixture, scope="function", outcome="passed"),
                _fixture(node, "setup", 900, scope="session", outcome="passed"),
            ]
        )
    timings = tmp_path / "timings.jsonl"
    timings.write_text("\n".join(json.dumps(row) for row in rows))
    output = tmp_path / "plan"
    matrix = plan_suites(
        tests_root=tests,
        enabled_suites={"required"},
        timings_path=timings,
        output_dir=output,
    )
    assignments = [
        (output / lane["plan_file"]).read_text().splitlines()
        for lane in matrix["include"]
    ]
    assert assignments[0] == [str(suite / "test_a.py")]
    assert assignments[1] == [str(suite / "test_b.py"), str(suite / "test_c.py")]
    assert len({file for lane in assignments for file in lane}) == 3


@pytest.mark.parametrize("outcome", ["failed", "skipped"])
def test_nonpassing_calls_do_not_admit_fixture_overhead(
    tmp_path: Path, outcome: str
) -> None:
    node = "src/tests/required/test_a.py::test_worker[param]"
    rows = [
        {**_phase(node, "call", 5), "outcome": outcome},
        _phase(node, "setup", 20),
        _fixture(node, "setup", 10, scope="function", outcome="passed"),
    ]
    path = tmp_path / "timings.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert load_file_timings(path) == {}


@pytest.mark.parametrize("phase", ["call", "setup", "teardown"])
def test_duplicate_authoritative_phase_is_rejected(tmp_path: Path, phase: str) -> None:
    row = _phase("src/tests/required/test_a.py::test_a", phase, 2)
    path = tmp_path / "timings.jsonl"
    path.write_text(json.dumps(row) + "\n" + json.dumps(row))
    with pytest.raises(ValueError, match="Duplicate authoritative test phase"):
        load_file_timings(path)


def test_fixture_costs_match_full_parametrized_nodes_before_file_aggregation(
    tmp_path: Path,
) -> None:
    first = "src/tests/required/test_a.py::TestWorker::test_run[first]"
    second = "src/tests/required/test_a.py::TestWorker::test_run[second]"
    rows = [
        _phase(first, "call", 3),
        _phase(first, "setup", 1),
        _phase(second, "call", 4),
        _phase(second, "setup", 20),
        _fixture(first, "setup", 10, scope="function", outcome="passed"),
        _fixture(second, "setup", 15, scope="function", outcome="passed"),
    ]
    path = tmp_path / "timings.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    assert load_file_timings(path) == {"src/tests/required/test_a.py": 23}


def test_late_fixture_cost_is_capped_but_not_proven_exclusive(tmp_path: Path) -> None:
    node = "src/tests/required/test_a.py::test_dynamic_fixture"
    rows = [
        _phase(node, "call", 10),
        _phase(node, "setup", 2),
        _fixture(node, "setup", 7, scope="function", outcome="passed"),
    ]
    path = tmp_path / "timings.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows))
    # Receipts do not locate an interval requested during call. The heuristic
    # can charge at most the observed setup wall; it is not a billing metric.
    assert load_file_timings(path) == {"src/tests/required/test_a.py": 12}


def test_plan_suites_balances_files_without_cache_writer_ownership(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required")
    for name in ("test_a.py", "test_b.py", "test_c.py"):
        (suite_root / name).write_text(
            f"def {name.removesuffix('.py')}():\n    pass\n",
            encoding="utf-8",
        )
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": f"{suite_root / name}::test",
                    "duration_seconds": duration,
                }
            )
            for name, duration in (
                ("test_a.py", 10.0),
                ("test_b.py", 6.0),
                ("test_c.py", 4.0),
            )
        ),
        encoding="utf-8",
    )

    matrix = plan_suites(
        tests_root=tests_root,
        enabled_suites={"required"},
        timings_path=timings_path,
        output_dir=tmp_path / "plan",
    )

    assert len(matrix["include"]) == 2
    assert all("cache_write_repositories" not in lane for lane in matrix["include"])
    lane_files = [
        (tmp_path / "plan" / lane["plan_file"]).read_text(encoding="utf-8")
        for lane in matrix["include"]
    ]
    assert "test_a.py" in lane_files[0]
    assert "test_b.py" in lane_files[1]
    assert "test_c.py" in lane_files[1]


def test_plan_suites_uses_declared_source_fallback_weight(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required")
    (suite_root / "test_inherited.py").write_text(
        (
            "E2E_PLANNER_FALLBACK_WEIGHT = 20.0\n\n"
            "class TestInherited(ScenarioBase):\n"
            "    pass\n"
        ),
        encoding="utf-8",
    )
    for name in ("test_a.py", "test_b.py"):
        (suite_root / name).write_text(
            f"def {name.removesuffix('.py')}():\n    pass\n",
            encoding="utf-8",
        )

    plan_suites(
        tests_root=tests_root,
        enabled_suites={"required"},
        timings_path=None,
        output_dir=tmp_path / "plan",
    )

    first_lane = (tmp_path / "plan" / "required-1.txt").read_text(encoding="utf-8")
    second_lane = (tmp_path / "plan" / "required-2.txt").read_text(encoding="utf-8")
    assert "test_inherited.py" in first_lane
    assert "test_a.py" not in first_lane
    assert "test_b.py" not in first_lane
    assert "test_a.py" in second_lane
    assert "test_b.py" in second_lane


@pytest.mark.parametrize("cached", [False, True])
def test_web_plan_starts_expensive_files_without_changing_required_order(
    tmp_path: Path, cached: bool
) -> None:
    tests_root = tmp_path / "tests"
    suites = {
        name: _write_suite(tests_root, name, lanes=1) for name in ("required", "web")
    }
    for suite in suites.values():
        for name, fallback in (("a", 1), ("b", 10), ("c", 5)):
            (suite / f"test_{name}.py").write_text(
                f"E2E_PLANNER_FALLBACK_WEIGHT = {fallback}\n"
                "def test_first():\n    pass\n"
                "def test_second():\n    pass\n"
            )
    timings = tmp_path / "timings.jsonl"
    timings.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": f"{suites['web'] / f'test_{name}.py'}::test_first",
                    "duration_seconds": duration,
                }
            )
            for name, duration in (("a", 4), ("b", 1), ("c", 9))
        )
        + "\n"
    )
    output = tmp_path / "plan"
    plan_suites(
        tests_root=tests_root,
        enabled_suites={"required", "web"},
        timings_path=timings if cached else None,
        output_dir=output,
    )
    web = (output / "web-1.txt").read_text().splitlines()
    required = (output / "required-1.txt").read_text().splitlines()
    expected = ["c", "a", "b"] if cached else ["b", "c", "a"]
    assert web == [str(suites["web"] / f"test_{name}.py") for name in expected]
    assert required == [
        str(suites["required"] / f"test_{name}.py") for name in ("a", "b", "c")
    ]
    coverage = json.loads((output / "coverage.json").read_text())
    assert sorted(web) == coverage["web"]
    assert sorted(required) == coverage["required"]
    before = (output / "web-1.txt").read_text()
    plan_suites(
        tests_root=tests_root,
        enabled_suites={"required", "web"},
        timings_path=timings if cached else None,
        output_dir=output,
    )
    assert (output / "web-1.txt").read_text() == before


def test_plan_suites_rejects_non_finite_source_fallback_weight(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required")
    (suite_root / "test_inherited.py").write_text(
        "E2E_PLANNER_FALLBACK_WEIGHT = 1e309\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must be a finite positive number"):
        plan_suites(
            tests_root=tests_root,
            enabled_suites={"required"},
            timings_path=None,
            output_dir=tmp_path / "plan",
        )


def test_load_suites_rejects_test_outside_suite_folder(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    _write_suite(tests_root, "required")
    tests_root.mkdir(exist_ok=True)
    (tests_root / "test_unowned.py").write_text(
        "def test_unowned():\n    pass\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must belong to a configured suite"):
        load_suites(tests_root)


def test_load_file_timings_maps_pre_suite_paths(tmp_path: Path) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": node_id,
                    "duration_seconds": 2.0,
                }
            )
            for node_id in (
                "src/tests/azents/public/test_agent.py::test_agent",
                "src/tests/azents/admin/test_01_admin_web.py::test_web",
                "src/tests/test_slack_provider_fake.py::test_fake",
            )
        ),
        encoding="utf-8",
    )

    assert load_file_timings(timings_path) == {
        "src/tests/required/public/test_agent.py": 2.0,
        "src/tests/web/admin/test_01_admin_web.py": 2.0,
        "src/tests/required/test_slack_provider_fake.py": 2.0,
    }


def test_load_file_timings_projects_subagent_capacity_split(tmp_path: Path) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": node_id,
                    "duration_seconds": duration,
                }
            )
            for node_id, duration in (
                (
                    "src/tests/required/public/test_subagents.py"
                    "::TestSubagents"
                    "::test_spawn_wait_tree_projection_and_child_detail_history",
                    3.0,
                ),
                (
                    "src/tests/required/public/test_subagents.py"
                    "::TestSubagents"
                    "::test_targetless_wait_observes_any_child_mailbox_message",
                    5.0,
                ),
                (
                    "src/tests/required/public/test_subagents.py"
                    "::TestSubagents"
                    "::test_active_overflow_remains_visible_and_blocks_new_activation",
                    7.0,
                ),
            )
        ),
        encoding="utf-8",
    )

    assert load_file_timings(timings_path) == {
        "src/tests/required/public/test_subagents.py": 3.0,
        "src/tests/required/public/test_subagent_capacity.py": 12.0,
    }


def test_load_file_timings_uses_file_high_watermarks_across_samples(
    tmp_path: Path,
) -> None:
    timings_root = tmp_path / "timings"
    timings_root.mkdir()
    samples = (
        (
            "100-1.jsonl",
            (
                ("src/tests/required/public/test_agent.py::test_a", 4.0),
                ("src/tests/required/public/test_agent.py::test_b", 3.0),
                ("src/tests/required/public/test_auth.py::test_auth", 8.0),
            ),
        ),
        (
            "100-2.jsonl",
            (
                ("src/tests/required/public/test_agent.py::test_a", 6.0),
                ("src/tests/required/public/test_agent.py::test_b", 5.0),
                ("src/tests/required/public/test_auth.py::test_auth", 2.0),
            ),
        ),
    )
    for name, records in samples:
        (timings_root / name).write_text(
            "\n".join(
                json.dumps(
                    {
                        "record_type": "test_phase",
                        "phase": "call",
                        "node_id": node_id,
                        "duration_seconds": duration,
                    }
                )
                for node_id, duration in records
            ),
            encoding="utf-8",
        )

    assert load_file_timings(timings_root) == {
        "src/tests/required/public/test_agent.py": 11.0,
        "src/tests/required/public/test_auth.py": 8.0,
    }


@pytest.mark.parametrize(
    "record",
    [
        [],
        {
            "record_type": "test_phase",
            "phase": "call",
            "node_id": "src/tests/required/public/test_agent.py::test_agent",
            "duration_seconds": True,
        },
    ],
)
def test_load_file_timings_rejects_invalid_call_records(
    tmp_path: Path,
    record: object,
) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid test timing record"):
        load_file_timings(timings_path)


def test_load_file_timings_ignores_other_json_record_types(tmp_path: Path) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        json.dumps({"record_type": "session_start", "started_at": 0}),
        encoding="utf-8",
    )

    assert load_file_timings(timings_path) == {}


def test_load_file_timings_projects_external_channel_split(tmp_path: Path) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": node_id,
                    "duration_seconds": duration,
                }
            )
            for node_id, duration in (
                (
                    "src/tests/azents/public/test_external_channels.py"
                    "::test_http_admission_unknown_participant_and_approval_journey",
                    1.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_connection_update_and_repeated_disconnect",
                    2.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_slack_binding_response_modes_gate_and_preserve_context",
                    3.0,
                ),
                (
                    "src/tests/required/public/test_external_channel_management.py"
                    "::test_multi_app_workspace_management_default_and_disconnect_journey",
                    4.0,
                ),
                (
                    "src/tests/required/public/test_external_channel_management.py"
                    "::test_multi_app_mention_selector_deduplicates_and_binds_open_access_route",
                    5.0,
                ),
                (
                    "src/tests/required/public/test_external_channel_management.py"
                    "::test_provider_native_channel_work_progress_journey",
                    6.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_socket_mode_recovers_then_acknowledges_and_preserves_route",
                    7.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_gateway_message_waits_for_location_then_binds",
                    8.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_configured_message_durably_provisions_conversation",
                    9.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_unmentioned_todo_work_tracks_activity_and_typing_recovers",
                    13.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_single_activation_and_interaction_journey[param]",
                    10.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_message_command_selector_and_component_journey",
                    11.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_discord_multi_management_and_lifecycle_journey",
                    12.0,
                ),
            )
        ),
        encoding="utf-8",
    )

    assert load_file_timings(timings_path) == {
        "src/tests/required/public/test_external_channel_management.py": 6.0,
        "src/tests/required/public/test_external_channel_workspace_management.py": 9.0,
        "src/tests/required/public/test_external_channel_provider_progress.py": 6.0,
        "src/tests/required/public/test_external_channel_slack_socket.py": 7.0,
        (
            "src/tests/required/public/test_external_channel_discord_gateway_binding.py"
        ): 8.0,
        (
            "src/tests/required/public/"
            "test_external_channel_discord_configured_provisioning.py"
        ): 9.0,
        (
            "src/tests/required/public/"
            "test_external_channel_discord_unmentioned_activity.py"
        ): 13.0,
        "src/tests/required/public/test_external_channel_discord_journeys.py": 33.0,
    }


def test_load_file_timings_projects_previous_discord_wrapper(tmp_path: Path) -> None:
    timings_path = tmp_path / "timings.jsonl"
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": (
                        "src/tests/required/public/"
                        "test_external_channel_discord_provisioning.py"
                        f"::{test_name}"
                    ),
                    "duration_seconds": duration,
                }
            )
            for test_name, duration in (
                (
                    "test_discord_configured_message_durably_provisions_conversation",
                    10.0,
                ),
                (
                    "test_discord_gateway_message_waits_for_location_then_binds",
                    9.0,
                ),
                (
                    "test_discord_unmentioned_todo_work_tracks_activity_and_typing_recovers",
                    8.0,
                ),
            )
        ),
        encoding="utf-8",
    )

    assert load_file_timings(timings_path) == {
        (
            "src/tests/required/public/"
            "test_external_channel_discord_configured_provisioning.py"
        ): 10.0,
        (
            "src/tests/required/public/test_external_channel_discord_gateway_binding.py"
        ): 9.0,
        (
            "src/tests/required/public/"
            "test_external_channel_discord_unmentioned_activity.py"
        ): 8.0,
    }


def test_plan_suites_assigns_split_discord_files_exactly_once(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required", lanes=4)
    split_files = (
        "test_external_channel_discord_configured_provisioning.py",
        "test_external_channel_discord_gateway_binding.py",
        "test_external_channel_discord_unmentioned_activity.py",
    )
    other_files = ("test_alpha.py", "test_beta.py", "test_gamma.py")
    for name in (*split_files, *other_files):
        (suite_root / name).write_text(
            f"def {name.removesuffix('.py')}():\n    pass\n",
            encoding="utf-8",
        )
    timings_path = tmp_path / "timings.jsonl"
    timing_nodes = (
        (
            "test_external_channel_discord_provisioning.py"
            "::test_discord_configured_message_durably_provisions_conversation",
            10.0,
        ),
        (
            "test_external_channel_discord_provisioning.py"
            "::test_discord_gateway_message_waits_for_location_then_binds",
            9.0,
        ),
        (
            "test_external_channel_discord_provisioning.py"
            "::test_discord_unmentioned_todo_work_tracks_activity_and_typing_recovers",
            8.0,
        ),
        ("test_alpha.py::test_alpha", 7.0),
        ("test_beta.py::test_beta", 6.0),
        ("test_gamma.py::test_gamma", 5.0),
    )
    timings_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "record_type": "test_phase",
                    "phase": "call",
                    "node_id": f"src/tests/required/public/{node_id}",
                    "duration_seconds": duration,
                }
            )
            for node_id, duration in timing_nodes
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "plan"

    matrix = plan_suites(
        tests_root=tests_root,
        enabled_suites={"required"},
        timings_path=timings_path,
        output_dir=output_dir,
    )

    lane_files = [
        [
            Path(line).name
            for line in (output_dir / lane["plan_file"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        for lane in matrix["include"]
    ]
    assert lane_files == [
        ["test_external_channel_discord_configured_provisioning.py"],
        ["test_external_channel_discord_gateway_binding.py"],
        [
            "test_external_channel_discord_unmentioned_activity.py",
            "test_gamma.py",
        ],
        ["test_alpha.py", "test_beta.py"],
    ]
    coverage = json.loads((output_dir / "coverage.json").read_text(encoding="utf-8"))
    covered_files = [Path(path).name for path in coverage["required"]]
    assigned_files = [name for lane in lane_files for name in lane]
    assert sorted(assigned_files) == sorted(covered_files)
    assert len(assigned_files) == len(set(assigned_files))
