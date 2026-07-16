"""Workspace model settings repository."""

import sqlalchemy as sa
from azcommon.result import Failure, Result, Success
from pydantic import TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import (
    DEFAULT_MAIN_MODEL_OPTION_LABEL,
    AgentModelSelection,
    SelectableModelOption,
    default_selectable_model_settings,
)
from azents.rdb.models.workspace_model_settings import RDBWorkspaceModelSettings

from .data import (
    DefaultModelCannotBeCleared,
    WorkspaceModelSettings,
    WorkspaceModelSettingsUpdate,
)

_model_selection_adapter = TypeAdapter[AgentModelSelection](AgentModelSelection)
_selectable_model_options_adapter = TypeAdapter[list[SelectableModelOption]](
    list[SelectableModelOption]
)


class WorkspaceModelSettingsRepository:
    """Workspace default model settings CRUD repository."""

    async def get(
        self,
        session: AsyncSession,
        workspace_id: str,
    ) -> WorkspaceModelSettings | None:
        """Fetch Workspace settings."""
        row = await session.get(RDBWorkspaceModelSettings, workspace_id)
        if row is None:
            return None
        return self._build(row)

    async def get_or_create(
        self,
        session: AsyncSession,
        workspace_id: str,
    ) -> WorkspaceModelSettings:
        """Fetch Workspace settings or create empty row."""
        row = await session.get(RDBWorkspaceModelSettings, workspace_id)
        if row is None:
            row = RDBWorkspaceModelSettings(workspace_id=workspace_id)
            session.add(row)
            await session.flush()
            await session.refresh(row)
        return self._build(row)

    async def update(
        self,
        session: AsyncSession,
        workspace_id: str,
        update: WorkspaceModelSettingsUpdate,
    ) -> Result[WorkspaceModelSettings, DefaultModelCannotBeCleared]:
        """Partially update Workspace settings."""
        row = await session.get(RDBWorkspaceModelSettings, workspace_id)
        if row is None:
            row = RDBWorkspaceModelSettings(workspace_id=workspace_id)
            session.add(row)
            await session.flush()
            await session.refresh(row)

        if (
            "default_model_selection" in update
            and update["default_model_selection"] is None
            and row.default_model_selection is not None
        ) or (
            "default_selectable_model_options" in update
            and update["default_selectable_model_options"] is None
            and row.default_selectable_model_options is not None
        ):
            return Failure(DefaultModelCannotBeCleared(workspace_id=workspace_id))

        values: dict[str, object] = {}
        if "default_model_selection" in update:
            selection = update["default_model_selection"]
            values["default_model_selection"] = (
                selection.model_dump(mode="json") if selection is not None else None
            )
        if "default_lightweight_model_selection" in update:
            selection = update["default_lightweight_model_selection"]
            values["default_lightweight_model_selection"] = (
                selection.model_dump(mode="json") if selection is not None else None
            )
        if "default_selectable_model_options" in update:
            options = update["default_selectable_model_options"]
            values["default_selectable_model_options"] = (
                [option.model_dump(mode="json") for option in options]
                if options is not None
                else None
            )
        if "default_main_model_label" in update:
            values["default_main_model_label"] = update["default_main_model_label"]
        if "default_lightweight_model_label" in update:
            values["default_lightweight_model_label"] = update[
                "default_lightweight_model_label"
            ]
        if values:
            await session.execute(
                sa.update(RDBWorkspaceModelSettings)
                .where(RDBWorkspaceModelSettings.workspace_id == workspace_id)
                .values(**values)
            )
            await session.refresh(row)
        assert row is not None
        return Success(self._build(row))

    async def set_default_model_if_empty(
        self,
        session: AsyncSession,
        workspace_id: str,
        selection: AgentModelSelection,
    ) -> WorkspaceModelSettings:
        """Set only when default model is empty."""
        row = await session.get(RDBWorkspaceModelSettings, workspace_id)
        if row is None:
            row = RDBWorkspaceModelSettings(
                workspace_id=workspace_id,
                default_model_selection=selection.model_dump(mode="json"),
                default_lightweight_model_selection=selection.model_dump(mode="json"),
                default_selectable_model_options=[
                    SelectableModelOption(
                        label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                        model_selection=selection,
                        settings=default_selectable_model_settings(selection),
                    ).model_dump(mode="json")
                ],
                default_main_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                default_lightweight_model_label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return self._build(row)
        if row.default_model_selection is None:
            selection_dict = selection.model_dump(mode="json")
            row.default_model_selection = selection_dict
            row.default_lightweight_model_selection = selection_dict
            row.default_selectable_model_options = [
                SelectableModelOption(
                    label=DEFAULT_MAIN_MODEL_OPTION_LABEL,
                    model_selection=selection,
                    settings=default_selectable_model_settings(selection),
                ).model_dump(mode="json")
            ]
            row.default_main_model_label = DEFAULT_MAIN_MODEL_OPTION_LABEL
            row.default_lightweight_model_label = DEFAULT_MAIN_MODEL_OPTION_LABEL
            await session.flush()
            await session.refresh(row)
        return self._build(row)

    def _build(self, row: RDBWorkspaceModelSettings) -> WorkspaceModelSettings:
        """Convert RDB row to domain model."""
        return WorkspaceModelSettings(
            workspace_id=row.workspace_id,
            default_model_selection=(
                _model_selection_adapter.validate_python(row.default_model_selection)
                if row.default_model_selection is not None
                else None
            ),
            default_lightweight_model_selection=(
                _model_selection_adapter.validate_python(
                    row.default_lightweight_model_selection
                )
                if row.default_lightweight_model_selection is not None
                else None
            ),
            default_selectable_model_options=(
                _selectable_model_options_adapter.validate_python(
                    row.default_selectable_model_options
                )
                if row.default_selectable_model_options is not None
                else None
            ),
            default_main_model_label=row.default_main_model_label,
            default_lightweight_model_label=row.default_lightweight_model_label,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
