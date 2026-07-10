"""Workspace model settings service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelOptionInput,
)
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import (
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)
from azents.services.llm_catalog import ModelCatalogReadService
from azents.services.model_options import (
    NormalizedSelectableModelOptions,
    build_legacy_selectable_model_options,
    normalize_selectable_model_options,
    normalize_stored_selectable_model_options,
)

from .data import (
    DefaultModelCannotBeCleared,
    InvalidSelectableModelOptions,
    ModelSelectionNotFound,
    WorkspaceModelSettingsOutput,
    WorkspaceModelSettingsUpdateInput,
)


@dataclasses.dataclass
class WorkspaceModelSettingsService:
    """Workspace default model settings service."""

    repository: Annotated[
        WorkspaceModelSettingsRepository, Depends(WorkspaceModelSettingsRepository)
    ]
    model_catalog_read_service: Annotated[ModelCatalogReadService, Depends()]
    session_manager: Annotated[
        SessionManager[AsyncSession], Depends(get_session_manager)
    ]

    async def get(self, workspace_id: str) -> WorkspaceModelSettingsOutput:
        """Fetch Workspace default model settings."""
        async with self.session_manager() as session:
            settings = await self.repository.get_or_create(session, workspace_id)
        return self._build_output_from_settings(settings)

    async def update(
        self,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdateInput,
    ) -> Result[
        WorkspaceModelSettingsOutput,
        ModelSelectionNotFound
        | InvalidSelectableModelOptions
        | DefaultModelCannotBeCleared,
    ]:
        """Update Workspace default model settings."""
        async with self.session_manager() as session:
            current = await self.repository.get(session, workspace_id)

        model_options: NormalizedSelectableModelOptions | None = None
        if (
            "default_selectable_model_options" in update.model_fields_set
            and update.default_selectable_model_options is None
        ):
            if (
                current is not None
                and current.default_selectable_model_options is not None
            ):
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
            async with self.session_manager() as session:
                current_or_empty = await self.repository.get_or_create(
                    session, workspace_id
                )
            return Success(self._build_output_from_settings(current_or_empty))
        if update.default_selectable_model_options is not None:
            options_result = await self._normalize_option_inputs(
                workspace_id,
                update.default_selectable_model_options,
                main_model_label=update.default_main_model_label,
                lightweight_model_label=update.default_lightweight_model_label,
            )
            match options_result:
                case Success(value):
                    model_options = value
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(options_result)
        elif (
            "default_model_selection" in update.model_fields_set
            or "default_lightweight_model_selection" in update.model_fields_set
        ):
            default_model_selection = (
                current.default_model_selection if current else None
            )
            if update.default_model_selection is not None:
                result = await self._resolve_model_selection_input(
                    workspace_id,
                    update.default_model_selection,
                )
                match result:
                    case Success(value):
                        default_model_selection = value
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(result)
            elif "default_model_selection" in update.model_fields_set:
                default_model_selection = None

            if default_model_selection is None:
                async with self.session_manager() as session:
                    result = await self.repository.update(
                        session,
                        workspace_id,
                        WorkspaceModelSettingsUpdate(default_model_selection=None),
                    )
                match result:
                    case Success(value):
                        return Success(self._build_output_from_settings(value))
                    case Failure(_):
                        return Failure(
                            DefaultModelCannotBeCleared(workspace_id=workspace_id)
                        )
                    case _:
                        assert_never(result)

            default_lightweight_model_selection = (
                current.default_lightweight_model_selection if current else None
            )
            if update.default_lightweight_model_selection is not None:
                result = await self._resolve_model_selection_input(
                    workspace_id,
                    update.default_lightweight_model_selection,
                )
                match result:
                    case Success(value):
                        default_lightweight_model_selection = value
                    case Failure(error):
                        return Failure(error)
                    case _:
                        assert_never(result)
            elif "default_lightweight_model_selection" in update.model_fields_set:
                default_lightweight_model_selection = default_model_selection
            if default_lightweight_model_selection is None:
                default_lightweight_model_selection = default_model_selection
            model_options = build_legacy_selectable_model_options(
                model_selection=default_model_selection,
                lightweight_model_selection=default_lightweight_model_selection,
                main_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                lightweight_label=DEFAULT_LIGHTWEIGHT_MODEL_OPTION_LABEL,
            )
        elif "default_main_model_label" in update.model_fields_set or (
            "default_lightweight_model_label" in update.model_fields_set
        ):
            if current is None or current.default_selectable_model_options is None:
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
            model_options = normalize_stored_selectable_model_options(
                selectable_model_options=current.default_selectable_model_options,
                main_model_label=update.default_main_model_label
                or current.default_main_model_label,
                lightweight_model_label=update.default_lightweight_model_label
                or current.default_lightweight_model_label,
            )

        if model_options is None:
            async with self.session_manager() as session:
                current_or_empty = await self.repository.get_or_create(
                    session, workspace_id
                )
            return Success(self._build_output_from_settings(current_or_empty))

        repo_update = WorkspaceModelSettingsUpdate(
            default_model_selection=model_options.model_selection,
            default_lightweight_model_selection=model_options.lightweight_model_selection,
            default_selectable_model_options=model_options.selectable_model_options,
            default_main_model_label=model_options.main_model_label,
            default_lightweight_model_label=model_options.lightweight_model_label,
        )
        async with self.session_manager() as session:
            result = await self.repository.update(session, workspace_id, repo_update)
        match result:
            case Success(value):
                return Success(self._build_output_from_settings(value))
            case Failure(_):
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
            case _:
                assert_never(result)

    async def _normalize_option_inputs(
        self,
        workspace_id: str,
        option_inputs: list[SelectableModelOptionInput],
        *,
        main_model_label: str | None,
        lightweight_model_label: str | None,
    ) -> Result[
        NormalizedSelectableModelOptions,
        InvalidSelectableModelOptions | ModelSelectionNotFound,
    ]:
        """Normalize default selectable option inputs into stored snapshots."""

        async def resolve_option(
            option_input: SelectableModelOptionInput,
        ) -> Result[AgentModelSelection, ModelSelectionNotFound]:
            return await self._resolve_model_selection_input(
                workspace_id,
                option_input.model_selection,
            )

        result = await normalize_selectable_model_options(
            option_inputs=option_inputs,
            main_model_label=main_model_label,
            lightweight_model_label=lightweight_model_label,
            resolve_model_selection=resolve_option,
        )
        match result:
            case Success(value):
                return Success(value)
            case Failure(error):
                if isinstance(error, list):
                    return Failure(InvalidSelectableModelOptions(errors=error))
                return Failure(error)
            case _:
                assert_never(result)

    async def _resolve_model_selection_input(
        self,
        workspace_id: str,
        selection_input: AgentModelSelectionInput,
    ) -> Result[AgentModelSelection, ModelSelectionNotFound]:
        """Convert model selection input to stored catalog snapshot."""
        result = await self.model_catalog_read_service.resolve_agent_model_selection(
            workspace_id=workspace_id,
            selection_input=selection_input,
        )
        match result:
            case Success(value):
                return Success(value)
            case Failure(_):
                return Failure(
                    ModelSelectionNotFound(
                        llm_provider_integration_id=(
                            selection_input.llm_provider_integration_id
                        ),
                        model_identifier=selection_input.model_identifier,
                    )
                )
            case _:
                assert_never(result)

    def _build_output_from_settings(
        self,
        settings: WorkspaceModelSettings,
    ) -> WorkspaceModelSettingsOutput:
        """Create output including effective lightweight fallback."""
        return WorkspaceModelSettingsOutput(
            default_model_selection=settings.default_model_selection,
            default_lightweight_model_selection=(
                settings.default_lightweight_model_selection
            ),
            default_selectable_model_options=settings.default_selectable_model_options,
            default_main_model_label=settings.default_main_model_label,
            default_lightweight_model_label=settings.default_lightweight_model_label,
            effective_default_lightweight_model_selection=(
                settings.default_lightweight_model_selection
                or settings.default_model_selection
            ),
        )
