"""Root AgentSession creation repository tests."""

import asyncio
from uuid import uuid4

import pytest
import sqlalchemy as sa
from azcommon.result import Success
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from azents.core.agent_automatic_project import AgentAutomaticProjectPolicy
from azents.core.agent_session_data import AgentSessionCreate
from azents.core.enums import (
    AgentRuntimeCapability,
    AgentSessionProductMode,
    LLMProvider,
    RuntimeRunnerState,
)
from azents.core.root_agent_session_creation import (
    AgentDefaultRootWorkspaceIntent,
    ExplicitRootWorkspaceIntent,
    RootAgentSessionCreationResult,
)
from azents.core.workspace import WorkspaceCreate
from azents.rdb.models.agent import RDBAgent
from azents.rdb.models.agent_automatic_project_item import (
    RDBAgentAutomaticProjectItem,
)
from azents.rdb.models.agent_automatic_project_setting import (
    RDBAgentAutomaticProjectSetting,
)
from azents.rdb.models.agent_runtime import RDBAgentRuntime
from azents.rdb.models.agent_session import RDBAgentSession
from azents.rdb.models.conversation import RDBConversation
from azents.rdb.models.llm_provider_integration import RDBLLMProviderIntegration
from azents.rdb.models.session_agent import RDBSessionAgent
from azents.rdb.models.session_agent_context import (
    RDBSessionAgentContext,
    RDBSessionAgentContextProject,
)
from azents.rdb.session_capabilities import (
    ReadSession,
    ReadWriteSession,
    WriteSession,
    create_read_write_session_manager,
)
from azents.repos.agent import AgentRepository
from azents.repos.agent_automatic_project import AgentAutomaticProjectRepository
from azents.repos.agent_project_catalog import AgentProjectCatalogRepository
from azents.repos.agent_project_default import AgentProjectDefaultRepository
from azents.repos.agent_project_preset import AgentProjectPresetRepository
from azents.repos.agent_runtime import AgentRuntimeRepository
from azents.repos.agent_session import AgentSessionRepository
from azents.repos.root_agent_session_creation import (
    RootAgentSessionCreationRepository,
)
from azents.repos.session_workspace_project import SessionWorkspaceProjectRepository
from azents.repos.workspace import WorkspaceRepository
from azents.testing.model_selection import (
    make_test_model_selection_dict,
    make_test_selectable_model_option_dicts,
)


async def _create_workspace(session: WriteSession, handle: str) -> str:
    """Create one Workspace for a root Session creation test."""
    repository = WorkspaceRepository()
    result = await repository.create(
        session,
        WorkspaceCreate(name="Root Session creation test", handle=handle),
    )
    assert isinstance(result, Success)
    workspace_id = await repository.resolve_id(session, handle)
    assert workspace_id is not None
    return workspace_id


async def _create_agent(
    session: WriteSession,
    *,
    workspace_id: str,
    slug: str,
    policy_paths: list[str],
    revision: int,
    workspace_path: str | None = "/workspace/agent",
    runtime_capability: AgentRuntimeCapability = AgentRuntimeCapability.MANAGED,
) -> str:
    """Create an Agent and its persisted automatic Project policy."""
    integration = RDBLLMProviderIntegration(
        workspace_id=workspace_id,
        provider=LLMProvider.ANTHROPIC,
        name=f"{slug}-integration",
        encrypted_credentials="encrypted-test-value",
        config=None,
    )
    session.write_session.add(integration)
    await session.write_session.flush()
    agent = RDBAgent(
        workspace_id=workspace_id,
        name="Root Session creation test agent",
        runtime_capability=runtime_capability,
        model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        lightweight_model_selection=make_test_model_selection_dict(
            integration_id=integration.id,
            provider=LLMProvider.ANTHROPIC,
            model_identifier=f"{slug}-id",
        ),
        selectable_model_options=make_test_selectable_model_option_dicts(
            model_selection=(
                make_test_model_selection_dict(
                    integration_id=integration.id,
                    provider=LLMProvider.ANTHROPIC,
                    model_identifier=f"{slug}-id",
                )
            ),
            lightweight_model_selection=(
                make_test_model_selection_dict(
                    integration_id=integration.id,
                    provider=LLMProvider.ANTHROPIC,
                    model_identifier=f"{slug}-id",
                )
            ),
        ),
        main_model_label="default",
        lightweight_model_label="lightweight",
    )
    session.write_session.add(agent)
    await session.write_session.flush()
    session.write_session.add(
        RDBAgentAutomaticProjectSetting(agent_id=agent.id, revision=revision)
    )
    await session.write_session.flush()
    session.write_session.add_all(
        [
            RDBAgentAutomaticProjectItem(
                agent_id=agent.id,
                path=path,
                position=position,
            )
            for position, path in enumerate(policy_paths)
        ]
    )
    await session.write_session.flush()
    if runtime_capability is AgentRuntimeCapability.MANAGED:
        runtime_repository = AgentRuntimeRepository()
        runtime = await runtime_repository.ensure_for_agent(session, agent.id)
        if workspace_path is not None:
            await runtime_repository.record_runner_state(
                session,
                runtime.id,
                RuntimeRunnerState.UNKNOWN,
                1,
                expected_desired_generation=runtime.desired_generation,
                workspace_path=workspace_path,
            )
    return agent.id


