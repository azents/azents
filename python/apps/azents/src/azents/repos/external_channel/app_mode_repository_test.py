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
    AgentSessionRunState,
    ExternalChannelAppMode,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationScopeKind,
    ExternalChannelDeliveryOperation,
    ExternalChannelDeliveryOriginType,
    ExternalChannelDeliveryStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelSessionActivationState,
    ExternalChannelTransport,
    LLMProvider,
    MailboxItemKind,
    MailboxSchedulingMode,
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
    RDBExternalChannelResource,
)
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.mailbox_item import RDBMailboxItem
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
    ExternalChannelDeliveryAttemptCreate,
    ExternalChannelInteractionCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelPurgePreparation,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
    ExternalChannelSessionActivationCreate,
    ExternalChannelSessionActivationDeliveryCreate,
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
        DELETE FROM external_channel_session_activation_deliveries
        WHERE activation_id IN (
            SELECT activation.id
            FROM external_channel_session_activations AS activation
            JOIN external_channel_bindings AS binding
              ON binding.id = activation.binding_id
            JOIN external_channel_agent_routes AS route
              ON route.id = binding.route_id
            JOIN external_channel_connections AS connection
              ON connection.id = route.connection_id
            WHERE connection.workspace_id = :workspace_id
        )
        """,
        """
        DELETE FROM external_channel_session_activations
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
        DELETE FROM external_channel_conversation_positions
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


