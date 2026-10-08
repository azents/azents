"""Workspace model settings service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends

from azents.core.active_model_capabilities import ConfiguredModelIdentity
from azents.core.agent import (
    AgentModelSelection,
    AgentModelSelectionInput,
    SelectableModelCandidateInput,
    SelectableModelOptionInput,
    SelectableModelSettings,
)
from azents.repos.workspace_model_settings.data import (
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)
from azents.repos.workspace_model_settings.operations import (
    WorkspaceModelSettingsOperationRepository,
)
from azents.services.active_model_capabilities import (
    ActiveModelCapabilitiesService,
    apply_to_workspace_read,
)
from azents.services.image_generation_catalog import ImageGenerationCatalogService
from azents.services.llm_catalog import ModelCatalogReadService
from azents.services.model_options import (
    NormalizedSelectableModelOptions,
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
        WorkspaceModelSettingsOperationRepository,
        Depends(WorkspaceModelSettingsOperationRepository),
    ]
    model_catalog_read_service: Annotated[ModelCatalogReadService, Depends()]
    image_generation_catalog_service: Annotated[
        ImageGenerationCatalogService, Depends()
    ]
    active_model_capabilities_service: Annotated[
        ActiveModelCapabilitiesService, Depends(ActiveModelCapabilitiesService)
    ]

    async def get(self, workspace_id: str) -> WorkspaceModelSettingsOutput:
        """Fetch Workspace default model settings."""
        settings = await self.repository.get_or_create(workspace_id)
        return await self._build_active_output_from_settings(settings)

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
        current = await self.repository.get(workspace_id)

        model_options: NormalizedSelectableModelOptions | None = None
        option_inputs = update.get("default_selectable_model_options")
        main_model_label = update.get("default_main_model_label")
        lightweight_model_label = update.get("default_lightweight_model_label")
        if "default_selectable_model_options" in update and option_inputs is None:
            if (
                current is not None
                and current.default_selectable_model_options is not None
            ):
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
            current_or_empty = await self.repository.get_or_create(workspace_id)
            return Success(
                await self._build_active_output_from_settings(current_or_empty)
            )
        configured_options = (
            current.default_selectable_model_options if current is not None else None
        )
        if (configured_options is not None or option_inputs) and (
            ("default_main_model_label" in update and main_model_label is None)
            or (
                "default_lightweight_model_label" in update
                and lightweight_model_label is None
            )
        ):
            return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
        if "default_main_model_label" not in update and current is not None:
            main_model_label = current.default_main_model_label
        if "default_lightweight_model_label" not in update and current is not None:
            lightweight_model_label = current.default_lightweight_model_label
        if option_inputs is not None:
            options_result = await self._normalize_option_inputs(
                workspace_id,
                option_inputs,
                main_model_label=main_model_label,
                lightweight_model_label=lightweight_model_label,
            )
            match options_result:
                case Success(value):
                    model_options = value
                case Failure(error):
                    return Failure(error)
                case _:
                    assert_never(options_result)
        elif "default_main_model_label" in update or (
            "default_lightweight_model_label" in update
        ):
            if current is None or current.default_selectable_model_options is None:
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
            model_options = normalize_stored_selectable_model_options(
                selectable_model_options=current.default_selectable_model_options,
                main_model_label=(
                    current.default_main_model_label
                    if main_model_label == ""
                    else main_model_label
                ),
                lightweight_model_label=(
                    current.default_lightweight_model_label
                    if lightweight_model_label == ""
                    else lightweight_model_label
                ),
            )

        if model_options is None:
            current_or_empty = await self.repository.get_or_create(workspace_id)
            return Success(
                await self._build_active_output_from_settings(current_or_empty)
            )

        repo_update = WorkspaceModelSettingsUpdate(
            default_model_selection=model_options.model_selection,
            default_lightweight_model_selection=model_options.lightweight_model_selection,
            default_selectable_model_options=model_options.selectable_model_options,
            default_main_model_label=model_options.main_model_label,
            default_lightweight_model_label=model_options.lightweight_model_label,
        )
        result = await self.repository.update(workspace_id, repo_update)
        match result:
            case Success(value):
                return Success(await self._build_active_output_from_settings(value))
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
            candidate_input: SelectableModelCandidateInput,
        ) -> Result[AgentModelSelection, ModelSelectionNotFound]:
            return await self._resolve_model_selection_input(
                workspace_id,
                candidate_input.model_selection,
            )

        async def validate_image_generation_config(
            selection: AgentModelSelection,
            settings: SelectableModelSettings,
        ) -> list[str]:
            return await self.image_generation_catalog_service.validate_option(
                workspace_id=workspace_id,
                selection=selection,
                settings=settings,
            )

        result = await normalize_selectable_model_options(
            option_inputs=option_inputs,
            main_model_label=main_model_label,
            lightweight_model_label=lightweight_model_label,
            resolve_model_selection=resolve_option,
            validate_image_generation_config=validate_image_generation_config,
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

    async def _build_active_output_from_settings(
        self, settings: WorkspaceModelSettings
    ) -> WorkspaceModelSettingsOutput:
        """Compile detached response metadata after any raw settings write."""
        selections: dict[ConfiguredModelIdentity, AgentModelSelection] = {}
        choices = [
            candidate.model_selection
            for option in settings.default_selectable_model_options or []
            for candidate in option.candidates
        ]
        for selection in (
            *choices,
            settings.default_model_selection,
            settings.default_lightweight_model_selection,
        ):
            if selection is not None:
                selections.setdefault(
                    ConfiguredModelIdentity.from_selection(selection), selection
                )
        if not selections:
            return self._build_output_from_settings(settings)
        compiled = await self.active_model_capabilities_service.capture_and_compile(
            workspace_id=settings.workspace_id,
            selections=list(selections.values()),
        )
        return self._build_output_from_settings(
            apply_to_workspace_read(settings, compiled)
        )

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
