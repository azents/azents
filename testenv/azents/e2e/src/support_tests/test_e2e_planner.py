"""Unit tests for folder-owned E2E suite planning."""

import json
from pathlib import Path

import pytest

from support.e2e_planner import load_file_timings, load_suites, plan_suites


def _write_suite(root: Path, name: str, *, lanes: int = 2) -> Path:
    suite_root = root / name
    suite_root.mkdir(parents=True)
    (suite_root / "suite.toml").write_text(
        (
            "[suite]\n"
            f'name = "{name}"\n'
            f"lanes = {lanes}\n"
            "timeout_minutes = 30\n"
            'cache_write_repositories = ["image-a"]\n'
        ),
        encoding="utf-8",
    )
    return suite_root


def test_plan_suites_balances_files_and_assigns_cache_writer(tmp_path: Path) -> None:
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
    assert matrix["include"][0]["cache_write_repositories"] == "image-a"
    assert matrix["include"][1]["cache_write_repositories"] == ""
    lane_files = [
        (tmp_path / "plan" / lane["plan_file"]).read_text(encoding="utf-8")
        for lane in matrix["include"]
    ]
    assert "test_a.py" in lane_files[0]
    assert "test_b.py" in lane_files[1]
    assert "test_c.py" in lane_files[1]


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
                    "src/tests/required/public/test_external_channels.py"
                    "::test_multi_app_workspace_management_default_and_disconnect_journey",
                    4.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
                    "::test_multi_app_mention_selector_deduplicates_and_binds_open_access_route",
                    5.0,
                ),
                (
                    "src/tests/required/public/test_external_channels.py"
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
        "src/tests/required/public/test_external_channel_management.py": 21.0,
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
