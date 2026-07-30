"""Tests for E2E server readiness polling."""

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
import requests
from docker.models.containers import Container
from pytest import MonkeyPatch
from testcontainers.core.container import DockerContainer

from support import server_readiness


@dataclass
class _Clock:
    now: float = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _WrappedContainer:
    def __init__(self) -> None:
        self.status = "running"
        self.reload_calls = 0

    def reload(self) -> None:
        self.reload_calls += 1


class _Container:
    def __init__(self) -> None:
        self.wrapped = _WrappedContainer()

    def get_container_host_ip(self) -> str:
        return "127.0.0.1"

    def get_exposed_port(self, port: int) -> int:
        return port

    def get_wrapped_container(self) -> Container:
        return cast(Container, self.wrapped)

    def get_logs(self) -> tuple[bytes, bytes]:
        return b"stdout", b"stderr"


class _ReadinessRequests:
    exceptions = requests.exceptions

    def __init__(self, *, succeed_on_attempt: int | None) -> None:
        self.succeed_on_attempt = succeed_on_attempt
        self.attempts = 0
        self.timeouts: list[float] = []

    def get(self, url: str, *, timeout: float) -> SimpleNamespace:
        del url
        self.attempts += 1
        self.timeouts.append(timeout)
        if self.attempts == self.succeed_on_attempt:
            return SimpleNamespace(status_code=200)
        raise requests.ConnectionError("not ready")


def _configure_polling(
    monkeypatch: MonkeyPatch,
    *,
    clock: _Clock,
    readiness_requests: _ReadinessRequests,
    timeout: float,
) -> None:
    monkeypatch.setattr(server_readiness, "time", clock)
    monkeypatch.setattr(server_readiness, "requests", readiness_requests)
    monkeypatch.setattr(server_readiness, "_SERVER_READY_TIMEOUT_SECONDS", timeout)
    monkeypatch.setattr(server_readiness, "_SERVER_READY_REQUEST_TIMEOUT_SECONDS", 2.0)
    monkeypatch.setattr(server_readiness, "_SERVER_READY_POLL_INTERVAL_SECONDS", 1.0)


def test_server_readiness_can_succeed_after_more_than_thirty_polls(
    monkeypatch: MonkeyPatch,
) -> None:
    """A running server can finish slow startup work within the deadline."""
    clock = _Clock()
    readiness_requests = _ReadinessRequests(succeed_on_attempt=32)
    container = _Container()
    _configure_polling(
        monkeypatch,
        clock=clock,
        readiness_requests=readiness_requests,
        timeout=40.0,
    )

    base_url = server_readiness.wait_for_server_ready(
        cast(DockerContainer, container),
        8010,
        "azents-public-server",
    )

    assert base_url == "http://127.0.0.1:8010"
    assert readiness_requests.attempts == 32
    assert container.wrapped.reload_calls == 32
    assert all(value <= 2.0 for value in readiness_requests.timeouts)


def test_server_readiness_fails_at_the_deadline(
    monkeypatch: MonkeyPatch,
) -> None:
    """A running but unavailable server still fails with captured logs."""
    clock = _Clock()
    readiness_requests = _ReadinessRequests(succeed_on_attempt=None)
    container = _Container()
    _configure_polling(
        monkeypatch,
        clock=clock,
        readiness_requests=readiness_requests,
        timeout=3.0,
    )

    with pytest.raises(
        pytest.fail.Exception,
        match="azents-public-server did not start in time",
    ):
        server_readiness.wait_for_server_ready(
            cast(DockerContainer, container),
            8010,
            "azents-public-server",
        )

    assert clock.now == 3.0
    assert readiness_requests.attempts == 3
    assert container.wrapped.reload_calls == 4
