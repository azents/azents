"""PostgreSQL authorization and lifecycle tests for the Memory VFS."""

import dataclasses
import datetime
import hashlib
from typing import NamedTuple

import sqlalchemy as sa
from psycopg import AsyncCursor
from pydantic import TypeAdapter
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionStatus,
    EventKind,
    WorkspaceUserRole,
)
from azents.core.json_value import JSONValue
from azents.engine.events.types import (
    ClientToolCallPayload,
    ClientToolResultPayload,
    NativeArtifact,
    UserMessagePayload,
    build_native_compat_key,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.event import RDBEvent
from azents.rdb.models.historical_memory import RDBHistoricalMemorySource
from azents.rdb.models.memory import RDBAgentMemory
from azents.rdb.models.workspace import RDBWorkspace
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.memory_vfs.data import (
    HistoricalMemoryVfsRecord,
    MemoryVfsAuthority,
    MemoryVfsUriQuery,
    SavedMemoryVfsRecord,
    SourceEventVfsRecord,
    SourceSessionVfsRecord,
)
from azents.repos.memory_vfs.repository import MemoryVfsRepository
from azents.repos.user import UserRepository
from azents.repos.user.data import UserCreate
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)

_NOW = datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.UTC)
_PAYLOAD_ADAPTER: TypeAdapter[dict[str, JSONValue]] = TypeAdapter(dict[str, JSONValue])


class _AgentFixture(NamedTuple):
    """Created Agent and its Workspace identity."""

    agent: RDBAgent
    workspace_id: str


async def _create_agent(
    session: AsyncSession,
    *,
    slug: str,
) -> _AgentFixture:
    workspace = RDBWorkspace(name="Memory VFS", handle=f"memory-vfs-{slug}")
    session.add(workspace)
    await session.flush()
    model_selection = make_test_model_selection_dict()
    agent = RDBAgent(
        workspace_id=workspace.id,
        name="Memory VFS",
        model_selection=model_selection,
        lightweight_model_selection=model_selection,
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=model_selection,
            lightweight_model_selection=model_selection,
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
        memory_enabled=True,
    )
    session.add(agent)
    await session.flush()
    runtime = RDBAgentRuntime(workspace_id=workspace.id, agent_id=agent.id)
    runtime.workspace_path = "/workspace/agent"
    session.add(runtime)
    await session.flush()
    return _AgentFixture(agent=agent, workspace_id=workspace.id)


class _SourceFixture(NamedTuple):
    """Created source Session and its captured tail Event."""

    session_id: str
    event_id: str


async def _create_source(
    session: AsyncSession,
    *,
    agent_id: str,
    workspace_id: str,
    slug: str,
    mode: AgentSessionProductMode,
    associated_user_id: str | None,
) -> _SourceFixture:
    source = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            product_mode=mode,
            associated_user_id=associated_user_id,
            agent_id=agent_id,
            title=f"{slug} title",
        ),
    )
    event = RDBEvent(
        session_id=source.id,
        kind=EventKind.USER_MESSAGE,
        payload=_PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=associated_user_id,
                content=f"{slug} source text",
            ).model_dump(mode="json")
        ),
    )
    event.id = hashlib.sha256(slug.encode()).hexdigest()[:32]
    session.add(event)
    row = RDBHistoricalMemorySource(
        source_session_id=source.id,
        admitted_at=_NOW - datetime.timedelta(hours=2),
    )
    row.completed_source_activity_at = _NOW - datetime.timedelta(hours=1)
    row.completed_source_tail_event_id = event.id
    row.prepared_at = _NOW
    row.source_title_snapshot = f"{slug} title"
    row.summary = f"{slug} historical summary"
    session.add(row)
    await session.flush()
    return _SourceFixture(session_id=source.id, event_id=event.id)


