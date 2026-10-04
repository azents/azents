"""Real PostgreSQL Workspace-default operation lifetime and atomicity tests."""

import asyncio
import dataclasses
import datetime
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from azcommon.result import Failure, Result, Success
from sqlalchemy.exc import IntegrityError

from azents.core.agent import (
    AgentModelSelection,
    SelectableModelCandidate,
    SelectableModelOption,
    SelectableModelSettings,
)
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.core.model_execution_options import ModelExecutionOptionId
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.model_candidate_chain_cutover import (
    RDBModelCandidateChainCutover,
)
from azents.rdb.models.workspace_model_settings import RDBWorkspaceModelSettings
from azents.rdb.session import SessionManager
from azents.rdb.session_capabilities import WriteSession
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import (
    DefaultModelCannotBeCleared,
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)
from azents.repos.workspace_model_settings.operations import (
    WorkspaceModelSettingsOperationRepository,
)


class ObservedDefaultsManager:
    """Track completed real Workspace scopes for operation and normalizer tests."""

    def __init__(self, manager: SessionManager[WriteSession]) -> None:
        self.manager = manager
        self.active = False
        self.sessions: list[WriteSession] = []
        self.resolved: list[bool] = []

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[WriteSession]:
        """Resolve the underlying scope before marking the operation complete."""
        assert not self.active
        self.active = True
        current: WriteSession | None = None
        try:
            async with self.manager() as session:
                current = session
                self.sessions.append(session)
                yield session
        finally:
            self.active = False
            if current is not None:
                self.resolved.append(not current.write_session.in_transaction())

    def assert_closed(self) -> None:
        """Assert that a typed catalog/image collaborator sees no Workspace scope."""
        assert not self.active
        assert all(self.resolved)
        assert all(
            not session.write_session.in_transaction() for session in self.sessions
        )


@dataclasses.dataclass(frozen=True)
class MarkerState:
    """Detached downgrade-marker state for transaction rollback comparisons."""

    exists: bool
    written_at: datetime.datetime | None


async def marker_state(session: WriteSession) -> MarkerState:
    """Read the real marker without retaining its ORM row across boundaries."""
    row = await session.read_session.get(RDBModelCandidateChainCutover, 1)
    return MarkerState(
        exists=row is not None,
        written_at=None if row is None else row.new_format_written_at,
    )


async def create_workspace(manager: SessionManager[WriteSession], handle: str) -> str:
    """Create a real Workspace for the settings foreign key."""
    async with manager() as session:
        result = await WorkspaceRepository().create(
            session, WorkspaceCreate(name="Defaults test", handle=handle)
        )
        assert isinstance(result, Success)
        workspace_id = await WorkspaceRepository().resolve_id(session, handle)
        assert workspace_id is not None
        return workspace_id


def selection(model_identifier: str) -> AgentModelSelection:
    """Build a complete catalog/source/capability snapshot with supported IDs."""
    capabilities = ModelCapabilities()
    capabilities.context_window.default_input_tokens = 8192
    capabilities.context_window.max_input_tokens = 65536
    capabilities.context_window.max_output_tokens = 8192
    capabilities.reasoning.supported = True
    return AgentModelSelection(
        pricing=None,
        llm_provider_integration_id="integration-1",
        provider=LLMProvider.OPENAI,
        model_identifier=model_identifier,
        model_display_name=f"Display {model_identifier}",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="test-family",
        normalized_capabilities=capabilities,
        supported_execution_options=[
            ModelExecutionOptionId.FAST,
            ModelExecutionOptionId.ULTRAFAST,
        ],
        model_snapshot={
            "source": "stored_catalog_projection",
            "catalog_id": "catalog-1",
            "snapshot_id": f"snapshot-{model_identifier}",
            "entry_id": f"entry-{model_identifier}",
            "lifecycle_status": "selectable",
        },
        source_metadata={
            "source_kind": "genai_prices",
            "source_snapshot_id": "source-1",
            "provider_identifier": model_identifier,
        },
        last_refreshed_at=datetime.datetime(2026, 10, 1, tzinfo=datetime.UTC),
    )


def full_update() -> WorkspaceModelSettingsUpdate:
    """Build all stored fields with distinct main/lightweight and candidate order."""
    main = selection("raw/main:model")
    fallback = selection("raw/fallback:model")
    lightweight = selection("raw/light:model")
    settings = SelectableModelSettings(
        context_window_tokens=4096, max_output_tokens=512, builtin_tools=[]
    )
    options = [
        SelectableModelOption(
            label="Quality",
            candidates=[
                SelectableModelCandidate(model_selection=main, settings=settings),
                SelectableModelCandidate(model_selection=fallback, settings=settings),
            ],
            subagent_enabled=False,
            subagent_guidance="Use for difficult tasks",
        ),
        SelectableModelOption(
            label="Quick",
            candidates=[
                SelectableModelCandidate(model_selection=lightweight, settings=settings)
            ],
            subagent_enabled=True,
            subagent_guidance=None,
        ),
    ]
    return WorkspaceModelSettingsUpdate(
        default_model_selection=main,
        default_lightweight_model_selection=lightweight,
        default_selectable_model_options=options,
        default_main_model_label="Quality",
        default_lightweight_model_label="Quick",
    )


