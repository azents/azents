"""Owned background fixture preparation with joined failure and cleanup evidence."""

import time
from collections.abc import Callable, Generator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass
from typing import Literal

from scripts.ci.pytest_timing import record_fixture_phase


@dataclass
class _SetupTiming:
    duration_seconds: float | None
    outcome: Literal["passed", "failed"] | None


@dataclass(frozen=True)
class BackgroundFixture[T]:
    """Allow the consuming scope to release its resources before fallback cleanup."""

    future: Future[T]
    owned: ExitStack

    def close(self) -> None:
        try:
            self.future.result()
        finally:
            self.owned.close()


@contextmanager
def background_fixture[T](
    factory: Callable[[], AbstractContextManager[T]], *, fixture: str
) -> Generator[BackgroundFixture[T], None, None]:
    """Prepare one owned fixture, join errors and drain before closing its resources."""
    timing = _SetupTiming(None, None)
    with ExitStack() as owned, ThreadPoolExecutor(max_workers=1) as executor:

        def prepare() -> T:
            started = time.monotonic()
            outcome: Literal["passed", "failed"] = "failed"
            try:
                value = owned.enter_context(factory())
                outcome = "passed"
                return value
            finally:
                timing.duration_seconds = time.monotonic() - started
                timing.outcome = outcome

        start = BackgroundFixture(executor.submit(prepare), owned)
        try:
            yield start
        finally:
            try:
                start.close()
            finally:
                assert timing.duration_seconds is not None
                assert timing.outcome is not None
                record_fixture_phase(
                    fixture=fixture,
                    scope="session",
                    node_id="",
                    phase="setup",
                    duration_seconds=timing.duration_seconds,
                    outcome=timing.outcome,
                )
