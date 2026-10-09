"""Docker-free coverage for owned E2E image preparation and readiness joins."""

import threading
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from typing import Any

import pytest

from support import e2e_image_preparation
from support.e2e_image_preparation import E2EImagePreparation, ImagePreparationError


def _failure(image: str) -> str:
    raise ValueError(f"secret-bearing builder output for {image}")


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for nested in error.exceptions for leaf in _leaves(nested)]
    return [error]


def test_core_join_does_not_wait_for_web_and_all_images_submit_once() -> None:
    barrier = threading.Barrier(5, timeout=5)
    release_web = threading.Event()
    calls: list[str] = []
    lock = threading.Lock()

    def build(image: str) -> str:
        with lock:
            calls.append(image)
        barrier.wait()
        if image in {"web", "admin-web"}:
            assert release_web.wait(5)
        return f"current-{image}"

    images = ("server", "runner", "provider", "web", "admin-web")
    operations = {image: lambda image=image: build(image) for image in images}
    with E2EImagePreparation({}, operations) as preparation:
        try:
            assert preparation.join(images[:3]) == {
                image: f"current-{image}" for image in images[:3]
            }
            assert not preparation.futures["web"].done()
            assert not preparation.futures["admin-web"].done()
        finally:
            release_web.set()
        assert preparation.join(preparation.selected_images) == {
            image: f"current-{image}" for image in images
        }
        assert preparation.join(images) == {
            image: f"current-{image}" for image in images
        }
    assert sorted(calls) == sorted(images)
    assert all(
        future.done() and not future.cancelled()
        for future in preparation.futures.values()
    )


@pytest.mark.parametrize("prepared", [{}, {"server": "verified-server"}])
def test_no_executor_for_empty_or_supplied_portfolio(
    prepared: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_executor(*args: object, **kwargs: object) -> None:
        raise AssertionError("An empty build batch must not create an executor")

    monkeypatch.setattr(e2e_image_preparation, "ThreadPoolExecutor", forbidden_executor)
    with E2EImagePreparation(prepared, {}) as preparation:
        assert preparation.join(preparation.selected_images) == prepared
        assert preparation.executor is None


def test_mixed_portfolio_captures_supplied_images_and_builds_once() -> None:
    supplied = {"server": "verified-server"}
    calls: list[str] = []

    def build() -> str:
        calls.append("web")
        return "built-web"

    preparation = E2EImagePreparation(supplied, {"web": build})
    supplied["server"] = "later-unverified-value"
    with preparation:
        assert preparation.join(preparation.selected_images) == {
            "server": "verified-server",
            "web": "built-web",
        }
    preparation.close()
    assert calls == ["web"]
    with pytest.raises(RuntimeError, match="entered only once"):
        preparation.__enter__()


def test_join_reports_all_failures_without_publishing_partial_success() -> None:
    with E2EImagePreparation(
        {}, {"server": lambda: _failure("server"), "web": lambda: _failure("web")}
    ) as preparation:
        for _ in range(2):
            with pytest.raises(ExceptionGroup) as captured:
                preparation.join(preparation.selected_images)
            errors = _leaves(captured.value)
            assert {
                error.image
                for error in errors
                if isinstance(error, ImagePreparationError)
            } == {"server", "web"}
            assert "secret-bearing" not in str(captured.value)
            assert all(isinstance(error, ImagePreparationError) for error in errors)
    assert preparation.reported_failures == {"server", "web"}
    preparation.close()


def test_consumer_failure_drains_and_preserves_unreported_image_failures() -> None:
    release = threading.Event()
    started = threading.Event()

    def web() -> str:
        started.set()
        assert release.wait(5)
        return _failure("web")

    preparation = E2EImagePreparation({"server": "current-server"}, {"web": web})
    primary = LookupError("consumer setup failed")
    with pytest.raises(ExceptionGroup) as captured:
        with preparation:
            assert started.wait(5)
            assert preparation.join(["server"]) == {"server": "current-server"}
            release.set()
            raise primary
    errors = _leaves(captured.value)
    assert errors[0] is primary
    assert isinstance(errors[1], ImagePreparationError)
    assert preparation.closed and preparation.futures["web"].done()
    preparation.close()


def test_close_reports_every_unconsumed_failure_once() -> None:
    preparation = E2EImagePreparation(
        {}, {"web": lambda: _failure("web"), "admin-web": lambda: _failure("admin-web")}
    )
    preparation.__enter__()
    with pytest.raises(ExceptionGroup) as captured:
        preparation.close()
    assert {
        error.image
        for error in _leaves(captured.value)
        if isinstance(error, ImagePreparationError)
    } == {"web", "admin-web"}
    assert all(future.done() for future in preparation.futures.values())
    preparation.close()


def test_partial_submit_failure_drains_even_when_enter_did_not_finish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = threading.Event()

    class FailingExecutor(ThreadPoolExecutor):
        def submit[T](
            self, fn: Callable[..., T], /, *args: Any, **kwargs: Any
        ) -> Future[T]:
            if completed.is_set():
                raise RuntimeError("submit failed")
            future = super().submit(fn, *args, **kwargs)
            assert completed.wait(5)
            return future

    def first() -> str:
        completed.set()
        return "current-server"

    monkeypatch.setattr(e2e_image_preparation, "ThreadPoolExecutor", FailingExecutor)
    preparation = E2EImagePreparation({}, {"server": first, "web": lambda: "web"})
    with pytest.raises(RuntimeError, match="submit failed"):
        preparation.__enter__()
    assert preparation.closed
    assert set(preparation.futures) == {"server"}
    assert preparation.futures["server"].done()


def test_worker_baseexception_preserves_identity_and_drains_other_builds() -> None:
    interruption = KeyboardInterrupt("abort")
    other_completed = threading.Event()

    def abort() -> str:
        raise interruption

    def other() -> str:
        other_completed.set()
        return "web"

    preparation = E2EImagePreparation({}, {"server": abort, "web": other})
    with pytest.raises(KeyboardInterrupt) as captured:
        with preparation:
            preparation.join(["server"])
    assert captured.value is interruption
    assert other_completed.is_set()
    assert all(
        future.done() and not future.cancelled()
        for future in preparation.futures.values()
    )


def test_interrupted_join_drains_pending_future_before_propagating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preparation = E2EImagePreparation({}, {"web": lambda: "current-web"})
    with pytest.raises(KeyboardInterrupt, match="join interrupted"):
        with preparation:
            future = preparation.futures["web"]
            original_result = future.result
            calls = 0

            def interrupted_result(timeout: float | None = None) -> str:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise KeyboardInterrupt("join interrupted")
                return original_result(timeout)

            monkeypatch.setattr(future, "result", interrupted_result)
            preparation.join(["web"])
    assert preparation.closed and future.done()
    assert preparation.reported_failures == set()


def test_unexpected_cancelled_future_is_failure_not_ready_image() -> None:
    preparation = E2EImagePreparation({}, {})
    preparation.__enter__()
    cancelled: Future[str] = Future()
    assert cancelled.cancel()
    preparation.selected_images = ("web",)
    preparation.futures["web"] = cancelled
    with pytest.raises(CancelledError) as captured:
        preparation.join(["web"])
    assert type(captured.value).__name__ == "CancelledError"
    preparation.close()
    assert preparation.reported_failures == {"web"}
