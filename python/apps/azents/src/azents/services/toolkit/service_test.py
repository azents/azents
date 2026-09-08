"""Toolkit service unit tests."""

import asyncio
import datetime
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import sqlalchemy as sa
from azcommon.result import Failure, Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.enums import AgentLifecycleStatus, WorkspaceUserRole
from azents.engine.tools.mcp import McpToolkitProvider
from azents.rdb.models.agent import RDBAgent
from azents.rdb.session import SessionManager
from azents.repos.agent import AgentRepository
from azents.repos.agent_admin import AgentAdminRepository
from azents.repos.github_user_installation import GithubUserInstallationRepository
from azents.repos.mcp_oauth_connection import MCPOAuthConnectionRepository
from azents.repos.system_setting.repository import SystemSettingRepository
from azents.repos.toolkit import (
    AgentToolkitRepository,
    ToolkitRepository,
    ToolkitScopeRepository,
)
from azents.repos.toolkit.data import NotFound, ToolkitConfig
from azents.repos.toolkit_operations import ToolkitOperationsRepository
from azents.repos.toolkit_operations.owned import AgentToolkitOperationsRepository
from azents.repos.workspace_user import WorkspaceUserRepository
from azents.services.agent.data import NotAdmin
from azents.services.github_platform_system_setting.runtime import (
    PlatformGitHubAppRuntimeService,
)
from azents.services.toolkit import ToolkitService, merge_envvar_credentials
from azents.services.toolkit.data import (
    AgentNotBelongToWorkspace,
    AgentToolkitOAuthConnectionInput,
    EffectiveSlugConflict,
    ToolkitCreateInput,
    ToolkitUpdateInput,
)


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
            owner_agent_id=None,
            toolkit_type="envvar",
            slug="database",
            name="Database",
            config=old_config,
            credentials='{"values":{"AZENTS_POSTGRES_USER":"user","AZENTS_POSTGRES_HOST":"host"}}',
            enabled=True,
            always_expose_tools=False,
            revision=1,
            created_at=datetime.datetime.now(datetime.UTC),
            updated_at=datetime.datetime.now(datetime.UTC),
        )
        toolkit_repo = MagicMock()
        toolkit_repo.get_shared_by_id = AsyncMock(return_value=existing)
        toolkit_repo.get_shared_by_id_for_update = AsyncMock(return_value=existing)
        toolkit_repo.update_by_id = AsyncMock(return_value=Success(existing))
        session_manager = MagicMock()
        session_manager.return_value = AsyncMock()
        service = _build_service(
            toolkit_repo=toolkit_repo,
            mcp_oauth_connection_repo=MagicMock(),
            scope_repo=MagicMock(),
            agent_toolkit_repo=MagicMock(),
            agent_repo=MagicMock(),
            agent_admin_repo=MagicMock(),
            github_user_installation_repo=MagicMock(),
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

        await_args = toolkit_repo.update_by_id.await_args
        assert await_args is not None
        repo_update = await_args.args[2]
        assert (
            repo_update["credentials"] == '{"values": {"AZENTS_POSTGRES_USER": "user"}}'
        )


def _toolkit_config(
    *,
    slug: str = "database",
    enabled: bool = True,
) -> ToolkitConfig:
    """Build a shared ToolkitConfig service fixture."""
    return ToolkitConfig(
        id="toolkit-1",
        workspace_id="workspace-1",
        owner_agent_id=None,
        toolkit_type="mcp",
        slug=slug,
        name="Toolkit",
        config={},
        credentials=None,
        enabled=enabled,
        always_expose_tools=False,
        revision=1,
        created_at=datetime.datetime.now(datetime.UTC),
        updated_at=datetime.datetime.now(datetime.UTC),
    )


def _service(
    *,
    toolkit_repo: MagicMock,
    agent_toolkit_repo: MagicMock,
    agent_repo: MagicMock,
) -> ToolkitService:
    """Build a ToolkitService with isolated repository doubles."""
    session_manager = MagicMock()
    session_manager.return_value = AsyncMock()
    return _build_service(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=MagicMock(),
        scope_repo=MagicMock(),
        agent_toolkit_repo=agent_toolkit_repo,
        agent_repo=agent_repo,
        agent_admin_repo=MagicMock(),
        github_user_installation_repo=MagicMock(),
        session_manager=session_manager,
        toolkit_registry={},
        github_runtime=MagicMock(),
    )


def _active_agent(
    *,
    agent_id: str = "agent-1",
    workspace_id: str = "workspace-1",
) -> SimpleNamespace:
    """Build the Agent fields used by Toolkit management authorization."""
    return SimpleNamespace(
        id=agent_id,
        workspace_id=workspace_id,
        lifecycle_status=AgentLifecycleStatus.ACTIVE,
    )


def _agent_management_service(
    *,
    toolkit_repo: MagicMock,
    agent_repo: MagicMock,
    agent_admin_repo: MagicMock,
    agent_toolkit_repo: MagicMock,
    toolkit_registry: dict[str, Any],
) -> ToolkitService:
    """Build a ToolkitService for Agent-owned management tests."""
    session_manager = MagicMock()
    session_manager.return_value = AsyncMock()
    return _build_service(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=MagicMock(),
        scope_repo=MagicMock(),
        agent_toolkit_repo=agent_toolkit_repo,
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        github_user_installation_repo=MagicMock(),
        session_manager=session_manager,
        toolkit_registry=toolkit_registry,
        github_runtime=MagicMock(),
    )


async def test_workspace_owner_can_manage_agent_without_explicit_admin() -> None:
    """Workspace Owner authority does not depend on an AgentAdmin row."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=_active_agent())
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock(return_value=False)
    service = _agent_management_service(
        toolkit_repo=MagicMock(),
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )

    result = await service.authorize_agent_management(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    agent_admin_repo.is_admin.assert_not_awaited()


async def test_explicit_agent_admin_can_manage_agent() -> None:
    """A non-Owner receives authority only through the AgentAdmin relation."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=_active_agent())
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock(return_value=True)
    service = _agent_management_service(
        toolkit_repo=MagicMock(),
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )

    result = await service.authorize_agent_management(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MEMBER,
    )

    assert isinstance(result, Success)
    agent_admin_repo.is_admin.assert_awaited_once()


async def test_workspace_manager_role_alone_cannot_manage_agent_toolkits() -> None:
    """Workspace Toolkit permissions do not grant Agent-only authority."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=_active_agent())
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock(return_value=False)
    service = _agent_management_service(
        toolkit_repo=MagicMock(),
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )

    result = await service.authorize_agent_management(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.MANAGER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotAdmin)


async def test_cross_workspace_agent_is_hidden_even_from_owner() -> None:
    """The path Workspace must own the active Agent before role evaluation."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(
        return_value=_active_agent(workspace_id="workspace-other")
    )
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock()
    service = _agent_management_service(
        toolkit_repo=MagicMock(),
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )

    result = await service.authorize_agent_management(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, AgentNotBelongToWorkspace)
    agent_admin_repo.is_admin.assert_not_awaited()


