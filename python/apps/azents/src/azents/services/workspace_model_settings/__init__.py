"""Workspace model settings service."""

import dataclasses
from typing import Annotated, assert_never

from azcommon.result import Failure, Result, Success
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection, AgentModelSelectionInput
from azents.rdb.deps import get_session_manager
from azents.rdb.session import SessionManager
from azents.repos.workspace_model_settings import WorkspaceModelSettingsRepository
from azents.repos.workspace_model_settings.data import WorkspaceModelSettingsUpdate
from azents.services.llm_catalog import ModelCatalogReadService

from .data import (
    DefaultModelCannotBeCleared,
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
        return self._build_output(
            default_model_selection=settings.default_model_selection,
            default_lightweight_model_selection=(
                settings.default_lightweight_model_selection
            ),
        )

    async def update(
        self,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdateInput,
    ) -> Result[
        WorkspaceModelSettingsOutput,
        ModelSelectionNotFound | DefaultModelCannotBeCleared,
    ]:
        """Update Workspace default model settings."""
        default_model_selection: AgentModelSelection | None = None
        default_lightweight_model_selection: AgentModelSelection | None = None
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

        async with self.session_manager() as session:
            current = await self.repository.get(session, workspace_id)
            repo_update = WorkspaceModelSettingsUpdate()
            if "default_model_selection" in update.model_fields_set:
                repo_update["default_model_selection"] = default_model_selection
            elif current is not None and current.default_model_selection is not None:
                repo_update["default_model_selection"] = current.default_model_selection
            if "default_lightweight_model_selection" in update.model_fields_set:
                repo_update["default_lightweight_model_selection"] = (
                    default_lightweight_model_selection
                )
            result = await self.repository.update(session, workspace_id, repo_update)
        match result:
            case Success(value):
                return Success(
                    self._build_output(
                        default_model_selection=value.default_model_selection,
                        default_lightweight_model_selection=(
                            value.default_lightweight_model_selection
                        ),
                    )
                )
            case Failure(_):
                return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))
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

    def _build_output(
        self,
        *,
        default_model_selection: AgentModelSelection | None,
        default_lightweight_model_selection: AgentModelSelection | None,
    ) -> WorkspaceModelSettingsOutput:
        """Create output including effective lightweight fallback."""
        return WorkspaceModelSettingsOutput(
            default_model_selection=default_model_selection,
            default_lightweight_model_selection=default_lightweight_model_selection,
            effective_default_lightweight_model_selection=(
                default_lightweight_model_selection or default_model_selection
            ),
        )
