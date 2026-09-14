"""Runtime Web Gateway transport authority tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from azents_runtime_control.runner_web import RunnerWebProtocol

from azents.core.enums import (
    RuntimeDesiredState,
    RuntimeProviderObservedState,
    RuntimeRunnerState,
)
from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.agent_runtime.data import AgentRuntime
from azents.repos.runtime_web.data import RuntimeWebCycle, RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebGatewayAuthority,
    RuntimeWebGatewayIdentity,
)
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityService,
    _runtime_ready,
)


def _runtime(**updates: object) -> AgentRuntime:
    now = datetime(2026, 9, 13, tzinfo=UTC)
    runtime = AgentRuntime(
        id="t" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        terminal_delete_acknowledgement_kind=None,
        desired_state=RuntimeDesiredState.RUNNING,
        desired_generation=552,
        provider_observed_state=RuntimeProviderObservedState.RUNNING,
        provider_observed_generation=552,
        runner_state=RuntimeRunnerState.READY,
        runner_generation=987_654_321,
        created_at=now,
        updated_at=now,
    )
    return runtime.model_copy(update=updates)


def test_runtime_ready_accepts_independent_kubernetes_runner_generation() -> None:
    """Accept a ready Runner whose generation is independent from lifecycle."""
    assert _runtime_ready(_runtime())


@pytest.mark.parametrize(
    "updates",
    [
        {"desired_state": RuntimeDesiredState.STOPPED},
        {"provider_observed_state": RuntimeProviderObservedState.STOPPED},
        {"provider_observed_generation": 551},
        {"runner_state": RuntimeRunnerState.UNKNOWN},
        {"runner_generation": 0},
    ],
)
def test_runtime_ready_rejects_stale_or_missing_runtime_evidence(
    updates: dict[str, object],
) -> None:
    """Reject stale Provider evidence and unavailable Runner connections."""
    assert not _runtime_ready(_runtime(**updates))


def test_http_tunnel_preserves_approval_beyond_transport_deadline() -> None:
    """Keep cycle approval authority beyond one finite HTTP transport."""
    now = datetime(2026, 9, 12, tzinfo=UTC)
    cycle_expires_at = now + timedelta(minutes=30)
    service = RuntimeWebGatewayAuthorityService(
        session_manager=MagicMock(),
        gateway_repository=MagicMock(),
        runtime_web_repository=MagicMock(),
        agent_session_repository=MagicMock(),
        workspace_user_repository=MagicMock(),
        runtime_repository=MagicMock(),
    )
    endpoint = RuntimeWebEndpoint(
        id="e" * 32,
        workspace_id="w" * 32,
        agent_id="a" * 32,
        agent_session_id="s" * 32,
        port=8765,
        hostname_key="endpoint",
        label="Preview",
        authority_revision=3,
        close_barrier=2,
        current_pending_request_id=None,
        current_cycle_id="c" * 32,
        created_at=now,
        updated_at=now,
    )
    cycle = RuntimeWebCycle(
        id="c" * 32,
        endpoint_id=endpoint.id,
        request_id="r" * 32,
        approver_user_id="u" * 32,
        duration_seconds=1_800,
        approved_at=now,
        expires_at=cycle_expires_at,
        close_barrier=endpoint.close_barrier,
        ended_at=None,
        end_reason=None,
        created_at=now,
    )
    authority = RuntimeWebGatewayAuthority(
        identity=RuntimeWebGatewayIdentity(
            id="i" * 32,
            user_id="u" * 32,
            auth_session_id="h" * 32,
            mode=RuntimeWebAuthMode.SHARED_COOKIE,
            issued_at=now,
            expires_at=cycle_expires_at,
        ),
        endpoint=endpoint,
        request=None,
        cycle=cycle,
        runtime_id="t" * 32,
        desired_generation=552,
        runner_generation=987_654_321,
        active=True,
        runtime_ready=True,
    )

    http_identity = service.tunnel_identity(
        authority=authority,
        protocol=RunnerWebProtocol.HTTP,
        now=now,
    )
    websocket_identity = service.tunnel_identity(
        authority=authority,
        protocol=RunnerWebProtocol.WEBSOCKET,
        now=now,
    )

    http_deadline = now + timedelta(minutes=10)
    assert http_identity.desired_generation == 552
    assert http_identity.runner_generation == 987_654_321
    assert http_identity.registration_deadline_at == now + timedelta(seconds=10)
    assert http_identity.approval_deadline_at == cycle_expires_at
    assert http_identity.transport_deadline_at == http_deadline
    assert http_identity.approval_deadline_at > http_identity.transport_deadline_at
    assert websocket_identity.desired_generation == 552
    assert websocket_identity.runner_generation == 987_654_321
    assert websocket_identity.approval_deadline_at == cycle_expires_at
    assert websocket_identity.transport_deadline_at == cycle_expires_at
