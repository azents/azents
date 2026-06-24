"""Workspace model settings repository tests."""

from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncSession

from azents.core.agent import AgentModelSelection
from azents.core.enums import LLMModelDeveloper, LLMProvider
from azents.core.llm_catalog import ModelCapabilities
from azents.repos.workspace import WorkspaceRepository
from azents.repos.workspace.data import WorkspaceCreate

from . import WorkspaceModelSettingsRepository


async def _create_workspace(session: AsyncSession, handle: str) -> str:
    """Create Workspace for tests and return internal ID."""
    repo = WorkspaceRepository()
    result = await repo.create(
        session,
        WorkspaceCreate(name="Test workspace", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repo.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


def _model_selection() -> AgentModelSelection:
    """Create model selection snapshot for tests."""
    return AgentModelSelection(
        llm_provider_integration_id="llm-integ-test",
        provider=LLMProvider.OPENAI,
        model_identifier="gpt-5-mini",
        model_display_name="GPT-5 mini",
        model_developer=LLMModelDeveloper.OPENAI,
        model_family="gpt-5",
        normalized_capabilities=ModelCapabilities(),
        model_snapshot={"id": "gpt-5-mini"},
    )


class TestWorkspaceModelSettingsRepository:
    """WorkspaceModelSettingsRepository tests."""

    async def test_get_or_create_returns_generated_timestamps(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Return DB creation timestamp when creating empty settings row."""
        workspace_id = await _create_workspace(
            rdb_session,
            "workspace-model-settings-get-or-create",
        )
        repo = WorkspaceModelSettingsRepository()

        settings = await repo.get_or_create(rdb_session, workspace_id)

        assert settings.workspace_id == workspace_id
        assert settings.default_model_selection is None
        assert settings.created_at
        assert settings.updated_at

    async def test_set_default_model_if_empty_returns_generated_timestamps(
        self,
        rdb_session: AsyncSession,
    ) -> None:
        """Return DB creation timestamp when creating default model settings."""
        workspace_id = await _create_workspace(
            rdb_session,
            "workspace-model-settings-set-default",
        )
        selection = _model_selection()
        repo = WorkspaceModelSettingsRepository()

        settings = await repo.set_default_model_if_empty(
            rdb_session,
            workspace_id,
            selection,
        )

        assert settings.workspace_id == workspace_id
        assert settings.default_model_selection == selection
        assert settings.created_at
        assert settings.updated_at
