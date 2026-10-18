"""Listener-free contracts for isolated E2E workers and fail-closed evidence."""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as element_tree
from collections import Counter
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts.ci.pytest_timing import record_fixture_phase

from support import e2e_parallel

_ROOT = Path(__file__).resolve().parents[5]
_WORKERS = frozenset({"gw0", "gw1"})


def _startup() -> dict[str, object]:
    return {
        "completed": True,
        "wall_seconds": 1.0,
        "task_seconds": 1.0,
        "overlap_seconds": 0.0,
        "readiness_scope": "server",
        "readiness_timings": {},
        "tasks": {"synthetic": {"duration_seconds": 1.0, "outcome": "success"}},
    }


def _worker(root: Path, worker: str, images: list[str]) -> Path:
    directory = e2e_parallel.worker_artifact_directory(root, worker)
    directory.mkdir(parents=True)
    (directory / "image-build-plan.json").write_text(json.dumps({"images": images}))
    (directory / "core-prerequisite-timings.json").write_text(json.dumps(_startup()))
    (root / f"fixture-timings-{worker}.jsonl").write_text(
        json.dumps(
            {
                "record_type": "fixture",
                "fixture": "synthetic",
                "scope": "session",
                "node_id": "",
                "phase": "setup",
                "duration_seconds": 1.0,
                "outcome": "passed",
            }
        )
        + "\n"
    )
    if images:
        (directory / "image-build-timings.jsonl").write_text(
            "".join(json.dumps(_image(image)) + "\n" for image in images)
        )
    return directory


def _image(image: str) -> dict[str, object]:
    return {
        "image": image,
        "duration_seconds": 1.0,
        "completed": True,
        "cache_backend": "none",
        "cache_scope": None,
        "cache_export_enabled": False,
        "build_mode": "full",
        "started_at_monotonic": 1.0,
        "finished_at_monotonic": 2.0,
    }


@pytest.mark.parametrize("worker", ["../gw0", "gw0/child", "controller", "GW0"])
def test_worker_directory_rejects_unbounded_identity(
    tmp_path: Path, worker: str
) -> None:
    with pytest.raises(ValueError, match="Invalid E2E worker"):
        e2e_parallel.worker_artifact_directory(tmp_path, worker)