async def test_repository_applies_scope_membership_lifecycle_and_enablement(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Every query reflects current root scope, lifecycle, and Agent enablement."""
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="repository")
        user = await UserRepository().create(
            session,
            UserCreate(email="memory-vfs@example.test"),
        )
        session.add(
            RDBWorkspaceUser(
                workspace_id=workspace_id,
                user_id=user.id,
                name="Memory VFS User",
                role=WorkspaceUserRole.MEMBER,
            )
        )
        team_session_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="memory-vfs-team",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        user_session_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="memory-vfs-user",
            mode=AgentSessionProductMode.USER,
            associated_user_id=user.id,
        )
        session.add_all(
            [
                RDBAgentMemory(
                    agent_id=agent.id,
                    user_id=None,
                    scope="agent",
                    type="project",
                    name="shared",
                    description="shared description",
                    content="shared content",
                ),
                RDBAgentMemory(
                    agent_id=agent.id,
                    user_id=user.id,
                    scope="user",
                    type="user",
                    name="personal",
                    description="personal description",
                    content="personal content",
                ),
            ]
        )
        await session.commit()

    repository = MemoryVfsRepository(session_manager=rdb_session_manager)
    team = MemoryVfsAuthority(
        root_session_id=team_session_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=None,
        memory_enabled=True,
    )
    personal = MemoryVfsAuthority(
        root_session_id=user_session_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=user.id,
        memory_enabled=True,
    )

    team_saved = await repository.list_saved(
        team,
        scopes=("agent", "user"),
        limit=10,
        max_bytes=100_000,
    )
    team_historical = await repository.list_historical(
        team,
        scopes=("team", "user"),
        limit=10,
        max_bytes=100_000,
    )
    personal_saved = await repository.list_saved(
        personal,
        scopes=("agent", "user"),
        limit=10,
        max_bytes=100_000,
    )
    personal_historical = await repository.list_historical(
        personal,
        scopes=("team", "user"),
        limit=10,
        max_bytes=100_000,
    )

    team_saved_records = [
        record
        for record in team_saved.records
        if isinstance(record, SavedMemoryVfsRecord)
    ]
    team_historical_records = [
        record
        for record in team_historical.records
        if isinstance(record, HistoricalMemoryVfsRecord)
    ]
    personal_saved_records = [
        record
        for record in personal_saved.records
        if isinstance(record, SavedMemoryVfsRecord)
    ]
    personal_historical_records = [
        record
        for record in personal_historical.records
        if isinstance(record, HistoricalMemoryVfsRecord)
    ]
    assert len(team_saved_records) == len(team_saved.records)
    assert len(team_historical_records) == len(team_historical.records)
    assert len(personal_saved_records) == len(personal_saved.records)
    assert len(personal_historical_records) == len(personal_historical.records)
    assert [record.name for record in team_saved_records] == ["shared"]
    assert [record.source_session_id for record in team_historical_records] == [
        team_session_id
    ]
    assert {record.name for record in personal_saved_records} == {
        "shared",
        "personal",
    }
    assert {record.source_session_id for record in personal_historical_records} == {
        team_session_id,
        user_session_id,
    }

    async with rdb_session_manager() as session:
        user_source = await session.get(RDBAgentSession, user_session_id)
        assert user_source is not None
        user_source.status = AgentSessionStatus.ARCHIVED
        await session.commit()
    assert (
        await repository.get_source(
            personal,
            scope="user",
            session_id=user_session_id,
            max_bytes=10_000,
        )
        is None
    )

    async with rdb_session_manager() as session:
        persisted_agent = await session.get(RDBAgent, agent.id)
        assert persisted_agent is not None
        persisted_agent.memory_enabled = False
        await session.commit()
    assert await repository.authorized(personal) is False
    assert (
        await repository.list_saved(
            personal,
            scopes=("agent", "user"),
            limit=10,
            max_bytes=100_000,
        )
    ).records == ()


async def test_repository_reauthorizes_the_exact_current_root_session(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Root identity, scope owner, lifecycle, and membership are live fences."""
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="root")
        user = await UserRepository().create(
            session,
            UserCreate(email="memory-vfs-root@example.test"),
        )
        other_user = await UserRepository().create(
            session,
            UserCreate(email="memory-vfs-other@example.test"),
        )
        session.add_all(
            [
                RDBWorkspaceUser(
                    workspace_id=workspace_id,
                    user_id=user.id,
                    name="Memory VFS Root User",
                    role=WorkspaceUserRole.MEMBER,
                ),
                RDBWorkspaceUser(
                    workspace_id=workspace_id,
                    user_id=other_user.id,
                    name="Memory VFS Other User",
                    role=WorkspaceUserRole.MEMBER,
                ),
            ]
        )
        team_session_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="memory-vfs-root-team",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        user_session_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="memory-vfs-root-user",
            mode=AgentSessionProductMode.USER,
            associated_user_id=user.id,
        )
        other_agent, other_workspace_id = await _create_agent(
            session,
            slug="other-root",
        )
        await session.commit()

    repository = MemoryVfsRepository(session_manager=rdb_session_manager)
    team = MemoryVfsAuthority(
        root_session_id=team_session_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=None,
        memory_enabled=True,
    )
    personal = MemoryVfsAuthority(
        root_session_id=user_session_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=user.id,
        memory_enabled=True,
    )

    assert await repository.authorized(team) is True
    assert await repository.authorized(personal) is True
    wrong_root = dataclasses.replace(team, root_session_id="0" * 32)
    assert await repository.authorized(wrong_root) is False
    assert (
        await repository.list_saved(
            wrong_root,
            scopes=("agent",),
            limit=10,
            max_bytes=100_000,
        )
    ).records == ()
    assert (
        await repository.list_sources(
            wrong_root,
            scopes=("team",),
            limit=10,
            max_bytes=100_000,
        )
    ).records == ()
    assert (
        await repository.authorized(
            dataclasses.replace(
                team,
                agent_id=other_agent.id,
                workspace_id=other_workspace_id,
            )
        )
        is False
    )
    assert (
        await repository.authorized(
            dataclasses.replace(team, associated_user_id=user.id)
        )
        is False
    )
    assert (
        await repository.authorized(
            dataclasses.replace(personal, associated_user_id=other_user.id)
        )
        is False
    )

    async with rdb_session_manager() as session:
        root = await session.get(RDBAgentSession, team_session_id)
        assert root is not None
        root.status = AgentSessionStatus.ARCHIVED
        await session.commit()
    assert await repository.authorized(team) is False

    async with rdb_session_manager() as session:
        await session.execute(
            sa.delete(RDBWorkspaceUser).where(
                RDBWorkspaceUser.workspace_id == workspace_id,
                RDBWorkspaceUser.user_id == user.id,
            )
        )
        await session.commit()
    assert await repository.authorized(personal) is False