async def test_agent_owned_create_sets_owner_without_scope_or_attachment() -> None:
    """Agent-owned creation writes only the canonical owner relation."""
    agent = _active_agent()
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=agent)
    agent_repo.lock_by_id = AsyncMock(return_value=agent)
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock()
    agent_toolkit_repo = MagicMock()
    agent_toolkit_repo.create = AsyncMock()
    scope_repo = MagicMock()
    scope_repo.create = AsyncMock()
    created = _toolkit_config(slug="private")
    created = created.model_copy(
        update={"id": "toolkit-owned", "owner_agent_id": "agent-1"}
    )
    toolkit_repo = MagicMock()
    toolkit_repo.has_effective_slug_conflict = AsyncMock(return_value=False)
    toolkit_repo.create = AsyncMock(return_value=Success(created))
    provider = McpToolkitProvider()
    service = _agent_management_service(
        toolkit_repo=toolkit_repo,
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=agent_toolkit_repo,
        toolkit_registry={"mcp": provider},
    )
    service.operations_repository.scope_repository = scope_repo

    result = await service.create_agent_owned(
        "agent-1",
        ToolkitCreateInput(
            workspace_id="workspace-1",
            toolkit_type="mcp",
            slug="private",
            name="Private",
            config={
                "server_url": "https://mcp.test",
                "auth_type": "none",
            },
            always_expose_tools=False,
        ),
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Success)
    create_args = toolkit_repo.create.await_args
    assert create_args is not None
    create = create_args.args[1]
    assert create.workspace_id == "workspace-1"
    assert create.owner_agent_id == "agent-1"
    scope_repo.create.assert_not_awaited()
    agent_toolkit_repo.create.assert_not_awaited()


