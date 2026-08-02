"""Phase 1 External Channel App mode repository boundary tests."""

import asyncio
import datetime
import json
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationLocation,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelParticipationSettingStatus,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelResponseMode,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSetupClaimStatus,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelAppClaim,
    RDBExternalChannelBinding,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelDeliveryAttempt,
    RDBExternalChannelInteraction,
    RDBExternalChannelParticipationSetting,
    RDBExternalChannelSetupClaim,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict

from .data import (
    ExternalChannelAgentRouteCreate,
    ExternalChannelBindingCreate,
    ExternalChannelChannelDefaultCreate,
    ExternalChannelConnectionCreate,
    ExternalChannelConversationPositionCreate,
    ExternalChannelInteractionCreate,
    ExternalChannelParticipationSettingCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSetupClaim,
    ExternalChannelSetupClaimCreate,
)
from .lifecycle import ExternalChannelLifecycleRepository
from .management import ExternalChannelManagementRepository
from .repository import ExternalChannelRepository, validate_interaction_projection
from .work import DeliverySettlement, ExternalChannelWorkRepository


def _at(minute: int) -> datetime.datetime:
    """Return stable timezone-aware timestamps."""
    return datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC) + datetime.timedelta(
        minutes=minute
    )


async def _workspace(session: AsyncSession, handle: str) -> str:
    """Create one Workspace root for an isolated repository fixture."""
    result = await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name=f"{handle} Workspace", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await WorkspaceRepository().resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _agent(session: AsyncSession, workspace_id: str, slug: str) -> RDBAgent:
    """Create one active Agent with a valid model-selection reference."""
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted",
        config=None,
    )
    session.add(integration)
    await session.flush()
    selection = make_test_model_selection_dict(
        integration_id=integration.id,
        provider=LLMProvider.ANTHROPIC,
        model_identifier=f"{slug}-model",
    )
    agent = RDBAgent(
        workspace_id=workspace_id,
        name=f"{slug} Agent",
        model_selection=selection,
        lightweight_model_selection=selection,
    )
    session.add(agent)
    await session.flush()
    return agent


