"""Completed authorized Session History operations for Engine tools."""

import dataclasses
import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
)
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSession
from azents.repos.message import MessageRepository
from azents.repos.session_history.repository import (
    VISIBLE_KINDS,
    EventSearchHit,
    SearchPage,
    SessionHistoryRepository,
    SessionHistoryScope,
    SessionSearchHit,
)
from azents.repos.workspace_user import WorkspaceUserRepository


class SessionHistoryUnavailableError(Exception):
    """Requested Session History is outside the authorized active scope."""


class _EventLike(Protocol):
    """Event fields detached by the completed History repository."""

    @property
    def id(self) -> str: ...

    @property
    def session_id(self) -> str: ...

    @property
    def kind(self) -> EventKind: ...

    @property
    def payload(self) -> object: ...

    @property
    def created_at(self) -> datetime.datetime: ...


@dataclasses.dataclass(frozen=True)
class SessionHistoryEvent:
    """Detached visible Event fields used by History tool rendering."""

    id: str
    session_id: str
    kind: EventKind
    payload: object
    created_at: datetime.datetime
    reverted: bool


@dataclasses.dataclass(frozen=True)
class SessionHistoryEventPage:
    """Authorized bounded visible Event page."""

    session_id: str
    items: list[SessionHistoryEvent]
    has_older: bool
    has_newer: bool


@dataclasses.dataclass(frozen=True)
class SessionHistoryToolEvent:
    """Authorized selected Event for tool-result text projection."""

    session_id: str
    event: SessionHistoryEvent


@dataclasses.dataclass(frozen=True)
class SessionHistoryScopedSearch:
    """Authorized within-Session search results."""

    session_id: str
    page: SearchPage[EventSearchHit]


@dataclasses.dataclass(frozen=True)
class _ActiveSessionRoot:
    """Concrete Session and its active privacy root."""

    concrete: AgentSession
    root: AgentSession


