"""Unit tests for folder-owned E2E suite planning."""

import json
from pathlib import Path

import pytest

from support.e2e_planner import load_suites, load_test_timings, plan_suites


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


def test_plan_suites_balances_test_nodes_and_assigns_cache_writer(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required")
    test_a = suite_root / "test_a.py"
    test_b = suite_root / "test_b.py"
    test_a.write_text(
        "def test_slow():\n    pass\n\ndef test_fast():\n    pass\n",
        encoding="utf-8",
    )
    test_b.write_text(
        "class TestGrouped:\n    def test_medium(self):\n        pass\n",
        encoding="utf-8",
    )
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
                (f"{test_a}::test_slow", 10.0),
                (f"{test_a}::test_fast", 4.0),
                (f"{test_b}::TestGrouped::test_medium", 6.0),
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
    assert f"{test_a.as_posix()}::test_slow\n" == lane_files[0]
    assert f"{test_a.as_posix()}::test_fast\n" in lane_files[1]
    assert f"{test_b.as_posix()}::TestGrouped::test_medium\n" in lane_files[1]


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


def test_load_test_timings_maps_paths_and_aggregates_parameters(
    tmp_path: Path,
) -> None:
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
                "src/tests/azents/public/test_agent.py::test_agent[first]",
                "src/tests/azents/public/test_agent.py::test_agent[second::case]",
                "src/tests/azents/admin/test_01_admin_web.py::test_web",
                "src/tests/test_slack_provider_fake.py::TestFake::test_contract",
            )
        ),
        encoding="utf-8",
    )

    assert load_test_timings(timings_path) == {
        "src/tests/required/public/test_agent.py::test_agent": 4.0,
        "src/tests/web/admin/test_01_admin_web.py::test_web": 2.0,
        (
            "src/tests/required/test_slack_provider_fake.py::TestFake::test_contract"
        ): 2.0,
    }


def test_plan_suites_falls_back_to_file_for_dynamic_collection(
    tmp_path: Path,
) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required", lanes=1)
    dynamic_test = suite_root / "test_dynamic.py"
    dynamic_test.write_text(
        "globals()['test_generated'] = lambda: None\n",
        encoding="utf-8",
    )

    matrix = plan_suites(
        tests_root=tests_root,
        enabled_suites={"required"},
        timings_path=None,
        output_dir=tmp_path / "plan",
    )

    plan_path = tmp_path / "plan" / matrix["include"][0]["plan_file"]
    assert plan_path.read_text(encoding="utf-8") == f"{dynamic_test.as_posix()}\n"


def test_plan_suites_preserves_source_order_within_lane(tmp_path: Path) -> None:
    tests_root = tmp_path / "tests"
    suite_root = _write_suite(tests_root, "required", lanes=1)
    ordered_test = suite_root / "test_ordered.py"
    ordered_test.write_text(
        "def test_z_first():\n    pass\n\ndef test_a_second():\n    pass\n",
        encoding="utf-8",
    )

    matrix = plan_suites(
        tests_root=tests_root,
        enabled_suites={"required"},
        timings_path=None,
        output_dir=tmp_path / "plan",
    )

    plan_path = tmp_path / "plan" / matrix["include"][0]["plan_file"]
    assert plan_path.read_text(encoding="utf-8") == (
        f"{ordered_test.as_posix()}::test_z_first\n"
        f"{ordered_test.as_posix()}::test_a_second\n"
    )
