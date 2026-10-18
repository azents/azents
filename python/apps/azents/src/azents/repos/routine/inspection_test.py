"""Real database authorization and exact-Session read inspection regressions."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Literal

import pytest
import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentSessionProductMode,
    AgentSessionStatus,
    WorkspaceUserRole,
)
from azents.core.routine import RoutineObjectiveOutcome, RoutineScope
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.workspace_user import RDBWorkspaceUser
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import (
    ReadOnlySession,
    ReadSession,
    WriteSession,
    create_read_only_session_manager,
    create_read_write_session_manager,
)
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.routine.completion_test import NOW, fixture, work
from azents.repos.routine.definition import RoutineDefinitionRepository
from azents.repos.routine.inspection import RoutineInspectionRepository
from azents.repos.routine.judgment_inbox_test import subject
from azents.repos.routine.persistence_test import _operations
from azents.repos.routine.records import RoutineWorkRecordRepository
from azents.repos.routine.state import RoutineStateRepository
from azents.repos.session_resource_authority import PublicSessionResourceNotFound
from azents.repos.toolkit_state import ToolkitStateRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.chat_write_test import _create_user
from azents.testing.committed_fixture_cleanup import committed_fixture_graph


def inspection(manager: SessionManager[WriteSession]) -> RoutineInspectionRepository:
    @asynccontextmanager
    async def read_manager() -> AsyncIterator[ReadSession]:
        async with manager() as session:
            yield ReadOnlySession(session.read_session)

    return RoutineInspectionRepository(
        session_manager=read_manager,
        sessions=AgentSessionRepository(),
        members=WorkspaceUserRepository(),
        definitions=RoutineDefinitionRepository(),
        records=RoutineWorkRecordRepository(),
        states=RoutineStateRepository(toolkit_states=ToolkitStateRepository()),
    )


async def member(manager: SessionManager[WriteSession], scope: RoutineScope) -> str:
    async with manager() as session:
        user_id = await _create_user(
            session, f"routine-read-{scope.session_id}@example.com"
        )
        session.write_session.add(
            RDBWorkspaceUser(
                workspace_id=scope.workspace_id,
                user_id=user_id,
                name="Routine inspection owner",
                role=WorkspaceUserRole.OWNER,
            )
        )
        await session.write_session.flush()
        return user_id


async def test_detail_reads_started_and_completed_work_without_mutating_it(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    f = await fixture(rdb_session_manager)
    user_id = await member(rdb_session_manager, f.scope)
    repo = inspection(rdb_session_manager)
    item = f.states[0]
    before = await repo.detail(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=user_id,
        slug=f.definitions[0].slug,
    )
    assert isinstance(before, Success)
    assert before.value.execution == item
    assert before.value.records == ()
    result = work(notify=True, outcome=RoutineObjectiveOutcome.FAILED)
    recording = await f.repository.complete(
        scope=f.scope,
        authority=f.authority,
        slug=f.definitions[0].slug,
        execution_id=item.context.execution_id,
        work=result,
        now=NOW,
    )
    after = await repo.detail(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=user_id,
        slug=f.definitions[0].slug,
    )
    assert isinstance(after, Success)
    assert after.value.execution == recording.state
    assert len(after.value.records) == 1
    assert after.value.records[0].work == result
    assert after.value.records[0].delivery_status == recording.state.delivery_status
    assert after.value.definition.content == f.definitions[0].content
    assert (
        await repo.detail(
            agent_id=f.scope.agent_id,
            session_id=f.scope.session_id,
            user_id=user_id,
            slug=f.definitions[0].slug,
        )
        == after
    )
    await _operations(rdb_session_manager).delete(
        scope=f.scope, slug=f.definitions[0].slug, owner=None
    )
    deleted = await repo.detail(
        agent_id=f.scope.agent_id,
        session_id=f.scope.session_id,
        user_id=user_id,
        slug=f.definitions[0].slug,
    )
    assert isinstance(deleted, Failure)
    assert isinstance(deleted.error, PublicSessionResourceNotFound)


@pytest.mark.parametrize(
    "access",
    ["team", "private_owner", "private_other", "outsider", "wrong_agent", "archived"],
)
async def test_inventory_and_detail_enforce_current_public_session_authority(
    rdb_session_manager: SessionManager[WriteSession],
    *,
    access: Literal[
        "team", "private_owner", "private_other", "outsider", "wrong_agent", "archived"
    ],
) -> None:
    scope = await subject(rdb_session_manager)
    user_id = await member(rdb_session_manager, scope)
    definitions = await _operations(rdb_session_manager).list_routines(scope=scope)
    async with rdb_session_manager() as session:
        if access in {"private_owner", "private_other"}:
            conversation = await session.write_session.get(
                RDBConversation, scope.session_id
            )
            assert conversation is not None
            other = await _create_user(session, f"other-{scope.session_id}@example.com")
            conversation.product_mode = AgentSessionProductMode.USER
            conversation.associated_user_id = (
                user_id if access == "private_owner" else other
            )
        if access == "outsider":
            user_id = await _create_user(
                session, f"outside-{scope.session_id}@example.com"
            )
        if access == "archived":
            target = await session.write_session.get(RDBAgentSession, scope.session_id)
            assert target is not None
            target.status = AgentSessionStatus.ARCHIVED
        await session.write_session.flush()
    repo = inspection(rdb_session_manager)
    agent_id = "wrong-agent" if access == "wrong_agent" else scope.agent_id
    inventory = await repo.list_for_session(
        agent_id=agent_id, session_id=scope.session_id, user_id=user_id
    )
    detail = await repo.detail(
        agent_id=agent_id,
        session_id=scope.session_id,
        user_id=user_id,
        slug=definitions[0].slug,
    )
    if access in {"team", "private_owner"}:
        assert isinstance(inventory, Success) and inventory.value.items == tuple(
            definitions
        )
        assert isinstance(detail, Success)
        assert detail.value.execution is None and detail.value.records == ()
    else:
        assert isinstance(inventory, Failure)
        assert isinstance(inventory.error, PublicSessionResourceNotFound)
        assert isinstance(detail, Failure)
        assert isinstance(detail.error, PublicSessionResourceNotFound)


async def test_empty_selected_session_never_falls_back_to_another_session(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    scope = await subject(rdb_session_manager)
    user_id = await member(rdb_session_manager, scope)
    definitions = await _operations(rdb_session_manager).list_routines(scope=scope)
    async with rdb_session_manager() as session:
        selected = await AgentSessionRepository().create(
            session,
            AgentSessionCreate(
                workspace_id=scope.workspace_id,
                agent_id=scope.agent_id,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
                title=None,
            ),
        )
    repo = inspection(rdb_session_manager)
    inventory = await repo.list_for_session(
        agent_id=scope.agent_id, session_id=selected.id, user_id=user_id
    )
    assert isinstance(inventory, Success) and inventory.value.items == ()
    foreign_slug = await repo.detail(
        agent_id=scope.agent_id,
        session_id=selected.id,
        user_id=user_id,
        slug=definitions[0].slug,
    )
    assert isinstance(foreign_slug, Failure)
    assert isinstance(foreign_slug.error, PublicSessionResourceNotFound)


async def test_real_read_only_scope_returns_latest_hundred_records(
    rdb_engine: AsyncEngine, latest_db_schema: None
) -> None:
    """Physical read-only transactions support inspection and exact retention."""
    del latest_db_schema
    metadata = sa.MetaData()
    async with rdb_engine.connect() as connection:
        await connection.run_sync(metadata.reflect)
    manager = create_read_write_session_manager(rdb_engine)
    readonly = create_read_only_session_manager(rdb_engine)
    scopes = 0

    @asynccontextmanager
    async def observed_read() -> AsyncIterator[ReadSession]:
        nonlocal scopes
        async with readonly() as session:
            assert (
                await session.read_session.scalar(sa.text("SHOW transaction_read_only"))
                == "on"
            )
            scopes += 1
            yield session

    async with committed_fixture_graph(rdb_engine, metadata):
        scope = await subject(manager)
        user_id = await member(manager, scope)
        definitions = await _operations(manager).list_routines(scope=scope)
        records = RoutineWorkRecordRepository()
        async with manager() as session:
            for index in range(101):
                await records.append(
                    session,
                    scope=scope,
                    routine_id=definitions[0].id,
                    execution_id=f"historical-execution-{index}",
                    started_at=NOW,
                    work=work(notify=False, outcome=RoutineObjectiveOutcome.FINISHED),
                )
        repo = replace(inspection(manager), session_manager=observed_read)
        inventory = await repo.list_for_session(
            agent_id=scope.agent_id, session_id=scope.session_id, user_id=user_id
        )
        detail = await repo.detail(
            agent_id=scope.agent_id,
            session_id=scope.session_id,
            user_id=user_id,
            slug=definitions[0].slug,
        )
        assert isinstance(inventory, Success)
        assert isinstance(detail, Success)
        assert len(detail.value.records) == 100
        assert detail.value.records[0].execution_id == "historical-execution-100"
        assert all(
            item.execution_id != "historical-execution-0"
            for item in detail.value.records
        )
        assert scopes == 2