def _connection_create(
    workspace_id: str,
    *,
    provider: ExternalChannelProvider = ExternalChannelProvider.SLACK,
    provider_app_id: str = "A1",
    provider_tenant_id: str = "T1",
) -> ExternalChannelConnectionCreate:
    """Build a Single-compatible connection writer payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=provider,
        transport=ExternalChannelTransport.HTTP,
        app_mode=ExternalChannelAppMode.SINGLE,
        status=ExternalChannelConnectionStatus.ACTIVE,
        provider_app_id=provider_app_id,
        provider_tenant_id=provider_tenant_id,
        provider_bot_user_id=None,
        http_callback_selector_hash=None,
        encrypted_credentials="ciphertext",
        capabilities=None,
        provider_config=None,
        last_verified_at=None,
        last_health_at=None,
        disconnected_at=None,
        socket_lease_owner=None,
        socket_lease_until=None,
        socket_heartbeat_at=None,
        socket_gap_detected_at=None,
        socket_gap_reason=None,
    )


def _route_create(
    connection_id: str,
    agent_id: str,
    *,
    mode: ExternalChannelAppMode,
) -> ExternalChannelAgentRouteCreate:
    """Build one explicit route writer payload."""
    return ExternalChannelAgentRouteCreate(
        connection_id=connection_id,
        agent_id=agent_id,
        agent_id_snapshot=agent_id,
        route_mode=ExternalChannelRouteMode.DEDICATED,
        connection_app_mode=mode,
        catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
        catalog_removed_at=None,
        catalog_removed_by_user_id=None,
    )


async def _resource(
    session: AsyncSession,
    repo: ExternalChannelRepository,
    *,
    connection_id: str,
    key: str,
) -> ExternalChannelResource:
    """Create a minimal canonical resource under one connection."""
    return await repo.create_resource_idempotent(
        session,
        ExternalChannelResourceCreate(
            connection_id=connection_id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key=key,
            labels=None,
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=None,
            unavailable_at=None,
            deleted_at=None,
        ),
    )


def _interaction_create(
    connection_id: str,
    *,
    key: str = "interaction-1",
    principal_id: str | None = None,
    projection: dict[str, object] | None = None,
) -> ExternalChannelInteractionCreate:
    """Build one bounded interaction admission payload."""
    return ExternalChannelInteractionCreate(
        connection_id=connection_id,
        transport=ExternalChannelTransport.HTTP,
        provider_interaction_key=key,
        interaction_type=ExternalChannelInteractionType.SHORTCUT,
        callback_id="callback",
        action_id="action",
        principal_id=principal_id,
        setup_claim_id=None,
        resource_correlation_key="slack:T1:C1:1.000001",
        projection=projection or {"interaction_id": "opaque"},
        status=ExternalChannelInteractionStatus.ACCEPTED,
        expires_at=_at(10),
        error_kind=None,
        error_summary=None,
    )


async def _cleanup_committed_workspace(
    engine: AsyncEngine,
    *,
    workspace_id: str,
) -> None:
    """Remove direct-engine concurrency fixtures in restrictive FK order."""
    statements = (
        """
        DELETE FROM external_channel_delivery_attempts
        WHERE binding_id IN (
            SELECT binding.id
            FROM external_channel_bindings AS binding
            JOIN external_channel_agent_routes AS route
              ON route.id = binding.route_id
            JOIN external_channel_connections AS connection
              ON connection.id = route.connection_id
            WHERE connection.workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM external_channel_bindings
        WHERE route_id IN (
            SELECT route.id
            FROM external_channel_agent_routes AS route
            JOIN external_channel_connections AS connection
              ON connection.id = route.connection_id
            WHERE connection.workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM external_channel_resources
        WHERE connection_id IN (
            SELECT id FROM external_channel_connections
            WHERE workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM external_channel_agent_routes
        WHERE connection_id IN (
            SELECT id FROM external_channel_connections
            WHERE workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM external_channel_connections
        WHERE workspace_id = :workspace_id
        """,
        """
        UPDATE session_agent_contexts
        SET root_session_agent_id = NULL
        WHERE workspace_id = :workspace_id
        """,
        """
        DELETE FROM session_agents
        WHERE agent_session_id IN (
            SELECT id FROM agent_sessions
            WHERE workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM session_agent_contexts
        WHERE workspace_id = :workspace_id
        """,
        "DELETE FROM agent_sessions WHERE workspace_id = :workspace_id",
        "DELETE FROM agents WHERE workspace_id = :workspace_id",
        """
        DELETE FROM llm_provider_integrations
        WHERE workspace_id = :workspace_id
        """,
        "DELETE FROM workspaces WHERE id = :workspace_id",
    )
    async with AsyncSession(engine) as session:
        for statement in statements:
            await session.execute(
                sa.text(statement),
                {"workspace_id": workspace_id},
            )
        await session.commit()


def test_interaction_projection_validation_exact_bounds_and_forbidden_keys() -> None:
    """Interaction metadata is bounded and capability-bearing keys fail closed."""
    base = {"items": ["x" * 2048] * 7 + [""]}
    remaining = 16 * 1024 - len(
        json.dumps(
            base, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
    )
    assert 0 <= remaining <= 2048
    exact = {"items": ["x" * 2048] * 7 + ["x" * remaining]}
    validate_interaction_projection(exact)
    with pytest.raises(ValueError, match="16 KiB"):
        validate_interaction_projection(
            {"items": ["x" * 2048] * 7 + ["x" * (remaining + 1)]}
        )

    validate_interaction_projection({"a": {"b": {"c": {"d": "value"}}}})
    with pytest.raises(ValueError, match="deeply nested"):
        validate_interaction_projection({"a": {"b": {"c": {"d": {"e": "value"}}}}})
    validate_interaction_projection({"items": list(range(64))})
    with pytest.raises(ValueError, match="too many entries"):
        validate_interaction_projection({"items": list(range(65))})
    validate_interaction_projection({"k" * 128: "v" * 2048})
    with pytest.raises(ValueError, match="key is too long"):
        validate_interaction_projection({"k" * 129: "value"})
    with pytest.raises(ValueError, match="string is too long"):
        validate_interaction_projection({"safe": "v" * 2049})

    for forbidden_key in (
        "token",
        "client_secret",
        "Authorization",
        "cookie-value",
        "response_url",
        "raw_body",
        "payload",
        "message_text",
        "message_body",
        "content",
        "file_bytes",
        "attachment",
        "privateUrl",
        "callback_uri",
    ):
        with pytest.raises(ValueError, match="forbidden key"):
            validate_interaction_projection({"nested": {forbidden_key: "private"}})
    for forbidden_value in (
        "https://hooks.slack.com/actions/private",
        "slack://open?team=T1",
        "xoxb-private-token",
        "Bearer private-credential",
        "Cookie: session=private",
        "raw message text",
    ):
        with pytest.raises(ValueError, match="forbidden value|opaque identifiers"):
            validate_interaction_projection({"state": forbidden_value})
    with pytest.raises(ValueError, match="binary"):
        validate_interaction_projection({"safe": b"not-json"})


async def test_interaction_admission_is_idempotent_and_validates_principal_boundary(
    rdb_session: AsyncSession,
) -> None:
    """Retries preserve the first projection and principals match the connection."""
    workspace_id = await _workspace(rdb_session, "interaction-boundary")
    repo = ExternalChannelRepository()
    connection = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id),
    )
    principal = await repo.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="T1",
            provider_user_id="U1",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )
    first = await repo.admit_interaction(
        rdb_session,
        _interaction_create(
            connection.id,
            principal_id=principal.id,
            projection={"state": "first"},
        ),
    )
    retry = await repo.admit_interaction(
        rdb_session,
        _interaction_create(
            connection.id,
            principal_id=principal.id,
            projection={"state": "first"},
        ),
    )
    foreign_principal = await repo.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="T2",
            provider_user_id="U2",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )

    assert first.created is True
    assert retry.created is False
    assert retry.interaction.id == first.interaction.id
    assert retry.interaction.projection == {"state": "first"}
    with pytest.raises(ValueError, match="retry is incompatible"):
        await repo.admit_interaction(
            rdb_session,
            _interaction_create(
                connection.id,
                principal_id=principal.id,
                projection={"state": "conflicting-retry"},
            ),
        )
    for invalid in (
        _interaction_create(
            connection.id,
            key="invalid-callback",
        ).model_copy(update={"callback_id": "https://hooks.slack.com/private"}),
        _interaction_create(
            connection.id,
            key="invalid-action",
        ).model_copy(update={"action_id": "xoxb-private-token"}),
        _interaction_create(
            connection.id,
            key="invalid-resource",
        ).model_copy(update={"resource_correlation_key": "raw message text"}),
        _interaction_create(
            connection.id,
            key="invalid-status",
        ).model_copy(update={"status": ExternalChannelInteractionStatus.FAILED}),
        _interaction_create(
            connection.id,
            key="invalid-error",
        ).model_copy(update={"error_summary": "provider failed"}),
    ):
        with pytest.raises(ValueError):
            await repo.admit_interaction(rdb_session, invalid)
    with pytest.raises(ValueError, match="principal does not match"):
        await repo.admit_interaction(
            rdb_session,
            _interaction_create(
                connection.id,
                key="foreign-principal",
                principal_id=foreign_principal.id,
            ),
        )


async def test_internal_multi_fixture_proves_route_cardinality_defaults_and_bindings(
    rdb_session: AsyncSession,
) -> None:
    """A direct transactional Multi fixture proves declarative Phase 1 boundaries."""
    workspace_id = await _workspace(rdb_session, "multi-fixture")
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email="multi-fixture@example.com"),
    )
    first_agent = await _agent(rdb_session, workspace_id, "multi-first")
    second_agent = await _agent(rdb_session, workspace_id, "multi-second")
    repo = ExternalChannelRepository()
    multi_connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id, provider_app_id="AM", provider_tenant_id="TM"
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi_connection)
    await rdb_session.flush()
    first_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            multi_connection.id,
            first_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    second_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            multi_connection.id,
            second_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    assert {first_route.agent_id, second_route.agent_id} == {
        first_agent.id,
        second_agent.id,
    }
    with pytest.raises(IntegrityError):
        async with rdb_session.begin_nested():
            await repo.create_agent_route(
                rdb_session,
                _route_create(
                    multi_connection.id,
                    first_agent.id,
                    mode=ExternalChannelAppMode.MULTI,
                ),
            )

    default = await repo.create_channel_default(
        rdb_session,
        ExternalChannelChannelDefaultCreate(
            connection_id=multi_connection.id,
            provider_channel_id="C1",
            route_id=first_route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    assert default.route_id == first_route.id
    with pytest.raises(IntegrityError):
        async with rdb_session.begin_nested():
            await repo.create_channel_default(
                rdb_session,
                ExternalChannelChannelDefaultCreate(
                    connection_id=multi_connection.id,
                    provider_channel_id="C1",
                    route_id=second_route.id,
                    status=ExternalChannelChannelDefaultStatus.ACTIVE,
                    configured_by_user_id=user.id,
                    configured_by_principal_id=None,
                    invalidated_at=None,
                    invalidation_reason=None,
                ),
            )
    with pytest.raises(ValueError, match="invalidation metadata"):
        await repo.create_channel_default(
            rdb_session,
            ExternalChannelChannelDefaultCreate(
                connection_id=multi_connection.id,
                provider_channel_id="C2",
                route_id=second_route.id,
                status=ExternalChannelChannelDefaultStatus.ACTIVE,
                configured_by_user_id=user.id,
                configured_by_principal_id=None,
                invalidated_at=_at(5),
                invalidation_reason="not-valid-at-create",
            ),
        )
    with pytest.raises(ValueError, match="invalidation metadata"):
        await repo.create_channel_default(
            rdb_session,
            ExternalChannelChannelDefaultCreate(
                connection_id=multi_connection.id,
                provider_channel_id="C3",
                route_id=second_route.id,
                status=ExternalChannelChannelDefaultStatus.ACTIVE,
                configured_by_user_id=user.id,
                configured_by_principal_id=None,
                invalidated_at=_at(5),
                invalidation_reason=None,
            ),
        )
    with pytest.raises(ValueError, match="invalidation metadata"):
        await repo.create_channel_default(
            rdb_session,
            ExternalChannelChannelDefaultCreate(
                connection_id=multi_connection.id,
                provider_channel_id="C3",
                route_id=second_route.id,
                status=ExternalChannelChannelDefaultStatus.ACTIVE,
                configured_by_user_id=user.id,
                configured_by_principal_id=None,
                invalidated_at=None,
                invalidation_reason="not-valid-at-create",
            ),
        )
    rdb_session.add(
        RDBExternalChannelChannelDefault(
            connection_id=multi_connection.id,
            provider_channel_id="C4",
            route_id=second_route.id,
            status=ExternalChannelChannelDefaultStatus.INVALIDATED,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            invalidated_at=_at(5),
            invalidation_reason="historical",
        )
    )
    await rdb_session.flush()
    active_after_history = await repo.create_channel_default(
        rdb_session,
        ExternalChannelChannelDefaultCreate(
            connection_id=multi_connection.id,
            provider_channel_id="C4",
            route_id=first_route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    assert active_after_history.provider_channel_id == "C4"

    resource = await _resource(
        rdb_session, repo, connection_id=multi_connection.id, key="binding-resource"
    )
    first_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=first_agent.id,
            title=None,
        ),
    )
    second_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=second_agent.id,
            title=None,
        ),
    )
    binding = await repo.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=first_route.id,
            agent_session_id=first_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    with pytest.raises(ValueError, match="another route"):
        await repo.create_binding_idempotent(
            rdb_session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=second_route.id,
                agent_session_id=second_session.id,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_access_request_id=None,
        )
    duplicate_first_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=first_agent.id,
            title=None,
        ),
    )
    with pytest.raises(ValueError, match="another Agent Session"):
        await repo.create_binding_idempotent(
            rdb_session,
            ExternalChannelBindingCreate(
                resource_id=resource.id,
                route_id=first_route.id,
                agent_session_id=duplicate_first_session.id,
                response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                disconnected_at=None,
                disconnect_reason=None,
            ),
            expected_access_request_id=None,
        )
    assert binding.route_id == first_route.id


async def test_channel_default_rejects_invalid_owner_and_lifecycle_boundaries(
    rdb_session: AsyncSession,
) -> None:
    """Defaults require an owned, available Multi route and active local Agent."""
    workspace_id = await _workspace(rdb_session, "default-negative")
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email="default-negative@example.com"),
    )
    agent = await _agent(rdb_session, workspace_id, "default-negative")
    repo = ExternalChannelRepository()
    single = await repo.create_connection(rdb_session, _connection_create(workspace_id))
    route = await repo.create_agent_route(
        rdb_session,
        _route_create(single.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
    )
    create = ExternalChannelChannelDefaultCreate(
        connection_id=single.id,
        provider_channel_id="C1",
        route_id=route.id,
        status=ExternalChannelChannelDefaultStatus.ACTIVE,
        configured_by_user_id=user.id,
        configured_by_principal_id=None,
        invalidated_at=None,
        invalidation_reason=None,
    )
    with pytest.raises(ValueError, match="not eligible"):
        await repo.create_channel_default(rdb_session, create)

    multi = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id, provider_app_id="A3", provider_tenant_id="T3"
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi)
    await rdb_session.flush()
    multi_route = await repo.create_agent_route(
        rdb_session,
        _route_create(multi.id, agent.id, mode=ExternalChannelAppMode.MULTI),
    )
    second_multi = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id, provider_app_id="A4", provider_tenant_id="T4"
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(second_multi)
    await rdb_session.flush()
    foreign_connection_route = await repo.create_agent_route(
        rdb_session,
        _route_create(second_multi.id, agent.id, mode=ExternalChannelAppMode.MULTI),
    )
    with pytest.raises(ValueError, match="connection or route"):
        await repo.create_channel_default(
            rdb_session,
            create.model_copy(
                update={
                    "connection_id": multi.id,
                    "route_id": foreign_connection_route.id,
                }
            ),
        )
    foreign_workspace_id = await _workspace(rdb_session, "default-foreign")
    foreign_agent = await _agent(rdb_session, foreign_workspace_id, "default-foreign")
    rdb_session.add(
        RDBExternalChannelAgentRoute(
            connection_id=multi.id,
            agent_id=foreign_agent.id,
            agent_id_snapshot=foreign_agent.id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
            connection_app_mode=ExternalChannelAppMode.MULTI,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
            catalog_removed_at=None,
            catalog_removed_by_user_id=None,
        )
    )
    await rdb_session.flush()
    foreign_workspace_route = await rdb_session.scalar(
        sa.select(RDBExternalChannelAgentRoute).where(
            RDBExternalChannelAgentRoute.connection_id == multi.id,
            RDBExternalChannelAgentRoute.agent_id == foreign_agent.id,
        )
    )
    assert foreign_workspace_route is not None
    with pytest.raises(ValueError, match="not eligible"):
        await repo.create_channel_default(
            rdb_session,
            create.model_copy(
                update={
                    "connection_id": multi.id,
                    "route_id": foreign_workspace_route.id,
                }
            ),
        )
    mode_mismatch_agent = await _agent(rdb_session, workspace_id, "mode-mismatch")
    with pytest.raises(IntegrityError):
        async with rdb_session.begin_nested():
            rdb_session.add(
                RDBExternalChannelAgentRoute(
                    connection_id=multi.id,
                    agent_id=mode_mismatch_agent.id,
                    agent_id_snapshot=mode_mismatch_agent.id,
                    route_mode=ExternalChannelRouteMode.DEDICATED,
                    connection_app_mode=ExternalChannelAppMode.SINGLE,
                    catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
                    catalog_removed_at=None,
                    catalog_removed_by_user_id=None,
                )
            )
            await rdb_session.flush()
    with pytest.raises(ValueError, match="must be active"):
        await repo.create_channel_default(
            rdb_session,
            create.model_copy(
                update={
                    "connection_id": multi.id,
                    "route_id": multi_route.id,
                    "status": ExternalChannelChannelDefaultStatus.INVALIDATED,
                    "invalidated_at": _at(5),
                    "invalidation_reason": "not-active",
                }
            ),
        )
    agent.lifecycle_status = AgentLifecycleStatus.DECOMMISSIONING
    await rdb_session.flush()
    with pytest.raises(ValueError, match="not eligible"):
        await repo.create_channel_default(
            rdb_session,
            create.model_copy(
                update={"connection_id": multi.id, "route_id": multi_route.id}
            ),
        )
    agent.lifecycle_status = AgentLifecycleStatus.ACTIVE
    route_rdb = await rdb_session.get(RDBExternalChannelAgentRoute, multi_route.id)
    assert route_rdb is not None
    route_rdb.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
    await rdb_session.flush()
    with pytest.raises(ValueError, match="not eligible"):
        await repo.create_channel_default(
            rdb_session,
            create.model_copy(
                update={"connection_id": multi.id, "route_id": multi_route.id}
            ),
        )


async def test_provider_configuration_actor_must_match_connection_identity(
    rdb_session: AsyncSession,
) -> None:
    """Provider-authored defaults and settings reject foreign provider principals."""
    workspace_id = await _workspace(rdb_session, "provider-actor-boundary")
    agent = await _agent(rdb_session, workspace_id, "provider-actor-boundary")
    repo = ExternalChannelRepository()
    single = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id),
    )
    single_route = await repo.create_agent_route(
        rdb_session,
        _route_create(single.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
    )
    multi = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="actor-multi-app",
            provider_tenant_id="T1",
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi)
    await rdb_session.flush()
    multi_route = await repo.create_agent_route(
        rdb_session,
        _route_create(multi.id, agent.id, mode=ExternalChannelAppMode.MULTI),
    )
    valid_principal = await repo.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="T1",
            provider_user_id="U-valid",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )
    foreign_principals = (
        await repo.create_principal_idempotent(
            rdb_session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.SLACK,
                provider_tenant_id="T2",
                provider_user_id="U-foreign-tenant",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        ),
        await repo.create_principal_idempotent(
            rdb_session,
            ExternalChannelPrincipalCreate(
                provider=ExternalChannelProvider.DISCORD,
                provider_tenant_id="G1",
                provider_user_id="U-foreign-provider",
                author_type=ExternalChannelPrincipalAuthorType.HUMAN,
                display_name=None,
                avatar_url=None,
                profile=None,
            ),
        ),
    )

    for index, principal in enumerate(foreign_principals):
        with pytest.raises(ValueError, match="provider actor is not eligible"):
            await repo.create_channel_default(
                rdb_session,
                ExternalChannelChannelDefaultCreate(
                    connection_id=multi.id,
                    provider_channel_id=f"C-foreign-{index}",
                    route_id=multi_route.id,
                    status=ExternalChannelChannelDefaultStatus.ACTIVE,
                    configured_by_user_id=None,
                    configured_by_principal_id=principal.id,
                    invalidated_at=None,
                    invalidation_reason=None,
                ),
            )
        with pytest.raises(ValueError, match="provider actor is not eligible"):
            await repo.create_participation_setting(
                rdb_session,
                ExternalChannelParticipationSettingCreate(
                    connection_id=single.id,
                    provider_parent_channel_id=f"C-foreign-{index}",
                    route_id=single_route.id,
                    location=ExternalChannelConversationLocation.THREADS,
                    response_mode=ExternalChannelResponseMode.MENTION_ONLY,
                    settings_generation=1,
                    configured_by_user_id=None,
                    configured_by_principal_id=principal.id,
                    status=ExternalChannelParticipationSettingStatus.ACTIVE,
                    invalidated_at=None,
                    invalidation_reason=None,
                ),
            )

    default = await repo.create_channel_default(
        rdb_session,
        ExternalChannelChannelDefaultCreate(
            connection_id=multi.id,
            provider_channel_id="C-valid",
            route_id=multi_route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=None,
            configured_by_principal_id=valid_principal.id,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    setting = await repo.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=single.id,
            provider_parent_channel_id="C-valid",
            route_id=single_route.id,
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            settings_generation=1,
            configured_by_user_id=None,
            configured_by_principal_id=valid_principal.id,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )

    assert default.configured_by_principal_id == valid_principal.id
    assert setting.configured_by_principal_id == valid_principal.id


async def test_setup_claim_selection_enforces_location_resource_identity(
    rdb_session: AsyncSession,
) -> None:
    """Threads freeze the source Resource and Channel freezes its parent Resource."""
    workspace_id = await _workspace(rdb_session, "setup-location-resource")
    agent = await _agent(rdb_session, workspace_id, "setup-location-resource")
    repo = ExternalChannelRepository()
    connection = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id),
    )
    route = await repo.create_agent_route(
        rdb_session,
        _route_create(connection.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
    )
    principal = await repo.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="T1",
            provider_user_id="U1",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )

    async def create_resource(
        *,
        resource_type: ExternalChannelResourceType,
        key: str,
    ) -> ExternalChannelResource:
        return await repo.create_resource_idempotent(
            rdb_session,
            ExternalChannelResourceCreate(
                connection_id=connection.id,
                resource_type=resource_type,
                provider_resource_key=key,
                labels=None,
                status=ExternalChannelResourceStatus.ACTIVE,
                latest_activity_at=None,
                unavailable_at=None,
                deleted_at=None,
            ),
        )

    async def create_claim(
        *,
        parent_channel_id: str,
        source_resource: ExternalChannelResource,
    ) -> ExternalChannelSetupClaim:
        position = await repo.create_conversation_position_idempotent(
            rdb_session,
            ExternalChannelConversationPositionCreate(
                connection_id=connection.id,
                scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
                provider_channel_id=parent_channel_id,
                provider_thread_key=None,
                read_through_position=None,
            ),
        )
        return await repo.create_setup_claim(
            rdb_session,
            ExternalChannelSetupClaimCreate(
                connection_id=connection.id,
                provider_parent_channel_id=parent_channel_id,
                route_id=route.id,
                conversation_position_id=position.id,
                source_resource_id=source_resource.id,
                principal_id=principal.id,
                source_projection={
                    "schema_version": 1,
                    "trigger_message_id": f"message-{parent_channel_id}",
                },
                source_revision=1,
                claim_generation=1,
                status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
                selected_setting_id=None,
                selected_resource_id=None,
                selected_source_revision=None,
                expires_at=_at(30),
                selected_at=None,
                completed_at=None,
            ),
        )

    threads_source = await create_resource(
        resource_type=ExternalChannelResourceType.THREAD,
        key="thread-source",
    )
    other_thread = await create_resource(
        resource_type=ExternalChannelResourceType.THREAD,
        key="thread-other",
    )
    threads_setting = await repo.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-threads",
            route_id=route.id,
            location=ExternalChannelConversationLocation.THREADS,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            settings_generation=1,
            configured_by_user_id=None,
            configured_by_principal_id=principal.id,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    threads_claim = await create_claim(
        parent_channel_id="C-threads",
        source_resource=threads_source,
    )
    with pytest.raises(ValueError, match="does not match location"):
        await repo.select_setup_claim(
            rdb_session,
            claim_id=threads_claim.id,
            expected_claim_generation=threads_claim.claim_generation,
            expected_source_revision=threads_claim.source_revision,
            selected_setting_id=threads_setting.id,
            selected_resource_id=other_thread.id,
            selected_at=_at(1),
        )
    selected_threads = await repo.select_setup_claim(
        rdb_session,
        claim_id=threads_claim.id,
        expected_claim_generation=threads_claim.claim_generation,
        expected_source_revision=threads_claim.source_revision,
        selected_setting_id=threads_setting.id,
        selected_resource_id=threads_source.id,
        selected_at=_at(2),
    )
    assert selected_threads is not None
    assert selected_threads.selected_resource_id == threads_source.id

    channel_source = await create_resource(
        resource_type=ExternalChannelResourceType.THREAD,
        key="channel-source",
    )
    wrong_parent = await create_resource(
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        key="C-other",
    )
    selected_parent = await create_resource(
        resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
        key="C-channel",
    )
    channel_setting = await repo.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-channel",
            route_id=route.id,
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
            configured_by_user_id=None,
            configured_by_principal_id=principal.id,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    channel_claim = await create_claim(
        parent_channel_id="C-channel",
        source_resource=channel_source,
    )
    for invalid_resource in (channel_source, wrong_parent):
        with pytest.raises(ValueError, match="does not match location"):
            await repo.select_setup_claim(
                rdb_session,
                claim_id=channel_claim.id,
                expected_claim_generation=channel_claim.claim_generation,
                expected_source_revision=channel_claim.source_revision,
                selected_setting_id=channel_setting.id,
                selected_resource_id=invalid_resource.id,
                selected_at=_at(3),
            )
    selected_channel = await repo.select_setup_claim(
        rdb_session,
        claim_id=channel_claim.id,
        expected_claim_generation=channel_claim.claim_generation,
        expected_source_revision=channel_claim.source_revision,
        selected_setting_id=channel_setting.id,
        selected_resource_id=selected_parent.id,
        selected_at=_at(4),
    )
    assert selected_channel is not None
    assert selected_channel.selected_resource_id == selected_parent.id
    fetched_channel = await repo.get_setup_claim(
        rdb_session,
        claim_id=selected_channel.id,
    )
    assert fetched_channel == selected_channel
    selected_claims = await repo.list_selected_setup_claims(rdb_session, limit=10)
    assert [claim.id for claim in selected_claims] == [
        selected_threads.id,
        selected_channel.id,
    ]
    selected_source_revision = selected_threads.selected_source_revision
    assert selected_source_revision is not None
    completed_threads = await repo.complete_setup_claim(
        rdb_session,
        claim_id=selected_threads.id,
        expected_claim_generation=selected_threads.claim_generation,
        expected_selected_source_revision=selected_source_revision,
        completed_at=_at(5),
    )
    assert completed_threads is not None
    selected_claims = await repo.list_selected_setup_claims(rdb_session, limit=10)
    assert [claim.id for claim in selected_claims] == [selected_channel.id]


async def test_binding_creation_serializes_on_resource_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Concurrent binding retries converge on one resource-wide row."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    workspace_id: str | None = None
    second_task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            workspace_id = await _workspace(setup, f"binding-lock-{suffix}")
            agent = await _agent(setup, workspace_id, f"binding-lock-{suffix}")
            repo = ExternalChannelRepository()
            connection = await repo.create_connection(
                setup,
                _connection_create(
                    workspace_id,
                    provider_app_id=f"AL{suffix}",
                    provider_tenant_id=f"TL{suffix}",
                ),
            )
            route = await repo.create_agent_route(
                setup,
                _route_create(
                    connection.id,
                    agent.id,
                    mode=ExternalChannelAppMode.SINGLE,
                ),
            )
            resource = await _resource(
                setup,
                repo,
                connection_id=connection.id,
                key=f"binding-lock-{suffix}",
            )
            agent_session = await AgentSessionRepository().create(
                setup,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    title=None,
                ),
            )
            await setup.commit()

        create = ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=route.id,
            agent_session_id=agent_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        )
        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as first_session:
            first = await repo.create_binding_idempotent(
                first_session,
                create,
                expected_access_request_id=None,
            )
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as second_session:
                second_task = asyncio.create_task(
                    repo.create_binding_idempotent(
                        second_session,
                        create,
                        expected_access_request_id=None,
                    )
                )
                await asyncio.sleep(0.1)
                assert not second_task.done()
                await first_session.commit()
                second = await asyncio.wait_for(second_task, timeout=5)
                await second_session.commit()

        assert second.id == first.id
        async with AsyncSession(rdb_engine) as verification:
            binding_count = await verification.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalChannelBinding)
                .where(RDBExternalChannelBinding.resource_id == resource.id)
            )
        assert binding_count == 1
    finally:
        if second_task is not None and not second_task.done():
            second_task.cancel()
            await asyncio.gather(second_task, return_exceptions=True)
        if workspace_id is not None:
            await _cleanup_committed_workspace(
                rdb_engine,
                workspace_id=workspace_id,
            )


async def test_provider_control_settlement_follows_lifecycle_lock_order(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Session-tree purge can finish while final settlement waits on authority."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    workspace_id: str | None = None
    settlement_task: asyncio.Task[DeliverySettlement] | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            workspace_id = await _workspace(setup, f"settlement-lock-{suffix}")
            agent = await _agent(setup, workspace_id, f"settlement-lock-{suffix}")
            repository = ExternalChannelRepository()
            connection = await repository.create_connection(
                setup,
                _connection_create(
                    workspace_id,
                    provider_app_id=f"AS{suffix}",
                    provider_tenant_id=f"TS{suffix}",
                ),
            )
            route = await repository.create_agent_route(
                setup,
                _route_create(
                    connection.id,
                    agent.id,
                    mode=ExternalChannelAppMode.SINGLE,
                ),
            )
            resource = await _resource(
                setup,
                repository,
                connection_id=connection.id,
                key=f"settlement-lock-{suffix}",
            )
            agent_session = await AgentSessionRepository().create(
                setup,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    title=None,
                ),
            )
            binding = await repository.create_binding_idempotent(
                setup,
                ExternalChannelBindingCreate(
                    resource_id=resource.id,
                    route_id=route.id,
                    agent_session_id=agent_session.id,
                    response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                    disconnected_at=None,
                    disconnect_reason=None,
                ),
                expected_access_request_id=None,
            )
            attempt = RDBExternalChannelDeliveryAttempt(
                origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                origin_id="manager-operation-1",
                operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                request_payload={
                    "channel_id": "C1",
                    "thread_ts": "1.000001",
                    "text": "Control",
                },
                status=ExternalChannelDeliveryStatus.PENDING,
                channel_action_id=None,
                binding_id=binding.id,
                provider_message_key=None,
                error_kind=None,
                error_summary=None,
                attempted_at=None,
                completed_at=None,
            )
            setup.add(attempt)
            await setup.commit()

        work_repository = ExternalChannelWorkRepository()
        lifecycle_repository = ExternalChannelLifecycleRepository()
        async with AsyncSession(rdb_engine) as start_session:
            assert await work_repository.start_delivery(
                start_session,
                delivery_attempt_id=attempt.id,
                now=_at(1),
            )
            await start_session.commit()

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as lifecycle_session:
            assert await lifecycle_session.scalar(
                sa.select(RDBAgentSession)
                .where(RDBAgentSession.id == agent_session.id)
                .with_for_update()
            )
            assert await lifecycle_session.scalar(
                sa.select(RDBExternalChannelBinding)
                .where(RDBExternalChannelBinding.id == binding.id)
                .with_for_update()
            )

            async def settle() -> DeliverySettlement:
                async with AsyncSession(rdb_engine) as settlement_session:
                    result = await work_repository.settle_delivery(
                        settlement_session,
                        delivery_attempt_id=attempt.id,
                        status=ExternalChannelDeliveryStatus.DELIVERED,
                        provider_message_key="slack:TS:C1:2.000001",
                        error_kind=None,
                        error_summary=None,
                        now=_at(3),
                    )
                    await settlement_session.commit()
                    return result

            settlement_task = asyncio.create_task(settle())
            await asyncio.sleep(0.1)
            assert not settlement_task.done()
            purged = await lifecycle_repository.prepare_session_tree_purge(
                lifecycle_session,
                session_ids=[agent_session.id],
                now=_at(2),
            )
            await lifecycle_session.commit()
            settlement = await asyncio.wait_for(settlement_task, timeout=5)

        assert purged.unknown_delivery_count == 1
        assert not settlement.accepted
        async with AsyncSession(rdb_engine) as verification:
            stored = await verification.get(
                RDBExternalChannelDeliveryAttempt,
                attempt.id,
            )
            assert stored is not None
            assert stored.status is ExternalChannelDeliveryStatus.UNKNOWN
            assert stored.error_kind == "PurgeOutcomeUnknown"
    finally:
        if settlement_task is not None and not settlement_task.done():
            settlement_task.cancel()
            await asyncio.gather(settlement_task, return_exceptions=True)
        if workspace_id is not None:
            await _cleanup_committed_workspace(
                rdb_engine,
                workspace_id=workspace_id,
            )


async def test_route_selection_observes_concurrent_agent_decommission(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """A waiting route selector fails closed after the Agent fence commits."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    workspace_id: str | None = None
    selection_task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            workspace_id = await _workspace(setup, f"route-fence-{suffix}")
            agent = await _agent(setup, workspace_id, f"route-fence-{suffix}")
            repo = ExternalChannelRepository()
            connection = await repo.create_connection(
                setup,
                _connection_create(
                    workspace_id,
                    provider_app_id=f"AF{suffix}",
                    provider_tenant_id=f"TF{suffix}",
                ),
            )
            route = await repo.create_agent_route(
                setup,
                _route_create(
                    connection.id,
                    agent.id,
                    mode=ExternalChannelAppMode.SINGLE,
                ),
            )
            await setup.commit()

        async with AsyncSession(
            rdb_engine,
            expire_on_commit=False,
        ) as decommission_session:
            await decommission_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == agent.id)
                .values(lifecycle_status=AgentLifecycleStatus.DECOMMISSIONING)
            )
            await decommission_session.flush()

            async def select_route() -> object:
                async with AsyncSession(
                    rdb_engine,
                    expire_on_commit=False,
                ) as routing_session:
                    locked_connection = await repo.lock_connection_for_routing(
                        routing_session,
                        connection_id=connection.id,
                    )
                    assert locked_connection is not None
                    selected = await repo.get_routable_route_by_id(
                        routing_session,
                        route_id=route.id,
                    )
                    await routing_session.commit()
                    return selected

            selection_task = asyncio.create_task(select_route())
            await asyncio.sleep(0.1)
            assert not selection_task.done()
            await decommission_session.commit()
            selected = await asyncio.wait_for(selection_task, timeout=5)

        assert selected is None
    finally:
        if selection_task is not None and not selection_task.done():
            selection_task.cancel()
            await asyncio.gather(selection_task, return_exceptions=True)
        if workspace_id is not None:
            await _cleanup_committed_workspace(
                rdb_engine,
                workspace_id=workspace_id,
            )


async def test_resource_wide_binding_unique_index_rejects_second_route(
    rdb_session: AsyncSession,
) -> None:
    """The active-binding index is resource-wide and keeps terminal history valid."""
    workspace_id = await _workspace(rdb_session, "binding-unique")
    first_agent = await _agent(rdb_session, workspace_id, "binding-first")
    second_agent = await _agent(rdb_session, workspace_id, "binding-second")
    repo = ExternalChannelRepository()
    multi_connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id, provider_app_id="AB", provider_tenant_id="TB"
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi_connection)
    await rdb_session.flush()
    first_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            multi_connection.id,
            first_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    second_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            multi_connection.id,
            second_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    resource = await _resource(
        rdb_session, repo, connection_id=multi_connection.id, key="binding-unique"
    )
    first_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=first_agent.id,
            title=None,
        ),
    )
    second_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=second_agent.id,
            title=None,
        ),
    )
    first = RDBExternalChannelBinding(
        resource_id=resource.id,
        route_id=first_route.id,
        agent_session_id=first_session.id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )
    rdb_session.add(first)
    await rdb_session.flush()

    with pytest.raises(
        IntegrityError, match="uq_external_channel_bindings_connected_resource"
    ):
        async with rdb_session.begin_nested():
            rdb_session.add(
                RDBExternalChannelBinding(
                    resource_id=resource.id,
                    route_id=second_route.id,
                    agent_session_id=second_session.id,
                    response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
                )
            )
            await rdb_session.flush()

    first.disconnected_at = _at(30)
    await rdb_session.flush()
    terminal_then_active = await repo.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=second_route.id,
            agent_session_id=second_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    assert terminal_then_active.route_id == second_route.id


