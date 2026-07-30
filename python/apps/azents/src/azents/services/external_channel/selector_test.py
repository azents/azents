"""Multi App selector catalog and immutable selection tests."""

import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    ExternalChannelAppMode,
    ExternalChannelConversationAdmissionStatus,
    ExternalChannelPrincipalAuthorType,
)
from azents.rdb.session import SessionManager
from azents.repos.external_channel.data import (
    ExternalChannelAgentRoute,
    ExternalChannelBinding,
    ExternalChannelCatalogRoute,
    ExternalChannelConnection,
    ExternalChannelConversationAdmission,
    ExternalChannelPrincipal,
)
from azents.repos.external_channel.repository import ExternalChannelRepository
from azents.services.external_channel.selector import (
    ExternalChannelSelectorCandidate,
    ExternalChannelSelectorService,
)

_NOW = datetime.datetime(2026, 7, 25, tzinfo=datetime.UTC)


class _Session:
    """Record the selector transaction completion boundary."""

    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        """Record the durable selection commit."""
        self.committed = True


def _connection() -> ExternalChannelConnection:
    """Build the fields consumed by selector catalog checks."""
    return ExternalChannelConnection.model_construct(
        id="connection-1",
        app_mode=ExternalChannelAppMode.MULTI,
    )


def _route(
    route_id: str,
    agent_id: str,
    *,
    allow_bot_messages: bool = False,
) -> ExternalChannelAgentRoute:
    """Build one active selector route."""
    return ExternalChannelAgentRoute.model_construct(
        id=route_id,
        connection_id="connection-1",
        agent_id=agent_id,
        allow_bot_messages=allow_bot_messages,
    )


def _admission(
    *,
    selected_route_id: str | None = None,
) -> ExternalChannelConversationAdmission:
    """Build one current pending selector admission."""
    return ExternalChannelConversationAdmission.model_construct(
        id="admission-1",
        connection_id="connection-1",
        resource_id="resource-1",
        initiating_principal_id="principal-1",
        status=ExternalChannelConversationAdmissionStatus.PENDING_SELECTION,
        selected_route_id=selected_route_id,
        expires_at=_NOW + datetime.timedelta(minutes=10),
    )


