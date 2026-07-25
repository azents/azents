"""Phase 1 External Channel App mode repository boundary tests."""

import datetime
import json

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentLifecycleStatus,
    ExternalChannelAppMode,
    ExternalChannelBindingActivationStatus,
    ExternalChannelBindingStatus,
    ExternalChannelChannelDefaultStatus,
    ExternalChannelConnectionStatus,
    ExternalChannelConversationAdmissionOrigin,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelHydrationStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelMessageLifecycle,
    ExternalChannelPrincipalAuthorType,
    ExternalChannelProvider,
    ExternalChannelResourceStatus,
    ExternalChannelResourceType,
    ExternalChannelRouteCatalogStatus,
    ExternalChannelRouteMode,
    ExternalChannelTransport,
    LLMProvider,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.external_channel import (
    RDBExternalChannelAgentRoute,
    RDBExternalChannelBinding,
    RDBExternalChannelChannelDefault,
    RDBExternalChannelConnection,
    RDBExternalChannelConversationAdmission,
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
    ExternalChannelConversationAdmissionCreate,
    ExternalChannelInteractionCreate,
    ExternalChannelMessage,
    ExternalChannelMessageCreate,
    ExternalChannelPrincipalCreate,
    ExternalChannelResource,
    ExternalChannelResourceCreate,
)
from .repository import ExternalChannelRepository, validate_interaction_projection


def _at(minute: int) -> datetime.datetime:
    """Return stable timezone-aware timestamps."""
    return datetime.datetime(2026, 7, 25, 0, minute, tzinfo=datetime.UTC)


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
    provider_app_id: str = "A1",
    provider_tenant_id: str = "T1",
) -> ExternalChannelConnectionCreate:
    """Build a Single-compatible connection writer payload."""
    return ExternalChannelConnectionCreate(
        workspace_id=workspace_id,
        provider=ExternalChannelProvider.SLACK,
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
            hydration_status=ExternalChannelHydrationStatus.PENDING,
            hydration_cursor=None,
            hydration_high_watermark_position=None,
            reconciliation_boundary_received_at=None,
            reconciliation_boundary_event_id=None,
            hydration_error_kind=None,
            hydration_error_summary=None,
            hydration_started_at=None,
            hydration_completed_at=None,
            latest_activity_at=None,
            unavailable_at=None,
            deleted_at=None,
        ),
    )