async def test_manual_binding_disconnect_creates_one_leave_presence(
    rdb_session: AsyncSession,
) -> None:
    """A repeated manager disconnect retains one durable leave control."""
    workspace_id = await _workspace(rdb_session, "binding-leave-presence")
    agent = await _agent(rdb_session, workspace_id, "binding-leave-presence")
    repository = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()
    connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="presence-app",
            provider_tenant_id="presence-team",
        ).model_dump()
    )
    rdb_session.add(connection)
    await rdb_session.flush()
    route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            connection.id,
            agent.id,
            mode=ExternalChannelAppMode.SINGLE,
        ),
    )
    resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="presence-resource",
            labels={
                "provider": "slack",
                "tenant_id": "presence-team",
                "channel_id": "presence-channel",
                "thread_ts": "1.000001",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    agent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    binding = RDBExternalChannelBinding(
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id=agent_session.id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )
    rdb_session.add(binding)
    await rdb_session.flush()

    first = await management.disconnect_binding(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent.id,
        agent_session_id=agent_session.id,
        binding_id=binding.id,
        now=_at(30),
        reason="manager_disconnected",
    )
    retry = await management.disconnect_binding(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent.id,
        agent_session_id=agent_session.id,
        binding_id=binding.id,
        now=_at(31),
        reason="manager_disconnected",
    )

    assert first is not None
    assert retry == first
    assert binding.disconnect_reason == "manager_disconnected"
    attempts = list(
        (
            await rdb_session.scalars(
                sa.select(RDBExternalChannelDeliveryAttempt).where(
                    RDBExternalChannelDeliveryAttempt.origin_type
                    == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                    RDBExternalChannelDeliveryAttempt.origin_id == binding.id,
                    RDBExternalChannelDeliveryAttempt.operation
                    == ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                )
            )
        ).all()
    )
    assert len(attempts) == 1
    assert first == (attempts[0].id,)
    assert attempts[0].request_payload == {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": "left",
        "tenant_id": "presence-team",
        "channel_id": "presence-channel",
        "thread_ts": "1.000001",
    }


async def test_multi_channel_default_transition_terminalizes_only_parent_state(
    rdb_session: AsyncSession,
) -> None:
    """Replace and clear terminalize parent participation without touching threads."""
    workspace_id = await _workspace(rdb_session, "default-parent-transition")
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email="default-parent-transition@example.com"),
    )
    first_agent = await _agent(rdb_session, workspace_id, "default-parent-first")
    second_agent = await _agent(rdb_session, workspace_id, "default-parent-second")
    repository = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()
    connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="default-parent-app",
            provider_tenant_id="default-parent-team",
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(connection)
    await rdb_session.flush()
    first_route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            connection.id,
            first_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    second_route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            connection.id,
            second_agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    first_default = await repository.create_channel_default(
        rdb_session,
        ExternalChannelChannelDefaultCreate(
            connection_id=connection.id,
            provider_channel_id="C-parent",
            route_id=first_route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    parent_resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
            provider_resource_key="C-parent",
            labels={
                "provider": "slack",
                "tenant_id": "default-parent-team",
                "channel_id": "C-parent",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    thread_resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="C-parent:1.000001",
            labels={
                "provider": "slack",
                "tenant_id": "default-parent-team",
                "channel_id": "C-parent",
                "thread_ts": "1.000001",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(2),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    first_parent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=first_agent.id,
            title=None,
        ),
    )
    thread_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=first_agent.id,
            title=None,
        ),
    )
    first_parent_binding = await repository.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=parent_resource.id,
            route_id=first_route.id,
            agent_session_id=first_parent_session.id,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    thread_binding = await repository.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=thread_resource.id,
            route_id=first_route.id,
            agent_session_id=thread_session.id,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    principal = await repository.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="default-parent-team",
            provider_user_id="U-parent",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )
    first_setting = await repository.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-parent",
            route_id=first_route.id,
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
            configured_by_user_id=None,
            configured_by_principal_id=principal.id,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    position = await repository.create_conversation_position_idempotent(
        rdb_session,
        ExternalChannelConversationPositionCreate(
            connection_id=connection.id,
            scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id="C-parent",
            provider_thread_key=None,
            read_through_position=None,
        ),
    )
    pending_first_claim = await repository.create_setup_claim(
        rdb_session,
        ExternalChannelSetupClaimCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-parent",
            route_id=first_route.id,
            conversation_position_id=position.id,
            source_resource_id=thread_resource.id,
            principal_id=principal.id,
            source_projection={
                "schema_version": 1,
                "trigger_message_id": "message-first",
            },
            source_revision=1,
            claim_generation=1,
            status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
            selected_setting_id=None,
            selected_resource_id=None,
            selected_source_revision=None,
            expires_at=_at(50),
            selected_at=None,
            completed_at=None,
        ),
    )
    first_claim = await repository.select_setup_claim(
        rdb_session,
        claim_id=pending_first_claim.id,
        expected_claim_generation=pending_first_claim.claim_generation,
        expected_source_revision=pending_first_claim.source_revision,
        selected_setting_id=first_setting.id,
        selected_resource_id=parent_resource.id,
        selected_at=_at(3),
    )
    assert first_claim is not None
    first_interaction_result = await repository.admit_interaction(
        rdb_session,
        _interaction_create(
            connection.id,
            key="default-parent-first-interaction",
            principal_id=principal.id,
            projection={
                "provider_parent_channel_id": "C-parent",
                "interaction_id": "opaque-first",
            },
        ).model_copy(
            update={
                "setup_claim_id": first_claim.id,
                "expires_at": _at(50),
            }
        ),
    )
    assert await management.update_binding_response_mode(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=first_agent.id,
        agent_session_id=first_parent_session.id,
        binding_id=first_parent_binding.id,
        configured_by_user_id=user.id,
        response_mode=ExternalChannelResponseMode.MENTION_ONLY,
    )
    first_setting_after_web_mutation = await rdb_session.get(
        RDBExternalChannelParticipationSetting,
        first_setting.id,
    )
    first_parent_binding_after_web_mutation = await rdb_session.get(
        RDBExternalChannelBinding,
        first_parent_binding.id,
    )
    assert first_setting_after_web_mutation is not None
    assert first_setting_after_web_mutation.settings_generation == 2
    assert (
        first_setting_after_web_mutation.response_mode
        is ExternalChannelResponseMode.MENTION_ONLY
    )
    assert first_setting_after_web_mutation.configured_by_user_id == user.id
    assert first_setting_after_web_mutation.configured_by_principal_id is None
    assert first_parent_binding_after_web_mutation is not None
    assert (
        first_parent_binding_after_web_mutation.response_mode
        is ExternalChannelResponseMode.MENTION_ONLY
    )
    assert await management.update_binding_response_mode(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=first_agent.id,
        agent_session_id=thread_session.id,
        binding_id=thread_binding.id,
        configured_by_user_id=user.id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )
    assert first_setting_after_web_mutation.settings_generation == 2
    thread_binding_after_web_mutation = await rdb_session.get(
        RDBExternalChannelBinding,
        thread_binding.id,
    )
    assert thread_binding_after_web_mutation is not None
    assert (
        thread_binding_after_web_mutation.response_mode
        is ExternalChannelResponseMode.ALL_MESSAGES
    )

    no_op = await management.replace_multi_channel_default(
        rdb_session,
        workspace_id=workspace_id,
        connection_id=connection.id,
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="C-parent",
        route_id=first_route.id,
        configured_by_user_id=user.id,
        now=_at(10),
    )

    assert no_op is not None
    assert no_op.channel_default is not None
    assert no_op.channel_default.id == first_default.id
    assert no_op.channel_default.route_id == first_route.id
    assert no_op.changed is False
    assert no_op.cleanup_intent_ids == ()
    assert first_parent_binding.disconnected_at is None

    replaced = await management.replace_multi_channel_default(
        rdb_session,
        workspace_id=workspace_id,
        connection_id=connection.id,
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="C-parent",
        route_id=second_route.id,
        configured_by_user_id=user.id,
        now=_at(20),
    )

    assert replaced is not None
    assert replaced.channel_default is not None
    assert replaced.changed is True
    assert replaced.channel_default.route_id == second_route.id
    assert replaced.invalidated_setting_count == 1
    assert replaced.terminated_setup_claim_count == 1
    assert replaced.expired_interaction_count == 1
    assert replaced.disconnected_parent_binding_count == 1
    assert len(replaced.cleanup_intent_ids) == 1
    first_setting_rdb = await rdb_session.get(
        RDBExternalChannelParticipationSetting,
        first_setting.id,
    )
    first_claim_rdb = await rdb_session.get(
        RDBExternalChannelSetupClaim, first_claim.id
    )
    first_interaction_rdb = await rdb_session.get(
        RDBExternalChannelInteraction,
        first_interaction_result.interaction.id,
    )
    first_parent_binding_rdb = await rdb_session.get(
        RDBExternalChannelBinding,
        first_parent_binding.id,
    )
    thread_binding_rdb = await rdb_session.get(
        RDBExternalChannelBinding,
        thread_binding.id,
    )
    assert first_setting_rdb is not None
    assert (
        first_setting_rdb.status
        is ExternalChannelParticipationSettingStatus.INVALIDATED
    )
    assert first_setting_rdb.settings_generation == 3
    assert first_setting_rdb.invalidation_reason == "selected_agent_replaced"
    assert first_claim_rdb is not None
    assert first_claim_rdb.status is ExternalChannelSetupClaimStatus.INVALIDATED
    assert first_claim_rdb.claim_generation == first_claim.claim_generation + 1
    assert first_interaction_rdb is not None
    assert first_interaction_rdb.status is ExternalChannelInteractionStatus.EXPIRED
    assert first_parent_binding_rdb is not None
    assert first_parent_binding_rdb.disconnected_at == _at(20)
    assert first_parent_binding_rdb.disconnect_reason == "selected_agent_replaced"
    assert thread_binding_rdb is not None
    assert thread_binding_rdb.disconnected_at is None
    assert await rdb_session.get(RDBAgentSession, first_parent_session.id) is not None
    assert await rdb_session.get(RDBAgentSession, thread_session.id) is not None

    second_parent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=second_agent.id,
            title=None,
        ),
    )
    second_parent_binding = await repository.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=parent_resource.id,
            route_id=second_route.id,
            agent_session_id=second_parent_session.id,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    second_setting = await repository.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-parent",
            route_id=second_route.id,
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.MENTION_ONLY,
            settings_generation=1,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    second_claim = await repository.create_setup_claim(
        rdb_session,
        ExternalChannelSetupClaimCreate(
            connection_id=connection.id,
            provider_parent_channel_id="C-parent",
            route_id=second_route.id,
            conversation_position_id=position.id,
            source_resource_id=thread_resource.id,
            principal_id=principal.id,
            source_projection={
                "schema_version": 1,
                "trigger_message_id": "message-second",
            },
            source_revision=1,
            claim_generation=1,
            status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
            selected_setting_id=None,
            selected_resource_id=None,
            selected_source_revision=None,
            expires_at=_at(50),
            selected_at=None,
            completed_at=None,
        ),
    )
    second_interaction_result = await repository.admit_interaction(
        rdb_session,
        _interaction_create(
            connection.id,
            key="default-parent-second-interaction",
            principal_id=principal.id,
            projection={
                "provider_parent_channel_id": "C-parent",
                "interaction_id": "opaque-second",
            },
        ).model_copy(
            update={
                "setup_claim_id": second_claim.id,
                "expires_at": _at(50),
            }
        ),
    )

    cleared = await management.clear_multi_channel_default(
        rdb_session,
        workspace_id=workspace_id,
        connection_id=connection.id,
        provider=ExternalChannelProvider.SLACK,
        provider_channel_id="C-parent",
        now=_at(30),
    )

    assert cleared is not None
    assert cleared.changed is True
    assert cleared.invalidated_setting_count == 1
    assert cleared.terminated_setup_claim_count == 1
    assert cleared.expired_interaction_count == 1
    assert cleared.disconnected_parent_binding_count == 1
    assert len(cleared.cleanup_intent_ids) == 1
    assert set(replaced.cleanup_intent_ids).isdisjoint(cleared.cleanup_intent_ids)
    second_setting_rdb = await rdb_session.get(
        RDBExternalChannelParticipationSetting,
        second_setting.id,
    )
    second_claim_rdb = await rdb_session.get(
        RDBExternalChannelSetupClaim,
        second_claim.id,
    )
    second_interaction_rdb = await rdb_session.get(
        RDBExternalChannelInteraction,
        second_interaction_result.interaction.id,
    )
    second_parent_binding_rdb = await rdb_session.get(
        RDBExternalChannelBinding,
        second_parent_binding.id,
    )
    active_defaults = list(
        (
            await rdb_session.scalars(
                sa.select(RDBExternalChannelChannelDefault).where(
                    RDBExternalChannelChannelDefault.connection_id == connection.id,
                    RDBExternalChannelChannelDefault.provider_channel_id == "C-parent",
                    RDBExternalChannelChannelDefault.status
                    == ExternalChannelChannelDefaultStatus.ACTIVE,
                )
            )
        ).all()
    )
    cleanup_attempts = list(
        (
            await rdb_session.scalars(
                sa.select(RDBExternalChannelDeliveryAttempt).where(
                    RDBExternalChannelDeliveryAttempt.origin_type
                    == ExternalChannelDeliveryOriginType.BINDING_DISCONNECT,
                    RDBExternalChannelDeliveryAttempt.operation
                    == ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                )
            )
        ).all()
    )
    assert second_setting_rdb is not None
    assert (
        second_setting_rdb.status
        is ExternalChannelParticipationSettingStatus.INVALIDATED
    )
    assert second_setting_rdb.invalidation_reason == "selected_agent_cleared"
    assert second_claim_rdb is not None
    assert second_claim_rdb.status is ExternalChannelSetupClaimStatus.EXPIRED
    assert second_interaction_rdb is not None
    assert second_interaction_rdb.status is ExternalChannelInteractionStatus.EXPIRED
    assert second_parent_binding_rdb is not None
    assert second_parent_binding_rdb.disconnected_at == _at(30)
    assert second_parent_binding_rdb.disconnect_reason == "selected_agent_cleared"
    assert thread_binding_rdb.disconnected_at is None
    assert await rdb_session.get(RDBAgentSession, second_parent_session.id) is not None
    assert active_defaults == []
    assert {attempt.binding_id for attempt in cleanup_attempts} == {
        first_parent_binding.id,
        second_parent_binding.id,
    }


