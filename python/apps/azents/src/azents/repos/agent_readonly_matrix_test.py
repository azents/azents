"""Owning user-write transactions enforce the canonical deleting-Agent boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
import sqlalchemy.event
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncEngine

from azents.core.agent_mutation import AgentMutationReadOnly
from azents.core.enums import WorkspaceUserRole
from azents.core.memory_scope import MemoryScope
from azents.rdb.models.agent_decommission import RDBAgentDecommissionJob
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.agent_decommission import AgentDecommissionRepository
from azents.repos.agent_decommission.lease_test import _create_job
from azents.repos.agent_operations import (
    AgentOperationNotAdmin,
    AgentOperationsRepository,
)
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_catalog.operations import (
    AgentProjectCatalogOperationsRepository,
)
from azents.repos.agent_runtime_environment import AgentRuntimeEnvironmentRepository
from azents.repos.memory import MemoryRepository
from azents.repos.memory.data import MemoryCreate
from azents.repos.memory.ui_operations import MemoryUIOperations
from azents.repos.workspace_user import WorkspaceUserRepository


def _agents(
    manager: SessionManager[WriteSession], workspace_id: str
) -> AgentOperationsRepository:
    users = Mock(spec=WorkspaceUserRepository)
    users.get.return_value = Mock(
        workspace_id=workspace_id, role=WorkspaceUserRole.OWNER
    )
    return AgentOperationsRepository(
        session_manager=manager,
        credential_cipher=Mock(),
        agent_repository=AgentRepository(),
        admin_repository=AgentAdminRepository(),
        workspace_model_settings_repository=Mock(),
        workspace_user_repository=users,
        agent_decommission_repository=AgentDecommissionRepository(),
        archived_session_retention_repository=Mock(),
        agent_session_repository=Mock(),
        runtime_profile_repository=Mock(),
        runtime_profile_availability_repository=Mock(),
    )


@pytest.mark.parametrize(
    "operation",
    [
        "settings",
        "avatar",
        "add_admin",
        "remove_admin",
        "memory_create",
        "memory_update",
        "memory_delete",
        "project_candidates",
        "project_status",
        "environment",
    ],
)
async def test_user_mutation_families_reject_deleting_agent(
    rdb_session_manager: SessionManager[WriteSession], operation: str
) -> None:
    create = MemoryCreate(
        scope=MemoryScope.AGENT,
        type="reference",
        name="preserved",
        description="Keep this record",
        content="Original",
    )
    async with rdb_session_manager() as session:
        fixture = await _create_job(session)
        memory = await MemoryRepository().create(
            session, agent_id=fixture.agent_id, user_id=None, create=create
        )
    agents = _agents(rdb_session_manager, fixture.workspace_id)
    memories = MemoryUIOperations(
        MemoryRepository(),
        AgentRepository(),
        AgentAdminRepository(),
        rdb_session_manager,
    )
    projects = AgentProjectCatalogOperationsRepository(
        AgentProjectCatalogRepository(), rdb_session_manager, rdb_session_manager
    )
    environment = AgentRuntimeEnvironmentRepository(
        rdb_session_manager, rdb_session_manager, Mock(), AgentAdminRepository()
    )
    with pytest.raises(AgentMutationReadOnly):
        match operation:
            case "settings":
                await agents.update_by_id(
                    agent_id=fixture.agent_id,
                    workspace_id=fixture.workspace_id,
                    workspace_user_id="owner",
                    update={"name": "Blocked rename"},
                    runtime_profile_change=None,
                    model_configuration_changed=False,
                    valid_model_target_labels=["default"],
                    model_target_label="default",
                    reasoning_effort=None,
                )
            case "avatar":
                await agents.update_avatar(
                    agent_id=fixture.agent_id,
                    workspace_id=fixture.workspace_id,
                    workspace_user_id="owner",
                    avatar=None,
                )
            case "add_admin":
                await agents.create_admin(
                    agent_id=fixture.agent_id, workspace_user_id="new-admin"
                )
            case "remove_admin":
                await agents.remove_admin(
                    agent_id=fixture.agent_id, workspace_user_id="admin"
                )
            case "memory_create":
                await memories.create_if_name_available(
                    agent_id=fixture.agent_id,
                    user_id=None,
                    create=create.model_copy(update={"name": "new"}),
                )
            case "memory_update":
                await memories.update_by_id(
                    memory.id, {"content": "Blocked replacement"}
                )
            case "memory_delete":
                await memories.delete_by_id(memory.id)
            case "project_candidates":
                await projects.upsert_candidates(
                    agent_id=fixture.agent_id, paths=("/observed-project",)
                )
            case "project_status":
                await projects.apply_statuses(
                    agent_id=fixture.agent_id, applications=()
                )
            case "environment":
                await environment.replace(
                    fixture.agent_id,
                    edits=[],
                    workspace_id=fixture.workspace_id,
                    workspace_user_id="owner",
                    role=WorkspaceUserRole.OWNER,
                )
            case _:
                raise AssertionError(operation)
    # Inspection remains available through the same owners after rejected writes.
    current = await agents.get_by_id(fixture.agent_id)
    assert current is not None and current.name != "Blocked rename"
    preserved = await memories.get_by_id(memory.id)
    assert preserved is not None and preserved.content == "Original"
    assert await projects.list_entries(agent_id=fixture.agent_id) == []


async def test_unauthorized_avatar_update_retains_confidential_denial(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    async with rdb_session_manager() as session:
        fixture = await _create_job(session)
    agents = _agents(rdb_session_manager, fixture.workspace_id)
    users = Mock(spec=WorkspaceUserRepository)
    users.get.return_value = None
    agents.workspace_user_repository = users
    result = await agents.update_avatar(
        agent_id=fixture.agent_id,
        workspace_id=fixture.workspace_id,
        workspace_user_id="outsider",
        avatar=None,
    )
    assert result.failure and isinstance(result.error, AgentOperationNotAdmin)


async def test_deletion_projection_is_batched_and_contains_only_requested_presence(
    rdb_session_manager: SessionManager[WriteSession],
    rdb_engine: AsyncEngine,
) -> None:
    async with rdb_session_manager() as session:
        visible = await _create_job(session)
        error = await _create_job(session)
        hidden = await _create_job(session)
        for fixture in (error, hidden):
            await session.write_session.execute(
                sa.update(RDBAgentDecommissionJob)
                .where(RDBAgentDecommissionJob.id == fixture.job_id)
                .values(
                    last_error_summary="private SQL credential/provider identifiers"
                )
            )
    # The completed operation makes one transaction/query for the authorized ID batch.
    opens = 0
    statements: list[str] = []

    def record_query(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        if "agent_decommission_jobs" in statement:
            statements.append(statement)

    @asynccontextmanager
    async def counted() -> AsyncIterator[WriteSession]:
        nonlocal opens
        opens += 1
        async with rdb_session_manager() as session:
            yield session

    agents = _agents(counted, visible.workspace_id)
    sa.event.listen(rdb_engine.sync_engine, "before_cursor_execute", record_query)
    try:
        result = await agents.deletion_errors_by_agent(
            [visible.agent_id, error.agent_id]
        )
    finally:
        sa.event.remove(rdb_engine.sync_engine, "before_cursor_execute", record_query)
    assert result == {visible.agent_id: False, error.agent_id: True}
    assert hidden.agent_id not in result
    assert len(statements) == 1
    assert opens == 1
    assert await agents.deletion_errors_by_agent([]) == {}
    assert opens == 1