@dataclasses.dataclass
class SessionHistoryOperationRepository:
    """Own completed Session History authority and read operations."""

    session_manager: SessionManager[AsyncSession]
    agent_session_repository: AgentSessionRepository
    workspace_user_repository: WorkspaceUserRepository
    history_repository: SessionHistoryRepository
    message_repository: MessageRepository

    async def search_in_session(
        self,
        *,
        agent_id: str,
        current_session_id: str,
        target_session_id: str,
        query: str,
        limit: int,
        before: str | None,
    ) -> SessionHistoryScopedSearch:
        """Authorize and search one Session in a completed transaction."""
        async with self.session_manager() as session:
            scope = await self._source_scope(
                session,
                current_session_id=current_session_id,
                agent_id=agent_id,
            )
            target = await self._target(
                session,
                session_id=target_session_id,
                scope=scope,
            )
            page = await self.history_repository.search_events(
                session,
                session_id=target.id,
                query=query,
                limit=limit,
                before=before,
            )
            return SessionHistoryScopedSearch(session_id=target.id, page=page)

    async def search_roots(
        self,
        *,
        agent_id: str,
        current_session_id: str,
        query: str,
        limit: int,
        before: tuple[datetime.datetime, str] | None,
    ) -> SearchPage[SessionSearchHit]:
        """Authorize and search visible root Sessions in one transaction."""
        async with self.session_manager() as session:
            scope = await self._source_scope(
                session,
                current_session_id=current_session_id,
                agent_id=agent_id,
            )
            return await self.history_repository.search_roots(
                session,
                scope=scope,
                query=query,
                limit=limit,
                before=before,
            )

    async def read_history(
        self,
        *,
        agent_id: str,
        current_session_id: str,
        target_session_id: str,
        limit: int,
        before: str | None,
        after: str | None,
        around_event_id: str | None,
    ) -> SessionHistoryEventPage:
        """Authorize and read one visible Event page in a completed transaction."""
        async with self.session_manager() as session:
            scope = await self._source_scope(
                session,
                current_session_id=current_session_id,
                agent_id=agent_id,
            )
            target = await self._target(
                session,
                session_id=target_session_id,
                scope=scope,
            )
            if around_event_id is not None:
                anchor = await self.message_repository.get_by_id(
                    session,
                    around_event_id,
                )
                if (
                    anchor is None
                    or anchor.session_id != target.id
                    or anchor.reverted
                    or anchor.kind not in VISIBLE_KINDS
                ):
                    raise SessionHistoryUnavailableError
            page = await self.message_repository.list_events_by_session_id_paginated(
                session,
                target.id,
                limit=limit,
                before=before,
                after=after,
                around=around_event_id,
                visible_kinds=VISIBLE_KINDS,
            )
            return SessionHistoryEventPage(
                session_id=target.id,
                items=[self._event(event, reverted=False) for event in page.items],
                has_older=page.has_more,
                has_newer=page.has_newer,
            )

    async def read_tool_event(
        self,
        *,
        agent_id: str,
        current_session_id: str,
        target_session_id: str,
        event_id: str,
    ) -> SessionHistoryToolEvent:
        """Authorize and read one selected Event in a completed transaction."""
        async with self.session_manager() as session:
            scope = await self._source_scope(
                session,
                current_session_id=current_session_id,
                agent_id=agent_id,
            )
            target = await self._target(
                session,
                session_id=target_session_id,
                scope=scope,
            )
            event = await self.message_repository.get_by_id(session, event_id)
            if event is None or event.session_id != target.id or event.reverted:
                raise SessionHistoryUnavailableError
            return SessionHistoryToolEvent(
                session_id=target.id,
                event=self._event(event, reverted=event.reverted),
            )

    async def _source_scope(
        self,
        session: AsyncSession,
        *,
        current_session_id: str,
        agent_id: str,
    ) -> SessionHistoryScope:
        """Bind History authority to the current execution root."""
        root = (await self._active_root(session, current_session_id)).root
        if root.agent_id != agent_id:
            raise SessionHistoryUnavailableError
        if root.product_mode is AgentSessionProductMode.TEAM:
            owner = None
        elif root.product_mode is AgentSessionProductMode.USER:
            owner = root.associated_user_id
            if (
                owner is None
                or await self.workspace_user_repository.get_by_workspace_and_user(
                    session,
                    workspace_id=root.workspace_id,
                    user_id=owner,
                )
                is None
            ):
                raise SessionHistoryUnavailableError
        else:
            raise SessionHistoryUnavailableError
        return SessionHistoryScope(
            agent_id=agent_id,
            workspace_id=root.workspace_id,
            associated_user_id=owner,
        )

    async def _target(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        scope: SessionHistoryScope,
    ) -> AgentSession:
        """Authorize one target independently of previous search results."""
        binding = await self._active_root(session, session_id)
        concrete, root = binding.concrete, binding.root
        if root.agent_id != scope.agent_id or root.workspace_id != scope.workspace_id:
            raise SessionHistoryUnavailableError
        if root.product_mode is AgentSessionProductMode.TEAM:
            return concrete
        if (
            root.product_mode is AgentSessionProductMode.USER
            and scope.associated_user_id is not None
            and root.associated_user_id == scope.associated_user_id
        ):
            return concrete
        raise SessionHistoryUnavailableError

    async def _active_root(
        self,
        session: AsyncSession,
        session_id: str,
    ) -> _ActiveSessionRoot:
        """Resolve one concrete active Session and its privacy root."""
        concrete = await self.agent_session_repository.get_by_id(session, session_id)
        if concrete is None or concrete.status is not AgentSessionStatus.ACTIVE:
            raise SessionHistoryUnavailableError
        if concrete.session_kind is AgentSessionKind.ROOT:
            return _ActiveSessionRoot(concrete=concrete, root=concrete)
        if concrete.session_kind is not AgentSessionKind.SUBAGENT:
            raise SessionHistoryUnavailableError
        root_agent = (
            await self.agent_session_repository.get_root_session_agent_by_session_id(
                session,
                session_id,
            )
        )
        if root_agent is None:
            raise SessionHistoryUnavailableError
        root = await self.agent_session_repository.get_by_id(
            session,
            root_agent.agent_session_id,
        )
        if (
            root is None
            or root.session_kind is not AgentSessionKind.ROOT
            or root.status is not AgentSessionStatus.ACTIVE
            or root.agent_id != concrete.agent_id
            or root.workspace_id != concrete.workspace_id
        ):
            raise SessionHistoryUnavailableError
        return _ActiveSessionRoot(concrete=concrete, root=root)

    @staticmethod
    def _event(event: _EventLike, *, reverted: bool) -> SessionHistoryEvent:
        """Detach the Event fields consumed by History rendering."""
        return SessionHistoryEvent(
            id=event.id,
            session_id=event.session_id,
            kind=event.kind,
            payload=event.payload,
            created_at=event.created_at,
            reverted=reverted,
        )