async def test_multi_route_removal_creates_leave_presence_before_detach(
    rdb_session: AsyncSession,
) -> None:
    """Route removal terminalizes participation and retains one leave control."""
    workspace_id = await _workspace(rdb_session, "route-leave-presence")
    user = await UserRepository().create(
        rdb_session,
        UserCreate(email="route-leave-presence@example.com"),
    )
    agent = await _agent(rdb_session, workspace_id, "route-leave-presence")
    repository = ExternalChannelRepository()
    lifecycle = ExternalChannelLifecycleRepository()
    connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="route-presence-app",
            provider_tenant_id="route-presence-team",
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(connection)
    await rdb_session.flush()
    route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            connection.id,
            agent.id,
            mode=ExternalChannelAppMode.MULTI,
        ),
    )
    channel_default = await repository.create_channel_default(
        rdb_session,
        ExternalChannelChannelDefaultCreate(
            connection_id=connection.id,
            provider_channel_id="route-presence-channel",
            route_id=route.id,
            status=ExternalChannelChannelDefaultStatus.ACTIVE,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.PARENT_CHANNEL,
            provider_resource_key="route-presence-channel",
            labels={
                "provider": "slack",
                "tenant_id": "route-presence-team",
                "channel_id": "route-presence-channel",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    source_resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="route-presence-channel:2.000001",
            labels={
                "provider": "slack",
                "tenant_id": "route-presence-team",
                "channel_id": "route-presence-channel",
                "thread_ts": "2.000001",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    agent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    binding = RDBExternalChannelBinding(
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id=agent_session.id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )
    rdb_session.add(binding)
    await rdb_session.flush()
    principal = await repository.create_principal_idempotent(
        rdb_session,
        ExternalChannelPrincipalCreate(
            provider=ExternalChannelProvider.SLACK,
            provider_tenant_id="route-presence-team",
            provider_user_id="route-presence-user",
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            display_name=None,
            avatar_url=None,
            profile=None,
        ),
    )
    setting = await repository.create_participation_setting(
        rdb_session,
        ExternalChannelParticipationSettingCreate(
            connection_id=connection.id,
            provider_parent_channel_id="route-presence-channel",
            route_id=route.id,
            location=ExternalChannelConversationLocation.CHANNEL,
            response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
            settings_generation=1,
            configured_by_user_id=user.id,
            configured_by_principal_id=None,
            status=ExternalChannelParticipationSettingStatus.ACTIVE,
            invalidated_at=None,
            invalidation_reason=None,
        ),
    )
    position = await repository.create_conversation_position_idempotent(
        rdb_session,
        ExternalChannelConversationPositionCreate(
            connection_id=connection.id,
            scope_kind=ExternalChannelConversationScopeKind.PARENT_CHANNEL,
            provider_channel_id="route-presence-channel",
            provider_thread_key=None,
            read_through_position=None,
        ),
    )
    claim = await repository.create_setup_claim(
        rdb_session,
        ExternalChannelSetupClaimCreate(
            connection_id=connection.id,
            provider_parent_channel_id="route-presence-channel",
            route_id=route.id,
            conversation_position_id=position.id,
            source_resource_id=source_resource.id,
            principal_id=principal.id,
            source_projection={
                "schema_version": 1,
                "trigger_message_id": "route-presence-message",
            },
            source_revision=1,
            claim_generation=1,
            status=ExternalChannelSetupClaimStatus.PENDING_LOCATION,
            selected_setting_id=None,
            selected_resource_id=None,
            selected_source_revision=None,
            expires_at=_at(50),
            selected_at=None,
            completed_at=None,
        ),
    )
    interaction_result = await repository.admit_interaction(
        rdb_session,
        _interaction_create(
            connection.id,
            key="route-presence-interaction",
            principal_id=principal.id,
            projection={
                "provider_parent_channel_id": "route-presence-channel",
                "interaction_id": "route-presence-opaque",
            },
        ).model_copy(
            update={
                "setup_claim_id": claim.id,
                "expires_at": _at(50),
            }
        ),
    )
    impact = await lifecycle.project_multi_route_impact(
        rdb_session,
        connection_id=connection.id,
        route_id=route.id,
    )

    removal = await lifecycle.remove_multi_route(
        rdb_session,
        connection_id=connection.id,
        route_id=route.id,
        removed_by_user_id=None,
        now=_at(30),
    )

    assert removal is not None
    assert impact is not None
    assert impact.active_default_count == 1
    assert impact.active_participation_setting_count == 1
    assert impact.nonterminal_setup_claim_count == 1
    assert impact.active_binding_count == 1
    assert impact.connected_parent_binding_count == 1
    assert len(removal.cleanup_intent_ids) == 1
    persisted_route = await rdb_session.get(RDBExternalChannelAgentRoute, route.id)
    assert persisted_route is not None
    assert persisted_route.agent_id is None
    persisted_default = await rdb_session.get(
        RDBExternalChannelChannelDefault,
        channel_default.id,
    )
    persisted_setting = await rdb_session.get(
        RDBExternalChannelParticipationSetting,
        setting.id,
    )
    persisted_claim = await rdb_session.get(
        RDBExternalChannelSetupClaim,
        claim.id,
    )
    persisted_interaction = await rdb_session.get(
        RDBExternalChannelInteraction,
        interaction_result.interaction.id,
    )
    assert persisted_default is not None
    assert persisted_default.status is ExternalChannelChannelDefaultStatus.INVALIDATED
    assert persisted_setting is not None
    assert (
        persisted_setting.status
        is ExternalChannelParticipationSettingStatus.INVALIDATED
    )
    assert persisted_setting.settings_generation == 2
    assert persisted_setting.invalidation_reason == "relationship_removed"
    assert persisted_claim is not None
    assert persisted_claim.status is ExternalChannelSetupClaimStatus.INVALIDATED
    assert persisted_claim.claim_generation == 2
    assert persisted_interaction is not None
    assert persisted_interaction.status is ExternalChannelInteractionStatus.EXPIRED
    attempt = await rdb_session.get(
        RDBExternalChannelDeliveryAttempt,
        removal.cleanup_intent_ids[0],
    )
    assert attempt is not None
    assert attempt.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
    assert attempt.request_payload == {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": "left",
        "tenant_id": "route-presence-team",
        "channel_id": "route-presence-channel",
    }


async def test_provider_uninstall_creates_one_leave_presence(
    rdb_session: AsyncSession,
) -> None:
    """A repeated provider termination retains one durable leave control."""
    workspace_id = await _workspace(rdb_session, "uninstall-leave-presence")
    agent = await _agent(rdb_session, workspace_id, "uninstall-leave-presence")
    repository = ExternalChannelRepository()
    connection = await repository.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id="uninstall-presence-app",
            provider_tenant_id="uninstall-presence-team",
        ),
    )
    route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            connection.id,
            agent.id,
            mode=ExternalChannelAppMode.SINGLE,
        ),
    )
    resource = await repository.create_resource_idempotent(
        rdb_session,
        ExternalChannelResourceCreate(
            connection_id=connection.id,
            resource_type=ExternalChannelResourceType.THREAD,
            provider_resource_key="uninstall-presence-resource",
            labels={
                "provider": "slack",
                "tenant_id": "uninstall-presence-team",
                "channel_id": "uninstall-presence-channel",
                "thread_ts": "3.000001",
            },
            status=ExternalChannelResourceStatus.ACTIVE,
            latest_activity_at=_at(1),
            unavailable_at=None,
            deleted_at=None,
        ),
    )
    agent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    binding = RDBExternalChannelBinding(
        resource_id=resource.id,
        route_id=route.id,
        agent_session_id=agent_session.id,
        response_mode=ExternalChannelResponseMode.ALL_MESSAGES,
    )
    rdb_session.add(binding)
    await rdb_session.flush()

    first = await repository.terminate_connection_for_provider_event(
        rdb_session,
        connection_id=connection.id,
        status=ExternalChannelConnectionStatus.DISCONNECTED,
        reason="app_uninstalled",
        now=_at(30),
        required_configuration_generation=None,
        required_socket_lease_owner=None,
        defer_provider_state_purge=True,
    )
    repeated = await repository.terminate_connection_for_provider_event(
        rdb_session,
        connection_id=connection.id,
        status=ExternalChannelConnectionStatus.DISCONNECTED,
        reason="app_uninstalled",
        now=_at(31),
        required_configuration_generation=None,
        required_socket_lease_owner=None,
        defer_provider_state_purge=True,
    )

    assert first is not None
    assert len(first) == 1
    assert repeated == ()
    attempt = await rdb_session.get(RDBExternalChannelDeliveryAttempt, first[0])
    assert attempt is not None
    assert attempt.operation is ExternalChannelDeliveryOperation.CONTROL_MESSAGE
    assert attempt.request_payload == {
        "control_kind": "session_presence",
        "control_version": 2,
        "presence_state": "left",
        "tenant_id": "uninstall-presence-team",
        "channel_id": "uninstall-presence-channel",
        "thread_ts": "3.000001",
    }