async def test_repository_exact_reads_reject_oversized_text_and_json_rows(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Exact queries never transfer Text or JSON beyond the caller byte bound."""
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="bounded-exact")
        source_session_id, event_id = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="bounded-exact-source",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        memory = RDBAgentMemory(
            agent_id=agent.id,
            user_id=None,
            scope="agent",
            type="project",
            name="oversized",
            description="d" * 1_000,
            content="c" * 1_000,
        )
        session.add(memory)
        historical = await session.get(
            RDBHistoricalMemorySource,
            source_session_id,
        )
        assert historical is not None
        historical.summary = "s" * 1_000
        source_event = await session.get(RDBEvent, event_id)
        assert source_event is not None
        source_event.payload = _PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=None,
                content="e" * 1_000,
            ).model_dump(mode="json")
        )
        tool_result = RDBEvent(
            session_id=source_session_id,
            kind=EventKind.CLIENT_TOOL_RESULT,
            payload=_PAYLOAD_ADAPTER.validate_python(
                ClientToolResultPayload(
                    call_id="oversized-result",
                    name="exec_command",
                    wire_dialect="json_function",
                    status="completed",
                    output="o" * 1_000,
                ).model_dump(mode="json")
            ),
        )
        session.add(tool_result)
        await session.commit()

    repository = MemoryVfsRepository(session_manager=rdb_session_manager)
    authority = MemoryVfsAuthority(
        root_session_id=source_session_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=None,
        memory_enabled=True,
    )
    assert (
        await repository.get_saved(
            authority,
            scope="agent",
            memory_id=memory.id,
            max_bytes=128,
        )
        is None
    )
    assert (
        await repository.get_historical(
            authority,
            scope="team",
            source_session_id=source_session_id,
            max_bytes=128,
        )
        is None
    )
    assert (
        await repository.get_event(
            authority,
            scope="team",
            session_id=source_session_id,
            event_id=event_id,
            max_bytes=128,
        )
        is None
    )
    assert (
        await repository.get_tool_result(
            authority,
            scope="team",
            session_id=source_session_id,
            event_id=tool_result.id,
            max_bytes=128,
        )
        is None
    )


async def test_event_candidates_use_two_queries_across_multiple_sources(
    rdb_session_manager: SessionManager[AsyncSession],
    rdb_engine: AsyncEngine,
) -> None:
    """Candidate and pairing query counts remain constant across source Sessions."""
    compat_key = build_native_compat_key(
        adapter="pydantic_ai",
        native_format="model_messages",
        provider="openai",
        model="gpt-test",
        schema_version="1",
    )
    artifact = NativeArtifact(
        compat_key=compat_key,
        adapter="pydantic_ai",
        native_format="model_messages",
        provider="openai",
        model="gpt-test",
        schema_version="1",
        item={"type": "function_call"},
    )
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="candidate-query")
        source_ids: list[str] = []
        for index in range(3):
            source_id, _ = await _create_source(
                session,
                agent_id=agent.id,
                workspace_id=workspace_id,
                slug=f"candidate-query-{index}",
                mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            )
            source_ids.append(source_id)
            call_id = f"call-{index}"
            session.add_all(
                [
                    RDBEvent(
                        session_id=source_id,
                        kind=EventKind.CLIENT_TOOL_CALL,
                        payload=_PAYLOAD_ADAPTER.validate_python(
                            ClientToolCallPayload(
                                call_id=call_id,
                                name="channel_action",
                                arguments="{}",
                                wire_dialect="json_function",
                                native_artifact=artifact,
                            ).model_dump(mode="json")
                        ),
                    ),
                    RDBEvent(
                        session_id=source_id,
                        kind=EventKind.CLIENT_TOOL_RESULT,
                        payload=_PAYLOAD_ADAPTER.validate_python(
                            ClientToolResultPayload(
                                call_id=call_id,
                                name="channel_action",
                                wire_dialect="json_function",
                                status="completed",
                                output='{"status":"delivered"}',
                            ).model_dump(mode="json")
                        ),
                    ),
                ]
            )
        await session.commit()

    authority = MemoryVfsAuthority(
        root_session_id=source_ids[0],
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=None,
        memory_enabled=True,
    )
    select_count = 0

    def count_selects(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal select_count
        if statement.lstrip().upper().startswith("SELECT"):
            select_count += 1

    event.listen(
        rdb_engine.sync_engine,
        "before_cursor_execute",
        count_selects,
    )
    try:
        page = await MemoryVfsRepository(
            session_manager=rdb_session_manager
        ).list_event_candidates(
            authority,
            scopes=("team",),
            session_id=None,
            limit=20,
            max_bytes=1_000_000,
        )
    finally:
        event.remove(
            rdb_engine.sync_engine,
            "before_cursor_execute",
            count_selects,
        )

    calls = [
        record
        for record in page.records
        if isinstance(record, SourceEventVfsRecord)
        and isinstance(record.event.payload, ClientToolCallPayload)
    ]
    assert len(calls) == 3
    assert all(record.paired_client_result is not None for record in calls)
    assert select_count == 2


async def test_broad_lists_omit_oversized_rows_before_body_transfer(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Broad grep pages retain bounded rows and truncate oversized body rows."""
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="bounded-broad")
        normal_source_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="bounded-normal",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        oversized_source_id, _ = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="bounded-oversized",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        oversized_source = await session.get(RDBAgentSession, oversized_source_id)
        assert oversized_source is not None
        oversized_source.title = "t" * 200
        oversized_historical = await session.get(
            RDBHistoricalMemorySource,
            oversized_source_id,
        )
        assert oversized_historical is not None
        oversized_historical.summary = "s" * 10_000
        normal_memory = RDBAgentMemory(
            agent_id=agent.id,
            user_id=None,
            scope="agent",
            type="project",
            name="bounded-normal",
            description="normal description",
            content="normal searchable content",
        )
        oversized_memory = RDBAgentMemory(
            agent_id=agent.id,
            user_id=None,
            scope="agent",
            type="project",
            name="bounded-oversized",
            description="d" * 10_000,
            content="c" * 10_000,
        )
        session.add_all([normal_memory, oversized_memory])
        await session.commit()

    repository = MemoryVfsRepository(session_manager=rdb_session_manager)
    authority = MemoryVfsAuthority(
        root_session_id=normal_source_id,
        agent_id=agent.id,
        workspace_id=workspace_id,
        associated_user_id=None,
        memory_enabled=True,
    )
    saved = await repository.list_saved(
        authority,
        scopes=("agent",),
        limit=10,
        max_bytes=1_000,
    )
    historical = await repository.list_historical(
        authority,
        scopes=("team",),
        limit=10,
        max_bytes=1_000,
    )
    sources = await repository.list_sources(
        authority,
        scopes=("team",),
        limit=10,
        max_bytes=1_000,
    )

    assert [
        record.name
        for record in saved.records
        if isinstance(record, SavedMemoryVfsRecord)
    ] == ["bounded-normal"]
    assert [
        record.source_session_id
        for record in historical.records
        if isinstance(record, HistoricalMemoryVfsRecord)
    ] == [normal_source_id]
    assert [
        record.session_id
        for record in sources.records
        if isinstance(record, SourceSessionVfsRecord)
    ] == [normal_source_id]
    assert saved.has_more is True
    assert historical.has_more is True
    assert sources.has_more is True


