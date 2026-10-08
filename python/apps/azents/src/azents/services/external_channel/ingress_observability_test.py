"""Post-SQL metric/Runtime projection and the actual read-only ingress CLI."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from azcommon import di
from azcommon.logging import RuntimeEnvironment
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from testcontainers.postgres import PostgresContainer

from azents.cli import external_channel_ingress as cli_module
from azents.core.config import Config
from azents.job_runtime.types import JobHandle, JobRequest, JobRuntime
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadWriteSession, WriteSession
from azents.repos.external_channel.ingress_control_read_test import (
    _Boundary,
    _ReadFault,
    _reads,
    _seed,
)
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetrics,
    ExternalChannelIngressMetricSnapshot,
)
from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
    ExternalChannelIngressObservation,
)


class _Runtime(JobRuntime):
    """Assert that Runtime counters are read only after actual SQL completion."""

    def __init__(self, boundary: _Boundary, outcome: str) -> None:
        self.boundary = boundary
        self.outcome = outcome
        self.observed: list[str] = []

    @property
    def active_count(self) -> int:
        self.boundary.closed()
        self.observed.append("active_count")
        if self.outcome == "error":
            raise ValueError("metric Runtime error")
        if self.outcome == "cancel":
            raise asyncio.CancelledError()
        assert self.outcome == "success"
        return 7

    @property
    def shutdown_drain_seconds(self) -> float | None:
        self.boundary.closed()
        self.observed.append("shutdown_drain_seconds")
        return None

    async def submit(self, request: JobRequest) -> JobHandle:
        raise AssertionError("Observation and status are read-only.")


class _Metrics(ExternalChannelIngressMetrics):
    """Witness the existing canonical metric sampler without replacing it."""

    def __init__(self, boundary: _Boundary) -> None:
        super().__init__()
        self.boundary = boundary
        self.calls: list[int] = []

    def snapshot(
        self,
        runtime: JobRuntime,
        *,
        active_backlog_size: int,
        oldest_queue_age_seconds: int | None,
    ) -> ExternalChannelIngressMetricSnapshot:
        self.boundary.closed()
        self.calls.append(active_backlog_size)
        return super().snapshot(
            runtime,
            active_backlog_size=active_backlog_size,
            oldest_queue_age_seconds=oldest_queue_age_seconds,
        )


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "populated"])
async def test_observation_closes_before_metrics_and_runtime_counts(
    rdb_session_manager: SessionManager[WriteSession], seeded: bool
) -> None:
    seed = await _seed(rdb_session_manager) if seeded else None
    boundary = _Boundary(rdb_session_manager)
    metrics = _Metrics(boundary)
    runtime = _Runtime(boundary, "success")
    service = ExternalChannelIngressObservabilityService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        metrics=metrics,
        runtime=runtime,
    )
    observation = await service.observe(limit=1)
    boundary.closed()
    assert boundary.events == ["open", "commit", "commit", "closed"]
    assert metrics.calls == [3 if seeded else 0]
    assert runtime.observed == ["active_count", "shutdown_drain_seconds"]
    assert observation.metrics.runtime_active_task_count == 7
    assert observation.queue.counts.total == (3 if seeded else 0)
    assert observation.queue.truncated == seeded
    if seed is not None:
        assert [item.id for item in observation.queue.items] == list(seed.item_ids[:1])


@pytest.mark.parametrize("outcome", ["error", "cancel"])
async def test_metric_projection_error_cancel_cannot_reopen_or_undo_read(
    rdb_session_manager: SessionManager[WriteSession], outcome: str
) -> None:
    boundary = _Boundary(rdb_session_manager)
    metrics = _Metrics(boundary)
    runtime = _Runtime(boundary, outcome)
    service = ExternalChannelIngressObservabilityService(
        repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
        metrics=metrics,
        runtime=runtime,
    )
    with pytest.raises(asyncio.CancelledError if outcome == "cancel" else ValueError):
        await service.observe()
    boundary.closed()
    assert boundary.events == ["open", "commit", "commit", "closed"]
    assert metrics.calls == [0]
    assert runtime.observed == ["active_count"]


@pytest.mark.parametrize("cancel", [False, True], ids=["error", "cancel"])
async def test_query_error_cancel_does_not_project_process_metrics(
    rdb_session_manager: SessionManager[WriteSession], cancel: bool
) -> None:
    boundary = _Boundary(rdb_session_manager)
    metrics = _Metrics(boundary)
    runtime = _Runtime(boundary, "success")
    service = ExternalChannelIngressObservabilityService(
        repository=_reads(boundary, _ReadFault(cancel)),
        metrics=metrics,
        runtime=runtime,
    )
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await service.observe()
    boundary.closed()
    assert metrics.calls == runtime.observed == []
    assert boundary.events == ["open", "closed"]


def _standalone_manager(engine: AsyncEngine) -> SessionManager[WriteSession]:
    """Use genuine isolated PG Sessions for the CLI's own asyncio.run loop."""

    @asynccontextmanager
    async def manager() -> AsyncIterator[WriteSession]:
        async with AsyncSession(engine, expire_on_commit=False) as raw_session:
            session = ReadWriteSession(raw_session)
            try:
                yield session
            except asyncio.CancelledError:
                await session.write_session.rollback()
                raise
            except Exception:
                await session.write_session.rollback()
                raise
            else:
                await session.write_session.commit()

    return manager


def test_actual_cli_status_formats_after_completed_isolated_pg_read(
    postgres_container: PostgresContainer,
    latest_db_schema: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the unchanged CLI with real PostgreSQL and an isolated typed DI graph."""
    boundaries: list[_Boundary] = []
    printed: list[ExternalChannelIngressObservation] = []

    @asynccontextmanager
    async def isolated_container(config: Config) -> AsyncIterator[di.Container]:
        engine = create_async_engine(postgres_container.get_connection_url())
        boundary = _Boundary(_standalone_manager(engine))
        boundaries.append(boundary)
        service = ExternalChannelIngressObservabilityService(
            repository=_reads(boundary, ExternalChannelIngressQueueRepository()),
            metrics=_Metrics(boundary),
            runtime=_Runtime(boundary, "success"),
        )
        try:
            async with di.Container(
                dependency_overrides={
                    ExternalChannelIngressObservabilityService: lambda: service,
                }
            ) as container:
                yield container
        finally:
            await engine.dispose()

    def echo(value: str) -> None:
        assert len(boundaries) == 1
        boundaries[0].closed()
        printed.append(ExternalChannelIngressObservation.model_validate_json(value))

    monkeypatch.setattr(
        cli_module.Config,
        "from_env",
        classmethod(
            lambda cls: Config.model_construct(
                runtime_env=RuntimeEnvironment.LOCAL, sentry_dsn=None
            )
        ),
    )
    monkeypatch.setattr(cli_module, "configure_logging_for_runtime", lambda **_: None)
    monkeypatch.setattr(cli_module, "run_with_container", isolated_container)
    monkeypatch.setattr(cli_module.typer, "echo", echo)
    cli_module.status(limit=7)
    assert boundaries[0].events == ["open", "commit", "commit", "closed"]
    assert len(printed) == 1 and printed[0].metrics.runtime_active_task_count == 7
    assert [command.name for command in cli_module.app.registered_commands] == [
        "status"
    ]