async def test_agent_scoped_management_excludes_multi_and_corrupt_single_routes(
    rdb_session: AsyncSession,
) -> None:
    """Agent management exposes only its exact sole Single-App route."""
    workspace_id = await _workspace(rdb_session, "management-route-boundary")
    agent = await _agent(rdb_session, workspace_id, "management-route-boundary")
    second_agent = await _agent(
        rdb_session, workspace_id, "management-route-boundary-second"
    )
    repo = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()

    multi = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id, provider_app_id="AM", provider_tenant_id="TM"
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi)
    await rdb_session.flush()
    await repo.create_agent_route(
        rdb_session,
        _route_create(multi.id, agent.id, mode=ExternalChannelAppMode.MULTI),
    )
    associated_multi_apps = await management.list_agent_multi_connections(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent.id,
    )
    assert len(associated_multi_apps) == 1
    assert associated_multi_apps[0].id == multi.id
    assert associated_multi_apps[0].active_agent_count == 1
    assert associated_multi_apps[0].configured_default_count == 0

    corrupt_single = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id, provider_app_id="AS", provider_tenant_id="TS"),
    )
    await repo.create_agent_route(
        rdb_session,
        _route_create(
            corrupt_single.id,
            agent.id,
            mode=ExternalChannelAppMode.SINGLE,
        ),
    )
    await rdb_session.execute(
        sa.text("DROP INDEX uq_external_channel_agent_routes_single_connection")
    )
    rdb_session.add(
        RDBExternalChannelAgentRoute(
            connection_id=corrupt_single.id,
            agent_id=second_agent.id,
            agent_id_snapshot=second_agent.id,
            route_mode=ExternalChannelRouteMode.DEDICATED,
            connection_app_mode=ExternalChannelAppMode.SINGLE,
            catalog_status=ExternalChannelRouteCatalogStatus.AVAILABLE,
            catalog_removed_at=None,
            catalog_removed_by_user_id=None,
        )
    )
    await rdb_session.flush()

    assert (
        await management.list_connections(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent.id,
        )
        == []
    )
    assert (
        await management.get_connection(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent.id,
            connection_id=multi.id,
        )
        is None
    )
    assert (
        await management.get_connection(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent.id,
            connection_id=corrupt_single.id,
        )
        is None
    )


