"""Multi App selector interaction-state tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConnectionStatus,
    ExternalChannelInteractionStatus,
    ExternalChannelInteractionType,
    ExternalChannelPrincipalAuthorType,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelCatalogRoute,
    ExternalChannelConnection,
    ExternalChannelInteraction,
    ExternalChannelPrincipal,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorError,
    ExternalChannelSelectorService,
)
from azents.services.external_channel.selector_state import (
    ExternalChannelSelectorState,
    projection_with_selector_state,
    selector_state_from_interaction,
)

_NOW = datetime.datetime(2026, 7, 31, tzinfo=datetime.UTC)


class _Session:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


def _route(route_id: str, agent_id: str) -> ExternalChannelAgentRoute:
    return ExternalChannelAgentRoute.model_construct(
        id=route_id,
        connection_id="connection-1",
        agent_id=agent_id,
    )


def _selector(
    *,
    selected_route_id: str | None = None,
    expires_at: datetime.datetime | None = None,
) -> ExternalChannelInteraction:
    state = ExternalChannelSelectorState(
        connection_id="connection-1",
        resource_id="resource-1",
        principal_id="principal-1",
        conversation_position_id="position-1",
        trigger_provider_message_key="slack:T-1:C-1:100.0001",
        range_start_position=None,
        trigger_position="100.0001",
        selected_route_id=selected_route_id,
    )
    return ExternalChannelInteraction.model_construct(
        id="selector-1",
        connection_id="connection-1",
        interaction_type=ExternalChannelInteractionType.MANAGEMENT_ACTION,
        principal_id="principal-1",
        projection=projection_with_selector_state({}, state),
        status=ExternalChannelInteractionStatus.ACCEPTED,
        expires_at=expires_at or _NOW + datetime.timedelta(minutes=10),
    )


class _Repository:
    def __init__(
        self,
        *,
        rows: list[ExternalChannelCatalogRoute],
        binding: ExternalChannelBinding | None = None,
        connection_status: ExternalChannelConnectionStatus = (
            ExternalChannelConnectionStatus.ACTIVE
        ),
    ) -> None:
        self.rows = rows
        self.binding = binding
        self.selector = _selector()
        self.calls: list[str] = []
        self.catalog_queries: list[tuple[str | None, int, int]] = []
        self.granted_agents: set[str] = set()
        self.blocked_agents: set[str] = set()
        self.author_type = ExternalChannelPrincipalAuthorType.HUMAN
        self.connection_status = connection_status

    async def lock_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
    ) -> ExternalChannelInteraction | None:
        del session
        self.calls.append("interaction_lock")
        return self.selector if interaction_id == self.selector.id else None

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        del session
        self.calls.append("connection_snapshot")
        if connection_id != "connection-1":
            return None
        return ExternalChannelConnection.model_construct(
            id="connection-1",
            app_mode=ExternalChannelAppMode.MULTI,
            status=self.connection_status,
        )

    async def get_principal(
        self,
        session: AsyncSession,
        *,
        principal_id: str,
    ) -> ExternalChannelPrincipal | None:
        del session
        self.calls.append("principal")
        if principal_id != "principal-1":
            return None
        return ExternalChannelPrincipal.model_construct(
            id=principal_id,
            author_type=self.author_type,
        )

    async def list_routable_multi_catalog_routes(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
        principal_id: str,
        author_type: ExternalChannelPrincipalAuthorType,
        search: str | None,
        offset: int,
        limit: int,
    ) -> list[ExternalChannelCatalogRoute]:
        del session
        self.calls.append("catalog")
        assert connection_id == "connection-1"
        assert principal_id == "principal-1"
        assert author_type is ExternalChannelPrincipalAuthorType.HUMAN
        self.catalog_queries.append((search, offset, limit))
        rows = [
            row
            for row in self.rows
            if row.route.require_active_agent_id() not in self.blocked_agents
            and (search is None or search.lower() in row.agent_name.lower())
        ]
        return rows[offset : offset + limit]

    async def get_active_access_grant(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
        agent_session_id: str | None,
    ) -> object | None:
        del session
        assert principal_id == "principal-1"
        assert agent_session_id is None
        return object() if agent_id in self.granted_agents else None

    async def lock_connection_for_routing(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        return await self.get_connection(session, connection_id=connection_id)

    async def get_routable_route_by_id(
        self,
        session: AsyncSession,
        *,
        route_id: str,
    ) -> ExternalChannelAgentRoute | None:
        del session
        self.calls.append("route_lock")
        return next((row.route for row in self.rows if row.route.id == route_id), None)

    async def lock_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> object | None:
        del session
        self.calls.append("resource_lock")
        if resource_id != "resource-1":
            return None
        return type(
            "Resource",
            (),
            {"id": "resource-1", "connection_id": "connection-1"},
        )()

    async def lock_connected_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        del session
        self.calls.append("binding_lock")
        assert resource_id == "resource-1"
        return self.binding

    async def get_active_block(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
    ) -> object | None:
        del session
        self.calls.append("block")
        assert principal_id == "principal-1"
        return object() if agent_id in self.blocked_agents else None

    async def replace_interaction_projection(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        projection: dict[str, object],
    ) -> ExternalChannelInteraction | None:
        del session
        self.calls.append("projection_replace")
        if interaction_id != self.selector.id:
            return None
        self.selector = self.selector.model_copy(update={"projection": projection})
        return self.selector

    async def transition_interaction(
        self,
        session: AsyncSession,
        *,
        interaction_id: str,
        status: ExternalChannelInteractionStatus,
        error_kind: str | None,
        error_summary: str | None,
        transitioned_at: datetime.datetime,
    ) -> ExternalChannelInteraction | None:
        del session, error_kind, error_summary, transitioned_at
        self.calls.append("interaction_transition")
        if interaction_id != self.selector.id:
            return None
        self.selector = self.selector.model_copy(update={"status": status})
        return self.selector


def _service(
    session: _Session, repository: _Repository
) -> ExternalChannelSelectorService:
    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return ExternalChannelSelectorService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    )


@pytest.mark.asyncio
async def test_catalog_uses_interaction_state_and_labels_access() -> None:
    session = _Session()
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"), agent_name="Alpha"
            ),
            ExternalChannelCatalogRoute(
                route=_route("route-2", "agent-2"), agent_name="Beta"
            ),
        ]
    )
    repository.granted_agents.add("agent-1")
    repository.blocked_agents.add("agent-2")

    catalog = await _service(session, repository).project_catalog(
        selector_interaction_id="selector-1",
        principal_id="principal-1",
        search=None,
        offset=0,
        now=_NOW,
    )

    assert catalog.candidates == (
        ExternalChannelSelectorCandidate(
            route_id="route-1",
            agent_name="Alpha",
            access="available",
        ),
    )
    assert catalog.next_offset is None
    assert repository.catalog_queries == [(None, 0, 21)]
    assert session.committed is False


@pytest.mark.asyncio
async def test_selection_replaces_only_typed_interaction_projection() -> None:
    session = _Session()
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"), agent_name="Alpha"
            ),
            ExternalChannelCatalogRoute(
                route=_route("route-2", "agent-2"), agent_name="Beta"
            ),
        ]
    )

    selection = await _service(session, repository).select_route(
        selector_interaction_id="selector-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )

    assert selection.status == "selected"
    assert (
        selector_state_from_interaction(
            selection.selector_interaction
        ).selected_route_id
        == "route-1"
    )
    assert "projection_replace" in repository.calls
    assert session.committed is True

    repeated = await _service(_Session(), repository).select_route(
        selector_interaction_id="selector-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )
    assert repeated.status == "already_selected"

    with pytest.raises(ExternalChannelSelectorError, match="immutable"):
        await _service(_Session(), repository).select_route(
            selector_interaction_id="selector-1",
            principal_id="principal-1",
            route_id="route-2",
            now=_NOW,
        )


@pytest.mark.asyncio
async def test_existing_binding_wins_without_selector_mutation() -> None:
    session = _Session()
    binding = ExternalChannelBinding.model_construct(id="binding-1", route_id="route-2")
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"), agent_name="Alpha"
            )
        ],
        binding=binding,
    )

    selection = await _service(session, repository).select_route(
        selector_interaction_id="selector-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )

    assert selection.status == "already_bound"
    assert selection.binding is binding
    assert "projection_replace" not in repository.calls


@pytest.mark.asyncio
async def test_expired_interaction_is_terminalized_before_selection() -> None:
    session = _Session()
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"), agent_name="Alpha"
            )
        ]
    )
    repository.selector = _selector(expires_at=_NOW - datetime.timedelta(seconds=1))

    selection = await _service(session, repository).select_route(
        selector_interaction_id="selector-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )

    assert selection.status == "expired"
    assert (
        selection.selector_interaction.status
        is ExternalChannelInteractionStatus.EXPIRED
    )
    assert "interaction_transition" in repository.calls
    assert "projection_replace" not in repository.calls


@pytest.mark.asyncio
async def test_catalog_rejects_cross_principal_interaction() -> None:
    repository = _Repository(rows=[])

    with pytest.raises(ExternalChannelSelectorError, match="unavailable"):
        await _service(_Session(), repository).project_catalog(
            selector_interaction_id="selector-1",
            principal_id="principal-2",
            search=None,
            offset=0,
            now=_NOW,
        )

    assert repository.catalog_queries == []


@pytest.mark.asyncio
async def test_catalog_rejects_connection_without_routing_authority() -> None:
    """Catalog projection cannot race past connection routing shutdown."""
    repository = _Repository(
        rows=[],
        connection_status=ExternalChannelConnectionStatus.RECONNECT_REQUIRED,
    )

    with pytest.raises(ExternalChannelSelectorError, match="unavailable"):
        await _service(_Session(), repository).project_catalog(
            selector_interaction_id="selector-1",
            principal_id="principal-1",
            search=None,
            offset=0,
            now=_NOW,
        )

    assert repository.catalog_queries == []