async def test_agent_owned_item_lookup_hides_another_agents_toolkit() -> None:
    """An authorized administrator cannot read another Agent's owned config."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=_active_agent())
    toolkit_repo = MagicMock()
    toolkit_repo.get_agent_owned_by_id = AsyncMock(return_value=None)
    service = _agent_management_service(
        toolkit_repo=toolkit_repo,
        agent_repo=agent_repo,
        agent_admin_repo=MagicMock(),
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )

    result = await service.get_agent_owned(
        "agent-1",
        "toolkit-owned-by-agent-2",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotFound)
    assert result.error.toolkit_id == "toolkit-owned-by-agent-2"


async def test_agent_github_installation_sync_rechecks_current_authority() -> None:
    """Installation persistence stops when AgentAdmin authority was removed."""
    agent_repo = MagicMock()
    agent_repo.get_by_id = AsyncMock(return_value=_active_agent())
    agent_admin_repo = MagicMock()
    agent_admin_repo.is_admin = AsyncMock(return_value=False)
    github_repo = MagicMock()
    github_repo.sync = AsyncMock()
    service = _agent_management_service(
        toolkit_repo=MagicMock(),
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )
    service.owned_operations.github_user_installation_repo = github_repo

    result = await service.sync_agent_github_installations(
        "agent-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        user_id="user-1",
        role=WorkspaceUserRole.MANAGER,
        platform_app_id="123",
        installations=[],
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotAdmin)
    github_repo.sync.assert_not_awaited()


async def test_agent_oauth_store_locks_owner_and_marks_incomplete_flow() -> None:
    """OAuth persistence revalidates ownership and authority in one transaction."""
    toolkit = _toolkit_config(slug="private").model_copy(
        update={"owner_agent_id": "agent-1"}
    )
    toolkit_repo = MagicMock()
    toolkit_repo.get_by_id_for_update = AsyncMock(return_value=toolkit)
    agent_repo = MagicMock()
    agent_repo.lock_by_id = AsyncMock(return_value=_active_agent())
    oauth_repo = MagicMock()
    oauth_repo.upsert_connected = AsyncMock()
    oauth_repo.mark_reconnect_required = AsyncMock()
    service = _agent_management_service(
        toolkit_repo=toolkit_repo,
        agent_repo=agent_repo,
        agent_admin_repo=MagicMock(),
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )
    service.owned_operations.mcp_oauth_connection_repo = oauth_repo

    result = await service.store_agent_oauth_connection(
        "agent-1",
        "toolkit-1",
        AgentToolkitOAuthConnectionInput(
            issuer="https://mcp.test",
            resource="https://mcp.test",
            server_url="https://mcp.test",
            authorization_endpoint="https://mcp.test/authorize",
            token_endpoint="https://mcp.test/token",
            registration_endpoint=None,
            client_id="client-1",
            client_secret="secret-1",
            token_endpoint_auth_method="client_secret_post",
            scope=None,
            access_token=None,
            refresh_token=None,
            expires_at=None,
        ),
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
        connected=False,
    )

    assert isinstance(result, Success)
    toolkit_repo.get_by_id_for_update.assert_awaited_once()
    agent_repo.lock_by_id.assert_awaited_once()
    oauth_repo.upsert_connected.assert_awaited_once()
    oauth_repo.mark_reconnect_required.assert_awaited_once()


async def test_agent_oauth_delete_rejects_another_agents_toolkit() -> None:
    """The service does not delete OAuth state through a mismatched Agent path."""
    toolkit = _toolkit_config(slug="private").model_copy(
        update={"owner_agent_id": "agent-other"}
    )
    toolkit_repo = MagicMock()
    toolkit_repo.get_by_id_for_update = AsyncMock(return_value=toolkit)
    oauth_repo = MagicMock()
    oauth_repo.delete_by_toolkit_id = AsyncMock()
    service = _agent_management_service(
        toolkit_repo=toolkit_repo,
        agent_repo=MagicMock(),
        agent_admin_repo=MagicMock(),
        agent_toolkit_repo=MagicMock(),
        toolkit_registry={},
    )
    service.owned_operations.mcp_oauth_connection_repo = oauth_repo

    result = await service.delete_agent_oauth_connection(
        "agent-1",
        "toolkit-1",
        workspace_id="workspace-1",
        workspace_user_id="workspace-user-1",
        role=WorkspaceUserRole.OWNER,
    )

    assert isinstance(result, Failure)
    assert isinstance(result.error, NotFound)
    oauth_repo.delete_by_toolkit_id.assert_not_awaited()


async def test_attach_rejects_effective_slug_conflict_before_projection_create() -> (
    None
):
    """Serialize the Agent namespace and reject a conflicting shared attachment."""
    toolkit = _toolkit_config(slug="github")
    toolkit_repo = MagicMock()
    toolkit_repo.get_shared_by_id_for_update = AsyncMock(return_value=toolkit)
    toolkit_repo.list_available_for_workspace_user = AsyncMock(return_value=[toolkit])
    toolkit_repo.has_effective_slug_conflict = AsyncMock(return_value=True)
    agent_repo = MagicMock()
    agent_repo.lock_by_id = AsyncMock(
        return_value=SimpleNamespace(workspace_id="workspace-1")
    )
    agent_toolkit_repo = MagicMock()
    agent_toolkit_repo.create = AsyncMock()

    result = await _service(
        toolkit_repo=toolkit_repo,
        agent_toolkit_repo=agent_toolkit_repo,
        agent_repo=agent_repo,
    ).attach_to_agent(
        "agent-1",
        toolkit.id,
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Failure)
    assert result.error == EffectiveSlugConflict(slug="github")
    agent_repo.lock_by_id.assert_awaited_once()
    agent_toolkit_repo.create.assert_not_awaited()


async def test_shared_slug_update_locks_attached_agents_before_conflict_check() -> None:
    """Lock every attached Agent in repository order before validating a new slug."""
    toolkit = _toolkit_config(slug="github")
    toolkit_repo = MagicMock()
    toolkit_repo.get_shared_by_id = AsyncMock(return_value=toolkit)
    toolkit_repo.get_shared_by_id_for_update = AsyncMock(return_value=toolkit)
    toolkit_repo.has_effective_slug_conflict = AsyncMock(
        side_effect=[False, True],
    )
    toolkit_repo.update_by_id = AsyncMock(return_value=Success(toolkit))
    agent_toolkit_repo = MagicMock()
    agent_toolkit_repo.list_agent_ids_by_toolkit = AsyncMock(
        return_value=["agent-a", "agent-b"],
    )
    agent_repo = MagicMock()
    agent_repo.lock_by_id = AsyncMock(
        side_effect=[
            SimpleNamespace(workspace_id="workspace-1"),
            SimpleNamespace(workspace_id="workspace-1"),
        ],
    )

    result = await _service(
        toolkit_repo=toolkit_repo,
        agent_toolkit_repo=agent_toolkit_repo,
        agent_repo=agent_repo,
    ).update_by_id(
        toolkit.id,
        {"slug": "github_new"},
        workspace_id="workspace-1",
        user_id="user-1",
    )

    assert isinstance(result, Failure)
    assert result.error == EffectiveSlugConflict(slug="github_new")
    assert [call.args[1] for call in agent_repo.lock_by_id.await_args_list] == [
        "agent-a",
        "agent-b",
    ]
    toolkit_repo.update_by_id.assert_not_awaited()


class _RaceToolkitRepository(ToolkitRepository):
    """Toolkit repository with deterministic shared availability for a race test."""

    async def list_available_for_workspace_user(
        self,
        session: AsyncSession,
        workspace_id: str,
        user_id: str,
    ) -> list[ToolkitConfig]:
        """Return the shared race Toolkit without requiring a User fixture."""
        del user_id
        toolkit = await self.get_shared_by_id(session, "toolkit-race-shared")
        if toolkit is None or toolkit.workspace_id != workspace_id:
            return []
        return [toolkit]


def _engine_session_manager(
    engine: AsyncEngine,
) -> SessionManager[AsyncSession]:
    """Create independent committing sessions for a concurrency test."""

    @asynccontextmanager
    async def session_manager() -> AsyncGenerator[AsyncSession, None]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            else:
                await session.commit()

    return session_manager


async def _seed_slug_race(
    session_manager: SessionManager[AsyncSession],
) -> None:
    """Seed one Agent, one shared Toolkit, and one conflicting owned Toolkit."""
    async with session_manager() as session:
        await session.execute(
            sa.text(
                """
                INSERT INTO workspaces (id, name, handle)
                VALUES ('workspace-race', 'Toolkit race', 'toolkit-race')
                """
            )
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO agents (
                    id, workspace_id, name, model_selection,
                    lightweight_model_selection, selectable_model_options,
                    main_model_label, lightweight_model_label
                )
                VALUES (
                    'agent-race',
                    'workspace-race',
                    'Toolkit race Agent',
                    '{}'::jsonb,
                    '{}'::jsonb,
                    '[{"label":"default","model_selection":{}}]'::jsonb,
                    'default',
                    'default'
                )
                """
            )
        )
        await session.execute(
            sa.text(
                """
                INSERT INTO toolkit_configs (
                    id, workspace_id, owner_agent_id, toolkit_type, slug, name, config
                )
                VALUES
                    (
                        'toolkit-race-shared',
                        'workspace-race',
                        NULL,
                        'mcp',
                        'shared',
                        'Shared race',
                        '{}'::jsonb
                    ),
                    (
                        'toolkit-race-owned',
                        'workspace-race',
                        'agent-race',
                        'mcp',
                        'conflict',
                        'Owned race',
                        '{}'::jsonb
                    )
                """
            )
        )


