"""Runtime Web Gateway transport authority tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from azents_runtime_control.runner_web import RunnerWebProtocol

from azents.rdb.models.runtime_web import RuntimeWebAuthMode
from azents.repos.runtime_web.data import RuntimeWebCycle, RuntimeWebEndpoint
from azents.repos.runtime_web.gateway_data import (
    RuntimeWebGatewayAuthority,
    RuntimeWebGatewayIdentity,
)
from azents.services.runtime_web.gateway_authority import (
    RuntimeWebGatewayAuthorityService,
)


def test_http_tunnel_bounds_approval_to_transport_deadline() -> None:
    """Keep every HTTP identity deadline within its absolute transport window."""
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
        duration_configuration_revision=1,
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
            epoch=1,
            browser_profile="chromium-149",
            issued_at=now,
            expires_at=cycle_expires_at,
        ),
        endpoint=endpoint,
        request=None,
        cycle=cycle,
        runtime_id="t" * 32,
        desired_generation=4,
        runner_generation=4,
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
    assert http_identity.registration_deadline_at == now + timedelta(seconds=10)
    assert http_identity.approval_deadline_at == http_deadline
    assert http_identity.transport_deadline_at == http_deadline
    assert websocket_identity.approval_deadline_at == cycle_expires_at
    assert websocket_identity.transport_deadline_at == cycle_expires_at
