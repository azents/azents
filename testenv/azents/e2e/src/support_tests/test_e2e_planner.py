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
