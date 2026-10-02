"""Workspace-default service normalization boundaries and preserved input rules."""

import asyncio
import dataclasses
from typing import Literal

import pytest
from azcommon.result import Failure, Result, Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelCandidateInput,
    SelectableModelOptionInput,
    SelectableModelSettings,
    SelectableModelSettingsInput,
)
from azents.rdb.models.workspace_model_settings import RDBWorkspaceModelSettings
from azents.rdb.session import SessionManager
from azents.repos.llm_catalog.data import CatalogNotFound
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import (
    DefaultModelCannotBeCleared as RepositoryClearError,
)
from azents.repos.workspace_model_settings.data import (
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)
from azents.repos.workspace_model_settings.operations import (
    WorkspaceModelSettingsOperationRepository,
)
from azents.repos.workspace_model_settings.operations_test import (
    ObservedDefaultsManager,
    create_workspace,
    full_update,
    marker_state,
    selection,
)
from azents.services.image_generation_catalog import ImageGenerationCatalogService
from azents.services.llm_catalog import ModelCatalogReadService
from azents.services.workspace_model_settings import WorkspaceModelSettingsService
from azents.services.workspace_model_settings.data import (
    DefaultModelCannotBeCleared,
    InvalidSelectableModelOptions,
    ModelSelectionNotFound,
    WorkspaceModelSettingsUpdateInput,
)


@dataclasses.dataclass(frozen=True)
class _CatalogCall:
    workspace_id: str
    input: AgentModelSelectionInput
    completed_scopes: int


@dataclasses.dataclass(frozen=True)
class _ImageCall:
    workspace_id: str
    selection: AgentModelSelection
    settings: SelectableModelSettings
    completed_scopes: int


class _Catalog(ModelCatalogReadService):
    """Typed detached catalog resolver that rejects an active Workspace scope."""

    def __init__(
        self,
        manager: ObservedDefaultsManager,
        missing: set[str],
        error: BaseException | None,
    ) -> None:
        self.manager = manager
        self.missing = missing
        self.error = error
        self.calls: list[_CatalogCall] = []

    async def resolve_agent_model_selection(
        self, *, workspace_id: str, selection_input: AgentModelSelectionInput
    ) -> Result[AgentModelSelection, CatalogNotFound]:
        self.manager.assert_closed()
        self.calls.append(
            _CatalogCall(workspace_id, selection_input, len(self.manager.resolved))
        )
        if self.error is not None:
            raise self.error
        if selection_input.model_identifier in self.missing:
            return Failure(
                CatalogNotFound(
                    integration_id=selection_input.llm_provider_integration_id
                )
            )
        return Success(selection(selection_input.model_identifier))


class _Images(ImageGenerationCatalogService):
    """Typed image validator that remains outside the Workspace transaction."""

    def __init__(
        self,
        manager: ObservedDefaultsManager,
        errors: list[str],
        error: BaseException | None,
    ) -> None:
        self.manager = manager
        self.errors = errors
        self.error = error
        self.calls: list[_ImageCall] = []

    async def validate_option(
        self,
        *,
        workspace_id: str,
        selection: AgentModelSelection,
        settings: SelectableModelSettings,
    ) -> list[str]:
        self.manager.assert_closed()
        self.calls.append(
            _ImageCall(workspace_id, selection, settings, len(self.manager.resolved))
        )
        if self.error is not None:
            raise self.error
        return list(self.errors)


@dataclasses.dataclass(frozen=True)
class _Fixture:
    workspace_id: str
    manager: ObservedDefaultsManager
    operations: WorkspaceModelSettingsOperationRepository
    service: WorkspaceModelSettingsService
    catalog: _Catalog
    images: _Images


async def _fixture(
    manager: SessionManager[AsyncSession],
    handle: str,
    *,
    missing: set[str],
    image_errors: list[str],
    catalog_error: BaseException | None,
    image_error: BaseException | None,
) -> _Fixture:
    id = await create_workspace(manager, handle)
    observed = ObservedDefaultsManager(manager)
    operations = WorkspaceModelSettingsOperationRepository(
        observed, WorkspaceModelSettingsRepository()
    )
    catalog = _Catalog(observed, missing, catalog_error)
    images = _Images(observed, image_errors, image_error)
    service = WorkspaceModelSettingsService(
        repository=operations,
        model_catalog_read_service=catalog,
        image_generation_catalog_service=images,
    )
    return _Fixture(id, observed, operations, service, catalog, images)


