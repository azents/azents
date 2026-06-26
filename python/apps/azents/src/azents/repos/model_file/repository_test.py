"""ModelFile repository tests."""

import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentSessionStartReason,
    LLMProvider,
    ModelFileStatus,
)
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFileCreate
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate
from azents.testing.model_selection import make_test_model_selection_dict


async def _create_agent_session(session: AsyncSession) -> tuple[str, str, str]:
    """Create AgentSession for tests."""
    await WorkspaceRepository().create(
        session,
        WorkspaceCreate(name="ModelFile test", handle="model-file-test-ws"),
    )
    workspace_id = await WorkspaceRepository().resolve_id(
        session,
        "model-file-test-ws",
    )
    assert workspace_id is not None

    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.OPENAI,
        name="model-file-test-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.add(integration)
    await session.flush()

    agent = RDBAgent(
        workspace_id=workspace_id,
        name="ModelFile test agent",
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="model-file-test-model-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier="model-file-test-model-id",
        ),
    )
    session.add(agent)
    await session.flush()

    runtime = RDBAgentRuntime(workspace_id=workspace_id, agent_id=agent.id)
    session.add(runtime)
    await session.flush()

    agent_session = await AgentSessionRepository().create(
        session,
        AgentSessionCreate(
            workspace_id=workspace_id,
            agent_id=agent.id,
            title=None,
            start_reason=AgentSessionStartReason.INITIAL,
        ),
    )
    return workspace_id, agent.id, agent_session.id


async def test_create_model_file_metadata(rdb_session: AsyncSession) -> None:
    """Create ModelFile metadata row and storage key."""
    workspace_id, agent_id, session_id = await _create_agent_session(rdb_session)
    repo = ModelFileRepository()

    created = await repo.create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="photo.jpg",
            media_type="image/jpeg",
            kind="image",
            size_bytes=123,
            created_run_index=4,
            expires_after_run_index=6,
            normalized_format="jpeg",
            sha256="1" * 64,
            metadata={"source": "test"},
        ),
    )

    assert created.status == ModelFileStatus.AVAILABLE
    assert created.created_run_index == 4
    assert created.expires_after_run_index == 6
    assert created.storage_key == (
        f"model-files/{workspace_id}/{session_id}/{created.id}"
    )
    assert created.created_at <= datetime.datetime.now(datetime.UTC)

    found = await repo.get_by_id(rdb_session, created.id)

    assert found is not None
    assert found.id == created.id
    assert found.metadata == {"source": "test"}


async def test_model_file_run_boundary_lifecycle_updates(
    rdb_session: AsyncSession,
) -> None:
    """Validate run boundary target fetch and lifecycle status update."""
    workspace_id, agent_id, session_id = await _create_agent_session(rdb_session)
    repo = ModelFileRepository()
    previous_file = await repo.create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="old.pdf",
            media_type="application/pdf",
            kind="document",
            size_bytes=123,
            created_run_index=1,
            expires_after_run_index=3,
            normalized_format="original",
            sha256="1" * 64,
            metadata={},
        ),
    )
    current_run_file = await repo.create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="new.pdf",
            media_type="application/pdf",
            kind="document",
            size_bytes=123,
            created_run_index=2,
            expires_after_run_index=4,
            normalized_format="original",
            sha256="2" * 64,
            metadata={},
        ),
    )

    candidates = await repo.list_for_run_boundary(
        rdb_session,
        session_id=session_id,
        current_run_index=4,
    )

    assert [item.id for item in candidates] == [previous_file.id, current_run_file.id]
    degraded_at = datetime.datetime.now(datetime.UTC)
    degraded = await repo.mark_degraded(
        rdb_session,
        model_file_id=previous_file.id,
        size_bytes=77,
        normalized_format="jpeg:300",
        sha256="3" * 64,
        degraded_at=degraded_at,
    )
    unreachable_at = datetime.datetime.now(datetime.UTC)
    unreachable = await repo.mark_unreachable(
        rdb_session,
        model_file_id=previous_file.id,
        unreachable_run_index=4,
        unreachable_at=unreachable_at,
    )
    deleted_at = datetime.datetime.now(datetime.UTC)
    deleted = await repo.mark_deleted(
        rdb_session,
        model_file_id=current_run_file.id,
        deleted_at=deleted_at,
    )

    found_previous = await repo.get_by_id(rdb_session, previous_file.id)
    found_current = await repo.get_by_id(rdb_session, current_run_file.id)
    assert degraded.status == ModelFileStatus.DEGRADED
    assert degraded.size_bytes == 77
    assert degraded.normalized_format == "jpeg:300"
    assert degraded.degraded_at == degraded_at
    assert unreachable.status == ModelFileStatus.UNREACHABLE
    assert unreachable.unreachable_run_index == 4
    assert unreachable.unreachable_at == unreachable_at
    assert found_previous is not None
    assert found_previous.status == ModelFileStatus.UNREACHABLE
    assert found_previous.unreachable_run_index == 4
    assert found_current is not None
    assert found_current.status == ModelFileStatus.DELETED
    assert found_current.deleted_at == deleted_at
    assert deleted.status == ModelFileStatus.DELETED


async def test_list_statuses_for_session_returns_known_model_files(
    rdb_session: AsyncSession,
) -> None:
    """ModelFile status lookup returns only IDs belonging to current session."""
    workspace_id, agent_id, session_id = await _create_agent_session(rdb_session)
    repo = ModelFileRepository()
    available = await repo.create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="image.jpg",
            media_type="image/jpeg",
            kind="image",
            size_bytes=123,
            created_run_index=1,
            expires_after_run_index=10,
            normalized_format="jpeg",
            sha256="1" * 64,
            metadata={},
        ),
    )
    deleted = await repo.create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="old.pdf",
            media_type="application/pdf",
            kind="document",
            size_bytes=123,
            created_run_index=1,
            expires_after_run_index=3,
            normalized_format="original",
            sha256="2" * 64,
            metadata={},
        ),
    )
    await repo.mark_deleted(
        rdb_session,
        model_file_id=deleted.id,
        deleted_at=datetime.datetime.now(datetime.UTC),
    )

    statuses = await repo.list_statuses_for_session(
        rdb_session,
        session_id=session_id,
        model_file_ids=[available.id, deleted.id, "9" * 32],
    )

    assert statuses == {
        available.id: ModelFileStatus.AVAILABLE,
        deleted.id: ModelFileStatus.DELETED,
    }
