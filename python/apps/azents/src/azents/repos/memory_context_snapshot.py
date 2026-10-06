"""Database-owned aggregate selection, filtering and boundary CAS operations."""

import dataclasses
import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from pydantic import ValidationError

from azents.core.enums import AgentSessionProductMode, EventKind
from azents.core.historical_memory_consolidation import ConsolidationScope
from azents.core.historical_memory_context import (
    MemoryContextPrompt,
    build_memory_context_snapshot,
    filter_memory_context_snapshot,
    prepare_memory_context_prompt,
)
from azents.core.historical_memory_snapshot import (
    MemoryContextSnapshotState,
    MemorySnapshotConsumer,
    SavedMemorySnapshotEntry,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.events.types import CompactionSummaryPayload
from azents.rdb.deps import get_read_only_session_manager, get_session_manager
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import ReadSession, WriteSession
from azents.repos.historical_memory import HistoricalMemoryRepository
from azents.repos.historical_memory_consolidation.foreground import (
    read_current_result,
)
from azents.repos.memory import MemoryRepository
from azents.repos.message import MessageRepository
from azents.repos.session_execution.ownership import fence_owned_session_mutation
from azents.repos.toolkit_state import ToolkitStateConflictError, ToolkitStateRepository
from azents.repos.toolkit_state.data import ToolkitStateRecord, ToolkitStateUpsert

_MEMORY_NAMESPACE = "memory"
_CONTEXT_SNAPSHOT_STATE = "context_snapshot"


@dataclasses.dataclass
class MemoryContextSnapshotRepository:
    """Compose database-only operations with independent scope checks."""

    historical_repository: Annotated[
        HistoricalMemoryRepository, Depends(HistoricalMemoryRepository)
    ]
    memory_repository: Annotated[MemoryRepository, Depends(MemoryRepository)]
    message_repository: Annotated[MessageRepository, Depends(MessageRepository)]
    toolkit_state_repository: Annotated[
        ToolkitStateRepository, Depends(ToolkitStateRepository)
    ]
    session_manager: Annotated[
        SessionManager[WriteSession], Depends(get_session_manager)
    ]

    read_session_manager: Annotated[
        SessionManager[ReadSession], Depends(get_read_only_session_manager)
    ]
    owner: SessionExecutionOwner | None

    @classmethod
    def create(
        cls,
        historical_repository: Annotated[
            HistoricalMemoryRepository, Depends(HistoricalMemoryRepository)
        ],
        memory_repository: Annotated[MemoryRepository, Depends(MemoryRepository)],
        message_repository: Annotated[MessageRepository, Depends(MessageRepository)],
        toolkit_state_repository: Annotated[
            ToolkitStateRepository, Depends(ToolkitStateRepository)
        ],
        session_manager: Annotated[
            SessionManager[WriteSession], Depends(get_session_manager)
        ],
        read_session_manager: Annotated[
            SessionManager[ReadSession], Depends(get_read_only_session_manager)
        ],
    ) -> "MemoryContextSnapshotRepository":
        """Construct an explicitly non-execution boundary operation."""
        return cls(
            historical_repository=historical_repository,
            memory_repository=memory_repository,
            message_repository=message_repository,
            toolkit_state_repository=toolkit_state_repository,
            session_manager=session_manager,
            read_session_manager=read_session_manager,
            owner=None,
        )

    def with_owner(
        self, owner: SessionExecutionOwner
    ) -> "MemoryContextSnapshotRepository":
        """Bind snapshot publication only, leaving prompt descriptions independent."""
        return dataclasses.replace(
            self,
            owner=owner,
        )

    async def prompt_for_turn(self, *, session_id: str) -> MemoryContextPrompt:
        async with self.read_session_manager() as session:
            await session.read_session.execute(
                sa.select(sa.func.set_config("statement_timeout", "2000", True))
            )
            consumer = (
                await self.historical_repository.get_snapshot_consumer_in_session(
                    session, session_id=session_id
                )
            )
            if consumer is None:
                return prepare_memory_context_prompt(None)
            record = await self.toolkit_state_repository.get(
                session,
                agent_id=consumer.agent_id,
                session_id=consumer.session_id,
                toolkit_namespace=_MEMORY_NAMESPACE,
                state_name=_CONTEXT_SNAPSHOT_STATE,
            )
            snapshot = self.decode_snapshot(record)
            if (
                snapshot is None
                or snapshot.boundary_head_event_id != consumer.model_input_head_event_id
            ):
                return prepare_memory_context_prompt(None)
            current_saved = await self.memory_repository.list_by_ids(
                session,
                agent_id=consumer.agent_id,
                memory_ids=[entry.memory_id for entry in snapshot.saved_entries],
            )
            saved_ids = {
                memory.id
                for memory in current_saved
                if memory.user_id is None
                or (
                    consumer.product_mode is AgentSessionProductMode.USER
                    and memory.user_id == consumer.associated_user_id
                )
            }
            available = []
            for selected in snapshot.historical_entries:
                entry = await read_current_result(
                    session,
                    consumer=consumer,
                    scope=selected.unit.scope,
                    selected=selected,
                )
                if entry is not None:
                    available.append(entry.unit.scope)
            result = prepare_memory_context_prompt(
                filter_memory_context_snapshot(
                    snapshot,
                    available_saved_ids=saved_ids,
                    available_scopes=available,
                )
            )
        return result

    async def refresh_snapshot(
        self,
        *,
        session_id: str,
        after_compaction: bool,
    ) -> bool:
        async with self.session_manager() as session:
            if self.owner is not None:
                if self.owner.session_id != session_id:
                    raise ValueError("Memory snapshot Session does not match owner")
                await fence_owned_session_mutation(session, self.owner)
            await session.write_session.execute(
                sa.select(sa.func.set_config("statement_timeout", "2000", True))
            )
            consumer = (
                await self.historical_repository.get_snapshot_consumer_in_session(
                    session, session_id=session_id
                )
            )
            if consumer is None:
                return False
            record = await self.toolkit_state_repository.get(
                session,
                agent_id=consumer.agent_id,
                session_id=consumer.session_id,
                toolkit_namespace=_MEMORY_NAMESPACE,
                state_name=_CONTEXT_SNAPSHOT_STATE,
            )
            previous = self.decode_snapshot(record)
            if after_compaction:
                if (
                    previous is not None
                    and previous.boundary_head_event_id
                    == consumer.model_input_head_event_id
                ):
                    return True
                if consumer.model_input_head_event_id is None:
                    return False
            if not await self._valid_boundary(session, consumer):
                return False
            return await self._select_snapshot(
                session, consumer=consumer, record=record, previous=previous
            )

    async def _select_snapshot(
        self,
        session: WriteSession,
        *,
        consumer: MemorySnapshotConsumer,
        record: ToolkitStateRecord | None,
        previous: MemoryContextSnapshotState | None,
    ) -> bool:
        saved = await self.memory_repository.list(
            session, agent_id=consumer.agent_id, user_id=None
        )
        if (
            consumer.product_mode is AgentSessionProductMode.USER
            and consumer.associated_user_id is not None
        ):
            saved.extend(
                await self.memory_repository.list(
                    session,
                    agent_id=consumer.agent_id,
                    user_id=consumer.associated_user_id,
                )
            )
        historical = []
        for scope in ConsolidationScope:
            entry = await read_current_result(
                session, consumer=consumer, scope=scope, selected=None
            )
            if entry is not None:
                historical.append(entry)
        saved_entries = []
        for memory in saved:
            scope = "agent" if memory.user_id is None else "user"
            saved_entries.append(
                SavedMemorySnapshotEntry(
                    memory_id=memory.id,
                    scope=scope,
                    name=memory.name,
                    type=memory.type,
                    description_snapshot=memory.description,
                    updated_at_snapshot=memory.updated_at,
                    vfs_path=f"azents://memory/saved/{scope}/{memory.id}.md",
                )
            )
        snapshot = build_memory_context_snapshot(
            boundary_head_event_id=consumer.model_input_head_event_id,
            created_at=datetime.datetime.now(datetime.UTC),
            saved_entries=saved_entries,
            historical_entries=historical,
        )
        if (
            previous is not None
            and previous.saved_entries == snapshot.saved_entries
            and previous.historical_entries == snapshot.historical_entries
        ):
            snapshot = previous.model_copy(
                update={"boundary_head_event_id": consumer.model_input_head_event_id}
            )
            if snapshot == previous:
                return True
        try:
            await self.toolkit_state_repository.save(
                session,
                ToolkitStateUpsert(
                    agent_id=consumer.agent_id,
                    session_id=consumer.session_id,
                    toolkit_namespace=_MEMORY_NAMESPACE,
                    state_name=_CONTEXT_SNAPSHOT_STATE,
                    state_json=snapshot.model_dump(mode="json"),
                    schema_version=2,
                    expected_version=None if record is None else record.version,
                ),
            )
        except ToolkitStateConflictError:
            return False
        return True

    async def _valid_boundary(
        self, session: ReadSession, consumer: MemorySnapshotConsumer
    ) -> bool:
        if consumer.model_input_head_event_id is None:
            return True
        event = await self.message_repository.get_event_by_id(
            session, consumer.model_input_head_event_id
        )
        return (
            event is not None
            and event.session_id == consumer.session_id
            and event.kind is EventKind.COMPACTION_SUMMARY
            and isinstance(event.payload, CompactionSummaryPayload)
        )

    @staticmethod
    def decode_snapshot(
        record: ToolkitStateRecord | None,
    ) -> MemoryContextSnapshotState | None:
        if record is None or record.schema_version != 2:
            return None
        try:
            return MemoryContextSnapshotState.model_validate(record.state_json)
        except ValidationError:
            return None