async def test_glob_inventory_projects_only_body_free_uri_columns(
    rdb_session_manager: SessionManager[AsyncSession],
    rdb_engine: AsyncEngine,
) -> None:
    """Glob discovers poison-sized bodies without selecting their body columns."""
    async with rdb_session_manager() as session:
        agent, workspace_id = await _create_agent(session, slug="body-free-glob")
        source_id, event_id = await _create_source(
            session,
            agent_id=agent.id,
            workspace_id=workspace_id,
            slug="body-free-glob-source",
            mode=AgentSessionProductMode.TEAM,
            associated_user_id=None,
        )
        source = await session.get(RDBAgentSession, source_id)
        assert source is not None
        source.title = "t" * 200
        historical = await session.get(RDBHistoricalMemorySource, source_id)
        assert historical is not None
        historical.summary = "s" * 10_000
        source_event = await session.get(RDBEvent, event_id)
        assert source_event is not None
        source_event.payload = _PAYLOAD_ADAPTER.validate_python(
            UserMessagePayload(
                sender_user_id=None,
                content="e" * 10_000,
            ).model_dump(mode="json")
        )
        memory = RDBAgentMemory(
            agent_id=agent.id,
            user_id=None,
            scope="agent",
            type="project",
            name="body-free-glob",
            description="d" * 10_000,
            content="c" * 10_000,
        )
        session.add(memory)
        await session.commit()

    projected_columns: list[tuple[str, ...]] = []

    def capture_projection(
        _connection: object,
        cursor: AsyncCursor[object],
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if not statement.lstrip().upper().startswith("SELECT"):
            return
        if not any(
            table in statement
            for table in (
                "agent_memories",
                "historical_memory_sources",
                "events JOIN agent_sessions",
                "FROM agent_sessions JOIN agents",
            )
        ):
            return
        description = cursor.description
        if description is not None:
            projected_columns.append(tuple(column[0] for column in description))

    event.listen(
        rdb_engine.sync_engine,
        "after_cursor_execute",
        capture_projection,
    )
    try:
        page = await MemoryVfsRepository(session_manager=rdb_session_manager).list_uris(
            MemoryVfsAuthority(
                root_session_id=source_id,
                agent_id=agent.id,
                workspace_id=workspace_id,
                associated_user_id=None,
                memory_enabled=True,
            ),
            query=MemoryVfsUriQuery(
                namespace="all",
                saved_scopes=("agent",),
                source_scopes=("team",),
                session_id=None,
                source_file_kinds=("session", "events", "tool-results"),
                include_readme=True,
            ),
            limit=100,
        )
    finally:
        event.remove(
            rdb_engine.sync_engine,
            "after_cursor_execute",
            capture_projection,
        )

    assert f"azents://memory/saved/agent/{memory.id}.md" in page.uris
    assert f"azents://memory/historical/team/{source_id}/summary.md" in page.uris
    assert f"azents://memory/sources/team/{source_id}/session.md" in page.uris
    assert f"azents://memory/sources/team/{source_id}/events/{event_id}.md" in page.uris
    assert projected_columns
    forbidden = {
        "description",
        "content",
        "summary",
        "title",
        "handle",
        "payload",
    }
    assert all(forbidden.isdisjoint(columns) for columns in projected_columns)