async def test_workspace_multi_management_uses_provider_neutral_stable_pagination(
    rdb_session: AsyncSession,
) -> None:
    """One list page orders Slack and Discord Multi Apps before applying offset."""
    workspace_id = await _workspace(rdb_session, "management-multi-page")
    repository = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()
    created_connections = [
        await repository.create_connection(
            rdb_session,
            _connection_create(
                workspace_id,
                provider=ExternalChannelProvider.SLACK,
                provider_app_id="MP1",
                provider_tenant_id="MT1",
            ).model_copy(update={"app_mode": ExternalChannelAppMode.MULTI}),
        ),
        await repository.create_connection(
            rdb_session,
            _connection_create(
                workspace_id,
                provider=ExternalChannelProvider.DISCORD,
                provider_app_id="MP2",
                provider_tenant_id="MT2",
            ).model_copy(update={"app_mode": ExternalChannelAppMode.MULTI}),
        ),
        await repository.create_connection(
            rdb_session,
            _connection_create(
                workspace_id,
                provider=ExternalChannelProvider.SLACK,
                provider_app_id="MP3",
                provider_tenant_id="MT3",
            ).model_copy(update={"app_mode": ExternalChannelAppMode.MULTI}),
        ),
    ]
    connections: list[RDBExternalChannelConnection] = []
    for created_connection in created_connections:
        connection = await rdb_session.get(
            RDBExternalChannelConnection,
            created_connection.id,
        )
        assert connection is not None
        connections.append(connection)
    connections[0].created_at = _at(2)
    connections[1].created_at = _at(1)
    connections[2].created_at = _at(2)
    await rdb_session.flush()
    expected = sorted(
        connections,
        key=lambda connection: (connection.created_at, connection.id),
    )

    first_page = await management.list_multi_connections(
        rdb_session,
        workspace_id=workspace_id,
        provider=None,
        offset=0,
        limit=2,
    )
    second_page = await management.list_multi_connections(
        rdb_session,
        workspace_id=workspace_id,
        provider=None,
        offset=2,
        limit=2,
    )
    slack_page = await management.list_multi_connections(
        rdb_session,
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
        offset=0,
        limit=2,
    )

    assert [connection.id for connection in first_page] == [
        connection.id for connection in expected[:2]
    ]
    assert [connection.id for connection in second_page] == [
        connection.id for connection in expected[2:]
    ]
    assert [connection.id for connection in slack_page] == [
        connection.id
        for connection in expected
        if connection.provider == ExternalChannelProvider.SLACK
    ]