def _service() -> RootAgentSessionCreationRepository:
    """Build the shared root Session creation boundary."""
    return RootAgentSessionCreationRepository(
        agent_session_repository=AgentSessionRepository(),
        agent_repository=AgentRepository(),
        automatic_project_repository=AgentAutomaticProjectRepository(),
        session_workspace_project_repository=SessionWorkspaceProjectRepository(),
    )


class TestRootAgentSessionCreationRepository:
    """Root Session Project initialization behavior."""

    async def test_runtime_free_explicit_empty_root_session_is_allowed(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """An explicit empty intent does not require Runtime capability."""
        workspace_id = await _create_workspace(rdb_session, "root-none-empty")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-none-empty",
            policy_paths=["/workspace/agent/default"],
            revision=1,
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        result = await _service().create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(existing_project_paths=[]),
        )

        assert result.initial_project_paths == ()

    async def test_runtime_free_empty_default_root_session_is_allowed(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """An empty automatic policy does not require managed Runtime."""
        workspace_id = await _create_workspace(rdb_session, "root-none-default")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-none-default",
            policy_paths=[],
            revision=1,
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        result = await _service().create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
            workspace_intent=AgentDefaultRootWorkspaceIntent(),
        )

        assert result.initial_project_paths == ()

    async def test_runtime_free_nonempty_default_root_session_is_rejected(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """A non-empty automatic policy requires managed Runtime."""
        workspace_id = await _create_workspace(rdb_session, "root-none-default-path")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-none-default-path",
            policy_paths=["/workspace/agent/default"],
            revision=1,
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        with pytest.raises(ValueError, match="managed Runtime"):
            await _service().create_root_session(
                rdb_session,
                create=AgentSessionCreate(
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    title=None,
                    primary_kind=None,
                    product_mode=AgentSessionProductMode.TEAM,
                    associated_user_id=None,
                ),
                workspace_intent=AgentDefaultRootWorkspaceIntent(),
            )

    async def test_empty_explicit_intent_does_not_require_runtime_state(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Creating a Project-free root Session does not resolve Runtime state."""
        workspace_id = await _create_workspace(rdb_session, "root-empty-runtime")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-empty-runtime",
            policy_paths=[],
            revision=1,
            workspace_path="/runtime/root-empty",
        )

        result = await _service().create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(existing_project_paths=[]),
        )

        assert result.initial_project_paths == ()

    async def test_prevalidated_explicit_paths_never_merge_policy(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Prevalidated explicit paths win over defaults, including empty intent."""
        workspace_id = await _create_workspace(rdb_session, "root-explicit")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-explicit",
            policy_paths=["/workspace/agent/policy-only"],
            revision=4,
        )
        service = _service()

        explicit = await service.create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(
                existing_project_paths=[
                    "/workspace/agent/explicit",
                ],
            ),
        )
        empty = await service.create_root_session(
            rdb_session,
            create=AgentSessionCreate(
                workspace_id=workspace_id,
                agent_id=agent_id,
                title=None,
                primary_kind=None,
                product_mode=AgentSessionProductMode.TEAM,
                associated_user_id=None,
            ),
            workspace_intent=ExplicitRootWorkspaceIntent(existing_project_paths=[]),
        )

        explicit_projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=explicit.agent_session.id,
        )
        empty_projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=empty.agent_session.id,
        )
        assert explicit.created is True
        assert explicit.initial_project_paths == ("/workspace/agent/explicit",)
        assert explicit.policy_revision is None
        assert [project.path for project in explicit_projects] == [
            "/workspace/agent/explicit"
        ]
        assert empty.initial_project_paths == ()
        assert empty_projects == []
        assert (
            await AgentProjectDefaultRepository().list_defaults(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectPresetRepository().list_presets(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectCatalogRepository().list_entries(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )

    async def test_team_primary_snapshots_policy_only_for_creation_winner(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """New primary receives policy Projects while reuse remains unchanged."""
        workspace_id = await _create_workspace(rdb_session, "root-primary")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary",
            policy_paths=[
                "/workspace/agent/policy-a",
                "/workspace/agent/policy-b",
            ],
            revision=7,
            workspace_path=None,
        )
        service = _service()

        created = await service.ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        await rdb_session.write_session.execute(
            sa.delete(RDBAgentAutomaticProjectItem).where(
                RDBAgentAutomaticProjectItem.agent_id == agent_id
            )
        )
        await rdb_session.write_session.execute(
            sa.delete(RDBAgentAutomaticProjectSetting).where(
                RDBAgentAutomaticProjectSetting.agent_id == agent_id
            )
        )
        reused = await service.ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )
        projects = await SessionWorkspaceProjectRepository().list_projects(
            rdb_session,
            session_id=created.agent_session.id,
        )

        assert created.created is True
        assert created.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )
        assert created.policy_revision == 7
        assert reused.created is False
        assert reused.agent_session.id == created.agent_session.id
        assert reused.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )
        assert reused.policy_revision is None
        assert [project.path for project in projects] == [
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        ]
        assert (
            await AgentProjectDefaultRepository().list_defaults(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectPresetRepository().list_presets(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )
        assert (
            await AgentProjectCatalogRepository().list_entries(
                rdb_session,
                agent_id=agent_id,
            )
            == []
        )

    async def test_team_primary_preserves_empty_policy(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """An empty automatic policy preserves the empty-Project behavior."""
        workspace_id = await _create_workspace(rdb_session, "root-primary-empty")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary-empty",
            policy_paths=[],
            revision=3,
        )

        result = await _service().ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

        assert result.created is True
        assert result.initial_project_paths == ()
        assert result.policy_revision == 3
        assert (
            await SessionWorkspaceProjectRepository().list_projects(
                rdb_session,
                session_id=result.agent_session.id,
            )
            == []
        )

    async def test_runtime_free_team_primary_preserves_empty_policy(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Runtime-free team primary creation accepts an empty policy."""
        workspace_id = await _create_workspace(
            rdb_session,
            "root-primary-none-empty",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary-none-empty",
            policy_paths=[],
            revision=4,
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        result = await _service().ensure_team_primary(
            rdb_session,
            workspace_id=workspace_id,
            agent_id=agent_id,
        )

        assert result.created is True
        assert result.initial_project_paths == ()
        assert result.policy_revision == 4

    async def test_runtime_free_team_primary_rejects_nonempty_policy_before_create(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Runtime-free team primary rejects Runtime-dependent defaults atomically."""
        workspace_id = await _create_workspace(
            rdb_session,
            "root-primary-none-project",
        )
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-primary-none-project",
            policy_paths=["/workspace/agent/project"],
            revision=4,
            runtime_capability=AgentRuntimeCapability.NONE,
        )

        with pytest.raises(ValueError, match="managed Runtime"):
            await _service().ensure_team_primary(
                rdb_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )

        assert (
            await AgentSessionRepository().list_active_by_agent_id(
                rdb_session,
                agent_id,
            )
            == []
        )

    async def test_team_primary_race_applies_policy_only_for_winner(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
    ) -> None:
        """A race loser reuses the winner's durable Project snapshot."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        async with AsyncSession(
            rdb_engine, expire_on_commit=False
        ) as _raw_setup_session:
            setup_session = ReadWriteSession(_raw_setup_session)
            workspace_id = await _create_workspace(
                setup_session,
                f"root-primary-race-{suffix}",
            )
            agent_id = await _create_agent(
                setup_session,
                workspace_id=workspace_id,
                slug=f"root-primary-race-{suffix}",
                policy_paths=[
                    "/workspace/agent/policy-a",
                    "/workspace/agent/policy-b",
                ],
                revision=5,
            )
            await setup_session.write_session.commit()

        service = _service()
        async with AsyncSession(
            rdb_engine, expire_on_commit=False
        ) as _raw_first_session:
            first_session = ReadWriteSession(_raw_first_session)
            first_pid = await first_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(first_pid, int)
            first = await service.ensure_team_primary(
                first_session,
                workspace_id=workspace_id,
                agent_id=agent_id,
            )
            async with AsyncSession(
                rdb_engine,
                expire_on_commit=False,
            ) as _raw_second_session:
                second_session = ReadWriteSession(_raw_second_session)
                second_pid = await second_session.read_session.scalar(
                    sa.text("SELECT pg_backend_pid()")
                )
                assert isinstance(second_pid, int)
                assert first_pid != second_pid

                async def ensure_second_primary() -> RootAgentSessionCreationResult:
                    return await service.ensure_team_primary(
                        second_session,
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                    )

                second_task = asyncio.create_task(ensure_second_primary())
                try:
                    async with asyncio.timeout(5):
                        async with AsyncSession(rdb_engine) as _raw_observer:
                            observer = ReadWriteSession(_raw_observer)
                            while True:
                                blockers = await observer.read_session.scalar(
                                    sa.text("SELECT pg_blocking_pids(:pid)"),
                                    {"pid": second_pid},
                                )
                                if first_pid in blockers:
                                    break
                                assert not second_task.done()
                    assert not second_task.done()
                    await first_session.write_session.commit()
                    second = await asyncio.wait_for(second_task, timeout=5)
                    await second_session.write_session.commit()
                finally:
                    if not second_task.done():
                        second_task.cancel()
                    await asyncio.gather(second_task, return_exceptions=True)

        assert first.created is True
        assert first.policy_revision == 5
        assert second.created is False
        assert second.policy_revision is None
        assert second.agent_session.id == first.agent_session.id
        assert second.initial_project_paths == (
            "/workspace/agent/policy-a",
            "/workspace/agent/policy-b",
        )

    @pytest.mark.parametrize("team_primary", [False, True])
    @pytest.mark.parametrize("reenable_runtime", [False, True])
    async def test_stale_project_authority_rolls_back_entire_root_tree(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
        team_primary: bool,
        reenable_runtime: bool,
    ) -> None:
        """Project validation cannot outlive the exact managed authority it read."""
        del latest_db_schema
        manager = create_read_write_session_manager(rdb_engine)
        suffix = uuid4().hex[:8]
        async with manager() as setup:
            workspace_id = await _create_workspace(setup, f"root-stale-{suffix}")
            agent_id = await _create_agent(
                setup,
                workspace_id=workspace_id,
                slug=f"root-stale-{suffix}",
                policy_paths=["/workspace/agent/project"],
                revision=9,
            )

        policy_read = asyncio.Event()
        resume_root = asyncio.Event()

        class PausedRootCreation(RootAgentSessionCreationRepository):
            async def _require_automatic_project_policy(
                self, session: ReadSession, *, agent_id: str
            ) -> AgentAutomaticProjectPolicy:
                policy = await super()._require_automatic_project_policy(
                    session, agent_id=agent_id
                )
                policy_read.set()
                await resume_root.wait()
                return policy

        base = _service()
        service = PausedRootCreation(
            agent_session_repository=base.agent_session_repository,
            agent_repository=base.agent_repository,
            automatic_project_repository=base.automatic_project_repository,
            session_workspace_project_repository=base.session_workspace_project_repository,
        )

        async def create_root() -> RootAgentSessionCreationResult:
            # Exercise the production scope's exception rollback, not a
            # test-specific rollback after observing a partially committed root.
            async with manager() as root:
                if team_primary:
                    return await service.ensure_team_primary(
                        root, workspace_id=workspace_id, agent_id=agent_id
                    )
                return await service.create_root_session(
                    root,
                    create=AgentSessionCreate(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        title=None,
                        primary_kind=None,
                        product_mode=AgentSessionProductMode.TEAM,
                        associated_user_id=None,
                    ),
                    workspace_intent=AgentDefaultRootWorkspaceIntent(),
                )

        root_task = asyncio.create_task(create_root())
        try:
            async with asyncio.timeout(10):
                await policy_read.wait()
                async with manager() as removal:
                    await removal.write_session.execute(
                        sa.delete(RDBAgentRuntime).where(
                            RDBAgentRuntime.agent_id == agent_id
                        )
                    )
                    await removal.write_session.execute(
                        sa.update(RDBAgent)
                        .where(RDBAgent.id == agent_id)
                        .values(
                            runtime_capability=AgentRuntimeCapability.NONE,
                            runtime_capability_version=(
                                RDBAgent.runtime_capability_version + 1
                            ),
                        )
                    )
                if reenable_runtime:
                    async with manager() as reenable:
                        await reenable.write_session.execute(
                            sa.update(RDBAgent)
                            .where(RDBAgent.id == agent_id)
                            .values(
                                runtime_capability=AgentRuntimeCapability.MANAGED,
                                runtime_capability_version=(
                                    RDBAgent.runtime_capability_version + 1
                                ),
                            )
                        )
                        await AgentRuntimeRepository().ensure_for_agent(
                            reenable, agent_id
                        )
                resume_root.set()
                with pytest.raises(
                    RuntimeError,
                    match="Agent Runtime authority changed during Session creation",
                ):
                    await root_task
        finally:
            resume_root.set()
            if not root_task.done():
                root_task.cancel()
            await asyncio.gather(root_task, return_exceptions=True)

        async with manager() as check:
            for model in (
                RDBAgentSession,
                RDBConversation,
                RDBSessionAgentContext,
            ):
                assert (
                    await check.read_session.scalar(
                        sa.select(sa.func.count())
                        .select_from(model)
                        .where(model.agent_id == agent_id)
                    )
                    == 0
                )
            assert (
                await check.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBSessionAgent)
                    .join(
                        RDBAgentSession,
                        RDBAgentSession.id == RDBSessionAgent.agent_session_id,
                    )
                    .where(RDBAgentSession.agent_id == agent_id)
                )
                == 0
            )
            assert (
                await check.read_session.scalar(
                    sa.select(sa.func.count())
                    .select_from(RDBSessionAgentContextProject)
                    .join(
                        RDBSessionAgentContext,
                        RDBSessionAgentContext.id
                        == RDBSessionAgentContextProject.session_agent_context_id,
                    )
                    .where(RDBSessionAgentContext.agent_id == agent_id)
                )
                == 0
            )

    @pytest.mark.parametrize("team_primary", [False, True])
    async def test_root_creation_does_not_invert_runtime_insert_fk_lock(
        self,
        rdb_engine: AsyncEngine,
        latest_db_schema: None,
        team_primary: bool,
    ) -> None:
        """The canonical wrapper must not lock Agent before Runtime creation."""
        del latest_db_schema
        suffix = uuid4().hex[:8]
        async with AsyncSession(rdb_engine, expire_on_commit=False) as raw_setup:
            setup = ReadWriteSession(raw_setup)
            workspace_id = await _create_workspace(setup, f"root-lock-{suffix}")
            agent_id = await _create_agent(
                setup,
                workspace_id=workspace_id,
                slug=f"root-lock-{suffix}",
                policy_paths=[],
                revision=7,
                runtime_capability=AgentRuntimeCapability.NONE,
            )
            await setup.write_session.execute(
                sa.update(RDBAgent)
                .where(RDBAgent.id == agent_id)
                .values(runtime_capability=AgentRuntimeCapability.MANAGED)
            )
            await setup.write_session.commit()

        policy_read = asyncio.Event()
        resume_root = asyncio.Event()
        runtime_inserted = asyncio.Event()
        commit_runtime = asyncio.Event()

        class PausedRootCreation(RootAgentSessionCreationRepository):
            async def _require_automatic_project_policy(
                self, session: ReadSession, *, agent_id: str
            ) -> AgentAutomaticProjectPolicy:
                policy = await super()._require_automatic_project_policy(
                    session, agent_id=agent_id
                )
                policy_read.set()
                await resume_root.wait()
                return policy

        base = _service()
        service = PausedRootCreation(
            agent_session_repository=base.agent_session_repository,
            agent_repository=base.agent_repository,
            automatic_project_repository=base.automatic_project_repository,
            session_workspace_project_repository=base.session_workspace_project_repository,
        )
        async with (
            AsyncSession(rdb_engine, expire_on_commit=False) as raw_root,
            AsyncSession(rdb_engine, expire_on_commit=False) as raw_runtime,
            AsyncSession(rdb_engine) as raw_observer,
        ):
            root = ReadWriteSession(raw_root)
            runtime_session = ReadWriteSession(raw_runtime)
            observer = ReadWriteSession(raw_observer)
            root_pid = await root.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            runtime_pid = await runtime_session.read_session.scalar(
                sa.text("SELECT pg_backend_pid()")
            )
            assert isinstance(root_pid, int) and isinstance(runtime_pid, int)
            assert root_pid != runtime_pid

            async def create_root() -> RootAgentSessionCreationResult:
                if team_primary:
                    result = await service.ensure_team_primary(
                        root, workspace_id=workspace_id, agent_id=agent_id
                    )
                else:
                    result = await service.create_root_session(
                        root,
                        create=AgentSessionCreate(
                            workspace_id=workspace_id,
                            agent_id=agent_id,
                            title=None,
                            primary_kind=None,
                            product_mode=AgentSessionProductMode.TEAM,
                            associated_user_id=None,
                        ),
                        workspace_intent=AgentDefaultRootWorkspaceIntent(),
                    )
                await root.write_session.commit()
                return result

            async def create_runtime() -> str:
                runtime = await AgentRuntimeRepository().ensure_for_agent(
                    runtime_session, agent_id
                )
                runtime_inserted.set()
                await commit_runtime.wait()
                await runtime_session.write_session.commit()
                return runtime.id

            root_task = asyncio.create_task(create_root())
            await asyncio.wait_for(policy_read.wait(), timeout=5)
            runtime_task = asyncio.create_task(create_runtime())
            try:
                async with asyncio.timeout(10):
                    # The old Agent-first guard blocks the Runtime INSERT's FK
                    # check after its unique index entry has already been added.
                    while not runtime_inserted.is_set():
                        blockers = await observer.read_session.scalar(
                            sa.text("SELECT pg_blocking_pids(:pid)"),
                            {"pid": runtime_pid},
                        )
                        if root_pid in blockers:
                            break
                        if runtime_task.done():
                            runtime_task.result()
                    resume_root.set()
                    while True:
                        blockers = await observer.read_session.scalar(
                            sa.text("SELECT pg_blocking_pids(:pid)"),
                            {"pid": root_pid},
                        )
                        if runtime_pid in blockers:
                            break
                        if root_task.done():
                            root_task.result()
                    commit_runtime.set()
                    runtime_id = await runtime_task
                    result = await root_task
            finally:
                resume_root.set()
                commit_runtime.set()
                for task in (root_task, runtime_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(root_task, runtime_task, return_exceptions=True)

        assert result.created and result.policy_revision == 7
        assert result.initial_project_paths == ()
        async with AsyncSession(rdb_engine) as raw_check:
            check = ReadWriteSession(raw_check)
            bound_runtime = await check.read_session.scalar(
                sa.select(RDBSessionAgentContext.agent_runtime_id)
                .join(
                    RDBSessionAgent,
                    RDBSessionAgent.context_id == RDBSessionAgentContext.id,
                )
                .where(RDBSessionAgent.agent_session_id == result.agent_session.id)
            )
            assert bound_runtime == runtime_id

    async def test_missing_policy_rolls_back_new_team_primary(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """A missing invariant policy row cannot silently become an empty policy."""
        workspace_id = await _create_workspace(rdb_session, "root-policy-missing")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-policy-missing",
            policy_paths=[],
            revision=1,
        )
        await rdb_session.write_session.execute(
            sa.delete(RDBAgentAutomaticProjectSetting).where(
                RDBAgentAutomaticProjectSetting.agent_id == agent_id
            )
        )

        with pytest.raises(
            RuntimeError,
            match="Agent automatic Project policy is missing",
        ):
            async with rdb_session.write_session.begin_nested():
                await _service().ensure_team_primary(
                    rdb_session,
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                )

        assert (
            await AgentSessionRepository().list_active_by_agent_id(
                rdb_session,
                agent_id,
            )
            == []
        )

    async def test_root_creation_rolls_back_session_context_and_projects(
        self,
        rdb_session: WriteSession,
    ) -> None:
        """Caller rollback removes the complete root Session initialization unit."""
        workspace_id = await _create_workspace(rdb_session, "root-rollback")
        agent_id = await _create_agent(
            rdb_session,
            workspace_id=workspace_id,
            slug="root-rollback",
            policy_paths=[],
            revision=1,
        )
        service = _service()

        with pytest.raises(RuntimeError, match="rollback"):
            async with rdb_session.write_session.begin_nested():
                await service.create_root_session(
                    rdb_session,
                    create=AgentSessionCreate(
                        workspace_id=workspace_id,
                        agent_id=agent_id,
                        title=None,
                        primary_kind=None,
                        product_mode=AgentSessionProductMode.TEAM,
                        associated_user_id=None,
                    ),
                    workspace_intent=AgentDefaultRootWorkspaceIntent(),
                )
                raise RuntimeError("rollback")

        assert (
            await AgentSessionRepository().list_active_by_agent_id(
                rdb_session,
                agent_id,
            )
            == []
        )
