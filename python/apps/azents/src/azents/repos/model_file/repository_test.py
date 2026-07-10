"""ModelFile repository tests."""

import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.enums import (
    AgentRunStatus,
    AgentSessionStartReason,
    LLMProvider,
    ModelFileStatus,
)
from azents.core.inference_profile import InferenceProfileSource
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.model_file_pin import RDBModelFilePin
from azents.repos.agent_execution import AgentRunRepository
from azents.repos.agent_execution.data import AgentRunCreate
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.agent_session.data import AgentSessionCreate
from azents.repos.model_file import ModelFileRepository
from azents.repos.model_file.data import ModelFileCreate
from azents.repos.model_file_pin import ModelFilePinRepository
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
            normalized_format="jpeg",
            sha256="1" * 64,
            metadata={"source": "test"},
        ),
    )

    assert created.status == ModelFileStatus.AVAILABLE
    assert created.created_run_index == 4
    assert created.storage_key == (
        f"model-files/{workspace_id}/{session_id}/{created.id}"
    )
    assert created.created_at <= datetime.datetime.now(datetime.UTC)

    found = await repo.get_by_id(rdb_session, created.id)

    assert found is not None
    assert found.id == created.id
    assert found.metadata == {"source": "test"}


async def test_mark_deleted_if_unpinned_updates_available_rows(
    rdb_session: AsyncSession,
) -> None:
    """ModelFile cleanup marks available unpinned rows as deleted."""
    workspace_id, agent_id, session_id = await _create_agent_session(rdb_session)
    repo = ModelFileRepository()
    model_file = await repo.create(
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
            normalized_format="original",
            sha256="1" * 64,
            metadata={},
        ),
    )
    deleted_at = datetime.datetime.now(datetime.UTC)

    deleted = await repo.mark_deleted_if_unpinned(
        rdb_session,
        model_file_ids=[model_file.id],
        deleted_at=deleted_at,
    )

    assert [item.id for item in deleted] == [model_file.id]
    found = await repo.get_by_id(rdb_session, model_file.id)
    assert found is not None
    assert found.status == ModelFileStatus.DELETED
    assert found.deleted_at == deleted_at


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


async def test_release_terminal_run_pins_preserves_pending(
    rdb_session: AsyncSession,
) -> None:
    """Release terminal pins without treating pending runs as terminal."""
    workspace_id, agent_id, session_id = await _create_agent_session(rdb_session)
    model_file = await ModelFileRepository().create(
        rdb_session,
        ModelFileCreate(
            workspace_id=workspace_id,
            session_id=session_id,
            agent_id=agent_id,
            name="pending.txt",
            media_type="text/plain",
            kind="document",
            size_bytes=7,
            created_run_index=1,
            normalized_format="original",
            sha256="3" * 64,
            metadata={},
        ),
    )
    run_repo = AgentRunRepository()
    terminal = await run_repo.create(
        rdb_session,
        AgentRunCreate(
            session_id=session_id,
            requested_model_target_label=None,
            requested_reasoning_effort=None,
            inference_profile_source=None,
            resolved_model_selection=None,
            resolved_reasoning_effort=None,
            resolved_at=None,
            effective_context_window_tokens=None,
            effective_auto_compaction_threshold_tokens=None,
            inference_profile_failure_code=None,
            inference_profile_failure_message=None,
            parent_agent_run_id=None,
        ),
    )
    await run_repo.mark_terminal(
        rdb_session,
        terminal.id,
        AgentRunStatus.COMPLETED,
        ended_at=datetime.datetime.now(datetime.UTC),
    )
    pending = await run_repo.create_pending(
        rdb_session,
        session_id=session_id,
        requested_model_target_label="Quality",
        requested_reasoning_effort=None,
        inference_profile_source=InferenceProfileSource.EXPLICIT_INPUT,
        parent_agent_run_id=None,
        resolved_model_selection=None,
        resolved_reasoning_effort=None,
        resolved_at=None,
        effective_context_window_tokens=None,
        effective_auto_compaction_threshold_tokens=None,
    )
    pin_repo = ModelFilePinRepository()
    await pin_repo.pin_many(
        rdb_session,
        session_id=session_id,
        run_id=terminal.id,
        model_file_ids=[model_file.id],
    )
    await pin_repo.pin_many(
        rdb_session,
        session_id=session_id,
        run_id=pending.id,
        model_file_ids=[model_file.id],
    )

    released = await pin_repo.release_terminal_run_pins(rdb_session, limit=10)
    remaining_run_ids = list(
        (
            await rdb_session.execute(
                sa.select(RDBModelFilePin.run_id).where(
                    RDBModelFilePin.model_file_id == model_file.id
                )
            )
        ).scalars()
    )

    assert released == 1
    assert remaining_run_ids == [pending.id]
