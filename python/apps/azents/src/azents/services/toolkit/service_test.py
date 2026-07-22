"""Toolkit service unit tests."""

import datetime
from unittest.mock import AsyncMock, MagicMock

from azcommon.result import Success

from azents.repos.toolkit.data import ToolkitConfig
from azents.services.toolkit import ToolkitService, merge_envvar_credentials
from azents.services.toolkit.data import ToolkitUpdateInput


class TestMergeEnvVarCredentials:
    """EnvVar credential update behavior."""

    def test_preserves_existing_value_for_blank_edit(self) -> None:
        """Keep a stored value when its edit field is empty."""
        merged = merge_envvar_credentials(
            '{"values":{"AZENTS_POSTGRES_USER":"old-user","AZENTS_POSTGRES_PASSWORD":"old-password","AZENTS_POSTGRES_HOST":"old-host"}}',
            {
                "values": {
                    "AZENTS_POSTGRES_USER": "new-user",
                    "AZENTS_POSTGRES_PASSWORD": "new-password",
                    "AZENTS_POSTGRES_HOST": "",
                }
            },
            {
                "entries": [
                    {"name": "AZENTS_POSTGRES_USER"},
                    {"name": "AZENTS_POSTGRES_PASSWORD"},
                    {"name": "AZENTS_POSTGRES_HOST"},
                ]
            },
        )

        assert merged == {
            "values": {
                "AZENTS_POSTGRES_USER": "new-user",
                "AZENTS_POSTGRES_PASSWORD": "new-password",
                "AZENTS_POSTGRES_HOST": "old-host",
            }
        }

    def test_removes_value_when_its_entry_is_removed(self) -> None:
        """Discard stored values that no longer have a configured entry."""
        merged = merge_envvar_credentials(
            '{"values":{"AZENTS_POSTGRES_USER":"user","AZENTS_POSTGRES_HOST":"host"}}',
            {"values": {}},
            {"entries": [{"name": "AZENTS_POSTGRES_USER"}]},
        )

        assert merged == {"values": {"AZENTS_POSTGRES_USER": "user"}}

    async def test_config_only_update_removes_deleted_value(self) -> None:
        """Prune removed entry credentials without requiring a credentials payload."""
        old_config = {
            "entries": [
                {"name": "AZENTS_POSTGRES_USER"},
                {"name": "AZENTS_POSTGRES_HOST"},
            ]
        }
        new_config = {"entries": [{"name": "AZENTS_POSTGRES_USER"}]}
        existing = ToolkitConfig(
            id="toolkit-1",
            workspace_id="workspace-1",
            toolkit_type="envvar",
            slug="database",
            name="Database",
            config=old_config,
            credentials='{"values":{"AZENTS_POSTGRES_USER":"user","AZENTS_POSTGRES_HOST":"host"}}',
            enabled=True,
            revision=1,
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        toolkit_repo = MagicMock()
        toolkit_repo.get_by_id = AsyncMock(return_value=existing)
        toolkit_repo.update_by_id = AsyncMock(return_value=Success(existing))
        session_manager = MagicMock()
        session_manager.return_value = AsyncMock()
        service = ToolkitService(
            toolkit_repo=toolkit_repo,
            mcp_oauth_connection_repo=MagicMock(),
            scope_repo=MagicMock(),
            agent_toolkit_repo=MagicMock(),
            agent_repo=MagicMock(),
            session_manager=session_manager,
            toolkit_registry={},
            github_runtime=MagicMock(),
        )
        update: ToolkitUpdateInput = {"config": new_config}

        await service.update_by_id(
            "toolkit-1",
            update,
            workspace_id="workspace-1",
            user_id="user-1",
        )

        repo_update = toolkit_repo.update_by_id.await_args.args[2]
        assert (
            repo_update["credentials"] == '{"values": {"AZENTS_POSTGRES_USER": "user"}}'
        )