async def test_concurrent_shared_attach_and_slug_update_preserve_unique_namespace(
    rdb_engine: AsyncEngine,
    latest_db_schema: None,
) -> None:
    """Serialize a shared attach race so exactly one conflicting mutation commits."""
    del latest_db_schema
    session_manager = _engine_session_manager(rdb_engine)
    await _seed_slug_race(session_manager)
    toolkit_repo = _RaceToolkitRepository()
    agent_repo = MagicMock(spec=AgentRepository)

    async def lock_agent(
        session: AsyncSession,
        agent_id: str,
    ) -> SimpleNamespace | None:
        workspace_id = await session.scalar(
            sa.select(RDBAgent.workspace_id)
            .where(RDBAgent.id == agent_id)
            .with_for_update(key_share=True)
        )
        if workspace_id is None:
            return None
        return SimpleNamespace(workspace_id=workspace_id)

    agent_repo.lock_by_id = AsyncMock(side_effect=lock_agent)
    service = _build_service(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=MagicMock(),
        scope_repo=MagicMock(),
        agent_toolkit_repo=AgentToolkitRepository(),
        agent_repo=agent_repo,
        agent_admin_repo=MagicMock(),
        github_user_installation_repo=MagicMock(),
        session_manager=session_manager,
        toolkit_registry={},
        github_runtime=MagicMock(),
    )
    start = asyncio.Event()

    async def attach() -> object:
        await start.wait()
        return await service.attach_to_agent(
            "agent-race",
            "toolkit-race-shared",
            workspace_id="workspace-race",
            user_id="user-race",
        )

    async def update_slug() -> object:
        await start.wait()
        return await service.update_by_id(
            "toolkit-race-shared",
            {"slug": "conflict"},
            workspace_id="workspace-race",
            user_id="user-race",
        )

    tasks = [asyncio.create_task(attach()), asyncio.create_task(update_slug())]
    try:
        start.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)

        successes = [result for result in results if isinstance(result, Success)]
        conflicts = [
            result
            for result in results
            if isinstance(result, Failure)
            and isinstance(result.error, EffectiveSlugConflict)
        ]
        assert len(successes) == 1
        assert len(conflicts) == 1

        async with session_manager() as session:
            effective = await toolkit_repo.list_effective_for_agent(
                session,
                "agent-race",
                workspace_id="workspace-race",
            )
        assert len({item.toolkit.slug for item in effective}) == len(effective)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        async with session_manager() as session:
            await session.execute(sa.text("DELETE FROM agents WHERE id = 'agent-race'"))
            await session.execute(
                sa.text("DELETE FROM workspaces WHERE id = 'workspace-race'")
            )