async def test_disconnect_lookup_uses_detached_single_route_snapshot(
    rdb_session: AsyncSession,
) -> None:
    """Only disconnect retries can resolve a detached disconnected Single App."""
    workspace_id = await _workspace(rdb_session, "disconnect-snapshot-lookup")
    agent = await _agent(rdb_session, workspace_id, "disconnect-snapshot-owner")
    other_agent = await _agent(rdb_session, workspace_id, "disconnect-snapshot-other")
    repository = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()
    created_connection = await repository.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id="AD-snapshot",
            provider_tenant_id="TD-snapshot",
        ),
    )
    created_route = await repository.create_agent_route(
        rdb_session,
        _route_create(
            created_connection.id,
            agent.id,
            mode=ExternalChannelAppMode.SINGLE,
        ),
    )
    connection = await rdb_session.get(
        RDBExternalChannelConnection,
        created_connection.id,
    )
    route = await rdb_session.get(
        RDBExternalChannelAgentRoute,
        created_route.id,
    )
    assert connection is not None
    assert route is not None
    connection.status = ExternalChannelConnectionStatus.DISCONNECTED
    route.agent_id = None
    route.catalog_status = ExternalChannelRouteCatalogStatus.REMOVED
    await rdb_session.flush()

    assert (
        await management.get_connection(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent.id,
            connection_id=connection.id,
        )
        is None
    )
    disconnected = await management.get_connection(
        rdb_session,
        workspace_id=workspace_id,
        agent_id=agent.id,
        connection_id=connection.id,
        include_disconnected=True,
    )
    assert disconnected is not None
    assert disconnected[0].id == connection.id
    assert disconnected[1].id == route.id
    assert (
        await management.get_connection(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=other_agent.id,
            connection_id=connection.id,
            include_disconnected=True,
        )
        is None
    )


