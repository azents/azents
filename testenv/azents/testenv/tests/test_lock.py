"""Resource lock unit tests."""

import threading
import time
from pathlib import Path

import pytest
from filelock import Timeout

from testenv.lock import exclusive_resource


def test_lock_acquire_release(tmp_path: Path) -> None:
    """Single tag acquire/release smoke test."""
    with exclusive_resource(["shared-oauth-app"], timeout=5, lock_dir=tmp_path):
        # lock file create check
        assert (tmp_path / "shared-oauth-app.lock").exists()


def test_multiple_tags_no_deadlock(tmp_path: Path) -> None:
    """Multiple tags are acquired in sorted order to avoid deadlocks."""
    with exclusive_resource(["z-tag", "a-tag"], timeout=5, lock_dir=tmp_path):
        pass


def test_lock_contention(tmp_path: Path) -> None:
    """Held tag makes a second acquire wait."""
    order: list[str] = []
    holding = threading.Event()
    release = threading.Event()

    def first() -> None:
        with exclusive_resource(["busy"], timeout=10, lock_dir=tmp_path):
            order.append("first-acquired")
            holding.set()
            release.wait(timeout=5)
            order.append("first-release")

    def second() -> None:
        holding.wait(timeout=5)
        # First lock stays held, so second acquire with timeout=2 should fail.
        with pytest.raises(Timeout):
            with exclusive_resource(["busy"], timeout=2, lock_dir=tmp_path):
                order.append("second-acquired")

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    # Wait for the second acquire to time out.
    time.sleep(3)
    release.set()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert "first-acquired" in order
    assert "first-release" in order
    # The second lock should not have been acquired.
    assert "second-acquired" not in order


def test_empty_tags(tmp_path: Path) -> None:
    """Empty tag list is a no-op."""
    with exclusive_resource([], timeout=5, lock_dir=tmp_path):
        pass