def _build_service(
    *,
    toolkit_repo: ToolkitRepository,
    mcp_oauth_connection_repo: MCPOAuthConnectionRepository,
    scope_repo: ToolkitScopeRepository,
    agent_toolkit_repo: AgentToolkitRepository,
    agent_repo: AgentRepository,
    agent_admin_repo: AgentAdminRepository,
    github_user_installation_repo: GithubUserInstallationRepository,
    session_manager: SessionManager[AsyncSession],
    toolkit_registry: dict[str, Any],
    github_runtime: PlatformGitHubAppRuntimeService,
) -> ToolkitService:
    """Compose test-owned repositories while preserving narrow collaborator probes."""
    operations = ToolkitOperationsRepository(
        toolkit_repository=toolkit_repo,
        scope_repository=scope_repo,
        agent_toolkit_repository=agent_toolkit_repo,
        agent_repository=agent_repo,
        workspace_user_repository=AsyncMock(spec=WorkspaceUserRepository),
        github_installation_repository=github_user_installation_repo,
        oauth_connection_repository=mcp_oauth_connection_repo,
        system_setting_repository=AsyncMock(spec=SystemSettingRepository),
        session_manager=session_manager,
    )
    owned = AgentToolkitOperationsRepository(
        toolkit_repo=toolkit_repo,
        mcp_oauth_connection_repo=mcp_oauth_connection_repo,
        agent_repo=agent_repo,
        agent_admin_repo=agent_admin_repo,
        github_user_installation_repo=github_user_installation_repo,
        session_manager=session_manager,
        shared_operations=operations,
    )
    return ToolkitService(
        operations_repository=operations,
        owned_operations=owned,
        toolkit_registry=toolkit_registry,
        github_runtime=github_runtime,
    )