class _Repository:
    """In-memory selector state that records trusted operation ordering."""

    def __init__(
        self,
        *,
        rows: list[ExternalChannelCatalogRoute],
        binding: ExternalChannelBinding | None = None,
    ) -> None:
        self.rows = rows
        self.binding = binding
        self.admission = _admission()
        self.calls: list[str] = []
        self.transitions: list[
            tuple[ExternalChannelConversationAdmissionStatus, str | None]
        ] = []
        self.catalog_queries: list[
            tuple[
                str,
                ExternalChannelPrincipalAuthorType,
                str | None,
                int,
                int,
            ]
        ] = []
        self.blocked_agents: set[str] = set()
        self.granted_agents: set[str] = set()
        self.author_type = ExternalChannelPrincipalAuthorType.HUMAN

    async def get_conversation_admission(
        self,
        session: AsyncSession,
        *,
        admission_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        del session
        self.calls.append("admission_snapshot")
        return self.admission if admission_id == self.admission.id else None

    async def get_connection(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        del session
        self.calls.append("connection_snapshot")
        return _connection() if connection_id == "connection-1" else None

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
        self.catalog_queries.append((principal_id, author_type, search, offset, limit))
        filtered = (
            self.rows
            if search is None
            else [row for row in self.rows if search.lower() in row.agent_name.lower()]
        )
        if author_type is ExternalChannelPrincipalAuthorType.BOT:
            filtered = [row for row in filtered if row.route.allow_bot_messages]
        filtered = [
            row
            for row in filtered
            if row.route.require_active_agent_id() not in self.blocked_agents
        ]
        return filtered[offset : offset + limit]

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

    async def get_active_access_grant(
        self,
        session: AsyncSession,
        *,
        agent_id: str,
        principal_id: str,
        agent_session_id: str | None,
    ) -> object | None:
        del session
        self.calls.append("grant")
        assert principal_id == "principal-1"
        assert agent_session_id is None
        return object() if agent_id in self.granted_agents else None

    async def lock_connection_for_routing(
        self,
        session: AsyncSession,
        *,
        connection_id: str,
    ) -> ExternalChannelConnection | None:
        del session
        self.calls.append("connection_lock")
        return _connection() if connection_id == "connection-1" else None

    async def get_routable_route_by_id(
        self,
        session: AsyncSession,
        *,
        route_id: str,
    ) -> ExternalChannelAgentRoute | None:
        del session
        self.calls.append("route_lock")
        for row in self.rows:
            if row.route.id == route_id:
                return row.route
        return None

    async def lock_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> object | None:
        del session
        self.calls.append("resource_lock")
        return (
            type(
                "Resource", (), {"id": "resource-1", "connection_id": "connection-1"}
            )()
            if resource_id == "resource-1"
            else None
        )

    async def lock_active_binding_by_resource(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelBinding | None:
        del session
        self.calls.append("binding_lock")
        assert resource_id == "resource-1"
        return self.binding

    async def lock_open_conversation_admission(
        self,
        session: AsyncSession,
        *,
        resource_id: str,
    ) -> ExternalChannelConversationAdmission | None:
        del session
        self.calls.append("admission_lock")
        return self.admission if resource_id == "resource-1" else None

    async def transition_conversation_admission(
        self,
        session: AsyncSession,
        *,
        admission_id: str,
        status: ExternalChannelConversationAdmissionStatus,
        selected_route_id: str | None,
    ) -> ExternalChannelConversationAdmission | None:
        del session
        self.calls.append("admission_transition")
        assert admission_id == self.admission.id
        self.transitions.append((status, selected_route_id))
        self.admission = self.admission.model_copy(
            update={"status": status, "selected_route_id": selected_route_id}
        )
        return self.admission


def _service(
    session: _Session,
    repository: _Repository,
) -> ExternalChannelSelectorService:
    """Build selector service with a one-transaction in-memory boundary."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        yield cast(AsyncSession, session)

    return ExternalChannelSelectorService(
        session_manager=cast(SessionManager[AsyncSession], session_manager),
        repository=cast(ExternalChannelRepository, repository),
    )


@pytest.mark.asyncio
async def test_catalog_excludes_blocks_and_labels_current_access() -> None:
    """Only current non-blocked routes are projected with current access state."""
    session = _Session()
    rows = [
        ExternalChannelCatalogRoute(route=_route("route-1", "agent-1"), agent_name="A"),
        ExternalChannelCatalogRoute(route=_route("route-2", "agent-2"), agent_name="B"),
        ExternalChannelCatalogRoute(route=_route("route-3", "agent-3"), agent_name="C"),
    ]
    repository = _Repository(rows=rows)
    repository.granted_agents.add("agent-1")
    repository.blocked_agents.add("agent-2")

    catalog = await _service(session, repository).project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=0,
        now=_NOW,
    )

    assert catalog.candidates == (
        ExternalChannelSelectorCandidate(
            route_id="route-1",
            agent_name="A",
            access="available",
        ),
        ExternalChannelSelectorCandidate(
            route_id="route-3",
            agent_name="C",
            access="access_required",
        ),
    )
    assert catalog.next_offset is None
    assert session.committed is False


@pytest.mark.asyncio
async def test_catalog_search_and_paging_are_bounded_and_deterministic() -> None:
    """Catalog pages preserve repository order and expose the next offset."""
    session = _Session()
    rows = [
        ExternalChannelCatalogRoute(
            route=_route(f"route-{index:02}", f"agent-{index:02}"),
            agent_name=f"Agent {index:02}",
        )
        for index in range(21)
    ]
    repository = _Repository(rows=rows)
    service = _service(session, repository)

    first_page = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=0,
        now=_NOW,
    )
    second_page = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=20,
        now=_NOW,
    )
    searched = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search="Agent 20",
        offset=0,
        now=_NOW,
    )

    assert [candidate.route_id for candidate in first_page.candidates] == [
        f"route-{index:02}" for index in range(20)
    ]
    assert first_page.next_offset == 20
    assert [candidate.route_id for candidate in second_page.candidates] == ["route-20"]
    assert second_page.next_offset is None
    assert [candidate.route_id for candidate in searched.candidates] == ["route-20"]
    assert repository.catalog_queries == [
        ("principal-1", ExternalChannelPrincipalAuthorType.HUMAN, None, 0, 21),
        ("principal-1", ExternalChannelPrincipalAuthorType.HUMAN, None, 20, 21),
        (
            "principal-1",
            ExternalChannelPrincipalAuthorType.HUMAN,
            "Agent 20",
            0,
            21,
        ),
    ]


@pytest.mark.asyncio
async def test_bot_catalog_and_selection_require_bot_enabled_routes() -> None:
    """Bot selectors expose and accept only routes that explicitly allow bots."""
    session = _Session()
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"),
                agent_name="Human only",
            ),
            ExternalChannelCatalogRoute(
                route=_route(
                    "route-2",
                    "agent-2",
                    allow_bot_messages=True,
                ),
                agent_name="Bot enabled",
            ),
        ]
    )
    repository.author_type = ExternalChannelPrincipalAuthorType.BOT
    service = _service(session, repository)

    catalog = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=0,
        now=_NOW,
    )

    assert [candidate.route_id for candidate in catalog.candidates] == ["route-2"]
    with pytest.raises(ValueError, match="Selected Agent is unavailable"):
        await service.select_route(
            admission_id="admission-1",
            principal_id="principal-1",
            route_id="route-1",
            now=_NOW,
        )


@pytest.mark.asyncio
async def test_catalog_paginates_after_block_filtering() -> None:
    """Blocked routes cannot consume visible page slots or offsets."""
    session = _Session()
    rows = [
        ExternalChannelCatalogRoute(
            route=_route(f"route-{index:02}", f"agent-{index:02}"),
            agent_name=f"Agent {index:02}",
        )
        for index in range(45)
    ]
    repository = _Repository(rows=rows)
    repository.blocked_agents.update(f"agent-{index:02}" for index in range(20))
    service = _service(session, repository)

    first_page = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=0,
        now=_NOW,
    )
    second_page = await service.project_catalog(
        admission_id="admission-1",
        principal_id="principal-1",
        search=None,
        offset=20,
        now=_NOW,
    )

    assert [candidate.route_id for candidate in first_page.candidates] == [
        f"route-{index:02}" for index in range(20, 40)
    ]
    assert first_page.next_offset == 20
    assert [candidate.route_id for candidate in second_page.candidates] == [
        f"route-{index:02}" for index in range(40, 45)
    ]
    assert second_page.next_offset is None


@pytest.mark.asyncio
async def test_catalog_rejects_expired_admission_before_query() -> None:
    """Expired selector admission cannot expose a stale Agent catalog."""
    session = _Session()
    repository = _Repository(rows=[])
    repository.admission = repository.admission.model_copy(
        update={"expires_at": _NOW - datetime.timedelta(seconds=1)}
    )

    with pytest.raises(ValueError, match="admission is unavailable"):
        await _service(session, repository).project_catalog(
            admission_id="admission-1",
            principal_id="principal-1",
            search=None,
            offset=0,
            now=_NOW,
        )

    assert repository.catalog_queries == []


@pytest.mark.asyncio
async def test_selection_uses_required_lock_order_and_is_immutable() -> None:
    """Selection locks durable owners before recording one route exactly once."""
    session = _Session()
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"),
                agent_name="A",
            )
        ]
    )

    selected = await _service(session, repository).select_route(
        admission_id="admission-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )

    assert selected.status == "selected"
    assert selected.admission.selected_route_id == "route-1"
    assert repository.transitions == [
        (ExternalChannelConversationAdmissionStatus.SELECTED, "route-1")
    ]
    assert repository.calls == [
        "admission_snapshot",
        "connection_lock",
        "route_lock",
        "principal",
        "resource_lock",
        "binding_lock",
        "admission_lock",
        "block",
        "admission_transition",
    ]
    assert session.committed is True


@pytest.mark.asyncio
async def test_existing_binding_is_a_non_mutating_selector_winner() -> None:
    """A selector cannot move a resource with an established binding."""
    session = _Session()
    binding = ExternalChannelBinding.model_construct(id="binding-1", route_id="route-2")
    repository = _Repository(
        rows=[
            ExternalChannelCatalogRoute(
                route=_route("route-1", "agent-1"),
                agent_name="A",
            )
        ],
        binding=binding,
    )

    selected = await _service(session, repository).select_route(
        admission_id="admission-1",
        principal_id="principal-1",
        route_id="route-1",
        now=_NOW,
    )

    assert selected.status == "already_bound"
    assert selected.binding is binding
    assert repository.transitions == []
    assert session.committed is True
