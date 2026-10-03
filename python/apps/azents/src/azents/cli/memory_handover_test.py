"""Operator CLI fails closed before environment access and reports only counts."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from azents.cli import memory_handover
from azents.core.historical_memory_cutover import (
    MemoryHandoverAction,
    MemoryHandoverRequest,
    MemoryHandoverResult,
)
from azents.services.historical_memory.cutover import MemoryHandoverService


def test_cli_requires_quiescence_confirmation_before_environment_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_config() -> None:
        raise AssertionError("No configuration or database access before confirmation")

    monkeypatch.setattr(memory_handover.Config, "from_env", forbidden_config)
    result = CliRunner().invoke(memory_handover.app, ["forward"])
    assert result.exit_code != 0 and "quiesced" in result.output


@dataclass
class _Config:
    runtime_env: str = "test"
    sentry_dsn: str | None = None


class _Container:
    def __init__(self, service: AsyncMock) -> None:
        self.service = service

    async def solve(self, expected: type[MemoryHandoverService]) -> AsyncMock:
        assert expected is MemoryHandoverService
        return self.service


def test_cli_passes_explicit_action_and_bounded_batch_then_reports_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = AsyncMock(spec=MemoryHandoverService)
    service.handover.return_value = MemoryHandoverResult(4, 2, 7)
    monkeypatch.setattr(memory_handover.Config, "from_env", _Config)
    monkeypatch.setattr(
        memory_handover, "configure_logging_for_runtime", lambda **_kw: None
    )

    @asynccontextmanager
    async def container(_config: _Config) -> AsyncIterator[_Container]:
        yield _Container(service)

    monkeypatch.setattr(memory_handover, "run_with_container", container)
    result = CliRunner().invoke(
        memory_handover.app,
        ["reactivate", "--confirm-execution-quiesced", "--batch-size", "1"],
    )
    assert result.exit_code == 0, result.output
    assert '"snapshots_reset": 4' in result.output
    service.handover.assert_awaited_once_with(
        MemoryHandoverRequest(MemoryHandoverAction.REACTIVATE, True, 1)
    )