async def test_multi_management_handoff_requires_completed_unexpired_channel_scope(
    rdb_session: AsyncSession,
) -> None:
    """Authenticated handoffs expose only completed live channel-bound state."""
    workspace_id = await _workspace(rdb_session, "multi-management-handoff")
    repo = ExternalChannelRepository()
    management = ExternalChannelManagementRepository()
    connection = await repo.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id="A-handoff",
            provider_tenant_id="T-handoff",
        ).model_copy(
            update={
                "app_mode": ExternalChannelAppMode.MULTI,
                "status": ExternalChannelConnectionStatus.ACTIVE,
            }
        ),
    )
    admission = await repo.admit_interaction(
        rdb_session,
        _interaction_create(connection.id, key="management-handoff").model_copy(
            update={
                "interaction_type": ExternalChannelInteractionType.MANAGEMENT_ACTION,
                "resource_correlation_key": "C-handoff:123.456",
            }
        ),
    )
    assert (
        await management.load_multi_management_handoff(
            rdb_session,
            workspace_id=workspace_id,
            interaction_id=admission.interaction.id,
            now=_at(5),
        )
        is None
    )
    processing = await repo.transition_interaction(
        rdb_session,
        interaction_id=admission.interaction.id,
        status=ExternalChannelInteractionStatus.PROCESSING,
        error_kind=None,
        error_summary=None,
        transitioned_at=_at(1),
    )
    assert processing is not None
    assert processing.status is ExternalChannelInteractionStatus.PROCESSING
    assert processing.updated_at == _at(1)
    completed = await repo.transition_interaction(
        rdb_session,
        interaction_id=admission.interaction.id,
        status=ExternalChannelInteractionStatus.COMPLETED,
        error_kind=None,
        error_summary=None,
        transitioned_at=_at(2),
    )
    assert completed is not None
    assert completed.status is ExternalChannelInteractionStatus.COMPLETED
    assert completed.updated_at == _at(2)

    handoff = await management.load_multi_management_handoff(
        rdb_session,
        workspace_id=workspace_id,
        interaction_id=admission.interaction.id,
        now=_at(5),
    )

    assert handoff is not None
    assert handoff.connection_id == connection.id
    assert handoff.provider_channel_id == "C-handoff"
    assert handoff.provider_thread_id == "123.456"
    assert handoff.expires_at == _at(10)
    assert (
        await management.load_multi_management_handoff(
            rdb_session,
            workspace_id=workspace_id,
            interaction_id=admission.interaction.id,
            now=_at(10),
        )
        is None
    )


async def test_multi_disconnect_terminalizes_zero_route_connection(
    rdb_session: AsyncSession,
) -> None:
    """A zero-route Multi App disconnect remains idempotent and credential-free."""
    workspace_id = await _workspace(rdb_session, "multi-zero-disconnect")
    connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="AZ",
            provider_tenant_id="TZ",
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(connection)
    await rdb_session.flush()
    lifecycle = ExternalChannelLifecycleRepository()

    first = await lifecycle.disconnect_multi_connection(
        rdb_session,
        connection_id=connection.id,
        now=_at(40),
        reason="manager_disconnected",
    )
    retry = await lifecycle.disconnect_multi_connection(
        rdb_session,
        connection_id=connection.id,
        now=_at(41),
        reason="manager_disconnected",
    )

    assert first is not None
    assert first.disconnected_route_count == 0
    assert retry is not None
    assert connection.status is ExternalChannelConnectionStatus.DISCONNECTED
    assert connection.encrypted_credentials is None


async def test_disconnect_releases_the_current_discord_app_claim(
    rdb_session: AsyncSession,
) -> None:
    """A disconnected Discord history no longer reserves its Application."""
    workspace_id = await _workspace(rdb_session, "discord-claim-disconnect")
    connection = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="discord-claim-app",
            provider_tenant_id="guild-1",
        )
        .model_copy(
            update={
                "provider": ExternalChannelProvider.DISCORD,
                "app_mode": ExternalChannelAppMode.MULTI,
            }
        )
        .model_dump()
    )
    rdb_session.add(connection)
    await rdb_session.flush()
    rdb_session.add(
        RDBExternalChannelAppClaim(
            provider=ExternalChannelProvider.DISCORD,
            provider_app_id="discord-claim-app",
            connection_id=connection.id,
            claim_generation=1,
        )
    )
    await rdb_session.flush()

    lifecycle = ExternalChannelLifecycleRepository()
    disconnected = await lifecycle.disconnect_multi_connection(
        rdb_session,
        connection_id=connection.id,
        now=_at(40),
        reason="manager_disconnected",
    )

    assert disconnected is not None
    assert (
        await rdb_session.scalar(
            sa.select(RDBExternalChannelAppClaim).where(
                RDBExternalChannelAppClaim.provider == ExternalChannelProvider.DISCORD,
                RDBExternalChannelAppClaim.provider_app_id == "discord-claim-app",
            )
        )
        is None
    )


async def test_agent_decommission_detaches_routes_before_agent_delete(
    rdb_session: AsyncSession,
) -> None:
    """Agent cleanup preserves route provenance without blocking physical deletion."""
    workspace_id = await _workspace(rdb_session, "route-agent-decommission")
    agent = await _agent(rdb_session, workspace_id, "route-agent-decommission")
    repo = ExternalChannelRepository()
    lifecycle = ExternalChannelLifecycleRepository()
    single = await repo.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id="AD-single",
            provider_tenant_id="TD-single",
        ),
    )
    multi = RDBExternalChannelConnection(
        **_connection_create(
            workspace_id,
            provider_app_id="AD-multi",
            provider_tenant_id="TD-multi",
        )
        .model_copy(update={"app_mode": ExternalChannelAppMode.MULTI})
        .model_dump()
    )
    rdb_session.add(multi)
    await rdb_session.flush()
    single_route = await repo.create_agent_route(
        rdb_session,
        _route_create(single.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
    )
    multi_route = await repo.create_agent_route(
        rdb_session,
        _route_create(multi.id, agent.id, mode=ExternalChannelAppMode.MULTI),
    )

    cleanup = await lifecycle.cleanup_decommissioned_agent(
        rdb_session,
        agent_id=agent.id,
        now=_at(60),
    )

    persisted_single_route = await rdb_session.get(
        RDBExternalChannelAgentRoute,
        single_route.id,
    )
    persisted_multi_route = await rdb_session.get(
        RDBExternalChannelAgentRoute,
        multi_route.id,
    )
    persisted_single_connection = await rdb_session.get(
        RDBExternalChannelConnection,
        single.id,
    )
    assert persisted_single_route is not None
    assert persisted_multi_route is not None
    assert persisted_single_connection is not None
    for route in (persisted_single_route, persisted_multi_route):
        assert route.catalog_status is ExternalChannelRouteCatalogStatus.REMOVED
        assert route.agent_id is None
        assert route.agent_id_snapshot == agent.id
    assert (
        persisted_single_connection.status
        is ExternalChannelConnectionStatus.DISCONNECTED
    )
    assert persisted_single_connection.encrypted_credentials == "ciphertext"
    assert multi.status is ExternalChannelConnectionStatus.ACTIVE
    assert cleanup.provider_state_purge_connection_ids == (single.id,)

    assert (
        await lifecycle.purge_disconnected_connection_provider_state(
            rdb_session,
            connection_ids=cleanup.provider_state_purge_connection_ids,
        )
        == 1
    )
    assert persisted_single_connection.encrypted_credentials is None

    await rdb_session.delete(agent)
    await rdb_session.flush()

    assert (
        await rdb_session.get(RDBExternalChannelAgentRoute, single_route.id)
    ) is persisted_single_route
    assert (
        await rdb_session.get(RDBExternalChannelAgentRoute, multi_route.id)
    ) is persisted_multi_route


async def test_agent_decommission_repairs_legacy_disconnected_single_route(
    rdb_session: AsyncSession,
) -> None:
    """Agent cleanup detaches a route left active by a historical disconnect."""
    workspace_id = await _workspace(rdb_session, "legacy-disconnected-single")
    agent = await _agent(rdb_session, workspace_id, "legacy-disconnected-single")
    repo = ExternalChannelRepository()
    lifecycle = ExternalChannelLifecycleRepository()
    connection = await repo.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id="AD-legacy-single",
            provider_tenant_id="TD-legacy-single",
        ),
    )
    route = await repo.create_agent_route(
        rdb_session,
        _route_create(connection.id, agent.id, mode=ExternalChannelAppMode.SINGLE),
    )
    connection_rdb = await rdb_session.get(
        RDBExternalChannelConnection,
        connection.id,
    )
    assert connection_rdb is not None
    connection_rdb.status = ExternalChannelConnectionStatus.DISCONNECTED
    connection_rdb.encrypted_credentials = None
    connection_rdb.provider_tenant_id = None
    connection_rdb.disconnected_at = _at(50)
    await rdb_session.flush()

    cleanup = await lifecycle.cleanup_decommissioned_agent(
        rdb_session,
        agent_id=agent.id,
        now=_at(60),
    )

    persisted_route = await rdb_session.get(RDBExternalChannelAgentRoute, route.id)
    assert cleanup.deleted_route_count == 0
    assert persisted_route is not None
    assert persisted_route.catalog_status is ExternalChannelRouteCatalogStatus.REMOVED
    assert persisted_route.agent_id is None
    assert persisted_route.agent_id_snapshot == agent.id

    await rdb_session.delete(agent)
    await rdb_session.flush()
