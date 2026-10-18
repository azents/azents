"""Background preparation owns startup failure, exact join, and cleanup."""

from collections.abc import Generator
from contextlib import contextmanager
from threading import Event
from unittest.mock import Mock

import pytest

from support import background_fixture as background


def test_background_setup_overlaps_body_and_closes_after_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reached, release = Event(), Event()
    lifecycle: list[str] = []
    receipt = Mock()
    monkeypatch.setattr(background, "record_fixture_phase", receipt)

    @contextmanager
    def prepare() -> Generator[str, None, None]:
        lifecycle.append("starting")
        reached.set()
        assert release.wait(timeout=5)
        try:
            yield "prepared"
        finally:
            lifecycle.append("closed")

    with background.background_fixture(prepare, fixture="synthetic") as start:
        assert reached.wait(timeout=5)
        assert not start.future.done()
        lifecycle.append("independent-body")
        release.set()
        assert start.future.result(timeout=5) == "prepared"
        assert "closed" not in lifecycle
    assert lifecycle == ["starting", "independent-body", "closed"]
    receipt.assert_called_once()
    assert receipt.call_args.kwargs["outcome"] == "passed"
    assert receipt.call_args.kwargs["duration_seconds"] >= 0


def test_unconsumed_setup_failure_is_joined_and_cleanup_still_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lifecycle: list[str] = []
    receipt = Mock()
    monkeypatch.setattr(background, "record_fixture_phase", receipt)

    @contextmanager
    def prepare() -> Generator[str, None, None]:
        try:
            raise ValueError("synthetic setup failure")
            yield "unreachable"
        finally:
            lifecycle.append("closed")

    with pytest.raises(ValueError, match="synthetic setup failure"):
        with background.background_fixture(prepare, fixture="synthetic"):
            pass
    assert lifecycle == ["closed"]
    assert receipt.call_args.kwargs["outcome"] == "failed"


def test_cleanup_failure_remains_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(background, "record_fixture_phase", Mock())

    @contextmanager
    def prepare() -> Generator[str, None, None]:
        yield "prepared"
        raise RuntimeError("synthetic cleanup failure")

    with pytest.raises(RuntimeError, match="synthetic cleanup failure"):
        with background.background_fixture(prepare, fixture="synthetic") as start:
            assert start.future.result(timeout=5) == "prepared"


def test_consuming_scope_closes_once_before_outer_fallback_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(background, "record_fixture_phase", Mock())
    lifecycle: list[str] = []

    @contextmanager
    def prepare() -> Generator[str, None, None]:
        try:
            yield "prepared"
        finally:
            lifecycle.append("closed")

    with background.background_fixture(prepare, fixture="synthetic") as start:
        assert start.future.result(timeout=5) == "prepared"
        start.close()
        assert lifecycle == ["closed"]
        start.close()
        assert lifecycle == ["closed"]
        lifecycle.append("later-independent-work")
    assert lifecycle == ["closed", "later-independent-work"]