def test_worker_redirect_keeps_shared_timing_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("AZENTS_CI_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    e2e_parallel.pytest_configure(Mock(spec=pytest.Config))
    assert os.environ["AZENTS_E2E_ARTIFACT_DIR"] == str(tmp_path / "workers/gw1")
    assert os.environ["AZENTS_CI_ARTIFACT_DIR"] == str(tmp_path)
    assert (tmp_path / "workers/gw1").is_dir()


def test_controller_rejects_stale_worker_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZENTS_E2E_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    (tmp_path / "workers").mkdir()
    config = Mock(spec=pytest.Config)
    config.getoption.return_value = 2
    with pytest.raises(pytest.UsageError, match="not fresh"):
        e2e_parallel.pytest_configure(config)


def test_parallel_e2e_requires_explicit_diagnostics_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZENTS_E2E_ARTIFACT_DIR", raising=False)
    config = Mock(spec=pytest.Config)
    config.getoption.return_value = 2
    with pytest.raises(pytest.UsageError, match="require AZENTS_E2E_ARTIFACT_DIR"):
        e2e_parallel.pytest_configure(config)


def test_explicit_background_fixture_receipt_keeps_its_worker_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AZENTS_CI_ARTIFACT_DIR", str(tmp_path))
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    record_fixture_phase(
        fixture="synthetic-background",
        scope="session",
        node_id="",
        phase="setup",
        duration_seconds=0.1,
        outcome="passed",
    )
    assert not (tmp_path / "pytest-timings.jsonl").exists()
    record = json.loads((tmp_path / "fixture-timings-gw1.jsonl").read_text())
    assert record["fixture"] == "synthetic-background"
    assert record["record_type"] == "fixture"


def test_image_merge_validates_all_and_preserves_raw_receipts(tmp_path: Path) -> None:
    sources = []
    for worker in ("gw0", "gw1"):
        source = _worker(tmp_path, worker, [worker])
        path = source / "image-build-timings.jsonl"
        sources.append(path.read_text())
    e2e_parallel.merge_worker_image_timings(
        tmp_path, workers=_WORKERS, require_complete=True
    )
    assert (tmp_path / "image-build-timings.jsonl").read_text() == "".join(sources)
    assert [
        p.read_text() for p in sorted(tmp_path.glob("workers/*/*.jsonl"))
    ] == sources
    with pytest.raises(FileExistsError):
        e2e_parallel.merge_worker_image_timings(
            tmp_path, workers=_WORKERS, require_complete=True
        )


def test_invalid_image_receipt_cannot_become_a_partial_merged_success(
    tmp_path: Path,
) -> None:
    for worker in ("gw0", "gw1"):
        directory = _worker(tmp_path, worker, [worker])
        payload = _image(worker)
        if worker == "gw1":
            payload["untrusted"] = "synthetic-private-value"
        (directory / "image-build-timings.jsonl").write_text(json.dumps(payload) + "\n")
    with pytest.raises(ValueError):
        e2e_parallel.merge_worker_image_timings(
            tmp_path, workers=_WORKERS, require_complete=True
        )
    assert not (tmp_path / "image-build-timings.jsonl").exists()
    assert len(list(tmp_path.glob("workers/*/*.jsonl"))) == 2


@pytest.mark.parametrize(
    "missing",
    [
        "worker",
        "image-build-plan.json",
        "core-prerequisite-timings.json",
        "image-build-timings.jsonl",
        "empty",
        "fixture",
        "incomplete",
        "unexpected",
    ],
)
def test_success_requires_every_expected_worker_receipt(
    tmp_path: Path, missing: str
) -> None:
    _worker(tmp_path, "gw0", ["gw0"])
    if missing != "worker":
        directory = _worker(tmp_path, "gw1", ["gw1"])
        if missing == "empty":
            (directory / "image-build-timings.jsonl").write_text("")
        elif missing == "incomplete":
            payload = _startup()
            payload["completed"] = False
            (directory / "core-prerequisite-timings.json").write_text(
                json.dumps(payload)
            )
        elif missing == "unexpected":
            _worker(tmp_path, "gw2", ["gw2"])
        elif missing == "fixture":
            (tmp_path / "fixture-timings-gw1.jsonl").unlink()
        else:
            (directory / missing).unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        e2e_parallel.merge_worker_image_timings(
            tmp_path, workers=_WORKERS, require_complete=True
        )
    assert not (tmp_path / "image-build-timings.jsonl").exists()


def test_prepared_images_allow_explicit_zero_local_builds(tmp_path: Path) -> None:
    for worker in _WORKERS:
        _worker(tmp_path, worker, [])
    e2e_parallel.merge_worker_image_timings(
        tmp_path, workers=_WORKERS, require_complete=True
    )
    assert not (tmp_path / "image-build-timings.jsonl").exists()


def test_publication_failure_retains_raw_and_no_partial_aggregate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for worker in _WORKERS:
        _worker(tmp_path, worker, [worker])
    before = {p: p.read_bytes() for p in tmp_path.glob("workers/*/*")}
    monkeypatch.setattr(os, "link", Mock(side_effect=OSError("Publication failed")))
    with pytest.raises(OSError, match="Publication failed"):
        e2e_parallel.merge_worker_image_timings(
            tmp_path, workers=_WORKERS, require_complete=True
        )
    assert not (tmp_path / "image-build-timings.jsonl").exists()
    assert not (tmp_path / ".image-build-timings.pending").exists()
    assert {p: p.read_bytes() for p in tmp_path.glob("workers/*/*")} == before


def _run_parallel(project: Path, evidence: Path) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for name in (
        "PYTEST_XDIST_WORKER",
        "PYTEST_XDIST_WORKER_COUNT",
        "PYTEST_XDIST_TESTRUNUID",
    ):
        environment.pop(name, None)
    environment["AZENTS_E2E_ARTIFACT_DIR"] = str(evidence)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(_ROOT / "testenv/azents/e2e/src"), str(_ROOT)]
    )
    return subprocess.run(
        [
            sys.executable,
            str(_ROOT / "scripts/ci/run_pytest.py"),
            "--project",
            str(project),
            "--artifact-dir",
            str(evidence),
            "--name",
            "parallel-e2e-contract",
            "--system-python",
            "--",
            "-q",
            "-p",
            "support.e2e_parallel",
            "-n",
            "2",
            "--dist",
            "loadfile",
            "--no-loadscope-reorder",
            "--max-worker-restart=0",
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_two_workers_preserve_failure_scope_and_raw_e2e_diagnostics(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    project.joinpath("conftest.py").write_text(
        "import json,os\nfrom pathlib import Path\nimport pytest\n"
        "from scripts.ci.pytest_timing import record_fixture_phase\n"
        "@pytest.fixture(scope='session')\ndef opaque():\n"
        "    root=Path(os.environ['AZENTS_E2E_ARTIFACT_DIR'])\n"
        f"    image={_image('synthetic-image')!r}\n"
        "    image['image']=root.name\n"
        "    (root/'image-build-timings.jsonl').write_text(json.dumps(image)+'\\n')\n"
        "    (root/'image-build-plan.json').write_text("
        "json.dumps({'images':[root.name]}))\n"
        "    (root/'core-prerequisite-timings.json').write_text("
        f"json.dumps({_startup()!r}))\n"
        "    record_fixture_phase(fixture='synthetic-background',scope='session',"
        "node_id='',phase='setup',duration_seconds=0.1,outcome='passed')\n"
        "    yield 'synthetic-private-fixture'\n"
    )
    project.joinpath("test_first.py").write_text(
        "def test_pass(opaque):\n    assert opaque\n"
        "def test_fail(opaque):\n    assert False, 'synthetic-private-failure'\n"
    )
    project.joinpath("test_second.py").write_text(
        "def test_other(opaque):\n    assert opaque\n"
        "def test_final(opaque):\n    assert opaque\n"
    )
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == 1, result.stdout + result.stderr
    assert json.loads((evidence / "test-run.json").read_text())["exit_code"] == 1
    junit = element_tree.parse(evidence / "junit.xml")
    assert len(list(junit.iter("testcase"))) == 4
    assert len(list(junit.iter("failure"))) == 1
    text = (evidence / "pytest-timings.jsonl").read_text()
    assert "synthetic-private-fixture" not in text
    assert "synthetic-private-failure" not in text
    records = [json.loads(line) for line in text.splitlines()]
    phases = [x for x in records if x["record_type"] == "test_phase"]
    assert len(phases) == 12
    assert set(Counter((x["node_id"], x["phase"]) for x in phases).values()) == {1}
    raw = [
        json.loads(line)
        for p in evidence.glob("fixture-timings-gw*.jsonl")
        for line in p.read_text().splitlines()
    ]
    assert Counter(json.dumps(x, sort_keys=True) for x in raw) == Counter(
        json.dumps(x, sort_keys=True) for x in records if x["record_type"] == "fixture"
    )
    assert len(list(evidence.glob("workers/*/image-build-timings.jsonl"))) == 2
    merged = [
        json.loads(line)
        for line in (evidence / "image-build-timings.jsonl").read_text().splitlines()
    ]
    assert {x["image"] for x in merged} == {"gw0", "gw1"}


def test_worker_death_aborts_before_restart_or_unfinished_file_replay(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    marker = tmp_path / "attempts.txt"
    project.joinpath("conftest.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def pytest_sessionstart(session):\n"
        "    worker=os.environ.get('PYTEST_XDIST_WORKER')\n"
        "    if worker is not None:\n"
        f"        (Path({str(tmp_path)!r}) / ('started-'+worker)).touch()\n"
    )
    project.joinpath("test_first.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "def test_01_crash():\n"
        f"    with Path({str(marker)!r}).open('a') as output:\n"
        "        output.write('crash\\n')\n"
        "    os._exit(17)\n"
        "def test_02_unfinished():\n"
        f"    with Path({str(marker)!r}).open('a') as output:\n"
        "        output.write('replayed\\n')\n"
    )
    project.joinpath("test_second.py").write_text(
        "def test_other():\n    assert True\n"
    )
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "without worker restart or replay" in result.stdout + result.stderr
    assert marker.read_text().splitlines() == ["crash"]
    assert len(list(tmp_path.glob("started-gw*"))) == 2
    assert json.loads((evidence / "test-run.json").read_text())["exit_code"] == 1


@pytest.mark.parametrize("lost_receipt", [False, True])
def test_green_cases_require_complete_worker_evidence_at_process_exit(
    tmp_path: Path, lost_receipt: bool
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    project.joinpath("conftest.py").write_text(
        "import json,os\nfrom pathlib import Path\nimport pytest\n"
        "@pytest.fixture(scope='session',autouse=True)\ndef receipts():\n"
        "    root=Path(os.environ['AZENTS_E2E_ARTIFACT_DIR'])\n"
        f"    image={_image('synthetic-image')!r}\n"
        "    image['image']=root.name\n"
        "    (root/'image-build-plan.json').write_text("
        "json.dumps({'images':[root.name]}))\n"
        "    (root/'core-prerequisite-timings.json').write_text("
        f"json.dumps({_startup()!r}))\n"
        f"    if not ({lost_receipt!r} and root.name=='gw1'):\n"
        "        (root/'image-build-timings.jsonl').write_text("
        "json.dumps(image)+'\\n')\n"
    )
    for file in ("first", "second"):
        project.joinpath(f"test_{file}.py").write_text(
            "def test_ok():\n    assert True\n"
        )
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == (1 if lost_receipt else 0), (
        result.stdout + result.stderr
    )
    assert len(list(element_tree.parse(evidence / "junit.xml").iter("testcase"))) == 2
    if lost_receipt:
        assert "Incomplete E2E worker image/startup evidence" in result.stderr
        assert not (evidence / "image-build-timings.jsonl").exists()


def test_loadfile_keeps_plan_order_and_each_complete_file_on_one_worker(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    project.joinpath("conftest.py").write_text(
        "import json,os\nfrom pathlib import Path\nimport pytest\n"
        "@pytest.fixture(scope='session',autouse=True)\ndef receipts():\n"
        "    root=Path(os.environ['AZENTS_E2E_ARTIFACT_DIR'])\n"
        "    (root/'image-build-plan.json').write_text(json.dumps({'images':[]}))\n"
        "    (root/'core-prerequisite-timings.json').write_text("
        f"json.dumps({_startup()!r}))\n"
        "@pytest.fixture\ndef owned():\n    return True\n"
    )
    counts = {"a_long": 1, "b_long": 1, "c_short": 4, "d_short": 4}
    for file, count in counts.items():
        project.joinpath(f"test_{file}.py").write_text(
            "".join(
                f"def test_{index}(owned):\n    assert owned\n"
                for index in range(count)
            )
        )
    evidence = tmp_path / "evidence"
    result = _run_parallel(project, evidence)
    assert result.returncode == 0, result.stdout + result.stderr
    file_workers: dict[str, set[str]] = {}
    orders: dict[str, list[str]] = {}
    for worker in ("gw0", "gw1"):
        records = [
            json.loads(line)
            for line in (evidence / f"fixture-timings-{worker}.jsonl")
            .read_text()
            .splitlines()
        ]
        nodes = [
            record["node_id"]
            for record in records
            if record["fixture"] == "owned" and record["phase"] == "setup"
        ]
        for node in nodes:
            file = node.split("::", 1)[0]
            file_workers.setdefault(file, set()).add(worker)
            orders.setdefault(file, []).append(node)
        assert nodes
        assert Path(nodes[0].split("::", 1)[0]).name in {
            "test_a_long.py",
            "test_b_long.py",
        }
    assert set().union(*file_workers.values()) == {"gw0", "gw1"}
    assert all(len(workers) == 1 for workers in file_workers.values())
    for file, nodes in orders.items():
        count = counts[Path(file).stem.removeprefix("test_")]
        assert [node.split("::", 1)[1] for node in nodes] == [
            f"test_{index}" for index in range(count)
        ]