async def test_session_activation_persists_ordered_delivery_and_activation(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """One trigger reuses its activation and becomes non-barrier after activation."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    workspace_id: str | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as session:
            workspace_id = await _workspace(session, f"activation-{suffix}")
            agent = await _agent(session, workspace_id, f"activation-{suffix}")
            repository = ExternalChannelRepository()
            work_repository = ExternalChannelWorkRepository()
            connection = await repository.create_connection(
                session,
                _connection_create(
                    workspace_id,
                    provider_app_id=f"AA{suffix}",
                    provider_tenant_id=f"TA{suffix}",
                ),
            )
            route = await repository.create_agent_route(
                session,
                _route_create(
                    connection.id,
                    agent.id,
                    mode=ExternalChannelAppMode.SINGLE,
                ),
            )
            resource = await _resource(
                session,
                repository,
                connection_id=connection.id,
                key=f"activation-{suffix}",
            )
            agent_session = await AgentSessionRepository().create(
                session,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    title=None,
                ),
            )
            binding = await repository.create_binding_idempotent(
                session,
                ExternalChannelBindingCreate(
                    resource_id=resource.id,
                    route_id=route.id,
                    agent_session_id=agent_session.id,
                    disconnected_at=None,
                    disconnect_reason=None,
                ),
                expected_access_request_id=None,
            )
            position = await repository.create_conversation_position_idempotent(
                session,
                ExternalChannelConversationPositionCreate(
                    connection_id=connection.id,
                    scope_kind=ExternalChannelConversationScopeKind.THREAD,
                    provider_channel_id=f"C{suffix}",
                    provider_thread_key=f"T{suffix}",
                    read_through_position=None,
                ),
            )
            session_link_delivery = await repository.create_delivery_attempt_idempotent(
                session,
                ExternalChannelDeliveryAttemptCreate(
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id=binding.id,
                    channel_action_id=None,
                    binding_id=binding.id,
                    operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
                    request_payload={"control_kind": "session_link"},
                    status=ExternalChannelDeliveryStatus.PENDING,
                    provider_message_key=None,
                    error_kind=None,
                    error_summary=None,
                    attempted_at=None,
                    completed_at=None,
                ),
            )
            tracker_delivery = await repository.create_delivery_attempt_idempotent(
                session,
                ExternalChannelDeliveryAttemptCreate(
                    origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
                    origin_id=binding.id,
                    channel_action_id=None,
                    binding_id=binding.id,
                    operation=ExternalChannelDeliveryOperation.PROGRESS_CREATE,
                    request_payload={"control_kind": "initial_progress"},
                    status=ExternalChannelDeliveryStatus.PENDING,
                    provider_message_key=None,
                    error_kind=None,
                    error_summary=None,
                    attempted_at=None,
                    completed_at=None,
                ),
            )
            mailbox_item = RDBMailboxItem(
                session_id=agent_session.id,
                kind=MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                idempotency_key=f"activation-{suffix}",
                payload={},
            )
            session.add(mailbox_item)
            await session.flush()
            create = ExternalChannelSessionActivationCreate(
                connection_id=connection.id,
                conversation_position_id=position.id,
                binding_id=binding.id,
                agent_session_id=agent_session.id,
                trigger_provider_message_key=f"message-{suffix}",
                trigger_position="00000000000000000001",
                range_start_position=None,
                state=ExternalChannelSessionActivationState.INITIALIZING,
                mailbox_item_id=mailbox_item.id,
                failure_kind=None,
                failure_summary=None,
                activated_at=None,
                blocked_at=None,
            )
            activation = await repository.create_session_activation_idempotent(
                session,
                create,
            )
            duplicate = await repository.create_session_activation_idempotent(
                session,
                create,
            )
            await repository.create_session_activation_delivery_idempotent(
                session,
                ExternalChannelSessionActivationDeliveryCreate(
                    activation_id=activation.id,
                    ordinal=0,
                    delivery_attempt_id=session_link_delivery.id,
                ),
            )
            await repository.create_session_activation_delivery_idempotent(
                session,
                ExternalChannelSessionActivationDeliveryCreate(
                    activation_id=activation.id,
                    ordinal=1,
                    delivery_attempt_id=tracker_delivery.id,
                ),
            )
            await session.commit()

        assert duplicate.id == activation.id
        async with AsyncSession(rdb_engine) as verification:
            barrier = await repository.get_open_session_activation_by_position(
                verification,
                conversation_position_id=position.id,
            )
            linked = await repository.list_session_activation_deliveries(
                verification,
                activation_id=activation.id,
            )
            assert barrier is not None
            assert barrier.id == activation.id
            assert [item.delivery_attempt_id for item in linked] == [
                session_link_delivery.id,
                tracker_delivery.id,
            ]
            pending_delivery_ids = (
                await work_repository.list_pending_provider_control_delivery_ids(
                    verification,
                    limit=20,
                )
            )
            assert session_link_delivery.id in pending_delivery_ids
            assert tracker_delivery.id not in pending_delivery_ids
            visible = await AgentSessionRepository().list_active_unread_by_agent_id(
                verification,
                agent.id,
                auto_archive_ttl_days=30,
            )
            detail = await AgentSessionRepository().get_with_unread_terminal_run_by_id(
                verification,
                agent_session.id,
            )
            assert [item.session.id for item in visible] == [agent_session.id]
            assert detail is not None
            assert detail.session.id == agent_session.id
            assert detail.session.run_state is AgentSessionRunState.IDLE
            assert barrier.mailbox_item_id == mailbox_item.id
            assert (
                await repository.get_session_activation_state_by_mailbox_item_id(
                    verification,
                    mailbox_item_id=mailbox_item.id,
                )
                is ExternalChannelSessionActivationState.INITIALIZING
            )
            assert (
                await repository.activate_session_activation(
                    verification,
                    activation_id=activation.id,
                    mailbox_item_id=mailbox_item.id,
                    activated_at=_at(1),
                )
                is None
            )
            started = await repository.start_delivery_attempt(
                verification,
                delivery_attempt_id=session_link_delivery.id,
                attempted_at=_at(1),
            )
            assert started is not None
            delivered = await repository.finish_delivery_attempt(
                verification,
                delivery_attempt_id=session_link_delivery.id,
                status=ExternalChannelDeliveryStatus.DELIVERED,
                provider_message_key=f"provider-{suffix}",
                error_kind=None,
                error_summary=None,
                completed_at=_at(2),
            )
            assert delivered is not None
            pending_delivery_ids = (
                await work_repository.list_pending_provider_control_delivery_ids(
                    verification,
                    limit=20,
                )
            )
            assert tracker_delivery.id in pending_delivery_ids
            tracker_started = await repository.start_delivery_attempt(
                verification,
                delivery_attempt_id=tracker_delivery.id,
                attempted_at=_at(2),
            )
            assert tracker_started is not None
            tracker_delivered = await repository.finish_delivery_attempt(
                verification,
                delivery_attempt_id=tracker_delivery.id,
                status=ExternalChannelDeliveryStatus.DELIVERED,
                provider_message_key=f"tracker-{suffix}",
                error_kind=None,
                error_summary=None,
                completed_at=_at(3),
            )
            assert tracker_delivered is not None
            other_session = await AgentSessionRepository().create(
                verification,
                AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent.id,
                    title=None,
                ),
            )
            other_mailbox_item = RDBMailboxItem(
                session_id=other_session.id,
                kind=MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION,
                scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
                requested_model_target_label=None,
                requested_reasoning_effort=None,
                sender_user_id=None,
                idempotency_key=f"other-activation-{suffix}",
                payload={},
            )
            verification.add(other_mailbox_item)
            await verification.flush()
            assert (
                await repository.activate_session_activation(
                    verification,
                    activation_id=activation.id,
                    mailbox_item_id=other_mailbox_item.id,
                    activated_at=_at(2),
                )
                is None
            )
            activated = await repository.activate_session_activation(
                verification,
                activation_id=activation.id,
                mailbox_item_id=mailbox_item.id,
                activated_at=_at(4),
            )
            await verification.commit()
            assert activated is not None
            assert activated.state is ExternalChannelSessionActivationState.ACTIVATED

        async with AsyncSession(rdb_engine) as verification:
            assert (
                await repository.get_open_session_activation_by_position(
                    verification,
                    conversation_position_id=position.id,
                )
                is None
            )
            await verification.execute(
                sa.delete(RDBMailboxItem).where(RDBMailboxItem.id == mailbox_item.id)
            )
            await verification.commit()

        async with AsyncSession(rdb_engine) as verification:
            consumed = await repository.lock_session_activation(
                verification,
                activation_id=activation.id,
            )
            assert consumed is not None
            assert consumed.state is ExternalChannelSessionActivationState.ACTIVATED
            assert consumed.mailbox_item_id == mailbox_item.id
    finally:
        if workspace_id is not None:
            await _cleanup_committed_workspace(
                rdb_engine,
                workspace_id=workspace_id,
            )


@pytest.mark.parametrize(
    "termination_path",
    ("management", "provider_loss", "provider_uninstall", "activation_block"),
)
async def test_terminal_activation_paths_block_initializing_provider_delivery(
    rdb_session: AsyncSession,
    termination_path: str,
) -> None:
    """Every terminal activation boundary fences its retained provider delivery."""
    suffix = f"{termination_path}-{uuid4().hex[:8]}"
    workspace_id = await _workspace(rdb_session, f"activation-terminal-{suffix}")
    agent = await _agent(rdb_session, workspace_id, f"activation-terminal-{suffix}")
    repository = ExternalChannelRepository()
    work_repository = ExternalChannelWorkRepository()
    connection = await repository.create_connection(
        rdb_session,
        _connection_create(
            workspace_id,
            provider_app_id=f"AT{suffix}",
            provider_tenant_id=f"TT{suffix}",
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
    resource = await _resource(
        rdb_session,
        repository,
        connection_id=connection.id,
        key=f"activation-terminal-{suffix}",
    )
    agent_session = await AgentSessionRepository().create(
        rdb_session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
        ),
    )
    binding = await repository.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=route.id,
            agent_session_id=agent_session.id,
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    position = await repository.create_conversation_position_idempotent(
        rdb_session,
        ExternalChannelConversationPositionCreate(
            connection_id=connection.id,
            scope_kind=ExternalChannelConversationScopeKind.THREAD,
            provider_channel_id=f"C{suffix}",
            provider_thread_key=f"T{suffix}",
            read_through_position=None,
        ),
    )
    mailbox_item = RDBMailboxItem(
        session_id=agent_session.id,
        kind=MailboxItemKind.EXTERNAL_CHANNEL_INVOCATION,
        scheduling_mode=MailboxSchedulingMode.WAKE_SESSION,
        requested_model_target_label=None,
        requested_reasoning_effort=None,
        sender_user_id=None,
        idempotency_key=f"activation-terminal-{suffix}",
        payload={},
    )
    rdb_session.add(mailbox_item)
    await rdb_session.flush()
    activation = await repository.create_session_activation_idempotent(
        rdb_session,
        ExternalChannelSessionActivationCreate(
            connection_id=connection.id,
            conversation_position_id=position.id,
            binding_id=binding.id,
            agent_session_id=agent_session.id,
            trigger_provider_message_key=f"message-{suffix}",
            trigger_position="00000000000000000001",
            range_start_position=None,
            state=ExternalChannelSessionActivationState.INITIALIZING,
            mailbox_item_id=mailbox_item.id,
            failure_kind=None,
            failure_summary=None,
            activated_at=None,
            blocked_at=None,
        ),
    )
    delivery = await repository.create_delivery_attempt_idempotent(
        rdb_session,
        ExternalChannelDeliveryAttemptCreate(
            origin_type=ExternalChannelDeliveryOriginType.MANAGER_OPERATION,
            origin_id=binding.id,
            channel_action_id=None,
            binding_id=binding.id,
            operation=ExternalChannelDeliveryOperation.CONTROL_MESSAGE,
            request_payload={"control_kind": "session_link"},
            status=ExternalChannelDeliveryStatus.PENDING,
            provider_message_key=None,
            error_kind=None,
            error_summary=None,
            attempted_at=None,
            completed_at=None,
        ),
    )
    await repository.create_session_activation_delivery_idempotent(
        rdb_session,
        ExternalChannelSessionActivationDeliveryCreate(
            activation_id=activation.id,
            ordinal=0,
            delivery_attempt_id=delivery.id,
        ),
    )

    if termination_path == "management":
        binding_row = await rdb_session.get(RDBExternalChannelBinding, binding.id)
        resource_row = await rdb_session.get(RDBExternalChannelResource, resource.id)
        assert binding_row is not None
        assert resource_row is not None
        terminate = ExternalChannelManagementRepository()._terminate_binding  # pyright: ignore[reportPrivateUsage]
        await terminate(
            rdb_session,
            binding=binding_row,
            resource=resource_row,
            now=_at(40),
            reason="manager_disconnected",
        )
    elif termination_path == "provider_loss":
        assert await repository.terminate_resource_for_provider_loss(
            rdb_session,
            resource_id=resource.id,
            reason="provider_resource_lost",
            now=_at(40),
        )
    elif termination_path == "provider_uninstall":
        assert (
            await repository.terminate_connection_for_provider_event(
                rdb_session,
                connection_id=connection.id,
                status=ExternalChannelConnectionStatus.DISCONNECTED,
                reason="app_uninstalled",
                now=_at(40),
                required_configuration_generation=None,
                required_socket_lease_owner=None,
                defer_provider_state_purge=True,
            )
            is not None
        )
    else:
        blocked_activation = await repository.block_session_activation(
            rdb_session,
            activation_id=activation.id,
            failure_kind="initial_delivery_unavailable",
            failure_summary=("External Channel initialization became non-recoverable."),
            blocked_at=_at(40),
        )
        assert blocked_activation is not None

    blocked = await repository.lock_session_activation(
        rdb_session,
        activation_id=activation.id,
    )
    assert blocked is not None
    assert blocked.state is ExternalChannelSessionActivationState.BLOCKED
    assert blocked.mailbox_item_id == mailbox_item.id
    assert blocked.failure_kind == (
        "initial_delivery_unavailable"
        if termination_path == "activation_block"
        else "binding_disconnected"
    )
    pending_delivery_ids = (
        await work_repository.list_pending_provider_control_delivery_ids(
            rdb_session,
            limit=20,
        )
    )
    assert delivery.id not in pending_delivery_ids
    assert (
        await work_repository.start_delivery(
            rdb_session,
            delivery_attempt_id=delivery.id,
            now=_at(41),
        )
        is None
    )
    terminal_delivery = await repository.lock_delivery_attempt(
        rdb_session,
        delivery_attempt_id=delivery.id,
    )
    assert terminal_delivery is not None
    assert terminal_delivery.status is ExternalChannelDeliveryStatus.NOT_ATTEMPTED


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


async def test_provider_control_start_follows_lifecycle_lock_order(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Session purge can finish while delivery start waits on connection authority."""
    del latest_db_schema
    suffix = uuid4().hex[:8]
    workspace_id: str | None = None
    start_task: asyncio.Task[object] | None = None
    try:
        async with AsyncSession(rdb_engine, expire_on_commit=False) as setup:
            workspace_id = await _workspace(setup, f"start-lock-{suffix}")
            agent = await _agent(setup, workspace_id, f"start-lock-{suffix}")
            repository = ExternalChannelRepository()
            connection = await repository.create_connection(
                setup,
                _connection_create(
                    workspace_id,
                    provider_app_id=f"AL{suffix}",
                    provider_tenant_id=f"TL{suffix}",
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
                key=f"start-lock-{suffix}",
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
        async with AsyncSession(rdb_engine) as authority_session:
            assert await authority_session.scalar(
                sa.select(RDBExternalChannelConnection)
                .where(RDBExternalChannelConnection.id == connection.id)
                .with_for_update()
            )

            async def start_delivery() -> object:
                async with AsyncSession(rdb_engine) as start_session:
                    result = await work_repository.start_delivery(
                        start_session,
                        delivery_attempt_id=attempt.id,
                        now=_at(2),
                    )
                    await start_session.commit()
                    return result

            start_task = asyncio.create_task(start_delivery())
            await asyncio.sleep(0.1)
            assert not start_task.done()

            async def purge_session() -> ExternalChannelPurgePreparation:
                async with AsyncSession(rdb_engine) as purge_session:
                    assert await purge_session.scalar(
                        sa.select(RDBAgentSession)
                        .where(RDBAgentSession.id == agent_session.id)
                        .with_for_update()
                    )
                    result = await lifecycle_repository.prepare_session_tree_purge(
                        purge_session,
                        session_ids=[agent_session.id],
                        now=_at(3),
                    )
                    await purge_session.commit()
                    return result

            purged = await asyncio.wait_for(purge_session(), timeout=5)
            assert not start_task.done()
            await authority_session.commit()
            started = await asyncio.wait_for(start_task, timeout=5)

        assert purged.not_attempted_delivery_count == 1
        assert started is None
        async with AsyncSession(rdb_engine) as verification:
            stored = await verification.get(
                RDBExternalChannelDeliveryAttempt,
                attempt.id,
            )
            assert stored is not None
            assert stored.status is ExternalChannelDeliveryStatus.NOT_ATTEMPTED
            assert stored.error_kind == "PurgeNotAttempted"
    finally:
        if start_task is not None and not start_task.done():
            start_task.cancel()
            await asyncio.gather(start_task, return_exceptions=True)
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
            disconnected_at=None,
            disconnect_reason=None,
        ),
        expected_access_request_id=None,
    )
    assert terminal_then_active.route_id == second_route.id


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
