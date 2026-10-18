"""Distributed pytest preserves failures, phase multiplicity and fixture receipts."""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from collections import Counter
from pathlib import Path

from azents.consts import PROJECT_ROOT


def _run_parallel(project: Path, evidence: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    # This subprocess owns a new controller, even if its parent test is a worker.
    for name in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
    ):
        environment.pop(name, None)
    environment["PATH"] = os.pathsep.join(
        [str(Path(sys.executable).parent), environment.get("PATH", "")]
    )
    root = PROJECT_ROOT.parents[2]
    return subprocess.run(
        [
            sys.executable,
            str(root / "scripts/ci/run_pytest.py"),
            "--project",
            str(project),
            "--artifact-dir",
            str(evidence),
            "--name",
            "parallel-contract",
            "--system-python",
            "--",
            "-q",
            "-n",
            "2",
            "--dist",
            "loadfile",
            "--max-worker-restart=0",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_two_workers_keep_complete_safe_evidence_and_failed_exit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "conftest.py").write_text(
        "import pytest\n@pytest.fixture(scope='session')\ndef opaque():\n"
        "    yield 'private-fixture-content'\n"
    )
    (project / "test_first.py").write_text(
        "def test_pass(opaque):\n    assert opaque\n"
        "def test_fail(opaque):\n    assert False, 'private-exception-content'\n"
    )
    (project / "test_second.py").write_text(
        "def test_other_pass(opaque):\n    assert opaque\n"
        "def test_final_pass(opaque):\n    assert opaque\n"
    )
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == 1, result.stdout + result.stderr
    native = json.loads((evidence / "test-run.json").read_text())
    assert native["exit_code"] == 1
    assert native["duration_seconds"] > 0
    junit = element_tree.parse(evidence / "junit.xml")
    assert len(list(junit.iter("testcase"))) == 4
    assert len(list(junit.iter("failure"))) == 1
    content = (evidence / "pytest-timings.jsonl").read_text()
    assert "private-fixture-content" not in content
    assert "private-exception-content" not in content
    records = [json.loads(line) for line in content.splitlines()]
    phases = [record for record in records if record["record_type"] == "test_phase"]
    assert len(phases) == 12
    assert set(Counter((row["node_id"], row["phase"]) for row in phases).values()) == {
        1
    }
    assert sum(row["outcome"] == "failed" for row in phases) == 1
    workers = sorted(evidence.glob("fixture-timings-gw*.jsonl"))
    assert [worker.name for worker in workers] == [
        "fixture-timings-gw0.jsonl",
        "fixture-timings-gw1.jsonl",
    ]
    raw_fixtures = []
    for worker in workers:
        worker_records = [json.loads(line) for line in worker.read_text().splitlines()]
        assert all(row["record_type"] == "fixture" for row in worker_records)
        assert any(
            row["fixture"] == "opaque" and row["phase"] == "teardown"
            for row in worker_records
        )
        raw_fixtures.extend(worker_records)
    assert Counter(json.dumps(row, sort_keys=True) for row in raw_fixtures) == Counter(
        json.dumps(row, sort_keys=True)
        for row in records
        if row["record_type"] == "fixture"
    )


def test_worker_process_crash_aborts_without_restart_or_replay(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "attempts.txt"
    (project / "conftest.py").write_text(
        "import os\nfrom pathlib import Path\nimport pytest\n"
        "def pytest_sessionstart(session):\n"
        "    worker = os.environ.get('PYTEST_XDIST_WORKER')\n"
        "    if worker is not None:\n"
        f"        (Path({str(tmp_path)!r}) / ('started-' + worker)).touch()\n"
        "@pytest.fixture(scope='session', autouse=True)\ndef resource():\n"
        "    yield 1\n"
    )
    (project / "test_first.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_01_crash():\n"
        f"    with Path({str(marker)!r}).open('a') as output:\n"
        "        output.write('crash\\n')\n"
        "    os._exit(17)\n"
        "def test_02_unfinished():\n"
        f"    with Path({str(marker)!r}).open('a') as output:\n"
        "        output.write('replayed\\n')\n"
    )
    (project / "test_second.py").write_text("def test_other():\n    assert True\n")
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "without worker restart or replay" in result.stdout + result.stderr
    assert marker.read_text().splitlines() == ["crash"]
    assert len(list(tmp_path.glob("started-gw*"))) == 2
    native = json.loads((evidence / "test-run.json").read_text())
    assert native["exit_code"] == 1
    assert list(evidence.glob("fixture-timings-gw*.jsonl"))