class _FailAfterWriteRepository(WorkspaceModelSettingsRepository):
    """Observe real marker/settings writes and then fail before commit."""

    def __init__(self) -> None:
        self.observed_marker: MarkerState | None = None
        self.observed_settings: WorkspaceModelSettings | None = None

    async def update(
        self,
        session: WriteSession,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdate,
    ) -> Result[WorkspaceModelSettings, DefaultModelCannotBeCleared]:
        result = await super().update(session, workspace_id, update)
        assert isinstance(result, Success)
        self.observed_settings = result.value
        self.observed_marker = await marker_state(session)
        raise RuntimeError("failed after marker and settings writes")


class _PauseAfterWriteRepository(WorkspaceModelSettingsRepository):
    """Pause after real partial work at an authoritative cancellation boundary."""

    def __init__(self) -> None:
        self.writes_ready = asyncio.Event()
        self.release = asyncio.Event()
        self.observed_marker: MarkerState | None = None

    async def update(
        self,
        session: WriteSession,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdate,
    ) -> Result[WorkspaceModelSettings, DefaultModelCannotBeCleared]:
        result = await super().update(session, workspace_id, update)
        self.observed_marker = await marker_state(session)
        self.writes_ready.set()
        await self.release.wait()
        return result


async def test_current_read_does_not_create_but_get_creates_empty_row(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Current and get-or-create keep their distinct side effects and close."""
    id = await create_workspace(rdb_session_manager, "defaults-empty-operation")
    async with rdb_session_manager() as session:
        before = await marker_state(session)
    manager = ObservedDefaultsManager(rdb_session_manager)
    repository = WorkspaceModelSettingsOperationRepository(
        manager, WorkspaceModelSettingsRepository()
    )
    assert await repository.get(id) is None
    first = await repository.get_or_create(id)
    again = await repository.get_or_create(id)
    assert first == again
    assert first.default_selectable_model_options is None
    assert first.default_model_selection is None
    assert first.default_main_model_label is None
    assert first.created_at and first.updated_at
    assert manager.resolved == [True, True, True]
    manager.assert_closed()
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBWorkspaceModelSettings, id) is not None
        assert await marker_state(session) == before


async def test_complete_update_persists_exact_snapshot_fields_and_marker(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Canonical settings and marker resolve in the same write operation."""
    id = await create_workspace(rdb_session_manager, "defaults-complete-operation")
    manager = ObservedDefaultsManager(rdb_session_manager)
    repository = WorkspaceModelSettingsOperationRepository(
        manager, WorkspaceModelSettingsRepository()
    )
    update = full_update()
    result = await repository.update(id, update)
    assert isinstance(result, Success)
    manager.assert_closed()
    assert manager.resolved == [True]
    async with rdb_session_manager() as session:
        row = await session.read_session.get(RDBWorkspaceModelSettings, id)
        assert row is not None
        main = update["default_model_selection"]
        lightweight = update["default_lightweight_model_selection"]
        options = update["default_selectable_model_options"]
        assert main is not None and lightweight is not None and options is not None
        assert row.default_model_selection == main.model_dump(mode="json")
        assert row.default_lightweight_model_selection == lightweight.model_dump(
            mode="json"
        )
        assert row.default_selectable_model_options == [
            option.model_dump(mode="json") for option in options
        ]
        assert row.default_main_model_label == "Quality"
        assert row.default_lightweight_model_label == "Quick"
        assert (await marker_state(session)).written_at is not None


@pytest.mark.parametrize(
    "field", ["default_model_selection", "default_selectable_model_options"]
)
async def test_configured_defaults_cannot_clear_and_failure_leaves_snapshot_unchanged(
    rdb_session_manager: SessionManager[WriteSession], field: str
) -> None:
    """The existing narrow clear guard retains settings and downgrade state."""
    id = await create_workspace(rdb_session_manager, f"defaults-guard-{field}")
    repository = WorkspaceModelSettingsOperationRepository(
        rdb_session_manager, WorkspaceModelSettingsRepository()
    )
    created = await repository.update(id, full_update())
    assert isinstance(created, Success)
    async with rdb_session_manager() as session:
        before = await marker_state(session)
    update: WorkspaceModelSettingsUpdate
    if field == "default_model_selection":
        update = WorkspaceModelSettingsUpdate(default_model_selection=None)
    else:
        update = WorkspaceModelSettingsUpdate(default_selectable_model_options=None)
    assert await repository.update(id, update) == Failure(
        DefaultModelCannotBeCleared(workspace_id=id)
    )
    assert await repository.get(id) == created.value
    async with rdb_session_manager() as session:
        assert await marker_state(session) == before


async def test_marker_first_constraint_failure_rolls_back_marker_and_empty_settings(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A settings constraint failure after marker SQL commits neither write."""
    id = await create_workspace(rdb_session_manager, "defaults-marker-first-failure")
    async with rdb_session_manager() as session:
        before = await marker_state(session)
    manager = ObservedDefaultsManager(rdb_session_manager)
    repository = WorkspaceModelSettingsOperationRepository(
        manager, WorkspaceModelSettingsRepository()
    )
    with pytest.raises(IntegrityError):
        await repository.update(
            id, WorkspaceModelSettingsUpdate(default_selectable_model_options=[])
        )
    manager.assert_closed()
    assert manager.resolved == [True]
    assert await repository.get(id) is None
    async with rdb_session_manager() as session:
        assert await marker_state(session) == before


async def test_failure_after_both_writes_rolls_back_existing_settings_and_marker(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """A late exception abandons real settings and marker changes together."""
    id = await create_workspace(rdb_session_manager, "defaults-late-write-failure")
    ordinary = WorkspaceModelSettingsOperationRepository(
        rdb_session_manager, WorkspaceModelSettingsRepository()
    )
    empty = await ordinary.get_or_create(id)
    async with rdb_session_manager() as session:
        before = await marker_state(session)
    manager = ObservedDefaultsManager(rdb_session_manager)
    writes = _FailAfterWriteRepository()
    repository = WorkspaceModelSettingsOperationRepository(manager, writes)
    with pytest.raises(RuntimeError, match="failed after marker and settings writes"):
        await repository.update(id, full_update())
    assert writes.observed_settings is not None
    assert writes.observed_settings.default_selectable_model_options is not None
    assert (
        writes.observed_marker is not None
        and writes.observed_marker.written_at is not None
    )
    manager.assert_closed()
    assert await ordinary.get(id) == empty
    async with rdb_session_manager() as session:
        assert await marker_state(session) == before


async def test_cancellation_after_both_writes_propagates_and_rolls_back(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Cancellation at an observed database boundary leaves no committed work."""
    id = await create_workspace(rdb_session_manager, "defaults-cancelled-write")
    async with rdb_session_manager() as session:
        before = await marker_state(session)
    manager = ObservedDefaultsManager(rdb_session_manager)
    writes = _PauseAfterWriteRepository()
    repository = WorkspaceModelSettingsOperationRepository(manager, writes)
    task = asyncio.create_task(repository.update(id, full_update()))
    try:
        await asyncio.wait_for(writes.writes_ready.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert task.cancelled()
    assert (
        writes.observed_marker is not None
        and writes.observed_marker.written_at is not None
    )
    manager.assert_closed()
    assert manager.resolved == [True]
    async with rdb_session_manager() as session:
        assert await session.read_session.get(RDBWorkspaceModelSettings, id) is None
        assert await marker_state(session) == before


@pytest.mark.parametrize("lightweight", [False, True])
async def test_configured_label_clear_is_rejected_by_complete_operation(
    rdb_session_manager: SessionManager[WriteSession], lightweight: bool
) -> None:
    """Internal partial updates cannot invalidate configured default label authority."""
    id = await create_workspace(rdb_session_manager, "defaults-repository-null-label")
    operations = WorkspaceModelSettingsOperationRepository(
        rdb_session_manager, WorkspaceModelSettingsRepository()
    )
    configured = await operations.update(id, full_update())
    assert isinstance(configured, Success)
    update: WorkspaceModelSettingsUpdate = {}
    if lightweight:
        update["default_lightweight_model_label"] = None
    else:
        update["default_main_model_label"] = None
    assert await operations.update(id, update) == Failure(
        DefaultModelCannotBeCleared(id)
    )
    assert await operations.get(id) == configured.value


async def test_initial_label_null_remains_valid_absence(
    rdb_session_manager: SessionManager[WriteSession],
) -> None:
    """Empty Workspace settings retain their initial nullable label representation."""
    id = await create_workspace(rdb_session_manager, "defaults-repository-initial-null")
    operations = WorkspaceModelSettingsOperationRepository(
        rdb_session_manager, WorkspaceModelSettingsRepository()
    )
    result = await operations.update(
        id,
        WorkspaceModelSettingsUpdate(
            default_main_model_label=None, default_lightweight_model_label=None
        ),
    )
    assert isinstance(result, Success)
    assert result.value.default_main_model_label is None
    assert result.value.default_lightweight_model_label is None
