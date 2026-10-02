"""Bounded PostgreSQL queries for the live read-only Memory VFS."""

import dataclasses
import datetime
from collections.abc import Sequence
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from azents.core.enums import (
    AgentSessionKind,
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
)
from azents.engine.events.action_messages import ActionMessagePayload
from azents.engine.events.output_parts import iter_output_parts
from azents.engine.events.types import (
    AgentMessagePayload,
    AssistantMessagePayload,
    ClientToolCallPayload,
    ClientToolResultPayload,
    Event,
    ExternalChannelMessagePayload,
    OutputTextPart,
    ProviderToolCallPayload,
    UserMessagePayload,
    upgrade_persisted_client_tool_payload,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import JSONValue, RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.memory_vfs.data import (
    HistoricalMemoryVfsRecord,
    MemoryVfsAuthority,
    MemoryVfsRecordPage,
    MemoryVfsUriPage,
    MemoryVfsUriQuery,
    SavedMemoryVfsRecord,
    SourceEventVfsRecord,
    SourceSessionVfsRecord,
    ToolResultVfsRecord,
)

_VISIBLE_EVENT_KINDS = (
    EventKind.USER_MESSAGE,
    EventKind.ACTION_MESSAGE,
    EventKind.EXTERNAL_CHANNEL_MESSAGE,
    EventKind.ASSISTANT_MESSAGE,
    EventKind.AGENT_MESSAGE,
    EventKind.CLIENT_TOOL_CALL,
    EventKind.CLIENT_TOOL_RESULT,
    EventKind.PROVIDER_TOOL_CALL,
)
_TOOL_RESULT_KINDS = (
    EventKind.CLIENT_TOOL_RESULT,
    EventKind.PROVIDER_TOOL_CALL,
)


@dataclasses.dataclass(frozen=True)
class _EventCandidate:
    """One bounded event candidate before batched result pairing."""

    scope: Literal["team", "user"]
    event: Event
    previous_event_id: str | None
    next_event_id: str | None


@dataclasses.dataclass(frozen=True)
class _QueryBudget:
    """Deterministic SQL row and per-row byte bounds for one query."""

    row_limit: int
    per_row_bytes: int
    limit_truncated: bool


@dataclasses.dataclass
class MemoryVfsRepository:
    """Own bounded SQL and current authorization for the Memory VFS."""

    session_manager: Annotated[
        SessionManager[AsyncSession],
        Depends(get_session_manager),
    ]

    async def authorized(self, authority: MemoryVfsAuthority) -> bool:
        """Return whether the current root authority may use the Memory mount."""
        if not authority.memory_enabled:
            return False
        async with self.session_manager() as session:
            return (
                await session.scalar(
                    sa.select(sa.literal(True)).where(self._agent_gate(authority))
                )
                is True
            )

    async def get_saved(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["agent", "user"],
        memory_id: str,
        max_bytes: int,
    ) -> SavedMemoryVfsRecord | None:
        """Return one currently visible size-bounded Saved Memory row."""
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return None
        async with self.session_manager() as session:
            statement = sa.select(
                RDBAgentMemory.id,
                RDBAgentMemory.user_id,
                RDBAgentMemory.type,
                RDBAgentMemory.name,
                RDBAgentMemory.description,
                RDBAgentMemory.content,
                RDBAgentMemory.created_at,
                RDBAgentMemory.updated_at,
            ).where(
                self._agent_gate(authority),
                RDBAgentMemory.id == memory_id,
                RDBAgentMemory.agent_id == authority.agent_id,
                self._text_byte_size(
                    RDBAgentMemory.type,
                    RDBAgentMemory.name,
                    RDBAgentMemory.description,
                    RDBAgentMemory.content,
                )
                <= max_bytes,
            )
            if scope == "agent":
                statement = statement.where(RDBAgentMemory.user_id.is_(None))
            elif authority.associated_user_id is not None:
                statement = statement.where(
                    RDBAgentMemory.user_id == authority.associated_user_id,
                    self._consumer_membership(authority),
                )
            else:
                return None
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return SavedMemoryVfsRecord(
            memory_id=row.id,
            scope="agent" if row.user_id is None else "user",
            memory_type=row.type,
            name=row.name,
            description=row.description,
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_saved(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["agent", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        """Return a row- and byte-bounded Saved Memory grep page."""
        self._require_limit(limit)
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        budget = self._query_budget(limit=limit, max_bytes=max_bytes)
        scope_filter = RDBAgentMemory.user_id.is_(None)
        if "user" in scopes and authority.associated_user_id is not None:
            user_filter = sa.and_(
                RDBAgentMemory.user_id == authority.associated_user_id,
                self._consumer_membership(authority),
            )
            scope_filter = (
                sa.or_(scope_filter, user_filter) if "agent" in scopes else user_filter
            )
        elif "agent" not in scopes:
            return MemoryVfsRecordPage((), False)
        fits = (
            self._text_byte_size(
                RDBAgentMemory.type,
                RDBAgentMemory.name,
                RDBAgentMemory.description,
                RDBAgentMemory.content,
            )
            <= budget.per_row_bytes
        )
        async with self.session_manager() as session:
            rows = list(
                (
                    await session.execute(
                        sa.select(
                            RDBAgentMemory.id,
                            RDBAgentMemory.user_id,
                            sa.case((fits, RDBAgentMemory.type), else_=None).label(
                                "type"
                            ),
                            sa.case((fits, RDBAgentMemory.name), else_=None).label(
                                "name"
                            ),
                            sa.case(
                                (fits, RDBAgentMemory.description),
                                else_=None,
                            ).label("description"),
                            sa.case((fits, RDBAgentMemory.content), else_=None).label(
                                "content"
                            ),
                            RDBAgentMemory.created_at,
                            RDBAgentMemory.updated_at,
                            fits.label("fits"),
                        )
                        .where(
                            self._agent_gate(authority),
                            RDBAgentMemory.agent_id == authority.agent_id,
                            scope_filter,
                        )
                        .order_by(
                            RDBAgentMemory.user_id.is_not(None),
                            RDBAgentMemory.id,
                        )
                        .limit(budget.row_limit)
                    )
                ).all()
            )
        records = tuple(
            SavedMemoryVfsRecord(
                memory_id=row.id,
                scope="agent" if row.user_id is None else "user",
                memory_type=row.type,
                name=row.name,
                description=row.description,
                content=row.content,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows[:limit]
            if row.fits
            and row.type is not None
            and row.name is not None
            and row.description is not None
            and row.content is not None
        )
        return MemoryVfsRecordPage(
            records,
            budget.limit_truncated
            or len(rows) > limit
            or len(records) < min(len(rows), limit),
        )

    async def get_historical(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        source_session_id: str,
        max_bytes: int,
    ) -> HistoricalMemoryVfsRecord | None:
        """Return one visible size-bounded Historical summary."""
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return None
        scope_filter = self._source_scope_filter(authority, (scope,))
        if scope_filter is None:
            return None
        statement = (
            sa.select(
                RDBHistoricalMemorySource.source_session_id,
                RDBAgentSession.product_mode,
                RDBAgentSession.title,
                RDBHistoricalMemorySource.completed_source_activity_at,
                RDBHistoricalMemorySource.prepared_at,
                RDBHistoricalMemorySource.summary,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBHistoricalMemorySource.source_session_id == source_session_id,
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
                RDBHistoricalMemorySource.prepared_at.is_not(None),
                RDBHistoricalMemorySource.completed_source_activity_at.is_not(None),
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
                self._text_byte_size(
                    RDBAgentSession.title,
                    RDBHistoricalMemorySource.summary,
                )
                <= max_bytes,
            )
        )
        async with self.session_manager() as session:
            row = (await session.execute(statement)).one_or_none()
        if row is None:
            return None
        return HistoricalMemoryVfsRecord(
            source_session_id=row.source_session_id,
            scope=self._scope(row.product_mode),
            source_title=row.title,
            source_activity_through=row.completed_source_activity_at,
            prepared_at=row.prepared_at,
            summary=row.summary,
        )

    async def list_historical(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        """Return row- and byte-bounded visible Historical summaries."""
        return await self._historical_query(
            authority,
            scopes=scopes,
            source_session_id=None,
            limit=limit,
            max_bytes=max_bytes,
        )

    async def get_source(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        max_bytes: int,
    ) -> SourceSessionVfsRecord | None:
        """Return one currently visible root source Session."""
        page = await self._source_query(
            authority,
            scopes=(scope,),
            session_id=session_id,
            limit=1,
            max_bytes=max_bytes,
        )
        record = page.records[0] if page.records else None
        return record if isinstance(record, SourceSessionVfsRecord) else None

    async def list_sources(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        """Return row- and byte-bounded visible root source Sessions."""
        return await self._source_query(
            authority,
            scopes=scopes,
            session_id=None,
            limit=limit,
            max_bytes=max_bytes,
        )

    async def get_event(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        event_id: str,
        max_bytes: int,
    ) -> SourceEventVfsRecord | None:
        """Return one currently visible event with adjacent visible paths."""
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return None
        async with self.session_manager() as session:
            if not await self._source_visible(
                session,
                authority,
                scope=scope,
                session_id=session_id,
            ):
                return None
            row = (
                await session.execute(
                    self._event_select().where(
                        RDBEvent.id == event_id,
                        RDBEvent.session_id == session_id,
                        RDBEvent.reverted.is_(False),
                        RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
                        self._event_byte_size() <= max_bytes,
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            previous_id = await session.scalar(
                sa.select(RDBEvent.id)
                .where(
                    RDBEvent.session_id == session_id,
                    RDBEvent.id < event_id,
                    RDBEvent.reverted.is_(False),
                    RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
                )
                .order_by(RDBEvent.id.desc())
                .limit(1)
            )
            next_id = await session.scalar(
                sa.select(RDBEvent.id)
                .where(
                    RDBEvent.session_id == session_id,
                    RDBEvent.id > event_id,
                    RDBEvent.reverted.is_(False),
                    RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
                )
                .order_by(RDBEvent.id)
                .limit(1)
            )
            event = self._event_from_values(
                id=row.id,
                session_id=row.session_id,
                kind=row.kind,
                payload=row.payload,
                external_id=row.external_id,
                adapter=row.adapter,
                provider=row.provider,
                model=row.model,
                native_format=row.native_format,
                schema_version=row.schema_version,
                created_at=row.created_at,
            )
            paired_result: Event | None = None
            if isinstance(event.payload, ClientToolCallPayload):
                remaining_bytes = max_bytes - row.payload_bytes
                if remaining_bytes < 1:
                    remaining_bytes = 1
                result_row = (
                    await session.execute(
                        self._event_select()
                        .where(
                            RDBEvent.session_id == session_id,
                            RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                            RDBEvent.reverted.is_(False),
                            RDBEvent.payload["call_id"].as_string()
                            == event.payload.call_id,
                            self._event_byte_size() <= remaining_bytes,
                        )
                        .order_by(RDBEvent.id)
                        .limit(1)
                    )
                ).one_or_none()
                if result_row is not None:
                    paired_result = self._event_from_values(
                        id=result_row.id,
                        session_id=result_row.session_id,
                        kind=result_row.kind,
                        payload=result_row.payload,
                        external_id=result_row.external_id,
                        adapter=result_row.adapter,
                        provider=result_row.provider,
                        model=result_row.model,
                        native_format=result_row.native_format,
                        schema_version=result_row.schema_version,
                        created_at=result_row.created_at,
                    )
        return SourceEventVfsRecord(
            scope=scope,
            event=event,
            previous_event_id=previous_id,
            next_event_id=next_id,
            paired_client_result=paired_result,
        )

    async def list_events(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        limit: int,
    ) -> MemoryVfsRecordPage:
        """Return bounded visible source events in canonical order."""
        self._require_limit(limit)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        async with self.session_manager() as session:
            if not await self._source_visible(
                session,
                authority,
                scope=scope,
                session_id=session_id,
            ):
                return MemoryVfsRecordPage((), False)
            rows = list(
                (
                    await session.execute(
                        sa.select(RDBEvent)
                        .where(
                            RDBEvent.session_id == session_id,
                            RDBEvent.reverted.is_(False),
                            RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
                        )
                        .order_by(RDBEvent.id)
                        .limit(limit + 1)
                    )
                ).scalars()
            )
            events = [self._event(row) for row in rows[:limit]]
            call_ids = {
                event.payload.call_id
                for event in events
                if isinstance(event.payload, ClientToolCallPayload)
            }
            result_rows: list[RDBEvent] = []
            if call_ids:
                result_rows = list(
                    (
                        await session.execute(
                            sa.select(RDBEvent).where(
                                RDBEvent.session_id == session_id,
                                RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                                RDBEvent.reverted.is_(False),
                                RDBEvent.payload["call_id"].as_string().in_(call_ids),
                            )
                        )
                    ).scalars()
                )
        results_by_call: dict[str, Event] = {}
        for result_row in result_rows:
            result_event = self._event(result_row)
            if isinstance(result_event.payload, ClientToolResultPayload):
                results_by_call[result_event.payload.call_id] = result_event
        records = tuple(
            SourceEventVfsRecord(
                scope=scope,
                event=event,
                previous_event_id=(rows[index - 1].id if index > 0 else None),
                next_event_id=(rows[index + 1].id if index + 1 < len(rows) else None),
                paired_client_result=(
                    results_by_call.get(event.payload.call_id)
                    if isinstance(event.payload, ClientToolCallPayload)
                    else None
                ),
            )
            for index, event in enumerate(events)
        )
        return MemoryVfsRecordPage(records, len(rows) > limit)

    async def list_event_candidates(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        session_id: str | None,
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        """Return globally bounded grep events with one batched result query."""
        self._require_limit(limit)
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsRecordPage((), False)
        candidate_bytes = (max_bytes + 1) // 2
        result_bytes = max_bytes // 2
        candidate_budget = self._query_budget(
            limit=limit,
            max_bytes=candidate_bytes,
        )
        event_fits = self._event_byte_size() <= candidate_budget.per_row_bytes
        statement = (
            sa.select(
                RDBEvent.id,
                RDBEvent.session_id,
                RDBEvent.kind,
                sa.case((event_fits, RDBEvent.payload), else_=None).label("payload"),
                sa.case((event_fits, RDBEvent.external_id), else_=None).label(
                    "external_id"
                ),
                sa.case((event_fits, RDBEvent.adapter), else_=None).label("adapter"),
                sa.case((event_fits, RDBEvent.provider), else_=None).label("provider"),
                sa.case((event_fits, RDBEvent.model), else_=None).label("model"),
                sa.case((event_fits, RDBEvent.native_format), else_=None).label(
                    "native_format"
                ),
                RDBEvent.schema_version,
                RDBEvent.created_at,
                RDBAgentSession.product_mode,
                sa.func.lag(RDBEvent.id)
                .over(
                    partition_by=RDBEvent.session_id,
                    order_by=RDBEvent.id,
                )
                .label("previous_id"),
                sa.func.lead(RDBEvent.id)
                .over(
                    partition_by=RDBEvent.session_id,
                    order_by=RDBEvent.id,
                )
                .label("next_id"),
                event_fits.label("fits"),
            )
            .join(RDBAgentSession, RDBAgentSession.id == RDBEvent.session_id)
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBEvent.reverted.is_(False),
                RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
            )
            .order_by(RDBEvent.session_id, RDBEvent.id)
            .limit(candidate_budget.row_limit)
        )
        if session_id is not None:
            statement = statement.where(RDBEvent.session_id == session_id)
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
            candidate_events: list[_EventCandidate] = []
            oversized = False
            for row in rows[:limit]:
                if not row.fits or row.payload is None:
                    oversized = True
                    continue
                candidate_events.append(
                    _EventCandidate(
                        scope=self._scope(row.product_mode),
                        event=self._event_from_values(
                            id=row.id,
                            session_id=row.session_id,
                            kind=row.kind,
                            payload=row.payload,
                            external_id=row.external_id,
                            adapter=row.adapter,
                            provider=row.provider,
                            model=row.model,
                            native_format=row.native_format,
                            schema_version=row.schema_version,
                            created_at=row.created_at,
                        ),
                        previous_event_id=row.previous_id,
                        next_event_id=row.next_id,
                    )
                )
            call_pairs = {
                (candidate.event.session_id, candidate.event.payload.call_id)
                for candidate in candidate_events
                if isinstance(candidate.event.payload, ClientToolCallPayload)
            }
            result_rows = []
            result_budget: _QueryBudget | None = None
            if call_pairs and result_bytes < 1:
                oversized = True
            elif call_pairs:
                result_budget = self._query_budget(
                    limit=len(call_pairs),
                    max_bytes=result_bytes,
                )
                result_fits = self._event_byte_size() <= result_budget.per_row_bytes
                pair_filter = sa.or_(
                    *(
                        sa.and_(
                            RDBEvent.session_id == pair_session_id,
                            RDBEvent.payload["call_id"].as_string() == call_id,
                        )
                        for pair_session_id, call_id in call_pairs
                    )
                )
                result_statement = (
                    sa.select(
                        RDBEvent.id,
                        RDBEvent.session_id,
                        RDBEvent.kind,
                        sa.case(
                            (result_fits, RDBEvent.payload),
                            else_=None,
                        ).label("payload"),
                        sa.case(
                            (result_fits, RDBEvent.external_id),
                            else_=None,
                        ).label("external_id"),
                        sa.case(
                            (result_fits, RDBEvent.adapter),
                            else_=None,
                        ).label("adapter"),
                        sa.case(
                            (result_fits, RDBEvent.provider),
                            else_=None,
                        ).label("provider"),
                        sa.case(
                            (result_fits, RDBEvent.model),
                            else_=None,
                        ).label("model"),
                        sa.case(
                            (result_fits, RDBEvent.native_format),
                            else_=None,
                        ).label("native_format"),
                        RDBEvent.schema_version,
                        RDBEvent.created_at,
                        result_fits.label("fits"),
                    )
                    .join(
                        RDBAgentSession,
                        RDBAgentSession.id == RDBEvent.session_id,
                    )
                    .where(
                        self._agent_gate(authority),
                        RDBEvent.kind == EventKind.CLIENT_TOOL_RESULT,
                        RDBEvent.reverted.is_(False),
                        RDBAgentSession.agent_id == authority.agent_id,
                        RDBAgentSession.workspace_id == authority.workspace_id,
                        RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                        RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                        scope_filter,
                        pair_filter,
                    )
                    .order_by(RDBEvent.session_id, RDBEvent.id)
                    .limit(result_budget.row_limit)
                )
                result_rows = list((await session.execute(result_statement)).all())
        results_by_call: dict[tuple[str, str], Event] = {}
        for row in result_rows[: len(call_pairs)]:
            if not row.fits or row.payload is None:
                oversized = True
                continue
            result_event = self._event_from_values(
                id=row.id,
                session_id=row.session_id,
                kind=row.kind,
                payload=row.payload,
                external_id=row.external_id,
                adapter=row.adapter,
                provider=row.provider,
                model=row.model,
                native_format=row.native_format,
                schema_version=row.schema_version,
                created_at=row.created_at,
            )
            if isinstance(result_event.payload, ClientToolResultPayload):
                results_by_call[
                    (result_event.session_id, result_event.payload.call_id)
                ] = result_event
        records = tuple(
            SourceEventVfsRecord(
                scope=candidate.scope,
                event=candidate.event,
                previous_event_id=candidate.previous_event_id,
                next_event_id=candidate.next_event_id,
                paired_client_result=(
                    results_by_call.get(
                        (
                            candidate.event.session_id,
                            candidate.event.payload.call_id,
                        )
                    )
                    if isinstance(
                        candidate.event.payload,
                        ClientToolCallPayload,
                    )
                    else None
                ),
            )
            for candidate in candidate_events
        )
        return MemoryVfsRecordPage(
            records,
            candidate_budget.limit_truncated
            or len(rows) > limit
            or (
                result_budget is not None
                and (
                    result_budget.limit_truncated or len(result_rows) > len(call_pairs)
                )
            )
            or oversized,
        )

    async def get_tool_result(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        event_id: str,
        max_bytes: int,
    ) -> ToolResultVfsRecord | None:
        """Return one authorized persisted textual tool result."""
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return None
        async with self.session_manager() as session:
            if not await self._source_visible(
                session,
                authority,
                scope=scope,
                session_id=session_id,
            ):
                return None
            row = (
                await session.execute(
                    self._event_select().where(
                        RDBEvent.id == event_id,
                        RDBEvent.session_id == session_id,
                        RDBEvent.reverted.is_(False),
                        RDBEvent.kind.in_(_TOOL_RESULT_KINDS),
                        self._event_byte_size() <= max_bytes,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        event = self._event_from_values(
            id=row.id,
            session_id=row.session_id,
            kind=row.kind,
            payload=row.payload,
            external_id=row.external_id,
            adapter=row.adapter,
            provider=row.provider,
            model=row.model,
            native_format=row.native_format,
            schema_version=row.schema_version,
            created_at=row.created_at,
        )
        return self._tool_result(scope, event)

    async def list_tool_results(
        self,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
        limit: int,
    ) -> MemoryVfsRecordPage:
        """Return bounded exact-result paths without broad body search."""
        self._require_limit(limit)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        async with self.session_manager() as session:
            if not await self._source_visible(
                session,
                authority,
                scope=scope,
                session_id=session_id,
            ):
                return MemoryVfsRecordPage((), False)
            rows = list(
                (
                    await session.execute(
                        sa.select(RDBEvent)
                        .where(
                            RDBEvent.session_id == session_id,
                            RDBEvent.reverted.is_(False),
                            RDBEvent.kind.in_(_TOOL_RESULT_KINDS),
                        )
                        .order_by(RDBEvent.id)
                        .limit(limit + 1)
                    )
                ).scalars()
            )
        records = tuple(
            record
            for row in rows[:limit]
            if (record := self._tool_result(scope, self._event(row))) is not None
        )
        return MemoryVfsRecordPage(records, len(rows) > limit)

    async def list_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        query: MemoryVfsUriQuery,
        limit: int,
    ) -> MemoryVfsUriPage:
        """Return a globally bounded body-free URI inventory."""
        self._require_limit(limit)
        if not await self.authorized(authority):
            return MemoryVfsUriPage((), False)
        uris = ["azents://memory/README.md"] if query.include_readme else []
        has_more = False
        if query.namespace in {"all", "saved"}:
            if remaining := limit - len(uris):
                page = await self._list_saved_uris(
                    authority,
                    scopes=query.saved_scopes,
                    limit=remaining,
                )
                uris.extend(page.uris)
                has_more = has_more or page.has_more
            else:
                has_more = True
        if query.namespace in {"all", "historical"}:
            if remaining := limit - len(uris):
                page = await self._list_historical_uris(
                    authority,
                    scopes=query.source_scopes,
                    source_session_id=query.session_id,
                    limit=remaining,
                )
                uris.extend(page.uris)
                has_more = has_more or page.has_more
            else:
                has_more = True
        if query.namespace in {"all", "sources"}:
            if "session" in query.source_file_kinds:
                if remaining := limit - len(uris):
                    page = await self._list_source_session_uris(
                        authority,
                        scopes=query.source_scopes,
                        session_id=query.session_id,
                        limit=remaining,
                    )
                    uris.extend(page.uris)
                    has_more = has_more or page.has_more
                else:
                    has_more = True
            if "events" in query.source_file_kinds:
                if remaining := limit - len(uris):
                    page = await self._list_event_uris(
                        authority,
                        scopes=query.source_scopes,
                        session_id=query.session_id,
                        kinds=_VISIBLE_EVENT_KINDS,
                        directory="events",
                        suffix=".md",
                        limit=remaining,
                    )
                    uris.extend(page.uris)
                    has_more = has_more or page.has_more
                else:
                    has_more = True
            if "tool-results" in query.source_file_kinds:
                if remaining := limit - len(uris):
                    page = await self._list_event_uris(
                        authority,
                        scopes=query.source_scopes,
                        session_id=query.session_id,
                        kinds=_TOOL_RESULT_KINDS,
                        directory="tool-results",
                        suffix=".txt",
                        limit=remaining,
                    )
                    uris.extend(page.uris)
                    has_more = has_more or page.has_more
                else:
                    has_more = True
        return MemoryVfsUriPage(tuple(sorted(set(uris))), has_more)

    async def _list_saved_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["agent", "user"]],
        limit: int,
    ) -> MemoryVfsUriPage:
        """Return body-free Saved Memory identifiers and scopes."""
        scope_filter = RDBAgentMemory.user_id.is_(None)
        if "user" in scopes and authority.associated_user_id is not None:
            user_filter = sa.and_(
                RDBAgentMemory.user_id == authority.associated_user_id,
                self._consumer_membership(authority),
            )
            scope_filter = (
                sa.or_(scope_filter, user_filter) if "agent" in scopes else user_filter
            )
        elif "agent" not in scopes:
            return MemoryVfsUriPage((), False)
        async with self.session_manager() as session:
            rows = list(
                (
                    await session.execute(
                        sa.select(
                            RDBAgentMemory.id,
                            RDBAgentMemory.user_id,
                        )
                        .where(
                            self._agent_gate(authority),
                            RDBAgentMemory.agent_id == authority.agent_id,
                            scope_filter,
                        )
                        .order_by(
                            RDBAgentMemory.user_id.is_not(None),
                            RDBAgentMemory.id,
                        )
                        .limit(limit + 1)
                    )
                ).all()
            )
        return MemoryVfsUriPage(
            tuple(
                "azents://memory/saved/"
                f"{'agent' if row.user_id is None else 'user'}/{row.id}.md"
                for row in rows[:limit]
            ),
            len(rows) > limit,
        )

    async def _list_historical_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        source_session_id: str | None,
        limit: int,
    ) -> MemoryVfsUriPage:
        """Return body-free Historical source identifiers and scopes."""
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsUriPage((), False)
        statement = (
            sa.select(
                RDBHistoricalMemorySource.source_session_id,
                RDBAgentSession.product_mode,
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
                RDBHistoricalMemorySource.prepared_at.is_not(None),
                RDBHistoricalMemorySource.completed_source_activity_at.is_not(None),
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
            )
            .order_by(RDBHistoricalMemorySource.source_session_id)
            .limit(limit + 1)
        )
        if source_session_id is not None:
            statement = statement.where(
                RDBHistoricalMemorySource.source_session_id == source_session_id
            )
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
        return MemoryVfsUriPage(
            tuple(
                "azents://memory/historical/"
                f"{self._scope(row.product_mode)}/{row.source_session_id}/summary.md"
                for row in rows[:limit]
            ),
            len(rows) > limit,
        )

    async def _list_source_session_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        session_id: str | None,
        limit: int,
    ) -> MemoryVfsUriPage:
        """Return body-free source Session identifiers and scopes."""
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsUriPage((), False)
        statement = (
            sa.select(
                RDBAgentSession.id,
                RDBAgentSession.product_mode,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
            )
            .order_by(RDBAgentSession.id)
            .limit(limit + 1)
        )
        if session_id is not None:
            statement = statement.where(RDBAgentSession.id == session_id)
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
        return MemoryVfsUriPage(
            tuple(
                "azents://memory/sources/"
                f"{self._scope(row.product_mode)}/{row.id}/session.md"
                for row in rows[:limit]
            ),
            len(rows) > limit,
        )

    async def _list_event_uris(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        session_id: str | None,
        kinds: Sequence[EventKind],
        directory: Literal["events", "tool-results"],
        suffix: Literal[".md", ".txt"],
        limit: int,
    ) -> MemoryVfsUriPage:
        """Return one globally bounded visible source-event URI page."""
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsUriPage((), False)
        async with self.session_manager() as session:
            statement = (
                sa.select(
                    RDBEvent.id,
                    RDBEvent.session_id,
                    RDBAgentSession.product_mode,
                )
                .join(
                    RDBAgentSession,
                    RDBAgentSession.id == RDBEvent.session_id,
                )
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .where(
                    self._agent_gate(authority),
                    RDBEvent.reverted.is_(False),
                    RDBEvent.kind.in_(kinds),
                    RDBAgentSession.agent_id == authority.agent_id,
                    RDBAgentSession.workspace_id == authority.workspace_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgent.id == authority.agent_id,
                    RDBAgent.workspace_id == authority.workspace_id,
                    RDBAgent.memory_enabled.is_(True),
                    scope_filter,
                )
                .order_by(RDBEvent.session_id, RDBEvent.id)
                .limit(limit + 1)
            )
            if session_id is not None:
                statement = statement.where(RDBEvent.session_id == session_id)
            rows = list((await session.execute(statement)).all())
        return MemoryVfsUriPage(
            tuple(
                f"azents://memory/sources/{self._scope(product_mode)}/"
                f"{session_id}/{directory}/{event_id}{suffix}"
                for event_id, session_id, product_mode in rows[:limit]
            ),
            len(rows) > limit,
        )

    async def _historical_query(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        source_session_id: str | None,
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        self._require_limit(limit)
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        budget = self._query_budget(limit=limit, max_bytes=max_bytes)
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsRecordPage((), False)
        fits = (
            self._text_byte_size(
                RDBAgentSession.title,
                RDBHistoricalMemorySource.summary,
            )
            <= budget.per_row_bytes
        )
        statement = (
            sa.select(
                RDBHistoricalMemorySource.source_session_id,
                RDBAgentSession.product_mode,
                sa.case((fits, RDBAgentSession.title), else_=None).label("title"),
                RDBHistoricalMemorySource.completed_source_activity_at,
                RDBHistoricalMemorySource.prepared_at,
                sa.case(
                    (fits, RDBHistoricalMemorySource.summary),
                    else_=None,
                ).label("summary"),
                fits.label("fits"),
            )
            .join(
                RDBAgentSession,
                RDBAgentSession.id == RDBHistoricalMemorySource.source_session_id,
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
                RDBHistoricalMemorySource.prepared_at.is_not(None),
                RDBHistoricalMemorySource.completed_source_activity_at.is_not(None),
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
            )
            .order_by(RDBHistoricalMemorySource.source_session_id)
            .limit(budget.row_limit)
        )
        if source_session_id is not None:
            statement = statement.where(
                RDBHistoricalMemorySource.source_session_id == source_session_id
            )
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
        records = tuple(
            HistoricalMemoryVfsRecord(
                source_session_id=row.source_session_id,
                scope=self._scope(row.product_mode),
                source_title=row.title,
                source_activity_through=row.completed_source_activity_at,
                prepared_at=row.prepared_at,
                summary=row.summary,
            )
            for row in rows[:limit]
            if row.fits and row.summary is not None
        )
        return MemoryVfsRecordPage(
            records,
            budget.limit_truncated
            or len(rows) > limit
            or len(records) < min(len(rows), limit),
        )

    async def _source_query(
        self,
        authority: MemoryVfsAuthority,
        *,
        scopes: Sequence[Literal["team", "user"]],
        session_id: str | None,
        limit: int,
        max_bytes: int,
    ) -> MemoryVfsRecordPage:
        self._require_limit(limit)
        self._require_max_bytes(max_bytes)
        if not authority.memory_enabled:
            return MemoryVfsRecordPage((), False)
        budget = self._query_budget(
            limit=limit,
            max_bytes=max_bytes,
            unique=session_id is not None,
        )
        scope_filter = self._source_scope_filter(authority, scopes)
        if scope_filter is None:
            return MemoryVfsRecordPage((), False)
        latest_event = (
            sa.select(sa.func.max(RDBEvent.id))
            .where(
                RDBEvent.session_id == RDBAgentSession.id,
                RDBEvent.reverted.is_(False),
                RDBEvent.kind.in_(_VISIBLE_EVENT_KINDS),
            )
            .correlate(RDBAgentSession)
            .scalar_subquery()
        )
        summary_exists = sa.exists(
            sa.select(RDBHistoricalMemorySource.source_session_id).where(
                RDBHistoricalMemorySource.source_session_id == RDBAgentSession.id,
                RDBHistoricalMemorySource.summary.is_not(None),
                RDBHistoricalMemorySource.summary != "",
            )
        )
        fits = (
            self._text_byte_size(
                RDBAgentSession.title,
                RDBAgentSession.handle,
            )
            <= budget.per_row_bytes
        )
        statement = (
            sa.select(
                RDBAgentSession.id,
                RDBAgentSession.product_mode,
                sa.case((fits, RDBAgentSession.title), else_=None).label("title"),
                sa.case((fits, RDBAgentSession.handle), else_=None).label("handle"),
                RDBAgentSession.last_activity_at,
                latest_event.label("latest_event_id"),
                summary_exists.label("summary_available"),
                fits.label("fits"),
            )
            .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
            .where(
                self._agent_gate(authority),
                RDBAgentSession.agent_id == authority.agent_id,
                RDBAgentSession.workspace_id == authority.workspace_id,
                RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                RDBAgent.id == authority.agent_id,
                RDBAgent.workspace_id == authority.workspace_id,
                RDBAgent.memory_enabled.is_(True),
                scope_filter,
            )
            .order_by(RDBAgentSession.id)
            .limit(budget.row_limit)
        )
        if session_id is not None:
            statement = statement.where(RDBAgentSession.id == session_id)
        async with self.session_manager() as session:
            rows = list((await session.execute(statement)).all())
        records = tuple(
            SourceSessionVfsRecord(
                session_id=row.id,
                scope=self._scope(row.product_mode),
                title=row.title,
                handle=row.handle,
                last_activity_at=row.last_activity_at,
                latest_visible_event_id=row.latest_event_id,
                summary_available=row.summary_available,
            )
            for row in rows[:limit]
            if row.fits and row.handle is not None
        )
        return MemoryVfsRecordPage(
            records,
            budget.limit_truncated
            or len(rows) > limit
            or len(records) < min(len(rows), limit),
        )

    async def _source_visible(
        self,
        session: AsyncSession,
        authority: MemoryVfsAuthority,
        *,
        scope: Literal["team", "user"],
        session_id: str,
    ) -> bool:
        scope_filter = self._source_scope_filter(authority, (scope,))
        if scope_filter is None:
            return False
        return (
            await session.scalar(
                sa.select(sa.literal(True))
                .select_from(RDBAgentSession)
                .join(RDBAgent, RDBAgent.id == RDBAgentSession.agent_id)
                .where(
                    self._agent_gate(authority),
                    RDBAgentSession.id == session_id,
                    RDBAgentSession.agent_id == authority.agent_id,
                    RDBAgentSession.workspace_id == authority.workspace_id,
                    RDBAgentSession.session_kind == AgentSessionKind.ROOT,
                    RDBAgentSession.status == AgentSessionStatus.ACTIVE,
                    RDBAgent.id == authority.agent_id,
                    RDBAgent.workspace_id == authority.workspace_id,
                    RDBAgent.memory_enabled.is_(True),
                    scope_filter,
                )
            )
            is True
        )

    @staticmethod
    def _text_byte_size(
        *columns: InstrumentedAttribute[str] | InstrumentedAttribute[str | None],
    ) -> sa.ColumnElement[int]:
        sizes = [
            sa.func.octet_length(sa.func.coalesce(column, "")) for column in columns
        ]
        total = sizes[0]
        for size in sizes[1:]:
            total = total + size
        return total

    @classmethod
    def _event_byte_size(cls) -> sa.ColumnElement[int]:
        return cls._text_byte_size(
            RDBEvent.external_id,
            RDBEvent.adapter,
            RDBEvent.provider,
            RDBEvent.model,
            RDBEvent.native_format,
        ) + sa.func.octet_length(sa.cast(RDBEvent.payload, sa.Text))

    @classmethod
    def _event_select(
        cls,
    ) -> sa.Select[
        tuple[
            str,
            str,
            EventKind,
            dict[str, JSONValue],
            str | None,
            str | None,
            str | None,
            str | None,
            str | None,
            str,
            datetime.datetime,
            int,
        ]
    ]:
        return sa.select(
            RDBEvent.id,
            RDBEvent.session_id,
            RDBEvent.kind,
            RDBEvent.payload,
            RDBEvent.external_id,
            RDBEvent.adapter,
            RDBEvent.provider,
            RDBEvent.model,
            RDBEvent.native_format,
            RDBEvent.schema_version,
            RDBEvent.created_at,
            cls._event_byte_size().label("payload_bytes"),
        )

    @staticmethod
    def _event_from_values(
        *,
        id: str,
        session_id: str,
        kind: EventKind,
        payload: dict[str, JSONValue],
        external_id: str | None,
        adapter: str | None,
        provider: str | None,
        model: str | None,
        native_format: str | None,
        schema_version: str,
        created_at: datetime.datetime,
    ) -> Event:
        typed_payload: object
        match kind:
            case EventKind.USER_MESSAGE:
                typed_payload = UserMessagePayload.model_validate(payload)
            case EventKind.ACTION_MESSAGE:
                typed_payload = ActionMessagePayload.model_validate(payload)
            case EventKind.EXTERNAL_CHANNEL_MESSAGE:
                typed_payload = ExternalChannelMessagePayload.model_validate(payload)
            case EventKind.ASSISTANT_MESSAGE:
                typed_payload = AssistantMessagePayload.model_validate(payload)
            case EventKind.AGENT_MESSAGE:
                typed_payload = AgentMessagePayload.model_validate(payload)
            case EventKind.CLIENT_TOOL_CALL:
                typed_payload = ClientToolCallPayload.model_validate(
                    upgrade_persisted_client_tool_payload(kind, payload)
                )
            case EventKind.CLIENT_TOOL_RESULT:
                typed_payload = ClientToolResultPayload.model_validate(
                    upgrade_persisted_client_tool_payload(kind, payload)
                )
            case EventKind.PROVIDER_TOOL_CALL:
                typed_payload = ProviderToolCallPayload.model_validate(payload)
            case _:
                raise ValueError("Unsupported Memory VFS event kind")
        return Event(
            id=id,
            session_id=session_id,
            kind=kind,
            payload=typed_payload,
            external_id=external_id,
            adapter=adapter,
            provider=provider,
            model=model,
            native_format=native_format,
            schema_version=schema_version,
            created_at=created_at,
        )

    @staticmethod
    def _agent_gate(authority: MemoryVfsAuthority) -> sa.ColumnElement[bool]:
        root_session = aliased(RDBAgentSession)
        agent = aliased(RDBAgent)
        if authority.associated_user_id is None:
            consumer_gate = sa.and_(
                root_session.product_mode == AgentSessionProductMode.TEAM,
                root_session.associated_user_id.is_(None),
            )
        else:
            consumer_gate = sa.and_(
                root_session.product_mode == AgentSessionProductMode.USER,
                root_session.associated_user_id == authority.associated_user_id,
                MemoryVfsRepository._consumer_membership(authority),
            )
        return sa.exists(
            sa.select(root_session.id)
            .join(agent, agent.id == root_session.agent_id)
            .where(
                root_session.id == authority.root_session_id,
                root_session.agent_id == authority.agent_id,
                root_session.workspace_id == authority.workspace_id,
                root_session.session_kind == AgentSessionKind.ROOT,
                root_session.status == AgentSessionStatus.ACTIVE,
                agent.id == authority.agent_id,
                agent.workspace_id == authority.workspace_id,
                agent.memory_enabled.is_(True),
                consumer_gate,
            )
        )

    @staticmethod
    def _consumer_membership(
        authority: MemoryVfsAuthority,
    ) -> sa.ColumnElement[bool]:
        if authority.associated_user_id is None:
            return sa.false()
        return sa.exists(
            sa.select(RDBWorkspaceUser.id).where(
                RDBWorkspaceUser.workspace_id == authority.workspace_id,
                RDBWorkspaceUser.user_id == authority.associated_user_id,
            )
        )

    @classmethod
    def _source_scope_filter(
        cls,
        authority: MemoryVfsAuthority,
        scopes: Sequence[Literal["team", "user"]],
    ) -> sa.ColumnElement[bool] | None:
        filters: list[sa.ColumnElement[bool]] = []
        if "team" in scopes:
            filters.append(RDBAgentSession.product_mode == AgentSessionProductMode.TEAM)
        if "user" in scopes and authority.associated_user_id is not None:
            filters.append(
                sa.and_(
                    RDBAgentSession.product_mode == AgentSessionProductMode.USER,
                    RDBAgentSession.associated_user_id == authority.associated_user_id,
                    cls._consumer_membership(authority),
                )
            )
        return sa.or_(*filters) if filters else None

    @staticmethod
    def _scope(mode: AgentSessionProductMode | None) -> Literal["team", "user"]:
        if mode is AgentSessionProductMode.TEAM:
            return "team"
        if mode is AgentSessionProductMode.USER:
            return "user"
        raise ValueError("Memory VFS source is not a root product Session")

    @staticmethod
    def _saved(row: RDBAgentMemory) -> SavedMemoryVfsRecord:
        return SavedMemoryVfsRecord(
            memory_id=row.id,
            scope="agent" if row.user_id is None else "user",
            memory_type=row.type,
            name=row.name,
            description=row.description,
            content=row.content,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _event(row: RDBEvent) -> Event:
        payload: object
        match row.kind:
            case EventKind.USER_MESSAGE:
                payload = UserMessagePayload.model_validate(row.payload)
            case EventKind.ACTION_MESSAGE:
                payload = ActionMessagePayload.model_validate(row.payload)
            case EventKind.EXTERNAL_CHANNEL_MESSAGE:
                payload = ExternalChannelMessagePayload.model_validate(row.payload)
            case EventKind.ASSISTANT_MESSAGE:
                payload = AssistantMessagePayload.model_validate(row.payload)
            case EventKind.AGENT_MESSAGE:
                payload = AgentMessagePayload.model_validate(row.payload)
            case EventKind.CLIENT_TOOL_CALL:
                payload = ClientToolCallPayload.model_validate(
                    upgrade_persisted_client_tool_payload(row.kind, row.payload)
                )
            case EventKind.CLIENT_TOOL_RESULT:
                payload = ClientToolResultPayload.model_validate(
                    upgrade_persisted_client_tool_payload(row.kind, row.payload)
                )
            case EventKind.PROVIDER_TOOL_CALL:
                payload = ProviderToolCallPayload.model_validate(row.payload)
            case _:
                raise ValueError("Unsupported Memory VFS event kind")
        return Event(
            id=row.id,
            session_id=row.session_id,
            kind=row.kind,
            payload=payload,
            external_id=row.external_id,
            adapter=row.adapter,
            provider=row.provider,
            model=row.model,
            native_format=row.native_format,
            schema_version=row.schema_version,
            created_at=row.created_at,
        )

    @staticmethod
    def _tool_result(
        scope: Literal["team", "user"],
        event: Event,
    ) -> ToolResultVfsRecord | None:
        payload = event.payload
        if isinstance(payload, ClientToolResultPayload):
            text = "\n".join(
                part.text
                for part in iter_output_parts(payload.output)
                if isinstance(part, OutputTextPart)
            )
            tool_name = payload.name or "tool"
            status = payload.status
        elif isinstance(payload, ProviderToolCallPayload):
            text = "\n".join(
                part.text
                for part in iter_output_parts(payload.semantic.output)
                if isinstance(part, OutputTextPart)
            )
            tool_name = payload.name
            status = payload.status or "unknown"
        else:
            return None
        return ToolResultVfsRecord(
            scope=scope,
            session_id=event.session_id,
            event_id=event.id,
            tool_name=tool_name,
            status=status,
            text=text,
            created_at=event.created_at,
        )

    @staticmethod
    def _require_limit(limit: int) -> None:
        if limit < 1:
            raise ValueError("Memory VFS query limit must be positive")

    @staticmethod
    def _require_max_bytes(max_bytes: int) -> None:
        if max_bytes < 1:
            raise ValueError("Memory VFS byte limit must be positive")

    @staticmethod
    def _query_budget(
        *,
        limit: int,
        max_bytes: int,
        unique: bool = False,
    ) -> _QueryBudget:
        row_limit = 1 if unique else min(limit + 1, max_bytes)
        return _QueryBudget(
            row_limit=row_limit,
            per_row_bytes=max(1, max_bytes // row_limit),
            limit_truncated=not unique and row_limit < limit + 1,
        )
