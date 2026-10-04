"""Completed Engine Toolkit state operation tests."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.engine_tool_state import (
    AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    AGENTS_TOOLKIT_NAMESPACE,
    CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
    CLAUDE_RULES_TOOLKIT_NAMESPACE,
    GITHUB_SELECTED_INSTALLATION_STATE_NAME,
    GITHUB_TOOLKIT_STATE_NAMESPACE,
    TODO_TOOLKIT_NAMESPACE,
    TODO_TOOLKIT_STATE_NAME,
    TOOL_SEARCH_TOOLKIT_NAMESPACE,
    TOOL_SEARCH_WORKING_SET_STATE_NAME,
    McpToolSnapshotItem,
    McpToolSnapshotState,
    TodoItem,
    TodoState,
)
from azents.core.session_resource_authority import SessionExecutionOwner
from azents.engine.tooling.toolkit_state_test import _create_agent_and_session
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.engine_tool_repositories import EngineMcpSnapshotFactory
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.toolkit_state.engine import (
    GitHubSelectedInstallationStore,
    McpToolSnapshotStore,
    TodoStateStore,
    ToolkitAgentsAppendixDedupeStateStore,
    ToolkitClaudeRulesAppendixDedupeStateStore,
    ToolWorkingSetStore,
)


async def test_engine_tool_state_operations_close_transactions_before_returning(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Completed state results return only after their transaction closes."""
    async with rdb_session_manager() as session:
        fixture = await _create_agent_and_session(session, "engine-operations")

    transaction_active = False
    write_transaction_count = 0
    read_transaction_count = 0

    @asynccontextmanager
    async def tracked_session_manager() -> AsyncIterator[WriteSession]:
        nonlocal transaction_active, write_transaction_count
        assert not transaction_active
        transaction_active = True
        write_transaction_count += 1
        try:
            async with rdb_session_manager() as session:
                yield session
        finally:
            transaction_active = False

    @asynccontextmanager
    async def read_session_manager() -> AsyncIterator[ReadSession]:
        nonlocal read_transaction_count
        read_transaction_count += 1
        async with rdb_session_manager() as session:
            yield session

    working_set_store = ToolWorkingSetStore(
        session_manager=tracked_session_manager,
    )
    agents_store = ToolkitAgentsAppendixDedupeStateStore(
        session_manager=tracked_session_manager,
    )
    claude_rules_store = ToolkitClaudeRulesAppendixDedupeStateStore(
        session_manager=tracked_session_manager,
    )
    todo_store = TodoStateStore(session_manager=tracked_session_manager)
    mcp_snapshot_store = McpToolSnapshotStore(
        session_manager=tracked_session_manager,
        read_session_manager=read_session_manager,
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
        toolkit_namespace="mcp",
        state_name="tool_snapshot:test",
    )
    github_selection_store = GitHubSelectedInstallationStore(
        session_manager=tracked_session_manager,
        read_session_manager=read_session_manager,
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
    )
    agent_id = fixture.agent_id
    session_id = fixture.agent_session_id

    activated = await working_set_store.activate(
        agent_id,
        session_id,
        ["beta", "alpha"],
    )
    assert not transaction_active
    assert activated.tool_names == ["beta", "alpha"]

    await agents_store.replace_appendix_dedupe(
        agent_id,
        session_id,
        ["/AGENTS.md"],
    )
    assert not transaction_active
    assert (
        await agents_store.load_appendix_dedupe(agent_id, session_id)
    ).appended_paths == ["/AGENTS.md"]
    assert not transaction_active

    await claude_rules_store.add_appendix_dedupe_paths(
        agent_id,
        session_id,
        ["/.claude/rules/python.md"],
    )
    assert not transaction_active
    assert (
        await claude_rules_store.load_appendix_dedupe(agent_id, session_id)
    ).appended_paths == ["/.claude/rules/python.md"]
    assert not transaction_active

    todo = await todo_store.replace(
        agent_id,
        session_id,
        TodoState(items=[TodoItem(content="Verify boundary", status="in_progress")]),
    )
    assert not transaction_active
    assert [item.content for item in todo.items] == ["Verify boundary"]

    cleared = await working_set_store.clear(agent_id, session_id)
    assert not transaction_active
    assert cleared.tool_names == []

    snapshot = McpToolSnapshotState(
        loaded_at="2026-10-01T00:00:00+00:00",
        server_url="https://mcp.example.test",
        tool_hash="snapshot-hash",
        tools=[
            McpToolSnapshotItem(
                raw_name="read",
                model_name="read",
                description="Read data",
                input_schema={"type": "object", "properties": {}},
                server_url="https://mcp.example.test",
                use_streamable_http=True,
            )
        ],
    )
    writes_before_snapshot_replace = write_transaction_count
    await mcp_snapshot_store.replace(snapshot)
    assert not transaction_active
    assert write_transaction_count == writes_before_snapshot_replace + 1
    reads_before_snapshot_load = read_transaction_count
    writes_before_snapshot_load = write_transaction_count
    assert await mcp_snapshot_store.load() == snapshot
    assert not transaction_active
    assert read_transaction_count == reads_before_snapshot_load + 1
    assert write_transaction_count == writes_before_snapshot_load

    writes_before_selection_save = write_transaction_count
    await github_selection_store.save("installation-1")
    assert not transaction_active
    assert write_transaction_count == writes_before_selection_save + 1
    reads_before_selection_load = read_transaction_count
    writes_before_selection_load = write_transaction_count
    assert await github_selection_store.load() == "installation-1"
    assert not transaction_active
    assert read_transaction_count == reads_before_selection_load + 1
    assert write_transaction_count == writes_before_selection_load

    async with rdb_session_manager() as session:
        repository = ToolkitStateRepository()
        working_set_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=TOOL_SEARCH_TOOLKIT_NAMESPACE,
            state_name=TOOL_SEARCH_WORKING_SET_STATE_NAME,
        )
        agents_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=AGENTS_TOOLKIT_NAMESPACE,
            state_name=AGENTS_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
        )
        claude_rules_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=CLAUDE_RULES_TOOLKIT_NAMESPACE,
            state_name=CLAUDE_RULES_APPENDIX_DEDUPE_TOOLKIT_STATE_NAME,
        )
        todo_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=TODO_TOOLKIT_NAMESPACE,
            state_name=TODO_TOOLKIT_STATE_NAME,
        )
        mcp_snapshot_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace="mcp",
            state_name="tool_snapshot:test",
        )
        github_selection_record = await repository.get(
            session,
            agent_id=agent_id,
            session_id=session_id,
            toolkit_namespace=GITHUB_TOOLKIT_STATE_NAMESPACE,
            state_name=GITHUB_SELECTED_INSTALLATION_STATE_NAME,
        )

    assert working_set_record is not None
    assert working_set_record.state_json == {
        "schema_version": 1,
        "tool_names": [],
    }
    assert agents_record is not None
    assert agents_record.state_json == {
        "schema_version": 1,
        "appended_paths": ["/AGENTS.md"],
    }
    assert claude_rules_record is not None
    assert claude_rules_record.state_json == {
        "schema_version": 1,
        "appended_paths": ["/.claude/rules/python.md"],
    }
    assert todo_record is not None
    assert todo_record.state_json == {
        "schema_version": 1,
        "items": [{"content": "Verify boundary", "status": "in_progress"}],
    }
    assert mcp_snapshot_record is not None
    assert mcp_snapshot_record.state_json == snapshot.model_dump(mode="json")
    assert github_selection_record is not None
    assert github_selection_record.state_json == {
        "schema_version": 1,
        "installation_id": "installation-1",
    }
    assert read_transaction_count == 2