def _inputs() -> list[SelectableModelOptionInput]:
    update = full_update()
    options = update["default_selectable_model_options"]
    assert options is not None
    return [
        SelectableModelOptionInput(
            label=f"  {option.label}  ",
            candidates=[
                SelectableModelCandidateInput(
                    model_selection=AgentModelSelectionInput(
                        llm_provider_integration_id=candidate.model_selection.llm_provider_integration_id,
                        model_identifier=candidate.model_selection.model_identifier,
                    ),
                    settings=SelectableModelSettingsInput(
                        context_window_tokens=candidate.settings.context_window_tokens,
                        max_output_tokens=candidate.settings.max_output_tokens,
                        builtin_tools=candidate.settings.builtin_tools,
                    ),
                )
                for candidate in option.candidates
            ],
            subagent_enabled=option.subagent_enabled,
            subagent_guidance=None
            if option.subagent_guidance is None
            else f"  {option.subagent_guidance}  ",
        )
        for option in options
    ]


async def test_normalizers_see_closed_current_scope_and_final_snapshot_is_exact(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Typed collaborators run between current read and the complete final write."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-normalization-boundary",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    result = await fixture.service.update(
        fixture.workspace_id,
        WorkspaceModelSettingsUpdateInput(
            default_selectable_model_options=_inputs(),
            default_main_model_label="  Quality  ",
            default_lightweight_model_label=" Quick ",
        ),
    )
    assert isinstance(result, Success)
    assert fixture.manager.resolved == [True, True]
    fixture.manager.assert_closed()
    assert [call.input.model_identifier for call in fixture.catalog.calls] == [
        "raw/main:model",
        "raw/fallback:model",
        "raw/light:model",
    ]
    assert [call.selection.model_identifier for call in fixture.images.calls] == [
        "raw/main:model",
        "raw/fallback:model",
        "raw/light:model",
    ]
    assert all(
        call.workspace_id == fixture.workspace_id and call.completed_scopes == 1
        for call in fixture.catalog.calls
    )
    assert all(
        call.workspace_id == fixture.workspace_id and call.completed_scopes == 1
        for call in fixture.images.calls
    )
    expected = full_update()
    options = expected["default_selectable_model_options"]
    assert options is not None
    assert result.value.default_selectable_model_options == options
    assert result.value.default_model_selection == expected["default_model_selection"]
    assert (
        result.value.default_lightweight_model_selection
        == expected["default_lightweight_model_selection"]
    )
    assert result.value.default_main_model_label == "Quality"
    assert result.value.default_lightweight_model_label == "Quick"
    async with rdb_session_manager() as session:
        stored = await session.get(RDBWorkspaceModelSettings, fixture.workspace_id)
        assert stored is not None
        assert stored.default_selectable_model_options == [
            option.model_dump(mode="json") for option in options
        ]
        assert (await marker_state(session)).written_at is not None


async def test_get_creates_empty_row_without_catalog_and_preserves_lightweight_fallback(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """GET's side effect and legacy effective lightweight fallback remain exact."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-service-get",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    assert await fixture.operations.get(fixture.workspace_id) is None
    output = await fixture.service.get(fixture.workspace_id)
    assert output.default_selectable_model_options is None
    assert output.effective_default_lightweight_model_selection is None
    assert await fixture.operations.get(fixture.workspace_id) is not None
    update = full_update()
    update["default_lightweight_model_selection"] = None
    await fixture.operations.update(fixture.workspace_id, update)
    fallback = await fixture.service.get(fixture.workspace_id)
    assert fallback.default_lightweight_model_selection is None
    assert (
        fallback.effective_default_lightweight_model_selection
        == update["default_model_selection"]
    )
    assert fixture.catalog.calls == []
    assert fixture.images.calls == []
    fixture.manager.assert_closed()


@pytest.mark.parametrize(
    ("update", "expected_error", "creates_row"),
    [
        (WorkspaceModelSettingsUpdateInput(), None, True),
        (
            WorkspaceModelSettingsUpdateInput(default_selectable_model_options=None),
            None,
            True,
        ),
        (
            WorkspaceModelSettingsUpdateInput(
                default_selectable_model_options=None,
                default_main_model_label="Ignored",
            ),
            None,
            True,
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label=None),
            DefaultModelCannotBeCleared,
            False,
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_lightweight_model_label=None),
            DefaultModelCannotBeCleared,
            False,
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label="Quality"),
            DefaultModelCannotBeCleared,
            False,
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_selectable_model_options=[]),
            InvalidSelectableModelOptions,
            False,
        ),
    ],
)
async def test_empty_row_null_omission_and_label_error_matrix(
    rdb_session_manager: SessionManager[AsyncSession],
    update: WorkspaceModelSettingsUpdateInput,
    expected_error: type[object] | None,
    creates_row: bool,
) -> None:
    """Null/omission branches keep existing empty-row creation and rejection rules."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-empty-matrix",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    async with rdb_session_manager() as session:
        marker_before = await marker_state(session)
    result = await fixture.service.update(fixture.workspace_id, update)
    if expected_error is None:
        assert isinstance(result, Success)
        assert result.value.default_selectable_model_options is None
        assert result.value.default_main_model_label is None
        assert result.value.default_lightweight_model_label is None
    else:
        assert isinstance(result, Failure)
        assert isinstance(result.error, expected_error)
    assert len(fixture.manager.sessions) == (2 if creates_row else 1)
    assert fixture.catalog.calls == [] and fixture.images.calls == []
    fixture.manager.assert_closed()
    async with rdb_session_manager() as session:
        assert (
            await session.get(RDBWorkspaceModelSettings, fixture.workspace_id)
            is not None
        ) == creates_row
        assert await marker_state(session) == marker_before


@pytest.mark.parametrize(
    ("update", "main", "lightweight"),
    [
        (WorkspaceModelSettingsUpdateInput(), "Quality", "Quick"),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label=None),
            "Quality",
            "Quick",
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_lightweight_model_label=None),
            "Quality",
            "Quick",
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label=""),
            "Quality",
            "Quick",
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label="Unknown"),
            "Quality",
            "Quick",
        ),
        (
            WorkspaceModelSettingsUpdateInput(
                default_lightweight_model_label="Unknown"
            ),
            "Quality",
            "Quality",
        ),
        (
            WorkspaceModelSettingsUpdateInput(default_main_model_label=" Quick "),
            "Quick",
            "Quick",
        ),
        (
            WorkspaceModelSettingsUpdateInput(
                default_main_model_label="Quick",
                default_lightweight_model_label="Quality",
            ),
            "Quick",
            "Quality",
        ),
    ],
)
async def test_configured_label_only_matrix_preserves_options_without_catalog_refresh(
    rdb_session_manager: SessionManager[AsyncSession],
    update: WorkspaceModelSettingsUpdateInput,
    main: str,
    lightweight: str,
) -> None:
    """Label null uses stored fallback; unknown labels use first ordered option."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-label-matrix",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    configured = full_update()
    await fixture.operations.update(fixture.workspace_id, configured)
    result = await fixture.service.update(fixture.workspace_id, update)
    assert isinstance(result, Success)
    assert result.value.default_main_model_label == main
    assert result.value.default_lightweight_model_label == lightweight
    assert (
        result.value.default_selectable_model_options
        == configured["default_selectable_model_options"]
    )
    assert fixture.catalog.calls == [] and fixture.images.calls == []
    fixture.manager.assert_closed()


async def test_configured_options_null_is_rejected_without_final_write(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Configured options cannot be cleared even if labels are supplied as well."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-clear-configured",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    configured = await fixture.operations.update(fixture.workspace_id, full_update())
    assert isinstance(configured, Success)
    result = await fixture.service.update(
        fixture.workspace_id,
        WorkspaceModelSettingsUpdateInput(
            default_selectable_model_options=None, default_main_model_label="Quick"
        ),
    )
    assert result == Failure(
        DefaultModelCannotBeCleared(workspace_id=fixture.workspace_id)
    )
    assert len(fixture.manager.sessions) == 2
    assert fixture.catalog.calls == [] and fixture.images.calls == []
    assert await fixture.operations.get(fixture.workspace_id) == configured.value


@pytest.mark.parametrize("failure_source", ["catalog", "image"])
async def test_catalog_and_image_rejections_keep_distinct_domain_results(
    rdb_session_manager: SessionManager[AsyncSession],
    failure_source: Literal["catalog", "image"],
) -> None:
    """Catalog miss and image eligibility rejection retain their distinct mappings."""
    fixture = await _fixture(
        rdb_session_manager,
        f"defaults-rejection-{failure_source}",
        missing={"raw/main:model"} if failure_source == "catalog" else set(),
        image_errors=["Enable the provider integration before using image generation."]
        if failure_source == "image"
        else [],
        catalog_error=None,
        image_error=None,
    )
    result = await fixture.service.update(
        fixture.workspace_id,
        WorkspaceModelSettingsUpdateInput(default_selectable_model_options=_inputs()),
    )
    assert isinstance(result, Failure)
    if failure_source == "catalog":
        assert result.error == ModelSelectionNotFound(
            llm_provider_integration_id="integration-1",
            model_identifier="raw/main:model",
        )
        assert fixture.images.calls == []
    else:
        assert isinstance(result.error, InvalidSelectableModelOptions)
        assert any(
            "Enable the provider integration" in error for error in result.error.errors
        )
    assert len(fixture.manager.sessions) == 1
    fixture.manager.assert_closed()
    async with rdb_session_manager() as session:
        assert (
            await session.get(RDBWorkspaceModelSettings, fixture.workspace_id) is None
        )


@pytest.mark.parametrize(
    ("failure_source", "cancel"),
    [("catalog", False), ("image", False), ("catalog", True), ("image", True)],
)
async def test_failed_or_cancelled_normalization_propagates_without_final_write(
    rdb_session_manager: SessionManager[AsyncSession],
    failure_source: Literal["catalog", "image"],
    cancel: bool,
) -> None:
    """External normalization failure/cancellation never becomes a DB callback/retry."""
    error = asyncio.CancelledError() if cancel else RuntimeError("normalization failed")
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-normalization-exception",
        missing=set(),
        image_errors=[],
        catalog_error=error if failure_source == "catalog" else None,
        image_error=error if failure_source == "image" else None,
    )
    with pytest.raises(type(error)):
        await fixture.service.update(
            fixture.workspace_id,
            WorkspaceModelSettingsUpdateInput(
                default_selectable_model_options=_inputs()
            ),
        )
    assert len(fixture.catalog.calls) == 1
    assert len(fixture.images.calls) == (1 if failure_source == "image" else 0)
    assert fixture.manager.resolved == [True]
    fixture.manager.assert_closed()
    async with rdb_session_manager() as session:
        assert (
            await session.get(RDBWorkspaceModelSettings, fixture.workspace_id) is None
        )


class _RejectUpdateRepository(WorkspaceModelSettingsRepository):
    """Return the existing narrow error to verify service result translation."""

    async def update(
        self,
        session: AsyncSession,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdate,
    ) -> Result[WorkspaceModelSettings, RepositoryClearError]:
        del session, update
        return Failure(RepositoryClearError(workspace_id=workspace_id))


async def test_final_repository_failure_maps_existing_service_error_after_resolution(
    rdb_session_manager: SessionManager[AsyncSession],
) -> None:
    """Translate final rejection after the write scope has closed."""
    fixture = await _fixture(
        rdb_session_manager,
        "defaults-final-rejection",
        missing=set(),
        image_errors=[],
        catalog_error=None,
        image_error=None,
    )
    fixture.operations.settings_repository = _RejectUpdateRepository()
    result = await fixture.service.update(
        fixture.workspace_id,
        WorkspaceModelSettingsUpdateInput(default_selectable_model_options=_inputs()),
    )
    assert result == Failure(
        DefaultModelCannotBeCleared(workspace_id=fixture.workspace_id)
    )
    assert fixture.manager.resolved == [True, True]
    fixture.manager.assert_closed()
