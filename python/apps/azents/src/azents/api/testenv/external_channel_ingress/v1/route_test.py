"""Tests for credential-free External Channel ingress devtools."""

import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from azents.api.testenv.external_channel_ingress.v1 import mount
from azents.core.enums import ExternalChannelResponseMode
from azents.job_runtime.types import JobHandle, JobOutcome, JobRequest, JobRuntime
from azents.repos.external_channel.ingress_control_read import (
    ExternalChannelIngressControlReadRepository,
)
from azents.repos.external_channel.ingress_queue_data import (
    ExternalChannelIngressDiagnosticCounts,
    ExternalChannelIngressDiagnosticSnapshot,
    ExternalChannelIngressOwner,
)
from azents.services.external_channel.ingress_metrics import (
    ExternalChannelIngressMetricSnapshot,
)
from azents.services.external_channel.ingress_observability import (
    ExternalChannelIngressObservabilityService,
    ExternalChannelIngressObservation,
)
from azents.services.external_channel.ingress_release import (
    ExternalChannelIngressReleaseService,
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


def _owner() -> ExternalChannelIngressOwner:
    """Return the existing canonical owner DTO for a completed-read double."""
    return ExternalChannelIngressOwner(
        id="owner-1",
        connection_id="connection-1",
        target_resource_id="resource-1",
        route_id="route-1",
        participation_setting_id=None,
        participation_settings_generation=None,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
        binding_id=None,
        session_id=None,
        preparation_attempt_count=0,
        preparation_next_attempt_at=None,
        lease_owner=None,
        lease_generation=0,
        lease_acquired_at=None,
        lease_expires_at=None,
        first_batch_pending=True,
        current_batch_id=None,
        current_batch_started_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


class _Reads(ExternalChannelIngressControlReadRepository):
    """Double only completed operations, with no Session or commit adapter."""

    def __init__(self, owner: ExternalChannelIngressOwner | None) -> None:
        self.owner = owner
        self.requested: list[str] = []

    async def get_release_owner(
        self, *, owner_id: str
    ) -> ExternalChannelIngressOwner | None:
        self.requested.append(owner_id)
        return self.owner


class _ObservationService(ExternalChannelIngressObservabilityService):
    """Return typed sanitized service output for the HTTP projection tests."""

    def __init__(self) -> None:
        self.limits: list[int] = []

    async def observe(self, *, limit: int = 200) -> ExternalChannelIngressObservation:
        self.limits.append(limit)
        return _observation()


class _Handle(JobHandle):
    async def wait(self) -> JobOutcome:
        raise AssertionError("The release endpoint must not await drain completion.")


class _Runtime(JobRuntime):
    """Record the actual typed Runtime submission contract."""

    def __init__(self) -> None:
        self.requests: list[JobRequest] = []

    @property
    def active_count(self) -> int:
        return len(self.requests)

    @property
    def shutdown_drain_seconds(self) -> float | None:
        return None

    async def submit(self, request: JobRequest) -> JobHandle:
        self.requests.append(request)
        return _Handle()


def _app(
    *,
    service: ExternalChannelIngressObservabilityService,
    runtime: JobRuntime,
    control: ExternalChannelIngressTestControl,
    repository: ExternalChannelIngressControlReadRepository,
) -> FastAPI:
    """Mount routes using completed service collaborators only."""
    app = FastAPI()
    mount(as_route_mounter(app))
    release = ExternalChannelIngressReleaseService(
        repository=repository, runtime=runtime
    )
    app.dependency_overrides[ExternalChannelIngressObservabilityService] = lambda: (
        service
    )
    app.dependency_overrides[ExternalChannelIngressReleaseService] = lambda: release
    app.dependency_overrides[get_external_channel_ingress_test_control] = lambda: (
        control
    )
    return app


def test_active_inspection_returns_only_sanitized_queue_and_metrics() -> None:
    """Inspection delegates to the bounded read-only observability service."""
    service = _ObservationService()
    app = _app(
        service=service,
        runtime=_Runtime(),
        control=ExternalChannelIngressTestControl(),
        repository=_Reads(None),
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
    assert service.limits == [7]
    serialized = response.text
    assert "message_body" not in serialized
    assert "credential" not in serialized


def test_release_submits_exact_owner_to_real_runtime_contract() -> None:
    """Release submits a coalesced owner request without mutating queue rows."""
    runtime = _Runtime()
    repository = _Reads(_owner())
    app = _app(
        service=_ObservationService(),
        runtime=runtime,
        control=ExternalChannelIngressTestControl(),
        repository=repository,
    )

    response = TestClient(app).post(
        "/external-channel-ingress/v1/release",
        json={"owner_id": "owner-1"},
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.handler_key == "external_channel.ingress"
    assert request.execution_key == (
        "external-channel-ingress:owner-1:2026-08-10T00:00:00.000000+00:00"
    )
    assert request.payload == {"owner_id": "owner-1"}
    assert repository.requested == ["owner-1"]


def test_release_rejects_missing_active_owner() -> None:
    """Release cannot invent a lifecycle without an active ingress owner."""
    runtime = _Runtime()
    app = _app(
        service=_ObservationService(),
        runtime=runtime,
        control=ExternalChannelIngressTestControl(),
        repository=_Reads(None),
    )

    response = TestClient(app).post(
        "/external-channel-ingress/v1/release",
        json={"owner_id": "owner-1"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Active ingress owner not found."}
    assert runtime.requests == []


def test_wake_failure_control_is_exact_and_rejects_rich_payloads() -> None:
    """Failure injection accepts only an exact Session identity."""
    control = ExternalChannelIngressTestControl()
    app = _app(
        service=_ObservationService(),
        runtime=_Runtime(),
        control=control,
        repository=_Reads(None),
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
