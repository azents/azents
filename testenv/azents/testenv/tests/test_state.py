"""State (run + tc scope) unit tests."""

import datetime as dt
import json
from pathlib import Path

from testenv.state import load_state, new_state


def test_set_get_run_scope(tmp_path: Path) -> None:
    """Run scope supports dotted keys."""
    state = new_state(run_id="2026-04-14/run-test", workdir=tmp_path)
    state.set_run("user.email", "foo@bar.baz")
    assert state.get_run("user.email") == "foo@bar.baz"
    assert state.get_run("user.missing") is None
    assert state.get_run("user.missing", "fallback") == "fallback"


def test_set_get_tc_scope(tmp_path: Path) -> None:
    """TC scope stores values separately."""
    state = new_state(run_id="2026-04-14/run-test", workdir=tmp_path)
    state.set_tc("TC-001", "byoa.installation_id", "install-1")
    state.set_tc("TC-002", "byoa.installation_id", "install-2")
    assert state.get_tc("TC-001", "byoa.installation_id") == "install-1"
    assert state.get_tc("TC-002", "byoa.installation_id") == "install-2"


def test_save_and_reload(tmp_path: Path) -> None:
    """State saves and reads back."""
    state = new_state(run_id="2026-04-14/run-save", workdir=tmp_path)
    state.set_run("user.email", "a@b.c")
    state.set_tc("TC-XYZ", "data.foo", {"nested": [1, 2]})
    state.push_finalizer("my-setup", "echo cleanup", scope="run")
    state.save()

    loaded = load_state(state.path)
    assert loaded.get_run("user.email") == "a@b.c"
    assert loaded.get_tc("TC-XYZ", "data.foo") == {"nested": [1, 2]}
    assert len(loaded.finalizers) == 1
    assert loaded.finalizers[0].setup_id == "my-setup"
    assert loaded.finalizers[0].cmd == "echo cleanup"


def test_has_provide(tmp_path: Path) -> None:
    """has_provide checks run and TC scopes."""
    state = new_state(run_id="r", workdir=tmp_path)
    state.set_run("a.b", 1)
    state.set_tc("TC-1", "x.y", 2)
    assert state.has_provide("a.b")
    assert not state.has_provide("a.c")
    assert state.has_provide("x.y", tc_id="TC-1")
    assert not state.has_provide("x.y", tc_id="TC-2")


def test_stale_threshold(tmp_path: Path) -> None:
    """last_verified_at starts stale and honors threshold checks."""
    state = new_state(run_id="r", workdir=tmp_path)
    # Typo values are stale.
    assert state.is_stale("any.key") is True

    state.mark_verified("fresh.key")
    assert state.is_stale("fresh.key", threshold_seconds=3600) is False

    # Two hours ago is stale.
    old = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=2)).isoformat()
    state.verified_at["old.key"] = old
    assert state.is_stale("old.key", threshold_seconds=3600) is True


def test_pop_finalizers_lifo(tmp_path: Path) -> None:
    """pop_all_finalizers returns finalizers in LIFO order."""
    state = new_state(run_id="r", workdir=tmp_path)
    state.push_finalizer("a", "echo a")
    state.push_finalizer("b", "echo b")
    state.push_finalizer("c", "echo c")
    order = state.pop_all_finalizers()
    assert [f.setup_id for f in order] == ["c", "b", "a"]
    assert state.finalizers == []


def test_to_dict_schema(tmp_path: Path) -> None:
    """to_dict returns the persisted document schema."""
    state = new_state(run_id="r", workdir=tmp_path)
    state.set_run("user.email", "x")
    state.mark_verified("user.email")
    state.push_finalizer("s1", "cmd")
    state.save()

    raw = json.loads(state.path.read_text())
    assert set(raw.keys()) == {"_meta", "run", "tc", "_finalizers", "_verified_at"}
    assert raw["_meta"]["run_id"] == "r"