async def _message(
    session: AsyncSession,
    repo: ExternalChannelRepository,
    *,
    resource_id: str,
    key: str,
) -> ExternalChannelMessage:
    """Create one source message suitable for a conversation admission."""
    return await repo.create_message_idempotent(
        session,
        ExternalChannelMessageCreate(
            resource_id=resource_id,
            provider_message_key=key,
            provider_position="1.000001",
            principal_id=None,
            author_type=ExternalChannelPrincipalAuthorType.HUMAN,
            current_revision_id=None,
            original_url=None,
            lifecycle=ExternalChannelMessageLifecycle.CURRENT,
            pending_size=0,
            provider_created_at=None,
            provider_updated_at=None,
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


def _admission_create(
    *,
    connection_id: str,
    resource_id: str,
    source_message_id: str,
    initiating_principal_id: str | None = None,
    selected_route_id: str | None = None,
    interaction_id: str | None = None,
    status: ExternalChannelConversationAdmissionStatus = (
        ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
    ),
) -> ExternalChannelConversationAdmissionCreate:
    """Build a route-neutral conversation-admission creation payload."""
    return ExternalChannelConversationAdmissionCreate(
        connection_id=connection_id,
        resource_id=resource_id,
        source_message_id=source_message_id,
        initiating_principal_id=initiating_principal_id,
        origin=ExternalChannelConversationAdmissionOrigin.SHORTCUT,
        status=status,
        selected_route_id=selected_route_id,
        interaction_id=interaction_id,
        expires_at=_at(20),
    )


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
            projection={"state": "conflicting-retry"},
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


async def test_conversation_admission_preserves_retries_and_ownership_boundaries(
    rdb_session: AsyncSession,
) -> None:
    """Open conflicts preserve valid retries but reject every foreign owner."""
    workspace_id = await _workspace(rdb_session, "conversation-boundary")
    agent = await _agent(rdb_session, workspace_id, "conversation")
    repo = ExternalChannelRepository()
    first_connection = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id, provider_app_id="A1", provider_tenant_id="T1"),
    )
    second_connection = await repo.create_connection(
        rdb_session,
        _connection_create(workspace_id, provider_app_id="A2", provider_tenant_id="T2"),
    )
    first_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            first_connection.id, agent.id, mode=ExternalChannelAppMode.SINGLE
        ),
    )
    second_route = await repo.create_agent_route(
        rdb_session,
        _route_create(
            second_connection.id, agent.id, mode=ExternalChannelAppMode.SINGLE
        ),
    )
    first_resource = await _resource(
        rdb_session, repo, connection_id=first_connection.id, key="resource-1"
    )
    second_resource = await _resource(
        rdb_session, repo, connection_id=second_connection.id, key="resource-2"
    )
    first_message = await _message(
        rdb_session, repo, resource_id=first_resource.id, key="message-1"
    )
    second_message = await _message(
        rdb_session, repo, resource_id=second_resource.id, key="message-2"
    )
    second_interaction = await repo.admit_interaction(
        rdb_session,
        _interaction_create(second_connection.id, key="interaction-2"),
    )
    first_principal = await repo.create_principal_idempotent(
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
    create = _admission_create(
        connection_id=first_connection.id,
        resource_id=first_resource.id,
        source_message_id=first_message.id,
        initiating_principal_id=first_principal.id,
        selected_route_id=first_route.id,
    )
    first = await repo.create_conversation_admission_idempotent(rdb_session, create)
    retry = await repo.create_conversation_admission_idempotent(
        rdb_session,
        create.model_copy(
            update={
                "origin": ExternalChannelConversationAdmissionOrigin.SINGLE_ROUTE,
                "selected_route_id": None,
            }
        ),
    )
    assert retry.id == first.id
    assert retry.origin is ExternalChannelConversationAdmissionOrigin.SHORTCUT
    assert retry.selected_route_id == first_route.id

    for invalid in (
        _admission_create(
            connection_id=first_connection.id,
            resource_id=second_resource.id,
            source_message_id=second_message.id,
        ),
        _admission_create(
            connection_id=first_connection.id,
            resource_id=first_resource.id,
            source_message_id=second_message.id,
        ),
        _admission_create(
            connection_id=first_connection.id,
            resource_id=first_resource.id,
            source_message_id=first_message.id,
            selected_route_id=second_route.id,
        ),
        _admission_create(
            connection_id=first_connection.id,
            resource_id=first_resource.id,
            source_message_id=first_message.id,
            interaction_id=second_interaction.interaction.id,
        ),
        _admission_create(
            connection_id=first_connection.id,
            resource_id=first_resource.id,
            source_message_id=first_message.id,
            initiating_principal_id=foreign_principal.id,
            selected_route_id=first_route.id,
        ),
    ):
        with pytest.raises(ValueError, match="does not match"):
            await repo.create_conversation_admission_idempotent(rdb_session, invalid)

    await rdb_session.execute(
        sa.update(RDBExternalChannelConversationAdmission)
        .where(RDBExternalChannelConversationAdmission.id == first.id)
        .values(status=ExternalChannelConversationAdmissionStatus.BOUND)
    )
    for offset, status in enumerate(
        (
            ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
            ExternalChannelConversationAdmissionStatus.SELECTED,
            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
        ),
        start=3,
    ):
        resource = await _resource(
            rdb_session,
            repo,
            connection_id=first_connection.id,
            key=f"open-status-{status.value}",
        )
        message = await _message(
            rdb_session,
            repo,
            resource_id=resource.id,
            key=f"open-message-{status.value}",
        )
        open_create = _admission_create(
            connection_id=first_connection.id,
            resource_id=resource.id,
            source_message_id=message.id,
            initiating_principal_id=first_principal.id,
            status=status,
        )
        open_admission = await repo.create_conversation_admission_idempotent(
            rdb_session, open_create
        )
        with pytest.raises(IntegrityError):
            async with rdb_session.begin_nested():
                rdb_session.add(
                    RDBExternalChannelConversationAdmission(
                        connection_id=first_connection.id,
                        resource_id=resource.id,
                        source_message_id=message.id,
                        initiating_principal_id=first_principal.id,
                        origin=ExternalChannelConversationAdmissionOrigin.SHORTCUT,
                        status=status,
                        selected_route_id=None,
                        interaction_id=None,
                        expires_at=_at(20 + offset),
                    )
                )
                await rdb_session.flush()
        open_admission_rdb = await rdb_session.get(
            RDBExternalChannelConversationAdmission,
            open_admission.id,
        )
        assert open_admission_rdb is not None
        open_admission_rdb.status = ExternalChannelConversationAdmissionStatus.BOUND
        await rdb_session.flush()
        later = await repo.create_conversation_admission_idempotent(
            rdb_session,
            open_create.model_copy(
                update={
                    "status": (
                        ExternalChannelConversationAdmissionStatus.PENDING_SELECTION
                    )
                }
            ),
        )
        assert later.id != open_admission.id
        assert (
            await rdb_session.scalar(
                sa.select(sa.func.count())
                .select_from(RDBExternalChannelConversationAdmission)
                .where(
                    RDBExternalChannelConversationAdmission.resource_id == resource.id,
                    RDBExternalChannelConversationAdmission.status.in_(
                        (
                            ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
                            ExternalChannelConversationAdmissionStatus.SELECTED,
                            ExternalChannelConversationAdmissionStatus.AWAITING_ACCESS,
                        )
                    ),
                )
            )
        ) == 1


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
            status=ExternalChannelBindingStatus.ACTIVE,
            activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
            activation_trigger_message_id=None,
            activated_at=None,
            projected_through_position=None,
            truncated_message_count=0,
            truncated_size=0,
            disconnected_at=None,
            disconnect_reason=None,
        ),
    )
    same_resource = await repo.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=second_route.id,
            agent_session_id=second_session.id,
            status=ExternalChannelBindingStatus.ACTIVE,
            activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
            activation_trigger_message_id=None,
            activated_at=None,
            projected_through_position=None,
            truncated_message_count=0,
            truncated_size=0,
            disconnected_at=None,
            disconnect_reason=None,
        ),
    )
    assert same_resource.id == binding.id


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
        status=ExternalChannelBindingStatus.ACTIVE,
        activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
    )
    rdb_session.add(first)
    await rdb_session.flush()

    with pytest.raises(
        IntegrityError, match="uq_external_channel_bindings_active_resource"
    ):
        async with rdb_session.begin_nested():
            rdb_session.add(
                RDBExternalChannelBinding(
                    resource_id=resource.id,
                    route_id=second_route.id,
                    agent_session_id=second_session.id,
                    status=ExternalChannelBindingStatus.ACTIVE,
                    activation_status=(
                        ExternalChannelBindingActivationStatus.WAITING_HYDRATION
                    ),
                )
            )
            await rdb_session.flush()

    first.status = ExternalChannelBindingStatus.DISCONNECTED
    first.disconnected_at = _at(30)
    await rdb_session.flush()
    terminal_then_active = await repo.create_binding_idempotent(
        rdb_session,
        ExternalChannelBindingCreate(
            resource_id=resource.id,
            route_id=second_route.id,
            agent_session_id=second_session.id,
            status=ExternalChannelBindingStatus.ACTIVE,
            activation_status=ExternalChannelBindingActivationStatus.WAITING_HYDRATION,
            activation_trigger_message_id=None,
            activated_at=None,
            projected_through_position=None,
            truncated_message_count=0,
            truncated_size=0,
            disconnected_at=None,
            disconnect_reason=None,
        ),
    )
    assert terminal_then_active.route_id == second_route.id
