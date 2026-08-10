"""Tests for credential-free External Channel ingress devtools."""

import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from azents.api.testenv.external_channel_ingress.v1 import mount
from azents.job_runtime.deps import get_job_runtime
from azents.job_runtime.types import JobRuntime
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.external_channel.ingress_queue import (
    ExternalChannelIngressQueueRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressDiagnosticCounts,
    ExternalChannelIngressDiagnosticSnapshot,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetricSnapshot,
)
from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
    ExternalChannelIngressObservation,
)
from azents.services.external_channel.ingress_test_control import (
    ExternalChannelIngressTestControl,
    get_external_channel_ingress_test_control,
)
from azents.utils.fastapi.route import as_route_mounter

_NOW = datetime.datetime(2026, 8, 10, tzinfo=datetime.UTC)


def _observation() -> ExternalChannelIngressObservation:
    """Build one empty sanitized diagnostic response."""
    return ExternalChannelIngressObservation(
        queue=ExternalChannelIngressDiagnosticSnapshot(
            observed_at=_NOW,
            owner_count=0,
            counts=ExternalChannelIngressDiagnosticCounts(
                pending=0,
                processing=0,
                retry_waiting=0,
            ),
            oldest_queue_age_seconds=None,
            items=(),
            truncated=False,
        ),
        metrics=ExternalChannelIngressMetricSnapshot(
            active_backlog_size=0,
            oldest_queue_age_seconds=None,
            claimed_batch_count=0,
            claimed_item_count=0,
            last_claimed_batch_size=0,
            processing_duration_seconds=0,
            retry_count=0,
            bounded_failure_count=0,
            cursor_suppression_count=0,
            mailbox_rows_committed=0,
            post_commit_wake_attempt_count=0,
            post_commit_wake_failure_count=0,
            runtime_active_task_count=0,
            runtime_shutdown_drain_seconds=None,
        ),
    )


def _app(
    *,
    service: object,
    runtime: object,
    control: ExternalChannelIngressTestControl,
    repository: object,
) -> FastAPI:
    """Mount routes with isolated dependency overrides."""
    session = SimpleNamespace(commit=AsyncMock())

    @asynccontextmanager
    async def session_manager() -> AsyncIterator[AsyncSession]:
        yield cast(AsyncSession, session)

    app = FastAPI()
    mount(as_route_mounter(app))
    app.dependency_overrides[ExternalChannelIngressObservabilityService] = lambda: (
        service
    )
    app.dependency_overrides[get_job_runtime] = lambda: runtime
    app.dependency_overrides[get_session_manager] = lambda: cast(
        SessionManager[AsyncSession],
        session_manager,
    )
    app.dependency_overrides[ExternalChannelIngressQueueRepository] = lambda: repository
    app.dependency_overrides[get_external_channel_ingress_test_control] = lambda: (
        control
    )
    return app


def test_active_inspection_returns_only_sanitized_queue_and_metrics() -> None:
    """Inspection delegates to the bounded read-only observability service."""
    service = SimpleNamespace(observe=AsyncMock(return_value=_observation()))
    app = _app(
        service=service,
        runtime=SimpleNamespace(),
        control=ExternalChannelIngressTestControl(),
        repository=SimpleNamespace(),
    )

    response = TestClient(app).get(
        "/external-channel-ingress/v1/active",
        params={"limit": 7},
    )

    assert response.status_code == 200
    assert response.json()["queue"]["counts"] == {
        "pending": 0,
        "processing": 0,
        "retry_waiting": 0,
    }
    service.observe.assert_awaited_once_with(limit=7)
    serialized = response.text
    assert "message_body" not in serialized
    assert "credential" not in serialized


def test_release_submits_exact_owner_to_real_runtime_contract() -> None:
    """Release submits a coalesced owner request without mutating queue rows."""
    runtime = SimpleNamespace(submit=AsyncMock())
    repository = SimpleNamespace(
        get_active_owner=AsyncMock(
            return_value=SimpleNamespace(created_at=_NOW),
        )
    )
    app = _app(
        service=SimpleNamespace(),
        runtime=cast(JobRuntime, runtime),
        control=ExternalChannelIngressTestControl(),
        repository=repository,
    )

    response = TestClient(app).post(
        "/external-channel-ingress/v1/release",
        json={"owner_id": "owner-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    request = runtime.submit.await_args.args[0]
    assert request.handler_key == "external_channel.ingress"
    assert request.execution_key == (
        "external-channel-ingress:owner-1:2026-08-10T00:00:00.000000+00:00"
    )
    assert request.payload == {"owner_id": "owner-1"}
    repository.get_active_owner.assert_awaited_once()


def test_release_rejects_missing_active_owner() -> None:
    """Release cannot invent a lifecycle without an active ingress owner."""
    runtime = SimpleNamespace(submit=AsyncMock())
    app = _app(
        service=SimpleNamespace(),
        runtime=cast(JobRuntime, runtime),
        control=ExternalChannelIngressTestControl(),
        repository=SimpleNamespace(get_active_owner=AsyncMock(return_value=None)),
    )

    response = TestClient(app).post(
        "/external-channel-ingress/v1/release",
        json={"owner_id": "owner-1"},
    )

    assert response.status_code == 404
    runtime.submit.assert_not_awaited()


def test_wake_failure_control_is_exact_and_rejects_rich_payloads() -> None:
    """Failure injection accepts only an exact Session identity."""
    control = ExternalChannelIngressTestControl()
    app = _app(
        service=SimpleNamespace(),
        runtime=SimpleNamespace(),
        control=control,
        repository=SimpleNamespace(),
    )
    client = TestClient(app)

    invalid = client.post(
        "/external-channel-ingress/v1/fail-next-wake",
        json={"session_id": "session-1", "message": "sensitive"},
    )
    accepted = client.post(
        "/external-channel-ingress/v1/fail-next-wake",
        json={"session_id": "session-1"},
    )

    assert invalid.status_code == 422
    assert accepted.status_code == 200
    assert control.consume_wake_failure(session_id="session-2") is False
    assert control.consume_wake_failure(session_id="session-1") is True
    assert control.consume_wake_failure(session_id="session-1") is False