async def test_working_set_composition_uses_the_callers_transaction(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Compaction composition preserves one caller-owned atomic transaction."""
    async with rdb_session_manager() as session:
        fixture = await _create_agent_and_session(session, "engine-composition")

    manager_call_count = 0

    @asynccontextmanager
    async def counted_session_manager() -> AsyncIterator[WriteSession]:
        nonlocal manager_call_count
        manager_call_count += 1
        async with rdb_session_manager() as session:
            yield session

    store = ToolWorkingSetStore(session_manager=counted_session_manager)
    await store.activate(
        fixture.agent_id,
        fixture.agent_session_id,
        ["active"],
    )
    assert manager_call_count == 1

    async with rdb_session_manager() as session:
        cleared = await store.clear_in_session(
            session,
            fixture.agent_id,
            fixture.agent_session_id,
        )
        assert cleared.tool_names == []
        assert manager_call_count == 1

    assert (
        await store.load(fixture.agent_id, fixture.agent_session_id)
    ).tool_names == []
    assert manager_call_count == 2


async def test_for_execution_snapshot_and_selection_loads_bypass_held_execution_lock(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Read-only descriptions bypass a held execution-owner tree lock."""
    del latest_db_schema
    write_manager = create_read_write_session_manager(rdb_engine)
    read_manager = create_read_only_session_manager(rdb_engine)
    async with write_manager() as session:
        fixture = await _create_agent_and_session(session, "snapshot-read-lock")

    async with write_manager() as session:
        current = await AgentSessionRepository().get_by_id(
            session,
            fixture.agent_session_id,
        )
    assert current is not None
    owner = SessionExecutionOwner(
        session_id=current.id,
        owner_generation=current.owner_generation,
    )
    factory = EngineMcpSnapshotFactory(
        session_manager=write_manager,
        read_session_manager=read_manager,
    )
    snapshot = McpToolSnapshotState(
        loaded_at="2026-10-01T00:00:00+00:00",
        server_url="https://mcp.example.test",
        tool_hash="lock-free-read",
        tools=[],
    )
    unbound_store = factory.create(
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
        toolkit_namespace="mcp",
        state_name="tool_snapshot:lock",
    )
    unbound_selection = factory.selected_installation(
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
    )
    assert unbound_store is not None
    assert unbound_selection is not None
    await unbound_store.replace(snapshot)
    await unbound_selection.save("installation-1")

    bound = factory.with_owner(owner)
    store = bound.create(
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
        toolkit_namespace="mcp",
        state_name="tool_snapshot:lock",
    )
    selection = bound.selected_installation(
        agent_id=fixture.agent_id,
        session_id=fixture.agent_session_id,
    )
    assert store is not None
    assert selection is not None
    assert store.session_manager is not write_manager
    assert store.read_session_manager is read_manager
    assert selection.read_session_manager is read_manager

    lock_acquired = asyncio.Event()
    release_lock = asyncio.Event()

    async def hold_execution_lock() -> None:
        async with write_manager() as session:
            locked = await AgentSessionRepository().wait_for_execution_lock_by_id(
                session,
                fixture.agent_session_id,
            )
            assert locked is not None
            assert locked.owner_generation == owner.owner_generation
            lock_acquired.set()
            await release_lock.wait()

    holder = asyncio.create_task(hold_execution_lock())
    try:
        await asyncio.wait_for(lock_acquired.wait(), timeout=5)
        loaded = await asyncio.wait_for(store.load(), timeout=1)
        assert loaded == snapshot
        assert await asyncio.wait_for(selection.load(), timeout=1) == "installation-1"
    finally:
        release_lock.set()
        await holder
